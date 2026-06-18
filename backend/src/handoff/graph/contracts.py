"""Typed handoff contracts: what each specialist is allowed to receive.

A handoff is only valid when the state can satisfy the target's input model. Asking a
specialist to work before its prerequisites exist is a policy violation, not a model
quirk to be retried.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel

from handoff.agents.schemas import (
    ComplianceResult,
    ResearchFindings,
    RiskAssessment,
    RouteTarget,
    VendorProfile,
)
from handoff.errors import PolicyViolation
from handoff.graph.state import ApprovalOutcome, DueDiligenceState


class ResearcherInput(BaseModel):
    vendor: VendorProfile


class RiskAnalystInput(BaseModel):
    vendor: VendorProfile
    research: ResearchFindings


class ComplianceInput(BaseModel):
    vendor: VendorProfile
    research: ResearchFindings


class ReportWriterInput(BaseModel):
    vendor: VendorProfile
    research: ResearchFindings
    risk: RiskAssessment
    compliance: ComplianceResult
    approval: ApprovalOutcome


class SupervisorInput(BaseModel):
    vendor: VendorProfile
    completed: list[str]
    risk_rating: str | None
    compliance_status: str | None
    approval_status: Literal["approved", "rejected"] | None
    report_ready: bool


def completed_steps(state: DueDiligenceState) -> list[str]:
    steps = {
        "researcher": state.research,
        "risk_analyst": state.risk,
        "compliance_checker": state.compliance,
        "approval": state.approval,
        "report_writer": state.report,
    }
    return [name for name, value in steps.items() if value is not None]


def supervisor_input(state: DueDiligenceState) -> SupervisorInput:
    approval_status: Literal["approved", "rejected"] | None = None
    if state.approval is not None:
        approval_status = "approved" if state.approval.approved else "rejected"
    return SupervisorInput(
        vendor=state.vendor,
        completed=completed_steps(state),
        risk_rating=state.risk.rating if state.risk else None,
        compliance_status=state.compliance.status if state.compliance else None,
        approval_status=approval_status,
        report_ready=state.report is not None,
    )


def _require[T](value: T | None, target: str, missing: str) -> T:
    if value is None:
        raise PolicyViolation(
            f"Handoff to {target} rejected: {missing} is not available yet",
            details={"target": target, "missing": missing},
        )
    return value


def build_input(target: RouteTarget, state: DueDiligenceState) -> BaseModel:
    match target:
        case "researcher":
            return ResearcherInput(vendor=state.vendor)
        case "risk_analyst":
            return RiskAnalystInput(
                vendor=state.vendor, research=_require(state.research, target, "research")
            )
        case "compliance_checker":
            return ComplianceInput(vendor=state.vendor, research=_require(state.research, target, "research"))
        case "approval":
            _require(state.risk, target, "risk assessment")
            _require(state.compliance, target, "compliance screening")
            return supervisor_input(state)
        case "report_writer":
            return ReportWriterInput(
                vendor=state.vendor,
                research=_require(state.research, target, "research"),
                risk=_require(state.risk, target, "risk assessment"),
                compliance=_require(state.compliance, target, "compliance screening"),
                approval=_require(state.approval, target, "approval decision"),
            )
        case "finish":
            _require(state.report, target, "final report")
            return supervisor_input(state)


def validate_handoff(target: RouteTarget, state: DueDiligenceState) -> None:
    if target != "finish" and target in completed_steps(state):
        raise PolicyViolation(
            f"Handoff to {target} rejected: step already completed", details={"target": target}
        )
    build_input(target, state)
