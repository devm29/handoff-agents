from __future__ import annotations

import asyncio
import os
from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import timedelta
from uuid import UUID

import httpx
import psycopg
import pytest
from pydantic import PostgresDsn
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from handoff.api.app import create_app
from handoff.bootstrap import escalation_policy, graph_policy
from handoff.config import Settings
from handoff.db.engine import make_engine, make_session_factory, migrate
from handoff.db.repositories import RunRepository
from handoff.graph.builder import DueDiligenceGraph, build_graph
from handoff.graph.persistence import postgres_checkpointer
from handoff.llm.fake import ScriptedFakeProvider
from handoff.services.approvals import ApprovalService
from handoff.services.runs import RunService
from handoff.tools.gateway import MCPToolGateway
from handoff.worker.executor import RunExecutor

TEST_DATABASE_URL = os.environ.get("TEST_DATABASE_URL", "postgresql://handoff@127.0.0.1:5504/handoff_test")
WORKER_ID = "test-worker"
ANALYST = {"Authorization": "Bearer demo-analyst-token"}
COMPLIANCE_LEAD = {"Authorization": "Bearer demo-compliance-lead-token"}
CRO = {"Authorization": "Bearer demo-cro-token"}

pytestmark = pytest.mark.postgres


def _postgres_required() -> bool:
    return os.environ.get("CI", "").lower() in ("1", "true") or os.environ.get("REQUIRE_POSTGRES") == "1"


def _postgres_available() -> bool:
    try:
        with psycopg.connect(TEST_DATABASE_URL, connect_timeout=2):
            return True
    except psycopg.Error:
        return False


@pytest.fixture(scope="session")
def settings() -> Settings:
    if not _postgres_available():
        message = f"PostgreSQL not reachable at {TEST_DATABASE_URL}"
        if _postgres_required():
            pytest.fail(f"{message}; integration tests are required here (CI / REQUIRE_POSTGRES=1)")
        pytest.skip(message)
    # Start every session from an empty schema so the Alembic migrations themselves are exercised.
    with psycopg.connect(TEST_DATABASE_URL, autocommit=True) as conn:
        conn.execute("DROP SCHEMA public CASCADE")
        conn.execute("CREATE SCHEMA public")
    return Settings(
        environment="test",
        database_url=PostgresDsn(TEST_DATABASE_URL),
        llm_provider="fake",
        fake_latency_ms=0,
        mcp_transport="inprocess",
        worker_id=WORKER_ID,
        approval_timeout_seconds=60,
    )


@dataclass
class Stack:
    client: httpx.AsyncClient
    sessions: async_sessionmaker[AsyncSession]
    graph: DueDiligenceGraph
    executor: RunExecutor
    approvals: ApprovalService
    runs: RunService

    async def work(self) -> list[UUID]:
        """Claim and execute every runnable run, like one worker pass."""
        executed: list[UUID] = []
        while True:
            async with self.sessions.begin() as session:
                run = await RunRepository(session).claim_next(WORKER_ID, timedelta(seconds=30))
            if run is None:
                return executed
            await self.executor.execute(run.id, fence=run.claims)
            executed.append(run.id)


@pytest.fixture
async def stack(settings: Settings, tools: MCPToolGateway) -> AsyncIterator[Stack]:
    await migrate(settings)
    engine = make_engine(settings)
    async with engine.begin() as conn:
        await conn.execute(text("TRUNCATE run_events, approvals, eval_reports, runs CASCADE"))
    sessions = make_session_factory(engine)
    app = create_app(settings)
    async with (
        postgres_checkpointer(settings.psycopg_url, max_size=4) as checkpointer,
        app.router.lifespan_context(app),
    ):
        await checkpointer.setup()
        policy = graph_policy(settings)
        graph = build_graph(checkpointer, policy=policy)
        approvals = ApprovalService(sessions, escalation_policy(settings))
        executor = RunExecutor(
            sessions=sessions,
            graph=graph,
            llm=ScriptedFakeProvider(),
            tools=tools,
            approvals=approvals,
            policy=policy,
        )
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(
            transport=transport, base_url="http://test/api", headers=ANALYST
        ) as client:
            yield Stack(
                client=client,
                sessions=sessions,
                graph=graph,
                executor=executor,
                approvals=approvals,
                runs=RunService(sessions, graph, settings),
            )
    await engine.dispose()
    await asyncio.sleep(0)
