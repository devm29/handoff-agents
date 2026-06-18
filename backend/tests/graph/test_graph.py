from __future__ import annotations

from typing import Any

import pytest
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.types import Command

from handoff.agents.schemas import VendorProfile
from handoff.errors import BudgetExceeded, PolicyViolation
from handoff.events.sink import MemorySink
from handoff.graph.builder import DueDiligenceGraph, build_graph
from handoff.graph.nodes import GraphContext, GraphPolicy
from handoff.graph.persistence import make_serializer
from handoff.graph.state import Budget, DueDiligenceState
from handoff.llm.fake import ScriptedFakeProvider, Transcript
from handoff.llm.types import ToolCall
from handoff.tools.gateway import MCPToolGateway

FAST_RETRY = GraphPolicy(node_max_attempts=3)


class Harness:
    def __init__(self, tools: MCPToolGateway, llm: ScriptedFakeProvider | None = None) -> None:
        self.graph: DueDiligenceGraph = build_graph(InMemorySaver(serde=make_serializer()), policy=FAST_RETRY)
        self.sink = MemorySink()
        self.context = GraphContext(
            run_id="test", llm=llm or ScriptedFakeProvider(), tools=tools, events=self.sink, policy=FAST_RETRY
        )
        self.config: Any = {"configurable": {"thread_id": "t"}, "recursion_limit": 60}

    async def start(
        self, name: str, country: str, *, budget: Budget | None = None, notes: str | None = None
    ) -> None:
        state = DueDiligenceState(
            vendor=VendorProfile(name=name, country=country, notes=notes),
            budget=budget or Budget(max_tokens=200_000, max_usd=2),
        )
        await self.graph.ainvoke(state, self.config, context=self.context)

    async def resume(self, decision: dict[str, Any]) -> None:
        await self.graph.ainvoke(Command(resume=decision), self.config, context=self.context)

    async def state(self) -> tuple[DueDiligenceState, Any]:
        snapshot = await self.graph.aget_state(self.config)
        return DueDiligenceState.model_validate(snapshot.values), snapshot


async def test_low_risk_vendor_is_auto_approved_end_to_end(tools: MCPToolGateway) -> None:
    h = Harness(tools)
    await h.start("Northwind Logistics", "DE")
    state, snapshot = await h.state()
    assert not snapshot.next
    assert state.approval is not None and state.approval.automatic
    assert state.report is not None and state.report.decision == "approved"
    assert [hf.target for hf in state.handoffs] == [
        "researcher",
        "risk_analyst",
        "compliance_checker",
        "approval",
        "report_writer",
        "finish",
    ]
    assert state.usage.llm_calls > 0 and state.usage.cost_usd > 0


async def test_sanctions_match_pauses_for_human_and_reject_is_honoured(tools: MCPToolGateway) -> None:
    h = Harness(tools)
    await h.start("Corvane Trading", "AE")
    _, snapshot = await h.state()
    assert snapshot.next == ("approval",)
    request = snapshot.interrupts[0].value
    assert request["recommendation"] == "reject"
    assert request["compliance_status"] == "match"

    await h.resume({"action": "reject", "reviewer": "lead", "comment": "SDN owner"})
    state, snapshot = await h.state()
    assert not snapshot.next
    assert state.approval is not None and not state.approval.approved
    assert state.report is not None and state.report.decision == "rejected"


async def test_edit_before_approve_overrides_rating_and_conditions(tools: MCPToolGateway) -> None:
    h = Harness(tools)
    await h.start("Helios Components", "GB")
    await h.resume(
        {
            "action": "edit",
            "reviewer": "ana",
            "edits": {"risk_rating": "medium", "conditions": ["SOC 2 in 30 days"]},
        }
    )
    state, _ = await h.state()
    assert state.approval is not None and state.approval.edited
    assert state.report is not None
    assert state.report.risk_rating == "medium"
    assert state.report.conditions == ["SOC 2 in 30 days"]
    assert state.report.decision == "approved_with_conditions"


async def test_spend_cap_stops_the_run(tools: MCPToolGateway) -> None:
    h = Harness(tools)
    with pytest.raises(BudgetExceeded):
        await h.start("Helios Components", "GB", budget=Budget(max_tokens=200_000, max_usd=0.03))
    failures = h.sink.of_type("node.failed")
    assert failures[-1]["error"]["kind"] == "BudgetExceeded"
    assert failures[-1]["will_retry"] is False


async def test_transient_model_errors_are_retried_per_node(tools: MCPToolGateway) -> None:
    h = Harness(tools)
    await h.start("Atlas Cloud Services", "US", notes="simulate:flaky-model")
    state, _ = await h.state()
    assert state.report is not None
    retried = [e for e in h.sink.of_type("node.failed") if e["will_retry"]]
    assert {e["node"] for e in retried} == {
        "researcher",
        "risk_analyst",
        "compliance_checker",
        "report_writer",
    }
    assert all(e["error"]["kind"] == "ModelError" for e in retried)
    attempts = [e["attempt"] for e in h.sink.of_type("node.completed") if e["node"] == "researcher"]
    assert attempts == [2]


class RogueResearcher(ScriptedFakeProvider):
    def _researcher(self, t: Transcript) -> ToolCall | str:
        return self._call("sanctions_check", name="Anyone", kind="person")


async def test_tool_outside_allowlist_is_a_policy_violation(tools: MCPToolGateway) -> None:
    h = Harness(tools, llm=RogueResearcher())
    with pytest.raises(PolicyViolation, match="outside its tool allowlist"):
        await h.start("Northwind Logistics", "DE")
    assert h.sink.of_type("node.failed")[0]["error"]["kind"] == "PolicyViolation"


async def test_history_supports_forking_into_a_new_thread(tools: MCPToolGateway) -> None:
    h = Harness(tools)
    await h.start("Northwind Logistics", "DE")
    history = [s async for s in h.graph.aget_state_history(h.config)]
    after_research = next(
        s
        for s in history
        if s.next == ("supervisor",) and s.values.get("research") is not None and s.values.get("risk") is None
    )
    values = DueDiligenceState.model_validate(after_research.values)
    patched = values.model_copy(update={"vendor": values.vendor.model_copy(update={"notes": "forked"})})
    fork_config: Any = {"configurable": {"thread_id": "fork"}, "recursion_limit": 60}
    await h.graph.aupdate_state(
        fork_config, {k: getattr(patched, k) for k in DueDiligenceState.model_fields}, as_node="researcher"
    )
    await h.graph.ainvoke(None, fork_config, context=h.context)
    forked = DueDiligenceState.model_validate((await h.graph.aget_state(fork_config)).values)
    assert forked.vendor.notes == "forked"
    assert forked.report is not None
    tool_calls = [s for s in forked.trajectory if s.kind == "tool_call" and s.agent == "researcher"]
    assert len(tool_calls) == 2, "research is inherited from the fork point, not redone"
