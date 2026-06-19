from __future__ import annotations

import asyncio

from handoff.bootstrap import graph_policy
from handoff.config import Settings
from handoff.errors import classify
from handoff.evals.runner import EvalSummary, ScenarioResult, run_scenario, summarize
from handoff.evals.scenarios import Scenario, load_suite
from handoff.graph.state import Budget, Usage
from handoff.llm.factory import build_provider
from handoff.tools.gateway import connect_tools


async def run_suite(
    settings: Settings, suite: str, *, concurrency: int = 3
) -> tuple[EvalSummary, list[ScenarioResult]]:
    scenarios = load_suite(suite)
    llm = build_provider(settings)
    judge = build_provider(settings, model=settings.judge_model)
    policy = graph_policy(settings)
    budget = Budget(max_tokens=settings.default_max_tokens, max_usd=settings.default_max_usd)
    gate = asyncio.Semaphore(concurrency)
    async with connect_tools(settings) as tools:

        async def one(index: int) -> ScenarioResult:
            async with gate:
                return await run_scenario(
                    scenarios[index], llm=llm, judge=judge, tools=tools, policy=policy, budget=budget
                )

        outcomes = await asyncio.gather(*(one(i) for i in range(len(scenarios))), return_exceptions=True)
    results = [
        outcome if isinstance(outcome, ScenarioResult) else _crashed(scenarios[i], outcome)
        for i, outcome in enumerate(outcomes)
    ]
    return summarize(suite, settings.llm_provider, results), results


def _crashed(scenario: Scenario, exc: BaseException) -> ScenarioResult:
    if not isinstance(exc, Exception):
        raise exc
    info = classify(exc)
    return ScenarioResult(
        scenario_id=scenario.id,
        description=scenario.description,
        status="error",
        score=None,
        judge_rationale=None,
        usage=Usage(),
        duration_ms=0,
        error=f"{info.kind}: {info.message}",
    )
