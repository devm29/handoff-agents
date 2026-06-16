from __future__ import annotations

import json
from collections.abc import AsyncGenerator
from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from handoff.db.models import RunEventRow
from handoff.db.repositories import EventRepository
from handoff.events.broker import ALL_RUNS, RESYNC_TYPE, EventBroker

REPLAY_PAGE = 500

GLOBAL_EVENT_TYPES = frozenset(
    {"run.status", "node.started", "approval.requested", "approval.decided", "approval.escalated"}
)


def _frame(event_id: int, event_type: str, data: dict[str, Any]) -> dict[str, str]:
    return {"id": str(event_id), "event": event_type, "data": json.dumps(data, default=str)}


def _row_message(row: RunEventRow) -> dict[str, Any]:
    return {
        "id": row.id,
        "run_id": str(row.run_id),
        "type": row.type,
        "payload": row.payload,
        "created_at": row.created_at.isoformat(),
    }


async def _replay(
    run_id: UUID, after: int, sessions: async_sessionmaker[AsyncSession]
) -> AsyncGenerator[RunEventRow]:
    last = after
    while True:
        async with sessions() as session:
            page = await EventRepository(session).since(run_id, last, REPLAY_PAGE)
        for row in page:
            yield row
            last = row.id
        if len(page) < REPLAY_PAGE:
            return


async def run_event_stream(
    run_id: UUID, after: int, broker: EventBroker, sessions: async_sessionmaker[AsyncSession]
) -> AsyncGenerator[dict[str, str]]:
    """Replay persisted events after `after`, then follow live ones without gaps or duplicates.

    Subscribing before the replay means nothing published in between is missed; ids at or
    below the last replayed one are skipped. A resync marker from the broker sends the stream
    back to the database for whatever the live feed may have dropped.
    """
    async with broker.subscribe(str(run_id)) as queue:
        last = after
        async for row in _replay(run_id, last, sessions):
            yield _frame(row.id, row.type, _row_message(row))
            last = row.id
        while True:
            message = await queue.get()
            if message.get("type") == RESYNC_TYPE:
                async for row in _replay(run_id, last, sessions):
                    yield _frame(row.id, row.type, _row_message(row))
                    last = row.id
                continue
            event_id = int(message["id"])
            if event_id <= last:
                continue
            if message.get("truncated"):
                async with sessions() as session:
                    stored = await EventRepository(session).get(event_id)
                if stored is None:
                    continue
                message = _row_message(stored)
            yield _frame(event_id, str(message["type"]), message)
            last = event_id


async def global_event_stream(broker: EventBroker) -> AsyncGenerator[dict[str, str]]:
    async with broker.subscribe(ALL_RUNS) as queue:
        while True:
            message = await queue.get()
            if message.get("type") == RESYNC_TYPE:
                yield {"event": "resync", "data": "{}"}
            elif message.get("type") in GLOBAL_EVENT_TYPES:
                yield _frame(int(message["id"]), str(message["type"]), message)
