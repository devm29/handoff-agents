from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any, Literal
from uuid import UUID

import structlog
from langgraph.types import Command
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from handoff.agents.checks import expected_decision
from handoff.db.models import RunRow, RunStatus
from handoff.db.repositories import EventRepository, RunRepository
from handoff.errors import LeaseLost, classify
from handoff.graph.budget import SpendLedger
from handoff.graph.builder import DueDiligenceGraph
from handoff.graph.nodes import GraphContext, GraphPolicy
from handoff.graph.state import DueDiligenceState, Usage
from handoff.llm.types import LLMProvider
from handoff.services.approvals import ApprovalService
from handoff.services.runs import thread_config
from handoff.telemetry.otel import mark_error, run_span, span_reference
from handoff.tools.gateway import ToolGateway
from handoff.worker.sink import DatabaseEventSink

log = structlog.get_logger(__name__)

RECURSION_LIMIT = 60

StopReason = Literal["cancelled", "lease_lost"]


def _ledger_from(run: RunRow) -> SpendLedger:
    return SpendLedger(
        usage=Usage(
            input_tokens=run.input_tokens,
            output_tokens=run.output_tokens,
            cost_usd=run.cost_usd,
            llm_calls=run.llm_calls,
            tool_calls=run.tool_calls,
        )
    )


