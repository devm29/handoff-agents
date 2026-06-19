from __future__ import annotations

from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from handoff.db.repositories import EventRepository, RunRepository
from handoff.errors import LeaseLost
from handoff.events.sink import EventType


class DatabaseEventSink:
    """Persists run events, publishes them over NOTIFY and keeps run counters current.

    Spend is always recorded, because it was really incurred. Progress writes carry the
    claim fence and raise LeaseLost once another worker owns the run.
    """

    def __init__(self, sessions: async_sessionmaker[AsyncSession], *, fence: int | None = None) -> None:
        self._sessions = sessions
        self._fence = fence

    async def emit(self, run_id: str, event_type: EventType, payload: dict[str, Any]) -> None:
        rid = UUID(run_id)
        async with self._sessions.begin() as session:
            await EventRepository(session).append(rid, event_type, payload)
            runs = RunRepository(session)
            match event_type:
                case "llm.call":
                    await runs.add_usage(
                        rid,
                        input_tokens=int(payload["input_tokens"]),
                        output_tokens=int(payload["output_tokens"]),
                        cost_usd=float(payload["cost_usd"]),
                        llm_calls=1,
                    )
                case "tool.call":
                    await runs.add_usage(rid, tool_calls=1)
                case "node.started":
                    if not await runs.set_current_node(rid, str(payload["node"]), fence=self._fence):
                        raise LeaseLost(run_id)
                case _:
                    pass
