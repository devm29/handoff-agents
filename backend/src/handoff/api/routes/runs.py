from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Header, Query, status
from sse_starlette.sse import EventSourceResponse

from handoff.api.deps import ContainerDep, RunServiceDep
from handoff.api.sse import run_event_stream
from handoff.db.models import RunStatus
from handoff.db.repositories import EventRepository
from handoff.services.dto import (
    CheckpointDetail,
    CheckpointSummary,
    CreateRunRequest,
    EventOut,
    ForkRequest,
    RunDetail,
    RunPage,
    RunSummary,
)

router = APIRouter(prefix="/runs", tags=["runs"])


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_run(body: CreateRunRequest, runs: RunServiceDep) -> RunSummary:
    return await runs.create(body)


@router.get("")
async def list_runs(
    runs: RunServiceDep,
    limit: Annotated[int, Query(ge=1, le=100)] = 25,
    cursor: str | None = None,
    status_filter: Annotated[list[RunStatus] | None, Query(alias="status")] = None,
    q: Annotated[str | None, Query(max_length=100)] = None,
) -> RunPage:
    return await runs.page(limit=limit, cursor=cursor, statuses=list(status_filter or []) or None, search=q)


@router.get("/{run_id}")
async def get_run(run_id: UUID, runs: RunServiceDep) -> RunDetail:
    return await runs.detail(run_id)


@router.post("/{run_id}/cancel")
async def cancel_run(run_id: UUID, runs: RunServiceDep) -> RunSummary:
    return await runs.cancel(run_id)


@router.get("/{run_id}/checkpoints")
async def list_checkpoints(run_id: UUID, runs: RunServiceDep) -> list[CheckpointSummary]:
    return await runs.checkpoints(run_id)


@router.get("/{run_id}/checkpoints/{checkpoint_id}")
async def get_checkpoint(run_id: UUID, checkpoint_id: str, runs: RunServiceDep) -> CheckpointDetail:
    return await runs.checkpoint(run_id, checkpoint_id)


@router.post("/{run_id}/fork", status_code=status.HTTP_201_CREATED)
async def fork_run(run_id: UUID, body: ForkRequest, runs: RunServiceDep) -> RunSummary:
    return await runs.fork(run_id, body)


@router.get("/{run_id}/events/history")
async def event_history(
    run_id: UUID,
    c: ContainerDep,
    runs: RunServiceDep,
    after: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=1_000)] = 500,
) -> list[EventOut]:
    await runs.require(run_id)
    async with c.sessions() as session:
        rows = await EventRepository(session).since(run_id, after, limit)
    return [
        EventOut(id=r.id, run_id=r.run_id, type=r.type, payload=r.payload, created_at=r.created_at)
        for r in rows
    ]


@router.get("/{run_id}/events", response_class=EventSourceResponse)
async def stream_events(
    run_id: UUID,
    c: ContainerDep,
    runs: RunServiceDep,
    after: Annotated[int, Query(ge=0)] = 0,
    last_event_id: Annotated[str | None, Header()] = None,
) -> EventSourceResponse:
    await runs.require(run_id)
    resume_from = int(last_event_id) if last_event_id and last_event_id.isdigit() else after
    return EventSourceResponse(run_event_stream(run_id, resume_from, c.broker, c.sessions), ping=15)
