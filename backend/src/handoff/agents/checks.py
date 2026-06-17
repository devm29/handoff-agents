"""Deterministic checks on what specialists submit.

Models write the compliance status and the final decision themselves; these checks make
sure neither can drift from the evidence (the screening results) or from the human decision.
"""

from __future__ import annotations

from handoff.agents.schemas import (
    ComplianceResult,
    DueDiligenceReport,
    ResearchFindings,
    ScreeningResult,
)
from handoff.graph.state import ApprovalOutcome

SCREENING_ORDER: dict[ScreeningResult, int] = {"clear": 0, "potential_match": 1, "match": 2}


def _normalize(name: str) -> str:
    return " ".join(name.casefold().split())


def worst_screening(compliance: ComplianceResult) -> ScreeningResult:
    return max((s.result for s in compliance.screened), key=SCREENING_ORDER.__getitem__, default="clear")


def unscreened_entities(research: ResearchFindings, compliance: ComplianceResult) -> list[str]:
    screened = {_normalize(s.name) for s in compliance.screened}
    required = [research.legal_name, *(o.name for o in research.beneficial_owners)]
    return [name for name in required if _normalize(name) not in screened]


def screening_problems(research: ResearchFindings, compliance: ComplianceResult) -> list[str]:
    problems: list[str] = []
    worst = worst_screening(compliance)
    if compliance.status != worst:
        problems.append(
            f"status is '{compliance.status}' but the screened entities include a '{worst}' result"
        )
    missing = unscreened_entities(research, compliance)
    if missing:
        problems.append(f"not screened: {', '.join(missing)}")
    return problems


def expected_decision(approval: ApprovalOutcome) -> str:
    if not approval.approved:
        return "rejected"
    return "approved_with_conditions" if approval.conditions else "approved"


def report_problems(report: DueDiligenceReport, approval: ApprovalOutcome) -> list[str]:
    problems: list[str] = []
    decision = expected_decision(approval)
    if report.decision != decision:
        problems.append(
            f"decision must be '{decision}' to match the reviewer outcome, not '{report.decision}'"
        )
    if report.risk_rating != approval.risk_rating:
        problems.append(f"risk_rating must be '{approval.risk_rating}' as set at approval")
    if approval.approved and sorted(report.conditions) != sorted(approval.conditions):
        problems.append("conditions must list exactly the conditions attached at approval")
    return problems
