from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import UUID

import structlog
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from handoff.auth import Principal
from handoff.db.models import ApprovalRow, ApprovalStatus, RunRow
from handoff.db.repositories import ApprovalRepository, EventRepository, RunRepository, notify_run_queued
from handoff.errors import ConflictError, NotFoundError, PermissionDeniedError, UnprocessableError
from handoff.graph.state import ApprovalDecision
from handoff.services.dto import ApprovalOut, ApprovalPage, DecisionRequest

log = structlog.get_logger(__name__)


class EscalationPolicy:
    """Pending approvals move up the tier list on each timeout and are rejected after the last one."""

    def __init__(self, tiers: list[str], timeout: timedelta) -> None:
        if not tiers:
            raise ValueError("at least one escalation tier is required")
        self.tiers = tiers
        self.timeout = timeout

    def first_tier(self) -> str:
        return self.tiers[0]

    def next_tier(self, level: int) -> str | None:
        return self.tiers[level + 1] if level + 1 < len(self.tiers) else None

    @property
    def top_tier(self) -> str:
        return self.tiers[-1]

    def check_reviewer(self, approval: ApprovalRow, request: DecisionRequest, reviewer: Principal) -> None:
        """Who may decide what. A reviewer can act on approvals at or below their own tier, and only
        the top tier may approve over a confirmed sanctions match, with a written justification."""
        if reviewer.tier < approval.escalation_level:
            raise PermissionDeniedError(
                f"This approval is assigned to {approval.assignee}; {reviewer.role} cannot decide it"
            )
        if request.action == "reject" or approval.request.get("compliance_status") != "match":
            return
        if reviewer.tier < len(self.tiers) - 1:
            raise PermissionDeniedError(
                f"Only {self.top_tier} can approve a vendor with a confirmed sanctions match"
            )
        if not (request.comment or "").strip():
            raise UnprocessableError(
                "Approving over a confirmed sanctions match needs a written justification in the comment"
            )


class ApprovalService:
    def __init__(self, sessions: async_sessionmaker[AsyncSession], policy: EscalationPolicy) -> None:
        self._sessions = sessions
        self._policy = policy

    async def page(self, *, statuses: list[str] | None, limit: int) -> ApprovalPage:
        async with self._sessions() as session:
            rows = await ApprovalRepository(session).page(statuses=statuses, limit=limit)
            names = await self._vendor_names(session, {r.run_id for r in rows})
        return ApprovalPage(items=[ApprovalOut.from_row(r, names.get(r.run_id, "")) for r in rows])

    async def get(self, approval_id: UUID) -> ApprovalOut:
        async with self._sessions() as session:
            row = await ApprovalRepository(session).get(approval_id)
            if row is None:
                raise NotFoundError("approval", str(approval_id))
            names = await self._vendor_names(session, {row.run_id})
        return ApprovalOut.from_row(row, names.get(row.run_id, ""))

    async def decide(self, approval_id: UUID, request: DecisionRequest, reviewer: Principal) -> ApprovalOut:
        async with self._sessions.begin() as session:
            approvals = ApprovalRepository(session)
            located = await approvals.get(approval_id)
            if located is None:
                raise NotFoundError("approval", str(approval_id))
            # Run first, then approval: the same order cancel() uses, so the two cannot deadlock.
            run = await RunRepository(session).get(located.run_id, for_update=True)
            approval = await approvals.get(approval_id, for_update=True)
            if approval is None:
                raise NotFoundError("approval", str(approval_id))
            if approval.status != "pending":
                raise ConflictError(f"Approval is already {approval.status}")
            if run is None or run.status != "awaiting_approval":
                raise ConflictError("The run is no longer waiting for this approval")
            self._policy.check_reviewer(approval, request, reviewer)
            await self._resolve(session, approval, run, request.to_decision(reviewer))
            return ApprovalOut.from_row(approval, run.vendor_name)

    async def create_pending(
        self,
        session: AsyncSession,
        *,
        run: RunRow,
        interrupt_id: str,
        request: dict[str, object],
        response_schema: dict[str, object] | None,
    ) -> ApprovalRow:
        repo = ApprovalRepository(session)
        existing = await repo.find_by_interrupt(run.id, interrupt_id)
        if existing is not None:
            return existing
        approval = await repo.add(
            ApprovalRow(
                run_id=run.id,
                interrupt_id=interrupt_id,
                status="pending",
                request=request,
                response_schema=response_schema,
                assignee=self._policy.first_tier(),
                escalation_level=0,
                due_at=datetime.now(UTC) + self._policy.timeout,
            )
        )
        await EventRepository(session).append(
            run.id,
            "approval.requested",
            {
                "approval_id": str(approval.id),
                "assignee": approval.assignee,
                "due_at": approval.due_at.isoformat(),
                "request": request,
            },
        )
        return approval

    async def sweep_overdue(self) -> int:
        """Escalate or expire approvals whose deadline passed. Returns how many were touched."""
        async with self._sessions.begin() as session:
            overdue = await ApprovalRepository(session).overdue()
            for approval in overdue:
                next_tier = self._policy.next_tier(approval.escalation_level)
                if next_tier is not None:
                    previous = approval.assignee
                    approval.escalation_level += 1
                    approval.assignee = next_tier
                    approval.due_at = datetime.now(UTC) + self._policy.timeout
                    await EventRepository(session).append(
                        approval.run_id,
                        "approval.escalated",
                        {
                            "approval_id": str(approval.id),
                            "from": previous,
                            "to": next_tier,
                            "level": approval.escalation_level,
                            "due_at": approval.due_at.isoformat(),
                        },
                    )
                    log.info("approval.escalated", approval_id=str(approval.id), to=next_tier)
                    continue
                run = await RunRepository(session).get(approval.run_id, for_update=True, skip_locked=True)
                if run is None:
                    continue
                if run.status != "awaiting_approval":
                    approval.status = "expired"
                    continue
                decision = ApprovalDecision(
                    action="reject",
                    reviewer="policy:timeout",
                    comment=f"No decision after escalation to {approval.assignee}; rejected by policy.",
                    automatic=True,
                )
                await self._resolve(session, approval, run, decision, status="expired")
                log.info("approval.expired", approval_id=str(approval.id))
            return len(overdue)

    async def _resolve(
        self,
        session: AsyncSession,
        approval: ApprovalRow,
        run: RunRow,
        decision: ApprovalDecision,
        *,
        status: ApprovalStatus | None = None,
    ) -> None:
        approval.status = status or ("rejected" if decision.action == "reject" else "approved")
        approval.decision = decision.model_dump(mode="json")
        approval.decided_by = decision.reviewer
        approval.decided_at = datetime.now(UTC)
        run.resume_payload = decision.model_dump(mode="json")
        await RunRepository(session).transition(run.id, "queued")
        events = EventRepository(session)
        await events.append(
            run.id,
            "approval.decided",
            {
                "approval_id": str(approval.id),
                "action": decision.action,
                "reviewer": decision.reviewer,
                "automatic": decision.automatic,
                "status": approval.status,
            },
        )
        await events.append(run.id, "run.status", {"status": "queued", "reason": "approval decided"})
        await notify_run_queued(session, run.id)

    @staticmethod
    async def _vendor_names(session: AsyncSession, run_ids: set[UUID]) -> dict[UUID, str]:
        return await RunRepository(session).vendor_names(list(run_ids))