class RunExecutor:
    """Drives one run's graph from wherever its thread checkpoint left off.

    `fence` is the claim count the worker obtained when it claimed the run. Every status
    write is conditional on it, so a worker whose lease went stale cannot clobber the state
    written by the worker that reclaimed the run.
    """

    def __init__(
        self,
        *,
        sessions: async_sessionmaker[AsyncSession],
        graph: DueDiligenceGraph,
        llm: LLMProvider,
        tools: ToolGateway,
        approvals: ApprovalService,
        policy: GraphPolicy,
    ) -> None:
        self._sessions = sessions
        self._graph = graph
        self._llm = llm
        self._tools = tools
        self._approvals = approvals
        self._policy = policy

    async def execute(self, run_id: UUID, *, fence: int) -> None:
        async with self._sessions() as session:
            run = await RunRepository(session).get(run_id)
        if run is None or run.status != "running" or run.claims != fence:
            return

        config = thread_config(run.thread_id) | {"recursion_limit": RECURSION_LIMIT}
        snapshot = await self._graph.aget_state(config)
        has_checkpoint = snapshot.created_at is not None
        graph_input: Any
        if run.resume_payload is not None and snapshot.interrupts:
            graph_input = Command(resume=run.resume_payload)
        elif has_checkpoint:
            graph_input = None
        else:
            graph_input = DueDiligenceState.model_validate(run.initial_state)

        bound = log.bind(run_id=str(run_id), vendor=run.vendor_name, claims=fence)
        sink = DatabaseEventSink(self._sessions, fence=fence)
        ledger = _ledger_from(run)
        context = GraphContext(
            run_id=str(run_id),
            llm=self._llm,
            tools=self._tools,
            events=sink,
            policy=self._policy,
            ledger=ledger,
        )
        with run_span(
            str(run_id), vendor=run.vendor_name, claims=fence, first_execution=run.trace_context
        ) as span:
            try:
                if run.trace_context is None and (reference := span_reference(span)) is not None:
                    await self._fenced(
                        run_id, lambda repo: repo.set_trace_context(run_id, reference, fence=fence)
                    )
                bound.info("run.started", resumed=has_checkpoint)
                await sink.emit(
                    str(run_id),
                    "run.status",
                    {
                        "status": "running",
                        "resumed": has_checkpoint,
                        "recovered": graph_input is None and fence > 1,
                        "claims": fence,
                        "resuming_approval": isinstance(graph_input, Command),
                    },
                )
                stopped = await self._drive(run_id, fence, graph_input, config, context)
                if stopped == "cancelled":
                    await self._finish(run_id, fence, "cancelled", {"status": "cancelled"})
                    bound.info("run.cancelled")
                elif stopped is None:
                    await self._settle(run_id, fence, config)
            except LeaseLost:
                span.set_attribute("handoff.run.outcome", "lease_lost")
                bound.warning("run.lease_lost")
            except Exception as exc:
                mark_error(span, exc)
                await self._fail(run_id, fence, exc, bound)
            finally:
                usage = ledger.usage
                span.set_attribute("gen_ai.usage.input_tokens", usage.input_tokens)
                span.set_attribute("gen_ai.usage.output_tokens", usage.output_tokens)
                span.set_attribute("handoff.run.cost_usd", round(usage.cost_usd, 6))

    async def _drive(
        self, run_id: UUID, fence: int, graph_input: Any, config: Any, context: GraphContext
    ) -> StopReason | None:
        async for _ in self._graph.astream(graph_input, config, context=context, stream_mode="updates"):
            stop = await self._stop_reason(run_id, fence)
            if stop == "lease_lost":
                raise LeaseLost(str(run_id))
            if stop is not None:
                return stop
        return None

    async def _fail(self, run_id: UUID, fence: int, exc: Exception, bound: Any) -> None:
        async with self._sessions() as session:
            current = await RunRepository(session).get(run_id)
        info = classify(exc, node=current.current_node if current else None)
        bound.warning("run.failed", kind=info.kind, error=info.message)
        try:
            await self._finish(
                run_id,
                fence,
                "failed",
                {"status": "failed", "error": info.model_dump(mode="json")},
                error=info.model_dump(mode="json"),
            )
        except LeaseLost:
            bound.warning("run.lease_lost")

    async def _settle(self, run_id: UUID, fence: int, config: Any) -> None:
        snapshot = await self._graph.aget_state(config)
        if snapshot.interrupts:
            interrupt = snapshot.interrupts[0]
            request = dict(interrupt.value) if isinstance(interrupt.value, dict) else {}
            async with self._sessions.begin() as session:
                run = await RunRepository(session).get(run_id, for_update=True)
                if run is None or run.claims != fence:
                    raise LeaseLost(str(run_id))
                await self._approvals.create_pending(
                    session,
                    run=run,
                    interrupt_id=interrupt.id,
                    request=request,
                    response_schema=getattr(interrupt, "response_schema", None),
                )
                moved = await RunRepository(session).transition(
                    run_id,
                    "awaiting_approval",
                    fence=fence,
                    resume_payload=None,
                    risk_rating=request.get("risk_rating"),
                )
                if not moved:
                    raise LeaseLost(str(run_id))
                await EventRepository(session).append(run_id, "run.status", {"status": "awaiting_approval"})
            log.info("run.awaiting_approval", run_id=str(run_id))
            return

        if snapshot.next:
            log.warning("run.stalled", run_id=str(run_id), next=list(snapshot.next))
            return

        state = DueDiligenceState.model_validate(snapshot.values)
        approval = state.approval
        decision = expected_decision(approval) if approval else None
        status: RunStatus = "rejected" if approval is not None and not approval.approved else "completed"
        await self._finish(
            run_id,
            fence,
            status,
            {"status": status, "decision": decision},
            report=state.report.model_dump(mode="json") if state.report else None,
            risk_rating=approval.risk_rating if approval else (state.risk.rating if state.risk else None),
            decision=decision,
        )
        log.info("run.finished", run_id=str(run_id), status=status)

    async def _finish(
        self, run_id: UUID, fence: int, status: RunStatus, event: dict[str, Any], **fields: Any
    ) -> None:
        async with self._sessions.begin() as session:
            moved = await RunRepository(session).transition(
                run_id, status, fence=fence, resume_payload=None, **fields
            )
            if not moved:
                raise LeaseLost(str(run_id))
            await EventRepository(session).append(run_id, "run.status", event)

    async def _fenced(self, run_id: UUID, write: Callable[[RunRepository], Awaitable[bool]]) -> None:
        async with self._sessions.begin() as session:
            if not await write(RunRepository(session)):
                raise LeaseLost(str(run_id))

    async def _stop_reason(self, run_id: UUID, fence: int) -> StopReason | None:
        async with self._sessions() as session:
            run = await RunRepository(session).get(run_id)
        if run is None or run.claims != fence or run.status != "running":
            return "lease_lost"
        return "cancelled" if run.cancel_requested else None
