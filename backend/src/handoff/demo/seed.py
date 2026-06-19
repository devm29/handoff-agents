"""Populate the database with a realistic mix of runs so the inspector has something to show."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta

from rich.console import Console
from sqlalchemy import func, select, text, update

from handoff.agents.schemas import VendorProfile
from handoff.auth import Principal
from handoff.config import Settings
from handoff.db.models import ApprovalRow, EvalReportRow, RunEventRow, RunRow
from handoff.db.repositories import EvalReportRepository
from handoff.evals.suite import run_suite
from handoff.graph.state import ApprovalEdits
from handoff.services.dto import BudgetIn, CreateRunRequest, DecisionRequest, ForkRequest, StatePatch
from handoff.worker.runtime import WorkerRuntime, worker_runtime

SEED_RUNS: list[CreateRunRequest] = [
    CreateRunRequest(
        vendor=VendorProfile(name="Northwind Logistics", country="DE", website="northwind-logistics.de")
    ),
    CreateRunRequest(
        vendor=VendorProfile(name="Atlas Cloud Services", country="US", website="atlascloud.io")
    ),
    CreateRunRequest(
        vendor=VendorProfile(
            name="Helios Components",
            country="GB",
            notes="Replacement supplier for wiring harnesses, 3-year contract.",
        )
    ),
    CreateRunRequest(
        vendor=VendorProfile(name="Corvane Trading", country="AE", notes="Spot purchases of copper cathode.")
    ),
    CreateRunRequest(
        vendor=VendorProfile(name="Meridian Pharma", country="ES", notes="Generic API supply for EU market.")
    ),
    CreateRunRequest(
        vendor=VendorProfile(name="Kestrel Microsystems", country="SG", notes="Custom ASIC design partner.")
    ),
    CreateRunRequest(
        vendor=VendorProfile(
            name="Quantum Ledger", country="EE", notes="Stablecoin payout rails for marketplace sellers."
        )
    ),
    CreateRunRequest(
        vendor=VendorProfile(name="Orion Freight", country="US", notes="Drayage for the Newark DC.")
    ),
    CreateRunRequest(
        vendor=VendorProfile(
            name="Bluefin Analytics",
            country="GB",
            registration_number="11290877",
            website="bluefin-analytics.com",
        )
    ),
    CreateRunRequest(
        vendor=VendorProfile(
            name="Lumen Health Partners", country="US", notes="Locum nurse staffing. simulate:flaky-model"
        )
    ),
    CreateRunRequest(
        vendor=VendorProfile(
            name="Helios Components", country="GB", notes="Re-screen with a tight spend cap."
        ),
        budget=BudgetIn(max_tokens=40_000, max_usd=0.04),
    ),
]

COMPLIANCE_LEAD = ("Sofia Marin", "compliance-lead")
CHIEF_RISK_OFFICER = ("James Whitaker", "chief-risk-officer")

DECISIONS: dict[str, tuple[tuple[str, str], DecisionRequest]] = {
    "Corvane Trading": (
        COMPLIANCE_LEAD,
        DecisionRequest(action="reject", comment="Majority owner is an SDN. Do not onboard."),
    ),
    "Meridian Pharma": (
        CHIEF_RISK_OFFICER,
        DecisionRequest(
            action="edit",
            comment="Proceed, but tie payment milestones to GMP remediation.",
            edits=ApprovalEdits(
                conditions=[
                    "Quarterly review of AEMPS inspection findings and CAPA status",
                    "Batch release certificates shared before each shipment",
                ]
            ),
        ),
    ),
    "Orion Freight": (COMPLIANCE_LEAD, DecisionRequest(action="reject", comment="Entity is dissolved.")),
}

_TABLES = (
    "run_events",
    "approvals",
    "eval_reports",
    "runs",
    "checkpoint_writes",
    "checkpoint_blobs",
    "checkpoints",
)


async def _settle(rt: WorkerRuntime, console: Console, max_wait: float = 120) -> None:
    stop = asyncio.Event()
    task = asyncio.create_task(rt.worker.run(stop))
    deadline = asyncio.get_running_loop().time() + max_wait
    try:
        while asyncio.get_running_loop().time() < deadline:
            await asyncio.sleep(0.5)
            async with rt.sessions() as session:
                busy = await session.scalar(
                    select(func.count()).select_from(RunRow).where(RunRow.status.in_(("queued", "running")))
                )
            if not busy:
                return
        console.print("[yellow]Timed out waiting for runs to settle[/]")
    finally:
        stop.set()
        await task


async def seed(settings: Settings, *, reset: bool, console: Console) -> None:
    settings = settings.model_copy(
        update={
            "llm_provider": "fake",
            "fake_latency_ms": 0,
            "worker_id": "seed",
            "mcp_transport": "inprocess",
        }
    )
    async with worker_runtime(settings) as rt:
        async with rt.sessions.begin() as session:
            existing = await session.scalar(select(func.count()).select_from(RunRow))
            if existing and not reset:
                console.print(f"[yellow]{existing} runs already exist.[/] Pass --reset to wipe and reseed.")
                return
            if reset:
                await session.execute(text(f"TRUNCATE {', '.join(_TABLES)} CASCADE"))

        console.print(f"Creating {len(SEED_RUNS)} runs")
        for request in SEED_RUNS:
            await rt.runs.create(request)
        await _settle(rt, console)

        pending = await rt.approvals.page(statuses=["pending"], limit=50)
        for approval in pending.items:
            planned = DECISIONS.get(approval.vendor_name)
            if planned is not None:
                (name, role), decision = planned
                reviewer = Principal(name=name, role=role, tier=settings.escalation_tiers.index(role))
                await rt.approvals.decide(approval.id, decision, reviewer)
                console.print(f"  {name} chose {decision.action} for {approval.vendor_name}")

        page = await rt.runs.page(limit=50, cursor=None, statuses=["completed"], search="Northwind")
        if page.items:
            source = page.items[0]
            checkpoints = await rt.runs.checkpoints(source.id)
            after_research = next((c for c in checkpoints if c.produced_by == "researcher"), None)
            if after_research is not None:
                detail = await rt.runs.checkpoint(source.id, after_research.checkpoint_id)
                if detail.state is not None:
                    vendor = detail.state.vendor.model_copy(
                        update={"notes": "Re-run after the 2026 ownership disclosure update."}
                    )
                    await rt.runs.fork(
                        source.id,
                        ForkRequest(
                            checkpoint_id=after_research.checkpoint_id, state_patch=StatePatch(vendor=vendor)
                        ),
                    )
                    console.print("  Forked Northwind Logistics from the post-research checkpoint")
        await _settle(rt, console)

        async with rt.sessions.begin() as session:
            quantum = await session.scalar(
                select(ApprovalRow.id)
                .join(RunRow, RunRow.id == ApprovalRow.run_id)
                .where(RunRow.vendor_name == "Quantum Ledger", ApprovalRow.status == "pending")
            )
            if quantum is not None:
                await session.execute(
                    update(ApprovalRow)
                    .where(ApprovalRow.id == quantum)
                    .values(due_at=datetime.now(UTC) - timedelta(seconds=1))
                )
        if await rt.approvals.sweep_overdue():
            console.print("  Escalated the Quantum Ledger approval after its deadline passed")

        summary, results = await run_suite(settings, "default")
        async with rt.sessions.begin() as session:
            await EvalReportRepository(session).add(
                EvalReportRow(
                    suite=summary.suite,
                    provider=summary.provider,
                    summary=summary.model_dump(mode="json"),
                    results={"scenarios": [r.model_dump(mode="json") for r in results]},
                )
            )
        console.print(f"  Stored eval report: {summary.passed}/{summary.scenarios} scenarios passed")

        await _spread_history(rt)
        stats = await rt.runs.stats()
        console.print(
            f"[green]Seeded[/] {stats.total_runs} runs, {stats.pending_approvals} approvals pending"
        )


async def _spread_history(rt: WorkerRuntime) -> None:
    """Shift each seeded run back in time so the dashboard reads like a few days of real use."""
    async with rt.sessions.begin() as session:
        run_ids = list(await session.scalars(select(RunRow.id).order_by(RunRow.created_at)))
        for index, run_id in enumerate(run_ids):
            hours_ago = (len(run_ids) - index) * 4.5 + (index % 3) * 0.7
            shift = timedelta(hours=hours_ago)
            await session.execute(
                update(RunRow)
                .where(RunRow.id == run_id)
                .values(
                    created_at=RunRow.created_at - shift,
                    updated_at=RunRow.updated_at - shift,
                    started_at=RunRow.started_at - shift,
                    completed_at=RunRow.completed_at - shift,
                    heartbeat_at=RunRow.heartbeat_at - shift,
                )
            )
            await session.execute(
                update(RunEventRow)
                .where(RunEventRow.run_id == run_id)
                .values(created_at=RunEventRow.created_at - shift)
            )
            await session.execute(
                update(ApprovalRow)
                .where(ApprovalRow.run_id == run_id)
                .values(
                    created_at=ApprovalRow.created_at - shift,
                    decided_at=ApprovalRow.decided_at - shift,
                )
            )
