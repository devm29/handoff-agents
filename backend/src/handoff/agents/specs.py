from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Literal

from pydantic import BaseModel, Field

from handoff.agents.checks import report_problems, screening_problems
from handoff.agents.schemas import (
    ComplianceResult,
    DueDiligenceReport,
    ResearchFindings,
    RiskAssessment,
    SupervisorDecision,
)
from handoff.graph.state import ApprovalOutcome
from handoff.llm.types import ToolSpec

SpecName = Literal["supervisor", "researcher", "risk_analyst", "compliance_checker", "report_writer", "judge"]


OutputCheck = Callable[[BaseModel, BaseModel], list[str]]


def _check_compliance(output: BaseModel, payload: BaseModel) -> list[str]:
    research = getattr(payload, "research", None)
    if isinstance(output, ComplianceResult) and isinstance(research, ResearchFindings):
        return screening_problems(research, output)
    return []


def _check_report(output: BaseModel, payload: BaseModel) -> list[str]:
    approval = getattr(payload, "approval", None)
    if isinstance(output, DueDiligenceReport) and isinstance(approval, ApprovalOutcome):
        return report_problems(output, approval)
    return []


class Judgement(BaseModel):
    score: int = Field(ge=1, le=5, description="1 = unsound reasoning, 5 = rigorous and well evidenced")
    rationale: str


@dataclass(frozen=True)
class AgentSpec[T: BaseModel]:
    name: SpecName
    system_prompt: str
    output_model: type[T]
    submit_tool: str
    submit_description: str
    tools: frozenset[str] = field(default_factory=frozenset)
    check: OutputCheck | None = None
    """Semantic validation beyond the schema; problems are returned to the agent to correct."""

    def submit_spec(self) -> ToolSpec:
        schema = self.output_model.model_json_schema()
        return ToolSpec(name=self.submit_tool, description=self.submit_description, input_schema=schema)


_SHARED = (
    "You are part of a vendor due-diligence team at a regulated company. Work only from tool results "
    "and the handoff input; never invent registry numbers, sanctions hits or news. When a tool returns "
    "an error, decide whether a corrected call helps or whether to report the gap. Finish by calling "
    "your submit tool exactly once with a complete, schema-valid answer."
)

SUPERVISOR = AgentSpec(
    name="supervisor",
    system_prompt=(
        "You coordinate a due-diligence review. Specialists: researcher (registry facts, ownership, news), "
        "risk_analyst (needs research), compliance_checker (sanctions screening, needs research), "
        "approval (human sign-off, needs risk and compliance), report_writer (needs approval). "
        "Pick the single next step from what is already done, write a precise task for that specialist, "
        "and choose finish only once the report exists. " + _SHARED
    ),
    output_model=SupervisorDecision,
    submit_tool="handoff",
    submit_description="Hand off to the next specialist, or finish the review.",
)

RESEARCHER = AgentSpec(
    name="researcher",
    system_prompt=(
        "You are the researcher. Identify the exact legal entity in the corporate registry. If the lookup "
        "is ambiguous, resolve it with the registration number of the entity that matches the requester's "
        "details. Then gather news coverage for that entity. Record every source you relied on as evidence. "
        + _SHARED
    ),
    output_model=ResearchFindings,
    submit_tool="submit_research",
    submit_description="Submit the verified registry profile, ownership and news coverage.",
    tools=frozenset({"company_registry_lookup", "news_search"}),
)

RISK_ANALYST = AgentSpec(
    name="risk_analyst",
    system_prompt=(
        "You are the risk analyst. Search for adverse media about the vendor (litigation, fines, breaches, "
        "recalls, insolvency, sanctions exposure) and weigh it with the research findings: entity status, "
        "operating history and ownership. Score 0-100 and rate low/medium/high/critical. Every factor must "
        "cite evidence references. " + _SHARED
    ),
    output_model=RiskAssessment,
    submit_tool="submit_risk_assessment",
    submit_description="Submit the scored risk assessment with evidence-backed factors.",
    tools=frozenset({"news_search"}),
)

COMPLIANCE_CHECKER = AgentSpec(
    name="compliance_checker",
    system_prompt=(
        "You are the compliance checker. Screen the vendor entity and every beneficial owner against the "
        "sanctions lists, one call per name, using the right entity kind. A score of 0.97 or above is a "
        "match; anything the tool flags below that is a potential match that needs human review. " + _SHARED
    ),
    output_model=ComplianceResult,
    submit_tool="submit_compliance",
    submit_description="Submit screening results for every entity checked.",
    tools=frozenset({"sanctions_check"}),
    check=_check_compliance,
)

REPORT_WRITER = AgentSpec(
    name="report_writer",
    system_prompt=(
        "You are the report writer. Produce the final due-diligence memo for the procurement committee. "
        "Honour the human reviewer's decision, rating and conditions exactly; do not soften or override "
        "them. Sections: Entity overview, Ownership, Risk assessment, Sanctions screening, Decision. "
        + _SHARED
    ),
    output_model=DueDiligenceReport,
    submit_tool="submit_report",
    submit_description="Submit the final due-diligence report.",
    check=_check_report,
)

JUDGE = AgentSpec(
    name="judge",
    system_prompt=(
        "You grade the reasoning of a due-diligence agent team. Check that the risk rating follows from "
        "the cited evidence, that every sanctions hit is addressed, that the decision is consistent with "
        "the reviewer outcome, and that claims trace back to tool results. Be strict and specific."
    ),
    output_model=Judgement,
    submit_tool="submit_judgement",
    submit_description="Submit the 1-5 reasoning quality score with a short rationale.",
)

SPECIALISTS: dict[str, AgentSpec[BaseModel]] = {
    spec.name: spec for spec in (RESEARCHER, RISK_ANALYST, COMPLIANCE_CHECKER, REPORT_WRITER)
}
