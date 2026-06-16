from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware

from handoff.api.deps import Container, current_reviewer
from handoff.api.errors import register_error_handlers
from handoff.api.routes import approvals, meta, runs, session
from handoff.auth import ReviewerDirectory
from handoff.bootstrap import escalation_policy, graph_policy
from handoff.config import Settings, get_settings
from handoff.db.engine import make_engine, make_session_factory, migrate
from handoff.events.broker import EventBroker
from handoff.graph.builder import build_graph
from handoff.graph.persistence import postgres_checkpointer
from handoff.log_config import configure_logging
from handoff.services.approvals import ApprovalService
from handoff.services.runs import RunService
from handoff.telemetry.otel import setup_tracing


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    configure_logging(settings.log_level, json=settings.log_json)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        setup_tracing(settings)
        if settings.auto_migrate:
            await migrate(settings)
        engine = make_engine(settings)
        sessions = make_session_factory(engine)
        broker = EventBroker(settings.psycopg_url)
        await broker.start()
        async with postgres_checkpointer(settings.psycopg_url, max_size=5) as checkpointer:
            await checkpointer.setup()
            graph = build_graph(checkpointer, policy=graph_policy(settings))
            app.state.container = Container(
                settings=settings,
                sessions=sessions,
                runs=RunService(sessions, graph, settings),
                approvals=ApprovalService(sessions, escalation_policy(settings)),
                broker=broker,
                reviewers=ReviewerDirectory(settings.reviewers, settings.escalation_tiers),
            )
            try:
                yield
            finally:
                await broker.stop()
                await engine.dispose()

    app = FastAPI(
        title="Handoff",
        version="0.1.0",
        summary="Durable multi-agent vendor due diligence with human approval gates.",
        lifespan=lifespan,
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_methods=["GET", "POST", "DELETE"],
        allow_headers=["*"],
        allow_credentials=True,
    )
    register_error_handlers(app)
    for public in (meta.public, session.router):
        app.include_router(public, prefix="/api")
    for protected in (runs.router, approvals.router, meta.router):
        app.include_router(protected, prefix="/api", dependencies=[Depends(current_reviewer)])
    return app
