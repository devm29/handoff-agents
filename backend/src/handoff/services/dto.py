from __future__ import annotations

import base64
from datetime import datetime
from typing import Any, Literal, Self
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from handoff.agents.schemas import (
    ComplianceResult,
    DueDiligenceReport,
    ResearchFindings,
    RiskAssessment,
    VendorProfile,
)
from handoff.auth import Principal
from handoff.db.models import ApprovalRow, RunRow, RunStatus
from handoff.errors import BadRequestError, ErrorInfo
from handoff.graph.state import ApprovalDecision, ApprovalEdits, ApprovalRequest, Budget, DueDiligenceState


class BudgetIn(BaseModel):
    max_tokens: int = Field(ge=1_000, le=2_000_000)
    max_usd: float = Field(gt=0, le=50)


class CreateRunRequest(BaseModel):
    vendor: VendorProfile
    budget: BudgetIn | None = None


class UsageOut(BaseModel):
    input_tokens: int
    output_tokens: int
    total_tokens: int
    cost_usd: float
    llm_calls: int
    tool_calls: int


class RunSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    vendor_name: str
    vendor_country: str
    status: RunStatus
    current_node: str | None
    risk_rating: str | None
    decision: str | None
    usage: UsageOut
    budget: Budget
    parent_run_id: UUID | None
    forked_from_checkpoint: str | None
    error: ErrorInfo | None
    claims: int
    created_at: datetime
    updated_at: datetime
    started_at: datetime | None
    completed_at: datetime | None

    @classmethod
    def from_row(cls, row: RunRow) -> Self:
        return cls(
            id=row.id,
            vendor_name=row.vendor_name,
            vendor_country=row.vendor_country,
            status=row.status,
            current_node=row.current_node,
            risk_rating=row.risk_rating,
            decision=row.decision,
            usage=UsageOut(
                input_tokens=row.input_tokens,
                output_tokens=row.output_tokens,
                total_tokens=row.input_tokens + row.output_tokens,
                cost_usd=round(row.cost_usd, 6),
                llm_calls=row.llm_calls,
                tool_calls=row.tool_calls,
            ),
            budget=Budget(max_tokens=row.budget_max_tokens, max_usd=row.budget_max_usd),
            parent_run_id=row.parent_run_id,
            forked_from_checkpoint=row.forked_from_checkpoint,
            error=ErrorInfo.model_validate(row.error) if row.error else None,
            claims=row.claims,
            created_at=row.created_at,
            updated_at=row.updated_at,
            started_at=row.started_at,
            completed_at=row.completed_at,
        )


class RunPage(BaseModel):
    items: list[RunSummary]
    next_cursor: str | None


class ApprovalOut(BaseModel):
    id: UUID
    run_id: UUID
    vendor_name: str
    status: Literal["pending", "approved", "rejected", "expired"]
    request: ApprovalRequest
    assignee: str
    escalation_level: int
    due_at: datetime
    decision: ApprovalDecision | None
    decided_by: str | None
    decided_at: datetime | None
    created_at: datetime

    @classmethod
    def from_row(cls, row: ApprovalRow, vendor_name: str) -> Self:
        return cls(
            id=row.id,
            run_id=row.run_id,
            vendor_name=vendor_name,
            status=row.status,
            request=ApprovalRequest.model_validate(row.request),
            assignee=row.assignee,
            escalation_level=row.escalation_level,
            due_at=row.due_at,
            decision=ApprovalDecision.model_validate(row.decision) if row.decision else None,
            decided_by=row.decided_by,
            decided_at=row.decided_at,
            created_at=row.created_at,
        )


class ApprovalPage(BaseModel):
    items: list[ApprovalOut]


class RunDetail(RunSummary):
    vendor: VendorProfile
    state: DueDiligenceState | None
    report: DueDiligenceReport | None
    approvals: list[ApprovalOut]


class CheckpointSummary(BaseModel):
    checkpoint_id: str
    parent_checkpoint_id: str | None
    step: int
    source: str
    produced_by: str | None
    next: list[str]
    interrupted: bool
    created_at: datetime | None
    cost_usd: float
    total_tokens: int


class CheckpointDetail(CheckpointSummary):
    state: DueDiligenceState | None


class StatePatch(BaseModel):
    model_config = ConfigDict(extra="forbid")

    vendor: VendorProfile | None = None
    budget: Budget | None = None
    research: ResearchFindings | None = None
    risk: RiskAssessment | None = None
    compliance: ComplianceResult | None = None

    def apply(self, state: DueDiligenceState) -> DueDiligenceState:
        changes = self.model_dump(exclude_none=True)
        return DueDiligenceState.model_validate({**state.model_dump(), **changes})


class ForkRequest(BaseModel):
    checkpoint_id: str = Field(min_length=1, max_length=64)
    state_patch: StatePatch = Field(default_factory=StatePatch)


class DecisionRequest(BaseModel):
    """The reviewer is never part of the body: it is the authenticated principal."""

    model_config = ConfigDict(extra="forbid")

    action: Literal["approve", "reject", "edit"]
    comment: str | None = Field(default=None, max_length=2_000)
    edits: ApprovalEdits | None = None

    @model_validator(mode="after")
    def _edits_match_action(self) -> Self:
        if self.action == "edit" and self.edits is None:
            raise ValueError("edits are required when action is 'edit'")
        if self.action != "edit" and self.edits is not None:
            raise ValueError("edits are only allowed when action is 'edit'")
        return self

    def to_decision(self, reviewer: Principal) -> ApprovalDecision:
        return ApprovalDecision(
            action=self.action,
            reviewer=reviewer.name,
            reviewer_role=reviewer.role,
            comment=self.comment.strip() if self.comment and self.comment.strip() else None,
            edits=self.edits,
        )


class EventOut(BaseModel):
    id: int
    run_id: UUID
    type: str
    payload: dict[str, Any]
    created_at: datetime


class TopologyNode(BaseModel):
    id: str
    label: str
    kind: Literal["start", "end", "supervisor", "specialist", "gate"]
    tools: list[str] = Field(default_factory=list)


class TopologyEdge(BaseModel):
    source: str
    target: str
    conditional: bool


class GraphTopology(BaseModel):
    nodes: list[TopologyNode]
    edges: list[TopologyEdge]


class Stats(BaseModel):
    runs_by_status: dict[str, int]
    total_runs: int
    pending_approvals: int
    total_cost_usd: float
    avg_cost_usd: float


class SessionOut(BaseModel):
    name: str
    role: str
    tier: int
    top_tier: bool


class SignInRequest(BaseModel):
    token: str = Field(min_length=1, max_length=256)


class EvalReportOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    suite: str
    provider: str
    summary: dict[str, Any]
    results: dict[str, Any]
    created_at: datetime


def encode_cursor(created_at: datetime, run_id: UUID) -> str:
    return base64.urlsafe_b64encode(f"{created_at.isoformat()}|{run_id}".encode()).decode()


def decode_cursor(cursor: str) -> tuple[datetime, UUID]:
    try:
        raw = base64.urlsafe_b64decode(cursor.encode()).decode()
        created, run_id = raw.split("|", 1)
        return datetime.fromisoformat(created), UUID(run_id)
    except (ValueError, UnicodeDecodeError) as exc:
        raise BadRequestError("invalid cursor") from exc
