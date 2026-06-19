"""Trajectory metrics: how the agents worked, not only what they concluded."""

from __future__ import annotations

from collections.abc import Sequence

from pydantic import BaseModel

from handoff.evals.scenarios import Expectation
from handoff.graph.state import DueDiligenceState

WEIGHTS = {
    "tool_sequence": 0.25,
    "handoff_order": 0.15,
    "efficiency": 0.15,
    "outcome": 0.25,
    "reasoning": 0.20,
}
PASS_THRESHOLD = 0.8


def lcs_length(a: Sequence[str], b: Sequence[str]) -> int:
    previous = [0] * (len(b) + 1)
    for x in a:
        current = [0]
        for j, y in enumerate(b, start=1):
            current.append(previous[j - 1] + 1 if x == y else max(previous[j], current[j - 1]))
        previous = current
    return previous[-1]


def sequence_similarity(expected: Sequence[str], actual: Sequence[str]) -> float:
    """LCS over the longer sequence: penalises missing, extra and out-of-order steps alike."""
    longest = max(len(expected), len(actual))
    return 1.0 if longest == 0 else lcs_length(expected, actual) / longest


class TrajectoryScore(BaseModel):
    tool_sequence: float
    exact_tool_match: bool
    handoff_order: float
    efficiency: float
    outcome: float
    reasoning: float
    overall: float
    passed: bool
    actual_tools: dict[str, list[str]]
    actual_handoffs: list[str]
    mismatches: list[str]


def actual_tools(state: DueDiligenceState) -> dict[str, list[str]]:
    tools: dict[str, list[str]] = {}
    for step in state.trajectory:
        if step.kind == "tool_call":
            tools.setdefault(step.agent, []).append(step.name)
    return tools


def score(
    state: DueDiligenceState, expected: Expectation, *, judge_score: int, required_human: bool
) -> TrajectoryScore:
    tools = actual_tools(state)
    agents = sorted(set(expected.tools) | set(tools))
    per_agent = [sequence_similarity(expected.tools.get(a, []), tools.get(a, [])) for a in agents]
    tool_sequence = sum(per_agent) / len(per_agent) if per_agent else 1.0
    exact = all(expected.tools.get(a, []) == tools.get(a, []) for a in agents)

    handoffs: list[str] = [h.target for h in state.handoffs]
    handoff_order = sequence_similarity(list(expected.handoffs), handoffs)

    optimal = sum(len(v) for v in expected.tools.values())
    taken = sum(len(v) for v in tools.values())
    efficiency = min(1.0, optimal / taken) if taken else 0.0

    mismatches: list[str] = []
    checks = {
        "risk_rating": (expected.risk_rating, state.approval.risk_rating if state.approval else None),
        "compliance_status": (
            expected.compliance_status,
            state.compliance.status if state.compliance else None,
        ),
        "decision": (expected.decision, state.report.decision if state.report else None),
        "requires_human": (expected.requires_human, required_human),
    }
    for name, (want, got) in checks.items():
        if want != got:
            mismatches.append(f"{name}: expected {want}, got {got}")
    for agent in agents:
        if expected.tools.get(agent, []) != tools.get(agent, []):
            mismatches.append(
                f"{agent} tools: expected {expected.tools.get(agent, [])}, got {tools.get(agent, [])}"
            )
    outcome = 1 - sum(1 for n in checks if any(m.startswith(f"{n}:") for m in mismatches)) / len(checks)

    reasoning = (judge_score - 1) / 4
    parts = {
        "tool_sequence": tool_sequence,
        "handoff_order": handoff_order,
        "efficiency": efficiency,
        "outcome": outcome,
        "reasoning": reasoning,
    }
    overall = sum(WEIGHTS[k] * v for k, v in parts.items())
    return TrajectoryScore(
        tool_sequence=round(tool_sequence, 3),
        exact_tool_match=exact,
        handoff_order=round(handoff_order, 3),
        efficiency=round(efficiency, 3),
        outcome=round(outcome, 3),
        reasoning=round(reasoning, 3),
        overall=round(overall, 3),
        passed=overall >= PASS_THRESHOLD and outcome == 1.0,
        actual_tools=tools,
        actual_handoffs=handoffs,
        mismatches=mismatches,
    )
