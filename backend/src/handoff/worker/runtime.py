from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from handoff.bootstrap import escalation_policy, graph_policy
from handoff.config import Settings
from handoff.db.engine import make_engine, make_session_factory, migrate
from handoff.graph.builder import DueDiligenceGraph, build_graph
from handoff.graph.persistence import postgres_checkpointer
from handoff.llm.factory import build_provider
from handoff.services.approvals import ApprovalService
from handoff.services.runs import RunService
from handoff.tools.gateway import connect_tools
from handoff.worker.executor import RunExecutor
from handoff.worker.main import Worker


@dataclass(frozen=True)
class WorkerRuntime:
    sessions: async_sessionmaker[AsyncSession]
    graph: DueDiligenceGraph
    runs: RunService
    approvals: ApprovalService
    worker: Worker


@asynccontextmanager
async def worker_runtime(settings: Settings) -> AsyncIterator[WorkerRuntime]:
    if settings.auto_migrate:
        await migrate(settings)
    engine = make_engine(settings)
    sessions = make_session_factory(engine)
    try:
        async with (
            postgres_checkpointer(
                settings.psycopg_url, max_size=settings.worker_concurrency + 2
            ) as checkpointer,
            connect_tools(settings) as tools,
        ):
            await checkpointer.setup()
            policy = graph_policy(settings)
            graph = build_graph(checkpointer, policy=policy)
            approvals = ApprovalService(sessions, escalation_policy(settings))
            executor = RunExecutor(
                sessions=sessions,
                graph=graph,
                llm=build_provider(settings),
                tools=tools,
                approvals=approvals,
                policy=policy,
            )
            worker = Worker(settings=settings, sessions=sessions, executor=executor, approvals=approvals)
            yield WorkerRuntime(
                sessions=sessions,
                graph=graph,
                runs=RunService(sessions, graph, settings),
                approvals=approvals,
                worker=worker,
            )
    finally:
        await engine.dispose()
