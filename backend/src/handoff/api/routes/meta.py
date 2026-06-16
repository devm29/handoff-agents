from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Query
from sqlalchemy import text
from sse_starlette.sse import EventSourceResponse

from handoff.api.deps import ContainerDep, RunServiceDep
from handoff.api.sse import global_event_stream
from handoff.db.repositories import EvalReportRepository
from handoff.services.dto import EvalReportOut, GraphTopology, Stats

public = APIRouter(tags=["meta"])
router = APIRouter(tags=["meta"])


@public.get("/healthz")
async def health(c: ContainerDep) -> dict[str, str]:
    async with c.sessions() as session:
        await session.execute(text("SELECT 1"))
    return {"status": "ok", "events": "listening" if c.broker.connected.is_set() else "connecting"}


@router.get("/graph")
async def graph_topology(runs: RunServiceDep) -> GraphTopology:
    return runs.topology()


@router.get("/stats")
async def stats(runs: RunServiceDep) -> Stats:
    return await runs.stats()


@router.get("/events", response_class=EventSourceResponse)
async def stream_all(c: ContainerDep) -> EventSourceResponse:
    return EventSourceResponse(global_event_stream(c.broker), ping=15)


@router.get("/evals/reports")
async def eval_reports(
    c: ContainerDep, limit: Annotated[int, Query(ge=1, le=50)] = 10
) -> list[EvalReportOut]:
    async with c.sessions() as session:
        rows = await EvalReportRepository(session).latest(limit)
    return [EvalReportOut.model_validate(r) for r in rows]
