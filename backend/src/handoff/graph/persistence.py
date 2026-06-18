from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from langgraph.checkpoint.serde.jsonplus import JsonPlusSerializer
from psycopg.rows import dict_row
from psycopg_pool import AsyncConnectionPool

from handoff.graph.state import STATE_MODELS


def make_serializer() -> JsonPlusSerializer:
    """Only our own state models may be revived from checkpoint blobs."""
    return JsonPlusSerializer(allowed_msgpack_modules=list(STATE_MODELS))


@asynccontextmanager
async def postgres_checkpointer(conninfo: str, *, max_size: int = 10) -> AsyncIterator[AsyncPostgresSaver]:
    pool = AsyncConnectionPool(
        conninfo,
        min_size=1,
        max_size=max_size,
        open=False,
        kwargs={"autocommit": True, "prepare_threshold": 0, "row_factory": dict_row},
    )
    await pool.open()
    try:
        saver = AsyncPostgresSaver(pool, serde=make_serializer())  # type: ignore[arg-type]
        yield saver
    finally:
        await pool.close()
