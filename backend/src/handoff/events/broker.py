from __future__ import annotations

import asyncio
import json
from collections import defaultdict
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

import psycopg
import structlog

from handoff.db.repositories import EVENTS_CHANNEL

log = structlog.get_logger(__name__)

ALL_RUNS = "*"
RESYNC_TYPE = "stream.resync"
_QUEUE_SIZE = 512


class EventBroker:
    """Fans Postgres NOTIFY messages out to in-process SSE subscribers.

    One LISTEN connection per API process. Subscribers get bounded queues; when one
    overflows, or the LISTEN connection drops and NOTIFYs may have been missed, the queue
    is replaced by a single resync marker and the stream re-reads from the database.
    """

    def __init__(self, conninfo: str) -> None:
        self._conninfo = conninfo
        self._subscribers: dict[str, set[asyncio.Queue[dict[str, Any]]]] = defaultdict(set)
        self._task: asyncio.Task[None] | None = None
        self.connected = asyncio.Event()

    async def start(self) -> None:
        self._task = asyncio.create_task(self._listen(), name="event-broker")

    async def stop(self) -> None:
        if self._task is not None:
            self._task.cancel()
            await asyncio.gather(self._task, return_exceptions=True)

    @asynccontextmanager
    async def subscribe(self, key: str) -> AsyncIterator[asyncio.Queue[dict[str, Any]]]:
        queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue(maxsize=_QUEUE_SIZE)
        self._subscribers[key].add(queue)
        try:
            yield queue
        finally:
            self._subscribers[key].discard(queue)
            if not self._subscribers[key]:
                del self._subscribers[key]

    def publish(self, message: dict[str, Any]) -> None:
        run_id = str(message.get("run_id", ""))
        for key in (run_id, ALL_RUNS):
            for queue in self._subscribers.get(key, ()):
                if queue.full():
                    log.warning("events.subscriber_lagging", run_id=run_id)
                    _resync(queue)
                    continue
                queue.put_nowait(message)

    def resync_all(self) -> None:
        for queues in self._subscribers.values():
            for queue in queues:
                _resync(queue)

    async def _listen(self) -> None:
        backoff = 1.0
        first = True
        while True:
            try:
                async with await psycopg.AsyncConnection.connect(self._conninfo, autocommit=True) as conn:
                    await conn.execute(f"LISTEN {EVENTS_CHANNEL}")
                    self.connected.set()
                    if not first:
                        self.resync_all()
                    first = False
                    backoff = 1.0
                    async for notify in conn.notifies():
                        try:
                            self.publish(json.loads(notify.payload))
                        except json.JSONDecodeError:
                            log.warning("events.bad_payload", payload=notify.payload[:200])
            except (psycopg.Error, OSError) as exc:
                self.connected.clear()
                log.warning("events.listen_failed", error=str(exc), retry_in=backoff)
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, 30.0)


def _resync(queue: asyncio.Queue[dict[str, Any]]) -> None:
    while not queue.empty():
        queue.get_nowait()
    queue.put_nowait({"type": RESYNC_TYPE})
