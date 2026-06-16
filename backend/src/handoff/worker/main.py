from __future__ import annotations

import asyncio
import contextlib
from datetime import timedelta
from uuid import UUID

import psycopg
import structlog
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from handoff.config import Settings
from handoff.db.repositories import RUNS_CHANNEL, RunRepository
from handoff.services.approvals import ApprovalService
from handoff.worker.executor import RunExecutor

log = structlog.get_logger(__name__)

SHUTDOWN_GRACE_SECONDS = 5.0
MAX_CLAIM_BACKOFF_SECONDS = 30.0


class WorkerLoopDied(RuntimeError):
    """A background loop ended while the worker was supposed to be running."""


class Worker:
    """Claims runs with SKIP LOCKED, executes them concurrently and keeps their leases alive.

    A run whose worker dies keeps status `running` until its heartbeat goes stale; then any
    worker, including a restarted one, claims it again and resumes from the thread checkpoint.
    Each claim bumps the run's claim count, which the executor uses as a fencing token.
    """

    def __init__(
        self,
        *,
        settings: Settings,
        sessions: async_sessionmaker[AsyncSession],
        executor: RunExecutor,
        approvals: ApprovalService,
    ) -> None:
        self._settings = settings
        self._sessions = sessions
        self._executor = executor
        self._approvals = approvals
        self._active: dict[UUID, asyncio.Task[None]] = {}
        self._wake = asyncio.Event()
        self._log = log.bind(worker_id=settings.worker_id)

    @property
    def active_runs(self) -> list[UUID]:
        return list(self._active)

    async def run(self, stop: asyncio.Event) -> None:
        """Run until `stop` is set. Raises WorkerLoopDied if any loop ends on its own, so the
        process exits non-zero and its supervisor restarts it instead of leaving a zombie."""
        loops = [
            asyncio.create_task(self._claim_loop(stop), name="claim"),
            asyncio.create_task(self._heartbeat_loop(stop), name="heartbeat"),
            asyncio.create_task(self._sweep_loop(stop), name="sweep"),
            asyncio.create_task(self._listen_loop(stop), name="listen"),
        ]
        stopper = asyncio.create_task(stop.wait(), name="stop")
        self._log.info("worker.started", concurrency=self._settings.worker_concurrency)
        died: asyncio.Task[None] | None = None
        try:
            done, _ = await asyncio.wait([stopper, *loops], return_when=asyncio.FIRST_COMPLETED)
            if not stop.is_set():
                died = next((task for task in loops if task in done), None)
        finally:
            stop.set()
            self._wake.set()
            for task in [stopper, *loops]:
                task.cancel()
            await asyncio.gather(stopper, *loops, return_exceptions=True)
            await self._drain()
        if died is not None:
            error = None if died.cancelled() else died.exception()
            self._log.error("worker.loop_died", loop=died.get_name(), error=repr(error))
            raise WorkerLoopDied(f"{died.get_name()} loop ended unexpectedly") from error
        self._log.info("worker.stopped")

    async def _claim_loop(self, stop: asyncio.Event) -> None:
        lease = timedelta(seconds=self._settings.worker_lease_seconds)
        backoff = self._settings.worker_poll_seconds
        while not stop.is_set():
            try:
                while len(self._active) < self._settings.worker_concurrency:
                    async with self._sessions.begin() as session:
                        run = await RunRepository(session).claim_next(self._settings.worker_id, lease)
                    if run is None:
                        break
                    self._log.info("run.claimed", run_id=str(run.id), claims=run.claims)
                    self._spawn(run.id, run.claims)
                backoff = self._settings.worker_poll_seconds
                timeout = self._settings.worker_poll_seconds
            except Exception:
                self._log.exception("worker.claim_failed", retry_in=backoff)
                timeout = backoff
                backoff = min(backoff * 2, MAX_CLAIM_BACKOFF_SECONDS)
            self._wake.clear()
            with contextlib.suppress(TimeoutError):
                await asyncio.wait_for(self._wake.wait(), timeout=timeout)

    def _spawn(self, run_id: UUID, fence: int) -> None:
        if run_id in self._active:
            return
        task = asyncio.create_task(self._execute(run_id, fence), name=f"run-{run_id}")
        self._active[run_id] = task

    async def _execute(self, run_id: UUID, fence: int) -> None:
        try:
            await self._executor.execute(run_id, fence=fence)
        except asyncio.CancelledError:
            self._log.info("run.interrupted", run_id=str(run_id))
            raise
        except Exception:
            self._log.exception("run.executor_crashed", run_id=str(run_id))
        finally:
            self._active.pop(run_id, None)
            self._wake.set()

    async def _heartbeat_loop(self, stop: asyncio.Event) -> None:
        while not stop.is_set():
            await asyncio.sleep(self._settings.worker_heartbeat_seconds)
            if not self._active:
                continue
            try:
                async with self._sessions.begin() as session:
                    await RunRepository(session).heartbeat(list(self._active), self._settings.worker_id)
            except Exception:
                self._log.exception("worker.heartbeat_failed")

    async def _sweep_loop(self, stop: asyncio.Event) -> None:
        while not stop.is_set():
            try:
                touched = await self._approvals.sweep_overdue()
                if touched:
                    self._wake.set()
            except Exception:
                self._log.exception("worker.sweep_failed")
            await asyncio.sleep(self._settings.sweep_interval_seconds)

    async def _listen_loop(self, stop: asyncio.Event) -> None:
        backoff = 1.0
        while not stop.is_set():
            try:
                async with await psycopg.AsyncConnection.connect(
                    self._settings.psycopg_url, autocommit=True
                ) as conn:
                    await conn.execute(f"LISTEN {RUNS_CHANNEL}")
                    backoff = 1.0
                    async for _ in conn.notifies():
                        self._wake.set()
            except (psycopg.Error, OSError) as exc:
                self._log.warning("worker.listen_failed", error=str(exc), retry_in=backoff)
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, 30.0)

    async def _drain(self) -> None:
        if not self._active:
            return
        pending = list(self._active.values())
        _, still_running = await asyncio.wait(pending, timeout=SHUTDOWN_GRACE_SECONDS)
        for task in still_running:
            task.cancel()
        await asyncio.gather(*still_running, return_exceptions=True)
