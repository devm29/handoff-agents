from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

from langchain_core.runnables import RunnableConfig
from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.types import StateSnapshot
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from handoff.agents.schemas import VendorProfile
from handoff.agents.specs import SPECIALISTS
from handoff.config import Settings
from handoff.db.models import TERMINAL_STATUSES, RunRow
from handoff.db.repositories import (
    ApprovalRepository,
    EventRepository,
    RunRepository,
    notify_run_queued,
)
from handoff.errors import ConflictError, NotFoundError
from handoff.graph.builder import DueDiligenceGraph
from handoff.graph.state import Budget, DueDiligenceState
from handoff.services.dto import (
    ApprovalOut,
    CheckpointDetail,
    CheckpointSummary,
    CreateRunRequest,
    ForkRequest,
    GraphTopology,
    RunDetail,
    RunPage,
    RunSummary,
    Stats,
    TopologyEdge,
    TopologyNode,
    decode_cursor,
    encode_cursor,
)

_START, _END = "__start__", "__end__"


def thread_config(thread_id: str, checkpoint_id: str | None = None) -> RunnableConfig:
    configurable: dict[str, Any] = {"thread_id": thread_id}
    if checkpoint_id:
        configurable["checkpoint_id"] = checkpoint_id
    return {"configurable": configurable}


def _checkpoint_id(config: RunnableConfig | None) -> str | None:
    if not config:
        return None
    value = config.get("configurable", {}).get("checkpoint_id")
    return str(value) if value else None


def _state_or_none(values: Any) -> DueDiligenceState | None:
    if isinstance(values, DueDiligenceState):
        return values
    if isinstance(values, dict) and values.get("vendor") is not None:
        return DueDiligenceState.model_validate(values)
    return None


