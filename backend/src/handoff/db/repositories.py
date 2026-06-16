from __future__ import annotations

import json
from collections.abc import Sequence
from datetime import datetime, timedelta
from typing import Any
from uuid import UUID

from sqlalchemy import and_, case, func, or_, select, text, update
from sqlalchemy.ext.asyncio import AsyncSession

from handoff.db.models import ApprovalRow, EvalReportRow, RunEventRow, RunRow, RunStatus

EVENTS_CHANNEL = "handoff_events"
RUNS_CHANNEL = "handoff_runs"
_NOTIFY_LIMIT = 7_500


def _escape_like(value: str) -> str:
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


class RunRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._s = session

    async def add(self, run: RunRow) -> RunRow:
        self._s.add(run)
        await self._s.flush()
        return run

    async def get(
        self, run_id: UUID, *, for_update: bool = False, skip_locked: bool = False
    ) -> RunRow | None:
        stmt = select(RunRow).where(RunRow.id == run_id)
        if for_update:
            stmt = stmt.with_for_update(skip_locked=skip_locked)
        return (await self._s.execute(stmt)).scalar_one_or_none()

    async def exists(self, run_id: UUID) -> bool:
        stmt = select(RunRow.id).where(RunRow.id == run_id)
        return (await self._s.execute(stmt)).scalar_one_or_none() is not None

    async def page(
        self,
        *,
        limit: int,
        statuses: Sequence[str] | None = None,
        search: str | None = None,
        before: tuple[datetime, UUID] | None = None,
    ) -> list[RunRow]:
        stmt = select(RunRow)
        if statuses:
            stmt = stmt.where(RunRow.status.in_(statuses))
        if search:
            stmt = stmt.where(RunRow.vendor_name.ilike(f"%{_escape_like(search)}%", escape="\\"))
        if before is not None:
            created, run_id = before
            stmt = stmt.where(
                or_(RunRow.created_at < created, and_(RunRow.created_at == created, RunRow.id < run_id))
            )
        stmt = stmt.order_by(RunRow.created_at.desc(), RunRow.id.desc()).limit(limit)
        return list((await self._s.execute(stmt)).scalars())

    async def vendor_names(self, run_ids: Sequence[UUID]) -> dict[UUID, str]:
        if not run_ids:
            return {}
        rows = await self._s.execute(select(RunRow.id, RunRow.vendor_name).where(RunRow.id.in_(run_ids)))
        return dict(rows.all())

    async def count_by_status(self) -> dict[str, int]:
        rows = await self._s.execute(select(RunRow.status, func.count()).group_by(RunRow.status))
        return dict(rows.all())

    async def totals(self) -> tuple[float, int]:
        row = (
            await self._s.execute(select(func.coalesce(func.sum(RunRow.cost_usd), 0.0), func.count()))
        ).one()
        return float(row[0]), int(row[1])

    async def claim_next(self, worker_id: str, lease: timedelta) -> RunRow | None:
        """Take one queued run, or a running one whose worker stopped heartbeating."""
        stale = func.now() - lease
        stmt = (
            select(RunRow)
            .where(
                or_(
                    RunRow.status == "queued",
                    and_(RunRow.status == "running", RunRow.heartbeat_at < stale),
                )
            )
            .order_by(RunRow.created_at)
            .limit(1)
            .with_for_update(skip_locked=True)
        )
        run = (await self._s.execute(stmt)).scalar_one_or_none()
        if run is None:
            return None
        run.status = "running"
        run.worker_id = worker_id
        run.heartbeat_at = await self._now()
        run.claims += 1
        run.started_at = run.started_at or run.heartbeat_at
        await self._s.flush()
        return run

    async def heartbeat(self, run_ids: Sequence[UUID], worker_id: str) -> None:
        if not run_ids:
            return
        await self._s.execute(
            update(RunRow)
            .where(RunRow.id.in_(run_ids), RunRow.worker_id == worker_id, RunRow.status == "running")
            .values(heartbeat_at=func.now())
        )

    async def add_usage(
        self,
        run_id: UUID,
        *,
        input_tokens: int = 0,
        output_tokens: int = 0,
        cost_usd: float = 0.0,
        llm_calls: int = 0,
        tool_calls: int = 0,
    ) -> None:
        await self._s.execute(
            update(RunRow)
            .where(RunRow.id == run_id)
            .values(
                input_tokens=RunRow.input_tokens + input_tokens,
                output_tokens=RunRow.output_tokens + output_tokens,
                cost_usd=RunRow.cost_usd + cost_usd,
                llm_calls=RunRow.llm_calls + llm_calls,
                tool_calls=RunRow.tool_calls + tool_calls,
            )
        )

    async def set_current_node(self, run_id: UUID, node: str, *, fence: int | None = None) -> bool:
        return await self._update(run_id, {"current_node": node}, fence)

    async def set_trace_context(self, run_id: UUID, context: dict[str, str], *, fence: int) -> bool:
        return await self._update(run_id, {"trace_context": context}, fence)

    async def transition(
        self, run_id: UUID, status: RunStatus, *, fence: int | None = None, **fields: Any
    ) -> bool:
        """Change status. With a fence (the claim count the caller holds) the write only lands if
        no other worker has claimed the run since, so a worker that lost its lease cannot
        overwrite the new owner's progress."""
        values: dict[str, Any] = {"status": status, **fields}
        if status in ("completed", "rejected", "failed", "cancelled"):
            values["completed_at"] = func.now()
            values["current_node"] = None
        return await self._update(run_id, values, fence)

    async def _update(self, run_id: UUID, values: dict[str, Any], fence: int | None) -> bool:
        stmt = update(RunRow).where(RunRow.id == run_id)
        if fence is not None:
            stmt = stmt.where(RunRow.claims == fence, RunRow.status == "running")
        updated = await self._s.execute(stmt.values(**values).returning(RunRow.id))
        return updated.scalar_one_or_none() is not None

    async def _now(self) -> datetime:
        return (await self._s.execute(select(func.now()))).scalar_one()


class ApprovalRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._s = session

    async def add(self, approval: ApprovalRow) -> ApprovalRow:
        self._s.add(approval)
        await self._s.flush()
        return approval

    async def get(self, approval_id: UUID, *, for_update: bool = False) -> ApprovalRow | None:
        stmt = select(ApprovalRow).where(ApprovalRow.id == approval_id)
        if for_update:
            stmt = stmt.with_for_update()
        return (await self._s.execute(stmt)).scalar_one_or_none()

    async def find_by_interrupt(self, run_id: UUID, interrupt_id: str) -> ApprovalRow | None:
        stmt = select(ApprovalRow).where(
            ApprovalRow.run_id == run_id, ApprovalRow.interrupt_id == interrupt_id
        )
        return (await self._s.execute(stmt)).scalar_one_or_none()

    async def for_run(self, run_id: UUID) -> list[ApprovalRow]:
        stmt = select(ApprovalRow).where(ApprovalRow.run_id == run_id).order_by(ApprovalRow.created_at)
        return list((await self._s.execute(stmt)).scalars())

    async def page(self, *, statuses: Sequence[str] | None, limit: int) -> list[ApprovalRow]:
        stmt = select(ApprovalRow)
        if statuses:
            stmt = stmt.where(ApprovalRow.status.in_(statuses))
        pending = ApprovalRow.status == "pending"
        stmt = stmt.order_by(
            case((pending, 0), else_=1),
            case((pending, ApprovalRow.due_at)).asc(),
            ApprovalRow.decided_at.desc().nulls_last(),
            ApprovalRow.created_at.desc(),
        ).limit(limit)
        return list((await self._s.execute(stmt)).scalars())

    async def count_pending(self) -> int:
        stmt = select(func.count()).select_from(ApprovalRow).where(ApprovalRow.status == "pending")
        return int((await self._s.execute(stmt)).scalar_one())

    async def overdue(self, limit: int = 50) -> list[ApprovalRow]:
        stmt = (
            select(ApprovalRow)
            .where(ApprovalRow.status == "pending", ApprovalRow.due_at <= func.now())
            .order_by(ApprovalRow.due_at)
            .limit(limit)
            .with_for_update(skip_locked=True)
        )
        return list((await self._s.execute(stmt)).scalars())


class EventRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._s = session

    async def append(self, run_id: UUID, event_type: str, payload: dict[str, Any]) -> RunEventRow:
        row = RunEventRow(run_id=run_id, type=event_type, payload=payload)
        self._s.add(row)
        await self._s.flush()
        await self._s.refresh(row, attribute_names=["created_at"])
        message = {
            "id": row.id,
            "run_id": str(run_id),
            "type": event_type,
            "payload": payload,
            "created_at": row.created_at.isoformat(),
        }
        encoded = json.dumps(message, default=str)
        if len(encoded) > _NOTIFY_LIMIT:
            encoded = json.dumps({"id": row.id, "run_id": str(run_id), "type": event_type, "truncated": True})
        await self._s.execute(
            text("SELECT pg_notify(:channel, :payload)"), {"channel": EVENTS_CHANNEL, "payload": encoded}
        )
        return row

    async def get(self, event_id: int) -> RunEventRow | None:
        return await self._s.get(RunEventRow, event_id)

    async def since(self, run_id: UUID, after_id: int, limit: int = 500) -> list[RunEventRow]:
        stmt = (
            select(RunEventRow)
            .where(RunEventRow.run_id == run_id, RunEventRow.id > after_id)
            .order_by(RunEventRow.id)
            .limit(limit)
        )
        return list((await self._s.execute(stmt)).scalars())

    async def count_by_type(self, run_id: UUID, event_type: str) -> list[tuple[str, int]]:
        node = RunEventRow.payload["node"].astext
        stmt = (
            select(node, func.count())
            .where(RunEventRow.run_id == run_id, RunEventRow.type == event_type)
            .group_by(node)
        )
        return [(str(n), int(c)) for n, c in (await self._s.execute(stmt)).all()]


class EvalReportRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._s = session

    async def add(self, report: EvalReportRow) -> EvalReportRow:
        self._s.add(report)
        await self._s.flush()
        return report

    async def latest(self, limit: int = 10) -> list[EvalReportRow]:
        stmt = select(EvalReportRow).order_by(EvalReportRow.created_at.desc()).limit(limit)
        return list((await self._s.execute(stmt)).scalars())


async def notify_run_queued(session: AsyncSession, run_id: UUID) -> None:
    await session.execute(
        text("SELECT pg_notify(:channel, :payload)"), {"channel": RUNS_CHANNEL, "payload": str(run_id)}
    )
