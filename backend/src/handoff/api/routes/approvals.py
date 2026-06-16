from __future__ import annotations

from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Query

from handoff.api.deps import ApprovalServiceDep, ReviewerDep
from handoff.services.dto import ApprovalOut, ApprovalPage, DecisionRequest

router = APIRouter(prefix="/approvals", tags=["approvals"])

ApprovalStatusFilter = Literal["pending", "approved", "rejected", "expired"]


@router.get("")
async def list_approvals(
    approvals: ApprovalServiceDep,
    status_filter: Annotated[list[ApprovalStatusFilter] | None, Query(alias="status")] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
) -> ApprovalPage:
    return await approvals.page(statuses=list(status_filter or []) or None, limit=limit)


@router.get("/{approval_id}")
async def get_approval(approval_id: UUID, approvals: ApprovalServiceDep) -> ApprovalOut:
    return await approvals.get(approval_id)


@router.post("/{approval_id}/decision")
async def decide(
    approval_id: UUID, body: DecisionRequest, approvals: ApprovalServiceDep, reviewer: ReviewerDep
) -> ApprovalOut:
    return await approvals.decide(approval_id, body, reviewer)
