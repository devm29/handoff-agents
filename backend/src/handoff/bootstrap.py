from __future__ import annotations

from datetime import timedelta

from handoff.config import Settings
from handoff.graph.nodes import GraphPolicy
from handoff.services.approvals import EscalationPolicy


def graph_policy(settings: Settings) -> GraphPolicy:
    return GraphPolicy(
        agent_max_turns=settings.agent_max_turns,
        max_output_tokens=settings.max_output_tokens,
        node_max_attempts=settings.node_max_attempts,
        auto_approve_max_risk=settings.auto_approve_max_risk,
    )


def escalation_policy(settings: Settings) -> EscalationPolicy:
    return EscalationPolicy(settings.escalation_tiers, timedelta(seconds=settings.approval_timeout_seconds))
