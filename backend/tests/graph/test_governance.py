from __future__ import annotations

from typing import Any

import pytest

from handoff.agents.schemas import (
    ComplianceResult,
    ResearchFindings,
    RiskAssessment,
    ScreenedEntity,
    VendorProfile,
)
from handoff.errors import BudgetExceeded, PolicyViolation
from handoff.graph.nodes import GraphPolicy, _auto_approvable, build_approval_request
from handoff.graph.state import Budget, DueDiligenceState
from handoff.llm.fake import ScriptedFakeProvider, Transcript
from handoff.llm.types import AssistantMessage, ChatRequest, ChatResponse, TokenUsage, ToolCall
from handoff.tools.gateway import MCPToolGateway

from .test_graph import Harness


class ClaimsClearCompliance(ScriptedFakeProvider):
    """Screens properly, then reports the run as clear no matter what the screening found."""

    def _compliance_checker(self, t: Transcript) -> ToolCall | str:
        decision = super()._compliance_checker(t)
        if isinstance(decision, ToolCall) and decision.name == "submit_compliance":
            decision.arguments["status"] = "clear"
        return decision


class SkipsAnOwner(ScriptedFakeProvider):
    def _compliance_checker(self, t: Transcript) -> ToolCall | str:
        decision = super()._compliance_checker(t)
        if isinstance(decision, ToolCall) and decision.name == "submit_compliance":
            decision.arguments["screened"] = decision.arguments["screened"][:1]
            decision.arguments["status"] = "clear"
        return decision


class TruncatesEveryResearcherReply(ScriptedFakeProvider):
    """The researcher always runs out of output tokens after a large, expensive prompt."""

    async def chat(self, request: ChatRequest) -> ChatResponse:
        if request.agent != "researcher":
            return await super().chat(request)
        return ChatResponse(
            message=AssistantMessage(text="Partial answer"),
            stop_reason="max_tokens",
            usage=TokenUsage(input_tokens=18_000, output_tokens=2_000),
            model="scripted-fake",
        )


async def test_compliance_status_that_contradicts_the_screening_is_refused(tools: MCPToolGateway) -> None:
    h = Harness(tools, llm=ClaimsClearCompliance())
    with pytest.raises(PolicyViolation, match="contradicts the record"):
        await h.start("Corvane Trading", "AE")
    _, snapshot = await h.state()
    assert snapshot.values.get("approval") is None, "the vendor never reached approval"


async def test_compliance_that_skips_a_beneficial_owner_is_refused(tools: MCPToolGateway) -> None:
    h = Harness(tools, llm=SkipsAnOwner())
    with pytest.raises(PolicyViolation, match="not screened"):
        await h.start("Atlas Cloud Services", "US")


def _research(owners: list[str]) -> ResearchFindings:
    return ResearchFindings.model_validate(
        {
            "legal_name": "Acme Ltd",
            "registration_number": "1",
            "jurisdiction": "GB",
            "status": "active",
            "incorporated_on": None,
            "industry": None,
            "address": None,
            "beneficial_owners": [{"name": n, "role": "director"} for n in owners],
            "summary": "ok",
        }
    )


def _state(compliance: ComplianceResult, owners: list[str]) -> DueDiligenceState:
    return DueDiligenceState(
        vendor=VendorProfile(name="Acme", country="GB"),
        budget=Budget(max_tokens=10_000, max_usd=1),
        research=_research(owners),
        risk=RiskAssessment(rating="low", score=5, rationale="Nothing adverse."),
        compliance=compliance,
    )


def test_gate_derives_status_from_screening_not_from_the_model() -> None:
    lying = ComplianceResult(
        status="clear",
        screened=[
            ScreenedEntity(name="Acme Ltd", kind="company", result="clear"),
            ScreenedEntity(name="Ivan Petrov", kind="person", result="match"),
        ],
        notes="All clear.",
    )
    request = build_approval_request(_state(lying, ["Ivan Petrov"]))
    assert request.compliance_status == "match"
    assert request.recommendation == "reject"
    assert not _auto_approvable(request, GraphPolicy())
    assert any("reported 'clear'" in f for f in request.key_findings)


def test_gate_will_not_auto_approve_with_unscreened_owners() -> None:
    partial = ComplianceResult(
        status="clear",
        screened=[ScreenedEntity(name="Acme Ltd", kind="company", result="clear")],
        notes="Screened the company.",
    )
    request = build_approval_request(_state(partial, ["Dana Wu"]))
    assert request.recommendation == "approve_with_conditions"
    assert any("Dana Wu" in c for c in request.conditions)
    assert not _auto_approvable(request, GraphPolicy())


async def test_budget_counts_spend_from_failed_attempts(tools: MCPToolGateway) -> None:
    h = Harness(tools, llm=TruncatesEveryResearcherReply())
    budget = Budget(max_tokens=50_000, max_usd=0.5)
    with pytest.raises(BudgetExceeded):
        await h.start("Northwind Logistics", "DE", budget=budget)

    failures: list[dict[str, Any]] = h.sink.of_type("node.failed")
    assert [f["error"]["kind"] for f in failures] == ["ModelError", "ModelError", "BudgetExceeded"]
    spent = h.context.ledger.usage
    one_call = 20_000
    assert spent.total_tokens < budget.max_tokens + one_call, "no call starts once the cap is reached"
    state, _ = await h.state()
    assert state.usage.total_tokens < spent.total_tokens, "graph state alone would have missed the retries"
