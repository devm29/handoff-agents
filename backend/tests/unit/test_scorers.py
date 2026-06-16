from __future__ import annotations

from handoff.agents.schemas import VendorProfile
from handoff.evals.scenarios import Expectation, load_suite
from handoff.evals.scorers import lcs_length, score, sequence_similarity
from handoff.graph.state import Budget, DueDiligenceState, Handoff, TrajectoryStep


def test_lcs_and_similarity() -> None:
    assert lcs_length(["a", "b", "c"], ["a", "c"]) == 2
    assert sequence_similarity(["a", "b"], ["a", "b"]) == 1.0
    assert sequence_similarity(["a"], ["a", "a"]) == 0.5
    assert sequence_similarity([], []) == 1.0


def _state(tools: list[tuple[str, str]]) -> DueDiligenceState:
    return DueDiligenceState(
        vendor=VendorProfile(name="Acme", country="US"),
        budget=Budget(max_tokens=1_000, max_usd=1),
        handoffs=[Handoff(target="researcher", task="t", rationale="r")],
        trajectory=[TrajectoryStep(kind="tool_call", agent=a, name=n) for a, n in tools],
    )


def test_extra_tool_call_costs_efficiency_and_sequence_points() -> None:
    expected = Expectation(
        handoffs=["researcher"],
        tools={"researcher": ["company_registry_lookup"]},
        risk_rating="low",
        compliance_status="clear",
        decision="approved",
        requires_human=False,
    )
    result = score(
        _state([("researcher", "company_registry_lookup"), ("researcher", "company_registry_lookup")]),
        expected,
        judge_score=5,
        required_human=False,
    )
    assert result.efficiency == 0.5
    assert result.tool_sequence == 0.5
    assert not result.exact_tool_match
    assert not result.passed
    assert any(m.startswith("risk_rating") for m in result.mismatches)


def test_default_suite_loads() -> None:
    suite = load_suite("default")
    assert len(suite) >= 8
    assert len({s.id for s in suite}) == len(suite)
