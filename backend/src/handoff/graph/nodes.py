from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Literal, Protocol

from langgraph.errors import GraphBubbleUp
from langgraph.runtime import Runtime
from langgraph.types import interrupt
from pydantic import BaseModel

from handoff.agents.checks import unscreened_entities, worst_screening
from handoff.agents.runner import AgentRunner
from handoff.agents.schemas import RISK_ORDER, RiskLevel, SupervisorDecision
from handoff.agents.specs import SPECIALISTS, SUPERVISOR, AgentSpec
from handoff.errors import LeaseLost, PolicyViolation, classify
from handoff.events.sink import EventSink
from handoff.graph.budget import BudgetGuard, SpendLedger
from handoff.graph.contracts import build_input, supervisor_input, validate_handoff
from handoff.graph.state import (
    ApprovalDecision,
    ApprovalOutcome,
    ApprovalRequest,
    DueDiligenceState,
    Handoff,
    TrajectoryStep,
)
from handoff.llm.types import LLMProvider
from handoff.tools.gateway import ToolGateway

Update = dict[str, Any]


class Node(Protocol):
    async def __call__(self, state: DueDiligenceState, *, runtime: Runtime[GraphContext]) -> Update: ...


SUPERVISOR_ATTEMPTS = 2


@dataclass(frozen=True)
class GraphPolicy:
    agent_max_turns: int = 8
    max_output_tokens: int = 8_000
    node_max_attempts: int = 3
    auto_approve_max_risk: RiskLevel | None = "low"


@dataclass
class GraphContext:
    run_id: str
    llm: LLMProvider
    tools: ToolGateway
    events: EventSink
    policy: GraphPolicy
    ledger: SpendLedger = field(default_factory=SpendLedger)

    def guard(self, state: DueDiligenceState) -> BudgetGuard:
        return BudgetGuard(state.budget, state.usage, self.ledger)


def _runner(ctx: GraphContext, guard: BudgetGuard) -> AgentRunner:
    return AgentRunner(
        run_id=ctx.run_id,
        llm=ctx.llm,
        tools=ctx.tools,
        events=ctx.events,
        budget=guard,
        max_turns=ctx.policy.agent_max_turns,
        max_output_tokens=ctx.policy.max_output_tokens,
    )


def instrument(name: str, node: Node) -> Node:
    """Emit node lifecycle events around a node, including attempts the retry policy makes."""

    async def wrapped(state: DueDiligenceState, *, runtime: Runtime[GraphContext]) -> Update:
        ctx = runtime.context
        attempt = runtime.execution_info.node_attempt if runtime.execution_info else 1
        await ctx.events.emit(ctx.run_id, "node.started", {"node": name, "attempt": attempt})
        started = time.perf_counter()
        try:
            update = await node(state, runtime=runtime)
        except (GraphBubbleUp, LeaseLost):
            raise
        except Exception as exc:
            info = classify(exc, node=name, attempt=attempt)
            will_retry = info.retryable and attempt < ctx.policy.node_max_attempts
            await ctx.events.emit(
                ctx.run_id,
                "node.failed",
                {
                    "node": name,
                    "attempt": attempt,
                    "will_retry": will_retry,
                    "error": info.model_dump(mode="json"),
                },
            )
            raise
        await ctx.events.emit(
            ctx.run_id,
            "node.completed",
            {"node": name, "attempt": attempt, "duration_ms": round((time.perf_counter() - started) * 1000)},
        )
        return update

    return wrapped


async def supervisor(state: DueDiligenceState, *, runtime: Runtime[GraphContext]) -> Update:
    ctx = runtime.context
    guard = ctx.guard(state)
    runner = _runner(ctx, guard)
    steps: list[TrajectoryStep] = []
    task = "Decide the next step of this due-diligence review."
    decision: SupervisorDecision | None = None
    for attempt in range(1, SUPERVISOR_ATTEMPTS + 1):
        result = await runner.run(SUPERVISOR, task, supervisor_input(state))
        steps.extend(result.steps)
        try:
            validate_handoff(result.output.next, state)
        except PolicyViolation as violation:
            if attempt == SUPERVISOR_ATTEMPTS:
                raise
            task = f"Your previous handoff was refused: {violation.message}. Choose a valid next step."
            continue
        decision = result.output
        break
    if decision is None:
        raise PolicyViolation("Supervisor produced no valid handoff")

    handoff = Handoff(target=decision.next, task=decision.task, rationale=decision.rationale)
    steps.append(TrajectoryStep(kind="handoff", agent="supervisor", name=handoff.target, detail=handoff.task))
    await ctx.events.emit(ctx.run_id, "handoff", handoff.model_dump(mode="json"))
    return {"active_handoff": handoff, "handoffs": [handoff], "usage": guard.delta, "trajectory": steps}


