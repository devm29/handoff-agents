from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from datetime import timedelta
from typing import Any, cast
from uuid import UUID, uuid4

import pytest
from sqlalchemy.exc import OperationalError

from handoff.config import Settings
from handoff.db.repositories import RunRepository
from handoff.services.approvals import ApprovalService
from handoff.worker.executor import RunExecutor
from handoff.worker.main import Worker, WorkerLoopDied


class FakeSessions:
    @asynccontextmanager
    async def begin(self) -> AsyncIterator[None]:
        yield None


@dataclass
class ClaimedRun:
    id: UUID
    claims: int = 1


@dataclass
class RecordingExecutor:
    executed: list[tuple[UUID, int]] = field(default_factory=list)
    done: asyncio.Event = field(default_factory=asyncio.Event)

    async def execute(self, run_id: UUID, *, fence: int) -> None:
        self.executed.append((run_id, fence))
        self.done.set()


class IdleApprovals:
    async def sweep_overdue(self) -> int:
        return 0


def _settings() -> Settings:
    return Settings(
        environment="test",
        database_url="postgresql://nobody@127.0.0.1:1/none",  # type: ignore[arg-type]
        worker_poll_seconds=0.02,
        worker_heartbeat_seconds=0.05,
        worker_lease_seconds=5,
        sweep_interval_seconds=0.05,
    )


def _worker(executor: RecordingExecutor) -> Worker:
    return Worker(
        settings=_settings(),
        sessions=cast("Any", FakeSessions()),
        executor=cast("RunExecutor", executor),
        approvals=cast("ApprovalService", IdleApprovals()),
    )


async def test_claim_loop_survives_a_database_error(monkeypatch: pytest.MonkeyPatch) -> None:
    run = ClaimedRun(id=uuid4(), claims=3)
    outcomes: list[ClaimedRun | Exception | None] = [
        OperationalError("SELECT", {}, Exception("connection reset")),
        run,
    ]

    async def claim_next(self: RunRepository, worker_id: str, lease: timedelta) -> ClaimedRun | None:
        outcome = outcomes.pop(0) if outcomes else None
        if isinstance(outcome, Exception):
            raise outcome
        return outcome

    monkeypatch.setattr(RunRepository, "claim_next", claim_next)
    monkeypatch.setattr(RunRepository, "heartbeat", lambda *a, **k: asyncio.sleep(0))
    executor = RecordingExecutor()
    worker = _worker(executor)
    stop = asyncio.Event()
    task = asyncio.create_task(worker.run(stop))
    await asyncio.wait_for(executor.done.wait(), timeout=5)
    stop.set()
    await asyncio.wait_for(task, timeout=10)
    assert executor.executed == [(run.id, 3)], "the claim fence is handed to the executor"


async def test_worker_exits_when_a_loop_dies(monkeypatch: pytest.MonkeyPatch) -> None:
    async def broken_sweep(self: Worker, stop: asyncio.Event) -> None:
        raise RuntimeError("sweep exploded")

    async def claim_nothing(self: RunRepository, worker_id: str, lease: timedelta) -> None:
        return None

    monkeypatch.setattr(RunRepository, "claim_next", claim_nothing)
    monkeypatch.setattr(Worker, "_sweep_loop", broken_sweep)
    worker = _worker(RecordingExecutor())
    with pytest.raises(WorkerLoopDied, match="sweep"):
        await asyncio.wait_for(worker.run(asyncio.Event()), timeout=10)


def test_default_worker_ids_are_unique_per_process() -> None:
    assert _settings().worker_id != _settings().worker_id