class RunService:
    def __init__(
        self, sessions: async_sessionmaker[AsyncSession], graph: DueDiligenceGraph, settings: Settings
    ) -> None:
        self._sessions = sessions
        self._graph = graph
        self._settings = settings

    async def create(self, request: CreateRunRequest) -> RunSummary:
        budget = Budget(
            max_tokens=request.budget.max_tokens if request.budget else self._settings.default_max_tokens,
            max_usd=request.budget.max_usd if request.budget else self._settings.default_max_usd,
        )
        state = DueDiligenceState(vendor=request.vendor, budget=budget)
        async with self._sessions.begin() as session:
            row = await self._insert(session, state)
            return RunSummary.from_row(row)

    async def _insert(
        self,
        session: AsyncSession,
        state: DueDiligenceState,
        *,
        run_id: UUID | None = None,
        parent: RunRow | None = None,
        checkpoint_id: str | None = None,
        seed_initial_state: bool = True,
    ) -> RunRow:
        run_id = run_id or uuid4()
        row = RunRow(
            id=run_id,
            thread_id=f"run-{run_id.hex}",
            vendor_name=state.vendor.name,
            vendor_country=state.vendor.country,
            vendor=state.vendor.model_dump(mode="json"),
            budget_max_tokens=state.budget.max_tokens,
            budget_max_usd=state.budget.max_usd,
            status="queued",
            initial_state=state.model_dump(mode="json") if seed_initial_state else None,
            parent_run_id=parent.id if parent else None,
            forked_from_checkpoint=checkpoint_id,
            input_tokens=state.usage.input_tokens,
            output_tokens=state.usage.output_tokens,
            cost_usd=state.usage.cost_usd,
            llm_calls=state.usage.llm_calls,
            tool_calls=state.usage.tool_calls,
        )
        await RunRepository(session).add(row)
        await session.refresh(row)
        payload: dict[str, Any] = {"status": "queued"}
        if parent is not None:
            payload |= {"forked_from_run": str(parent.id), "checkpoint_id": checkpoint_id}
        await EventRepository(session).append(row.id, "run.status", payload)
        await notify_run_queued(session, row.id)
        return row

    async def page(
        self, *, limit: int, cursor: str | None, statuses: list[str] | None, search: str | None
    ) -> RunPage:
        before = decode_cursor(cursor) if cursor else None
        async with self._sessions() as session:
            rows = await RunRepository(session).page(
                limit=limit + 1, statuses=statuses, search=search, before=before
            )
        next_cursor = (
            encode_cursor(rows[limit - 1].created_at, rows[limit - 1].id) if len(rows) > limit else None
        )
        return RunPage(items=[RunSummary.from_row(r) for r in rows[:limit]], next_cursor=next_cursor)

    async def _require(self, session: AsyncSession, run_id: UUID, *, for_update: bool = False) -> RunRow:
        row = await RunRepository(session).get(run_id, for_update=for_update)
        if row is None:
            raise NotFoundError("run", str(run_id))
        return row

    async def require(self, run_id: UUID) -> None:
        async with self._sessions() as session:
            if not await RunRepository(session).exists(run_id):
                raise NotFoundError("run", str(run_id))

    async def detail(self, run_id: UUID) -> RunDetail:
        async with self._sessions() as session:
            row = await self._require(session, run_id)
            approvals = await ApprovalRepository(session).for_run(run_id)
        snapshot = await self._graph.aget_state(thread_config(row.thread_id))
        state = _state_or_none(snapshot.values)
        if state is None and row.initial_state:
            state = DueDiligenceState.model_validate(row.initial_state)
        summary = RunSummary.from_row(row)
        return RunDetail(
            **summary.model_dump(),
            vendor=VendorProfile.model_validate(row.vendor),
            state=state,
            report=state.report if state else None,
            approvals=[ApprovalOut.from_row(a, row.vendor_name) for a in approvals],
        )

    async def cancel(self, run_id: UUID) -> RunSummary:
        async with self._sessions.begin() as session:
            row = await self._require(session, run_id, for_update=True)
            if row.status in TERMINAL_STATUSES:
                raise ConflictError(f"Run is already {row.status}")
            events = EventRepository(session)
            if row.status == "running":
                row.cancel_requested = True
                await events.append(row.id, "run.status", {"status": "running", "cancel_requested": True})
            else:
                for approval in await ApprovalRepository(session).for_run(run_id):
                    if approval.status == "pending":
                        approval.status = "expired"
                await RunRepository(session).transition(row.id, "cancelled")
                await events.append(row.id, "run.status", {"status": "cancelled"})
            await session.flush()
            await session.refresh(row)
            return RunSummary.from_row(row)

    async def _history(self, thread_id: str) -> list[StateSnapshot]:
        snapshots = [s async for s in self._graph.aget_state_history(thread_config(thread_id))]
        return list(reversed(snapshots))

    @staticmethod
    def _summaries(history: list[StateSnapshot]) -> list[tuple[CheckpointSummary, StateSnapshot]]:
        by_id = {_checkpoint_id(s.config): s for s in history}
        out: list[tuple[CheckpointSummary, StateSnapshot]] = []
        for snapshot in history:
            checkpoint_id = _checkpoint_id(snapshot.config) or ""
            parent_id = _checkpoint_id(snapshot.parent_config)
            parent = by_id.get(parent_id) if parent_id else None
            source = str(snapshot.metadata.get("source", "loop")) if snapshot.metadata else "loop"
            if parent is not None and parent.next:
                produced_by: str | None = parent.next[0]
            elif source == "input":
                produced_by = "input"
            elif source == "update":
                produced_by = "fork"
            else:
                produced_by = None
            state = _state_or_none(snapshot.values)
            step = snapshot.metadata.get("step", -1) if snapshot.metadata else -1
            summary = CheckpointSummary(
                checkpoint_id=checkpoint_id,
                parent_checkpoint_id=parent_id,
                step=int(step) if isinstance(step, int) else -1,
                source=source,
                produced_by=produced_by,
                next=list(snapshot.next),
                interrupted=bool(snapshot.interrupts),
                created_at=datetime.fromisoformat(snapshot.created_at) if snapshot.created_at else None,
                cost_usd=state.usage.cost_usd if state else 0.0,
                total_tokens=state.usage.total_tokens if state else 0,
            )
            out.append((summary, snapshot))
        return out

    async def checkpoints(self, run_id: UUID) -> list[CheckpointSummary]:
        async with self._sessions() as session:
            row = await self._require(session, run_id)
        return [summary for summary, _ in self._summaries(await self._history(row.thread_id))]

    async def checkpoint(self, run_id: UUID, checkpoint_id: str) -> CheckpointDetail:
        async with self._sessions() as session:
            row = await self._require(session, run_id)
        for summary, snapshot in self._summaries(await self._history(row.thread_id)):
            if summary.checkpoint_id == checkpoint_id:
                return CheckpointDetail(**summary.model_dump(), state=_state_or_none(snapshot.values))
        raise NotFoundError("checkpoint", checkpoint_id)

    async def fork(self, run_id: UUID, request: ForkRequest) -> RunSummary:
        async with self._sessions() as session:
            source_run = await self._require(session, run_id)
        match = next(
            (
                (summary, snapshot)
                for summary, snapshot in self._summaries(await self._history(source_run.thread_id))
                if summary.checkpoint_id == request.checkpoint_id
            ),
            None,
        )
        if match is None:
            raise NotFoundError("checkpoint", request.checkpoint_id)
        summary, snapshot = match
        state = _state_or_none(snapshot.values)
        if state is None:
            raise ConflictError("The input checkpoint has no state to fork; start a new run instead")
        state = request.state_patch.apply(state)

        new_id = uuid4()
        thread_id = f"run-{new_id.hex}"
        replay_from_start = summary.produced_by in (None, "input", "fork", _START)
        # The checkpoint must exist before the row: the insert wakes workers, and one that claims the
        # run before its thread has a checkpoint would start over from the initial state.
        if not replay_from_start and summary.produced_by is not None:
            values = {name: getattr(state, name) for name in DueDiligenceState.model_fields}
            await self._graph.aupdate_state(thread_config(thread_id), values, as_node=summary.produced_by)
        try:
            async with self._sessions.begin() as session:
                row = await self._insert(
                    session,
                    state,
                    run_id=new_id,
                    parent=source_run,
                    checkpoint_id=request.checkpoint_id,
                    seed_initial_state=True,
                )
                return RunSummary.from_row(row)
        except BaseException:
            checkpointer = self._graph.checkpointer
            if isinstance(checkpointer, BaseCheckpointSaver):
                await checkpointer.adelete_thread(thread_id)
            raise

    async def stats(self) -> Stats:
        async with self._sessions() as session:
            by_status = await RunRepository(session).count_by_status()
            total_cost, total = await RunRepository(session).totals()
            pending = await ApprovalRepository(session).count_pending()
        return Stats(
            runs_by_status=by_status,
            total_runs=total,
            pending_approvals=pending,
            total_cost_usd=round(total_cost, 4),
            avg_cost_usd=round(total_cost / total, 4) if total else 0.0,
        )

    def topology(self) -> GraphTopology:
        drawable = self._graph.get_graph()
        nodes: list[TopologyNode] = []
        for node_id in drawable.nodes:
            if node_id == _START:
                nodes.append(TopologyNode(id=node_id, label="Start", kind="start"))
            elif node_id == _END:
                nodes.append(TopologyNode(id=node_id, label="End", kind="end"))
            elif node_id == "supervisor":
                nodes.append(TopologyNode(id=node_id, label="Supervisor", kind="supervisor"))
            elif node_id == "approval":
                nodes.append(TopologyNode(id=node_id, label="Human approval", kind="gate"))
            else:
                spec = SPECIALISTS[node_id]
                label = node_id.replace("_", " ").capitalize()
                nodes.append(
                    TopologyNode(id=node_id, label=label, kind="specialist", tools=sorted(spec.tools))
                )
        edges = [
            TopologyEdge(source=e.source, target=e.target, conditional=e.conditional) for e in drawable.edges
        ]
        return GraphTopology(nodes=nodes, edges=edges)
