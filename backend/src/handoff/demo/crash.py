"""Kill a worker mid-run and show the run resuming from its last checkpoint."""

from __future__ import annotations

import asyncio
import os
import signal
import subprocess
import sys
from pathlib import Path
from uuid import UUID

from rich.console import Console
from rich.table import Table

from handoff.agents.schemas import VendorProfile
from handoff.config import Settings
from handoff.db.engine import make_engine, make_session_factory, migrate
from handoff.db.models import TERMINAL_STATUSES
from handoff.db.repositories import EventRepository, RunRepository
from handoff.graph.builder import NODE_ORDER, build_graph
from handoff.graph.persistence import postgres_checkpointer
from handoff.services.dto import CreateRunRequest
from handoff.services.runs import RunService

DEMO_WORKER_PREFIX = "crash-demo"
# A short lease so the restarted worker can take the orphaned run over within seconds.
DEMO_LEASE_SECONDS = 6


def _spawn_worker(settings: Settings, log_path: Path, generation: int) -> subprocess.Popen[bytes]:
    env = os.environ | {
        "HANDOFF_WORKER_ID": f"{DEMO_WORKER_PREFIX}-{generation}",
        "HANDOFF_WORKER_LEASE_SECONDS": str(DEMO_LEASE_SECONDS),
        "HANDOFF_WORKER_HEARTBEAT_SECONDS": "1",
        "HANDOFF_WORKER_POLL_SECONDS": "1",
        "HANDOFF_LLM_PROVIDER": "fake",
        "HANDOFF_FAKE_LATENCY_MS": str(max(settings.fake_latency_ms, 400)),
        "HANDOFF_DATABASE_URL": settings.psycopg_url,
    }
    with log_path.open("ab") as log:
        # The child inherits its own copy of the descriptor, so ours can be closed right away.
        return subprocess.Popen(
            [sys.executable, "-m", "handoff.cli", "worker"], env=env, stdout=log, stderr=subprocess.STDOUT
        )


async def crash_demo(settings: Settings, *, kill_after: int, console: Console, log_path: Path) -> bool:
    await migrate(settings)
    engine = make_engine(settings)
    sessions = make_session_factory(engine)
    async with postgres_checkpointer(settings.psycopg_url, max_size=2) as checkpointer:
        await checkpointer.setup()
        runs = RunService(sessions, build_graph(checkpointer), settings)

        async def state() -> tuple[str, str | None, str | None, int]:
            async with sessions() as session:
                row = await RunRepository(session).get(run_id)
            assert row is not None
            count = len(await runs.checkpoints(run_id))
            return row.status, row.current_node, row.worker_id, count

        summary = await runs.create(
            CreateRunRequest(
                vendor=VendorProfile(name="Atlas Cloud Services", country="US", notes="crash demo")
            )
        )
        run_id: UUID = summary.id
        console.print(f"Created run [bold]{run_id}[/] for Atlas Cloud Services")

        worker = _spawn_worker(settings, log_path, 1)
        console.print(f"Started worker pid {worker.pid} (logs: {log_path})")
        try:
            while True:
                await asyncio.sleep(0.25)
                status, node, owner, count = await state()
                if owner and not owner.startswith(DEMO_WORKER_PREFIX):
                    console.print(f"[red]Run was claimed by another worker ({owner}). Stop it and retry.[/]")
                    return False
                if count >= kill_after and status == "running":
                    break
                if status in TERMINAL_STATUSES:
                    console.print("[red]Run finished before the kill point; lower --kill-after.[/]")
                    return False

            os.kill(worker.pid, signal.SIGKILL)
            worker.wait()
            status, node, _, checkpoints_at_kill = await state()
            in_flight = node or "unknown"
            async with sessions() as session:
                seen = await EventRepository(session).since(run_id, 0, limit=5_000)
            kill_mark = seen[-1].id if seen else 0
            console.print(
                f"[red]SIGKILL[/] worker during [bold]{in_flight}[/] "
                f"after {checkpoints_at_kill} checkpoints. "
                f"Run status is still [bold]{status}[/] but its worker is gone."
            )

            await asyncio.sleep(1)
            worker = _spawn_worker(settings, log_path, 2)
            console.print(
                f"Started a new worker pid {worker.pid}; it takes the run over once the dead worker's "
                f"{DEMO_LEASE_SECONDS}s lease goes stale"
            )
            for _ in range(240):
                await asyncio.sleep(0.5)
                status, node, _, after = await state()
                if status in TERMINAL_STATUSES:
                    break
            console.print(f"Run finished as [bold]{status}[/] with {after} checkpoints")

            async with sessions() as session:
                events = await EventRepository(session).since(run_id, 0, limit=5_000)
            before = [e for e in events if e.id <= kill_mark]
            after_events = [e for e in events if e.id > kill_mark]
            table = Table(title="Node executions around the crash", title_justify="left")
            table.add_column("Node")
            table.add_column("Completed before kill", justify="right")
            table.add_column("Started after restart", justify="right")
            for name in NODE_ORDER:
                done = sum(1 for e in before if e.type == "node.completed" and e.payload.get("node") == name)
                rerun = sum(
                    1 for e in after_events if e.type == "node.started" and e.payload.get("node") == name
                )
                table.add_row(name, str(done), str(rerun))
            console.print(table)
            restored = sum(1 for e in before if e.type == "node.completed")
            # A node that completed before the kill but starts again after it was redone, which the
            # checkpoints should have prevented. The supervisor runs between every step, so it is
            # compared by count; everything else should not repeat at all.
            completed_before = {
                name: sum(1 for e in before if e.type == "node.completed" and e.payload.get("node") == name)
                for name in NODE_ORDER
            }
            redone = [
                name
                for name in NODE_ORDER
                if name not in ("supervisor", in_flight)
                and completed_before[name] > 0
                and any(e.type == "node.started" and e.payload.get("node") == name for e in after_events)
            ]
            if redone:
                console.print(f"[red]Work finished before the crash ran again: {', '.join(redone)}[/]")
                return False
            console.print(
                f"{restored} completed node executions were restored from Postgres checkpoints; "
                f"only [bold]{in_flight}[/] (in flight at the kill) ran again."
            )
            return status == "completed"
        finally:
            if worker.poll() is None:
                worker.send_signal(signal.SIGTERM)
                try:
                    worker.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    worker.kill()
            await engine.dispose()
