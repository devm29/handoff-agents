from __future__ import annotations

import time
from typing import Any

from langgraph.checkpoint.memory import InMemorySaver
from langgraph.types import Command
from pydantic import BaseModel

from handoff.agents.runner import AgentRunner
from handoff.agents.specs import JUDGE
from handoff.errors import PolicyViolation, classify
from handoff.evals.scenarios import Scenario
from handoff.evals.scorers import TrajectoryScore, score
from handoff.events.sink import MemorySink
from handoff.graph.budget import BudgetGuard, SpendLedger
from handoff.graph.builder import build_graph
from handoff.graph.nodes import GraphContext, GraphPolicy
from handoff.graph.persistence import make_serializer
from handoff.graph.state import Budget, DueDiligenceState, Usage
from handoff.llm.types import LLMProvider
from handoff.tools.gateway import ToolGateway

JUDGE_BUDGET = Budget(max_tokens=60_000, max_usd=0.5)


class ScenarioResult(BaseModel):
    scenario_id: str
    description: str
    status: str
    score: TrajectoryScore | None
    judge_rationale: str | None
    usage: Usage
    duration_ms: int
    error: str | None = None


class EvalSummary(BaseModel):
    suite: str
    provider: str
    scenarios: int
    passed: int
    pass_rate: float
    mean: dict[str, float]
    total_cost_usd: float
    total_tokens: int


class ToolEvidence(BaseModel):
    agent: str
    tool: str
    arguments: dict[str, Any]
    ok: bool
    result_preview: str | None


class JudgeInput(BaseModel):
    vendor: dict[str, Any]
    research: dict[str, Any] | None
    risk: dict[str, Any] | None
    compliance: dict[str, Any] | None
    approval: dict[str, Any] | None
    report: dict[str, Any] | None
    tool_calls: list[ToolEvidence]
    trajectory: list[str]


def _judge_input(state: DueDiligenceState) -> JudgeInput:
    def dump(model: BaseModel | None) -> dict[str, Any] | None:
        return model.model_dump(mode="json") if model is not None else None

    return JudgeInput(
        vendor=state.vendor.model_dump(mode="json"),
        research=dump(state.research),
        risk=dump(state.risk),
        compliance=dump(state.compliance),
        approval=dump(state.approval),
        report=dump(state.report),
        tool_calls=[
            ToolEvidence(
                agent=s.agent, tool=s.name, arguments=s.arguments, ok=s.ok, result_preview=s.result_preview
            )
            for s in state.trajectory
            if s.kind == "tool_call"
        ],
        trajectory=[f"{s.agent}:{s.kind}:{s.name}" for s in state.trajectory if s.kind != "llm_call"],
    )


async def run_scenario(
    scenario: Scenario,
    *,
    llm: LLMProvider,
    judge: LLMProvider,
    tools: ToolGateway,
    policy: GraphPolicy,
    budget: Budget,
) -> ScenarioResult:
    """Run one scenario end to end and score it. Never raises: any failure, including one from
    the judge, becomes an `error` result that keeps whatever was spent before it."""
    graph = build_graph(InMemorySaver(serde=make_serializer()), policy=policy)
    ledger = SpendLedger()
    context = GraphContext(
        run_id=scenario.id, llm=llm, tools=tools, events=MemorySink(), policy=policy, ledger=ledger
    )
    config: Any = {"configurable": {"thread_id": scenario.id}, "recursion_limit": 60}
    judge_guard = BudgetGuard(JUDGE_BUDGET, Usage())
    started = time.perf_counter()

    def elapsed() -> int:
        return round((time.perf_counter() - started) * 1000)

    try:
        required_human = False
        await graph.ainvoke(DueDiligenceState(vendor=scenario.vendor, budget=budget), config, context=context)
        snapshot = await graph.aget_state(config)
        while snapshot.interrupts:
            required_human = True
            if scenario.reviewer is None:
                raise PolicyViolation("Scenario hit the approval gate but defines no reviewer decision")
            resume = scenario.reviewer.model_dump(mode="json")
            await graph.ainvoke(Command(resume=resume), config, context=context)
            snapshot = await graph.aget_state(config)

        state = DueDiligenceState.model_validate(snapshot.values)
        runner = AgentRunner(
            run_id=f"judge-{scenario.id}",
            llm=judge,
            tools=tools,
            events=MemorySink(),
            budget=judge_guard,
            max_turns=3,
            max_output_tokens=4_000,
        )
        verdict = await runner.run(
            JUDGE, "Grade the reasoning quality of this completed due-diligence run.", _judge_input(state)
        )
    except Exception as exc:
        info = classify(exc)
        return ScenarioResult(
            scenario_id=scenario.id,
            description=scenario.description,
            status="error",
            score=None,
            judge_rationale=None,
            usage=ledger.usage + judge_guard.delta,
            duration_ms=elapsed(),
            error=f"{info.kind}: {info.message}",
        )

    result = score(state, scenario.expected, judge_score=verdict.output.score, required_human=required_human)
    return ScenarioResult(
        scenario_id=scenario.id,
        description=scenario.description,
        status="passed" if result.passed else "failed",
        score=result,
        judge_rationale=verdict.output.rationale,
        usage=ledger.usage + judge_guard.delta,
        duration_ms=elapsed(),
    )


def summarize(suite: str, provider: str, results: list[ScenarioResult]) -> EvalSummary:
    scored = [r.score for r in results if r.score is not None]
    metrics = ("tool_sequence", "handoff_order", "efficiency", "outcome", "reasoning", "overall")
    mean = {m: round(sum(getattr(s, m) for s in scored) / len(scored), 3) if scored else 0.0 for m in metrics}
    passed = sum(1 for r in results if r.status == "passed")
    return EvalSummary(
        suite=suite,
        provider=provider,
        scenarios=len(results),
        passed=passed,
        pass_rate=round(passed / len(results), 3) if results else 0.0,
        mean=mean,
        total_cost_usd=round(sum(r.usage.cost_usd for r in results), 4),
        total_tokens=sum(r.usage.total_tokens for r in results),
    )