def specialist(spec: AgentSpec[BaseModel], field: str) -> Node:
    async def node(state: DueDiligenceState, *, runtime: Runtime[GraphContext]) -> Update:
        handoff = state.active_handoff
        if handoff is None or handoff.target != spec.name:
            raise PolicyViolation(f"{spec.name} was invoked without a matching handoff")
        payload = build_input(handoff.target, state)
        guard = runtime.context.guard(state)
        result = await _runner(runtime.context, guard).run(spec, handoff.task, payload)
        return {field: result.output, "usage": guard.delta, "trajectory": result.steps}

    return node


def build_approval_request(state: DueDiligenceState) -> ApprovalRequest:
    """Build the recommendation from the screening evidence, not from the status the model reported."""
    research, risk, compliance = state.research, state.risk, state.compliance
    if research is None or risk is None or compliance is None:
        raise PolicyViolation("Approval requested before research, risk and compliance completed")

    status = worst_screening(compliance)
    unscreened = unscreened_entities(research, compliance)
    conditions: list[str] = []
    flagged = [s for s in compliance.screened if s.result != "clear"]
    for entity in flagged:
        if entity.result == "potential_match":
            conditions.append(
                f"Enhanced due diligence to clear the potential sanctions match on {entity.name}"
            )
    for name in unscreened:
        conditions.append(f"Sanctions screening of {name}, which was not screened")
    if any(f.category == "cyber" for f in risk.factors):
        conditions.append("Supplier provides current SOC 2 Type II or ISO 27001 evidence within 60 days")
    if any(f.category in ("legal", "operational") and f.severity != "low" for f in risk.factors):
        conditions.append("Quarterly review of regulatory actions and remediation progress")
    if risk.rating in ("high", "critical") and not conditions:
        conditions.append("Executive sponsor sign-off and quarterly risk review")

    recommendation: Literal["approve", "approve_with_conditions", "reject"]
    if status == "match" or risk.rating == "critical":
        recommendation = "reject"
    elif conditions:
        recommendation = "approve_with_conditions"
    else:
        recommendation = "approve"

    key_findings = [f"[{f.severity}] {f.description}" for f in risk.factors]
    key_findings.extend(f"Sanctions {s.result.replace('_', ' ')}: {s.name}" for s in flagged)
    if status != compliance.status:
        key_findings.append(
            f"Compliance checker reported '{compliance.status}' but its screening results show '{status}'"
        )
    key_findings.extend(f"Not screened: {name}" for name in unscreened)
    return ApprovalRequest(
        vendor=research.legal_name,
        recommendation=recommendation,
        risk_rating=risk.rating,
        risk_score=risk.score,
        compliance_status=status,
        summary=f"{risk.rationale} Sanctions screening: {compliance.notes}",
        conditions=conditions if recommendation != "reject" else [],
        key_findings=key_findings,
    )


def _auto_approvable(request: ApprovalRequest, policy: GraphPolicy) -> bool:
    limit = policy.auto_approve_max_risk
    return (
        limit is not None
        and request.recommendation == "approve"
        and request.compliance_status == "clear"
        and RISK_ORDER[request.risk_rating] <= RISK_ORDER[limit]
    )


async def approval_gate(state: DueDiligenceState, *, runtime: Runtime[GraphContext]) -> Update:
    request = build_approval_request(state)
    if _auto_approvable(request, runtime.context.policy):
        decision = ApprovalDecision(action="approve", reviewer="policy:auto-approve", automatic=True)
    else:
        decision = interrupt(request.model_dump(mode="json"), response_schema=ApprovalDecision)

    edits = decision.edits if decision.action == "edit" else None
    outcome = ApprovalOutcome(
        approved=decision.action != "reject",
        edited=edits is not None,
        automatic=decision.automatic,
        reviewer=decision.reviewer,
        comment=decision.comment,
        risk_rating=edits.risk_rating if edits and edits.risk_rating else request.risk_rating,
        conditions=edits.conditions if edits and edits.conditions is not None else request.conditions,
        summary=edits.summary if edits and edits.summary else request.summary,
    )
    step = TrajectoryStep(
        kind="approval",
        agent="approval",
        name=decision.action,
        detail=f"{decision.reviewer}{' (automatic)' if decision.automatic else ''}",
    )
    return {"approval": outcome, "trajectory": [step]}


SPECIALIST_FIELDS: dict[str, str] = {
    "researcher": "research",
    "risk_analyst": "risk",
    "compliance_checker": "compliance",
    "report_writer": "report",
}


def specialist_nodes() -> dict[str, Node]:
    return {name: specialist(SPECIALISTS[name], field) for name, field in SPECIALIST_FIELDS.items()}
