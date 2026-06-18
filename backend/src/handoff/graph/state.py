from __future__ import annotations

import operator
from datetime import UTC, datetime
from typing import Annotated, Any, Literal
from uuid import uuid4

from pydantic import BaseModel, Field

from handoff.agents.schemas import (
    ComplianceResult,
    DueDiligenceReport,
    ResearchFindings,
    RiskAssessment,
    RiskLevel,
    RouteTarget,
    ScreeningResult,
    VendorProfile,
)


def _now() -> datetime:
    return datetime.now(UTC)


class Budget(BaseModel):
    max_tokens: int = Field(gt=0)
    max_usd: float = Field(gt=0)


class Usage(BaseModel):
    input_tokens: int = 0
    output_tokens: int = 0
    cost_usd: float = 0.0
    llm_calls: int = 0
    tool_calls: int = 0

    @property
    def total_tokens(self) -> int:
        return self.input_tokens + self.output_tokens

    def __add__(self, other: Usage) -> Usage:
        return Usage(
            input_tokens=self.input_tokens + other.input_tokens,
            output_tokens=self.output_tokens + other.output_tokens,
            cost_usd=round(self.cost_usd + other.cost_usd, 6),
            llm_calls=self.llm_calls + other.llm_calls,
            tool_calls=self.tool_calls + other.tool_calls,
        )


def add_usage(left: Usage | None, right: Usage | None) -> Usage:
    return (left or Usage()) + (right or Usage())


class Handoff(BaseModel):
    """The contract a supervisor hands to a specialist: who, what, and why."""

    id: str = Field(default_factory=lambda: uuid4().hex[:12])
    source: Literal["supervisor"] = "supervisor"
    target: RouteTarget
    task: str
    rationale: str
    created_at: datetime = Field(default_factory=_now)


class TrajectoryStep(BaseModel):
    kind: Literal["handoff", "tool_call", "llm_call", "approval", "submit"]
    agent: str
    name: str
    ok: bool = True
    detail: str | None = None
    arguments: dict[str, Any] = Field(default_factory=dict)
    result_preview: str | None = None
    tokens: int = 0
    at: datetime = Field(default_factory=_now)


class ApprovalRequest(BaseModel):
    vendor: str
    recommendation: Literal["approve", "approve_with_conditions", "reject"]
    risk_rating: RiskLevel
    risk_score: int
    compliance_status: ScreeningResult
    summary: str
    conditions: list[str] = Field(default_factory=list)
    key_findings: list[str] = Field(default_factory=list)


class ApprovalEdits(BaseModel):
    risk_rating: RiskLevel | None = None
    conditions: list[str] | None = None
    summary: str | None = Field(default=None, max_length=4_000)


class ApprovalDecision(BaseModel):
    action: Literal["approve", "reject", "edit"]
    reviewer: str = Field(min_length=1, max_length=120)
    reviewer_role: str | None = Field(default=None, max_length=64)
    comment: str | None = Field(default=None, max_length=2_000)
    edits: ApprovalEdits | None = None
    automatic: bool = False


class ApprovalOutcome(BaseModel):
    approved: bool
    edited: bool
    automatic: bool
    reviewer: str
    comment: str | None
    risk_rating: RiskLevel
    conditions: list[str]
    summary: str
    decided_at: datetime = Field(default_factory=_now)


class DueDiligenceState(BaseModel):
    vendor: VendorProfile
    budget: Budget
    usage: Annotated[Usage, add_usage] = Field(default_factory=Usage)
    handoffs: Annotated[list[Handoff], operator.add] = Field(default_factory=list)
    trajectory: Annotated[list[TrajectoryStep], operator.add] = Field(default_factory=list)
    active_handoff: Handoff | None = None
    research: ResearchFindings | None = None
    risk: RiskAssessment | None = None
    compliance: ComplianceResult | None = None
    approval: ApprovalOutcome | None = None
    report: DueDiligenceReport | None = None


STATE_MODELS: tuple[type[BaseModel], ...] = (
    DueDiligenceState,
    VendorProfile,
    Budget,
    Usage,
    Handoff,
    TrajectoryStep,
    ApprovalOutcome,
    ApprovalDecision,
    ApprovalEdits,
    ResearchFindings,
    RiskAssessment,
    ComplianceResult,
    DueDiligenceReport,
)
