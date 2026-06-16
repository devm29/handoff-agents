from __future__ import annotations

from typing import Any, Literal, Protocol

EventType = Literal[
    "run.status",
    "node.started",
    "node.completed",
    "node.failed",
    "handoff",
    "llm.call",
    "tool.call",
    "approval.requested",
    "approval.decided",
    "approval.escalated",
]


class EventSink(Protocol):
    async def emit(self, run_id: str, event_type: EventType, payload: dict[str, Any]) -> None: ...


class NullSink:
    async def emit(self, run_id: str, event_type: EventType, payload: dict[str, Any]) -> None:
        return None


class MemorySink:
    def __init__(self) -> None:
        self.events: list[tuple[str, EventType, dict[str, Any]]] = []

    async def emit(self, run_id: str, event_type: EventType, payload: dict[str, Any]) -> None:
        self.events.append((run_id, event_type, payload))

    def of_type(self, event_type: EventType) -> list[dict[str, Any]]:
        return [payload for _, kind, payload in self.events if kind == event_type]
