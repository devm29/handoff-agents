from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import uuid4

import anyio
import pytest

from handoff.auth import Principal, ReviewerDirectory
from handoff.config import DEMO_REVIEWERS, Settings
from handoff.db.models import ApprovalRow
from handoff.errors import ModelError, PermissionDeniedError, ToolError, UnprocessableError
from handoff.evals.runner import run_scenario
from handoff.evals.scenarios import load_suite
from handoff.events.broker import RESYNC_TYPE, EventBroker
from handoff.graph.nodes import GraphPolicy
from handoff.graph.state import Budget
from handoff.llm.fake import ScriptedFakeProvider
from handoff.llm.types import ChatRequest, ChatResponse
from handoff.services.approvals import EscalationPolicy
from handoff.services.dto import DecisionRequest
from handoff.tools.gateway import connect_tools

TIERS = ["analyst", "compliance-lead", "chief-risk-officer"]


async def test_mcp_gateway_reconnects_after_the_transport_breaks() -> None:
    async with connect_tools(Settings(mcp_transport="inprocess")) as gateway:
        first = await gateway._current()

        async def broken(*_: Any, **__: Any) -> Any:
            raise anyio.BrokenResourceError

        first.call_tool = broken  # type: ignore[method-assign]
        with pytest.raises(ToolError) as failure:
            await gateway.call("sanctions_check", {"name": "Dana Wu", "kind": "person"})
        assert failure.value.retryable

        outcome = await gateway.call("sanctions_check", {"name": "Dana Wu", "kind": "person"})
        assert not outcome.is_error
        assert gateway.reconnects == 1
        assert await gateway._current() is not first
        assert gateway.connection_state() == "connected"
    assert gateway.connection_state() == "closed"


async def test_lagging_subscriber_gets_a_resync_marker_instead_of_silent_drops() -> None:
    broker = EventBroker("postgresql://unused")
    async with broker.subscribe("run-1") as queue:
        size = queue.maxsize
        for i in range(size + 5):
            broker.publish({"id": i, "run_id": "run-1", "type": "llm.call"})
        drained = [queue.get_nowait() for _ in range(queue.qsize())]
    # The event that overflowed is replaced by the marker; the stream re-reads it from the database.
    assert drained[0]["type"] == RESYNC_TYPE
    assert [m["id"] for m in drained[1:]] == list(range(size + 1, size + 5))


class JudgeRefuses(ScriptedFakeProvider):
    async def chat(self, request: ChatRequest) -> ChatResponse:
        raise ModelError("Model declined the request", retryable=False)


async def test_a_failing_judge_becomes_an_error_result(tools: Any) -> None:
    scenario = load_suite("default")[0]
    result = await run_scenario(
        scenario,
        llm=ScriptedFakeProvider(),
        judge=JudgeRefuses(),
        tools=tools,
        policy=GraphPolicy(),
        budget=Budget(max_tokens=200_000, max_usd=2),
    )
    assert result.status == "error"
    assert result.error == "ModelError: Model declined the request"
    assert result.usage.llm_calls > 0, "spend before the failure is kept"


def _approval(*, compliance: str, level: int = 0) -> ApprovalRow:
    return ApprovalRow(
        id=uuid4(),
        run_id=uuid4(),
        interrupt_id="i",
        status="pending",
        request={"compliance_status": compliance},
        assignee=TIERS[level],
        escalation_level=level,
        due_at=datetime.now(UTC) + timedelta(hours=1),
    )


def _reviewer(role: str) -> Principal:
    return Principal(name=role.title(), role=role, tier=TIERS.index(role))


@pytest.fixture
def policy() -> EscalationPolicy:
    return EscalationPolicy(TIERS, timedelta(hours=1))


def test_reviewer_below_the_assigned_tier_cannot_decide(policy: EscalationPolicy) -> None:
    escalated = _approval(compliance="clear", level=1)
    with pytest.raises(PermissionDeniedError, match="assigned to compliance-lead"):
        policy.check_reviewer(escalated, DecisionRequest(action="approve"), _reviewer("analyst"))
    policy.check_reviewer(escalated, DecisionRequest(action="approve"), _reviewer("chief-risk-officer"))


def test_confirmed_match_needs_the_top_tier_and_a_justification(policy: EscalationPolicy) -> None:
    match = _approval(compliance="match")
    policy.check_reviewer(match, DecisionRequest(action="reject"), _reviewer("analyst"))
    with pytest.raises(PermissionDeniedError, match="chief-risk-officer"):
        policy.check_reviewer(match, DecisionRequest(action="approve"), _reviewer("compliance-lead"))
    with pytest.raises(UnprocessableError, match="justification"):
        policy.check_reviewer(
            match, DecisionRequest(action="approve", comment=" "), _reviewer("chief-risk-officer")
        )
    policy.check_reviewer(
        match,
        DecisionRequest(action="approve", comment="Licence OFAC-2026-118 covers this supply."),
        _reviewer("chief-risk-officer"),
    )


def test_directory_authenticates_by_token_only() -> None:
    directory = ReviewerDirectory(DEMO_REVIEWERS, TIERS)
    principal = directory.authenticate("demo-cro-token")
    assert principal is not None and (principal.role, principal.tier) == ("chief-risk-officer", 2)
    assert directory.authenticate("demo-cro-token ") is None
    assert directory.authenticate("") is None


def test_production_refuses_demo_tokens() -> None:
    with pytest.raises(ValueError, match="demo reviewer tokens"):
        Settings(environment="production")
