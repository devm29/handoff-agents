from __future__ import annotations

from typing import Any

from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph
from langgraph.types import RetryPolicy

from handoff.errors import HandoffError
from handoff.graph.nodes import (
    GraphContext,
    GraphPolicy,
    approval_gate,
    instrument,
    specialist_nodes,
    supervisor,
)
from handoff.graph.state import DueDiligenceState

DueDiligenceGraph = CompiledStateGraph[DueDiligenceState, GraphContext, DueDiligenceState, DueDiligenceState]

NODE_ORDER = ("supervisor", "researcher", "risk_analyst", "compliance_checker", "approval", "report_writer")


def _retryable(exc: Exception) -> bool:
    return isinstance(exc, HandoffError) and exc.retryable


def route_from_supervisor(state: DueDiligenceState) -> str:
    handoff = state.active_handoff
    if handoff is None or handoff.target == "finish":
        return END
    return handoff.target


def build_graph(
    checkpointer: BaseCheckpointSaver[Any] | None = None, *, policy: GraphPolicy | None = None
) -> DueDiligenceGraph:
    retry = RetryPolicy(
        max_attempts=(policy or GraphPolicy()).node_max_attempts,
        initial_interval=0.5,
        backoff_factor=2.0,
        max_interval=8.0,
        retry_on=_retryable,
    )
    builder = StateGraph(DueDiligenceState, context_schema=GraphContext)
    builder.add_node("supervisor", instrument("supervisor", supervisor), retry_policy=retry)
    for name, node in specialist_nodes().items():
        builder.add_node(name, instrument(name, node), retry_policy=retry)
    builder.add_node("approval", instrument("approval", approval_gate))

    builder.add_edge(START, "supervisor")
    builder.add_conditional_edges(
        "supervisor",
        route_from_supervisor,
        [*NODE_ORDER[1:], END],
    )
    for name in NODE_ORDER[1:]:
        builder.add_edge(name, "supervisor")
    return builder.compile(checkpointer=checkpointer)
