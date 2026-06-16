from __future__ import annotations

import asyncio
import json
import signal
import sys
from enum import StrEnum
from pathlib import Path
from typing import TYPE_CHECKING, Annotated

import typer
import uvicorn
from rich.console import Console

from handoff.config import Settings, get_settings
from handoff.log_config import configure_logging

if TYPE_CHECKING:
    from handoff.evals.runner import EvalSummary, ScenarioResult

app = typer.Typer(help="Handoff: durable multi-agent vendor due diligence.", no_args_is_help=True)
db_app = typer.Typer(help="Database utilities.", no_args_is_help=True)
eval_app = typer.Typer(help="Trajectory evaluations.", no_args_is_help=True)
demo_app = typer.Typer(help="Scripted demos.", no_args_is_help=True)
app.add_typer(db_app, name="db")
app.add_typer(eval_app, name="eval")
app.add_typer(demo_app, name="demo")

console = Console() if sys.stdout.isatty() else Console(width=140)


class Provider(StrEnum):
    fake = "fake"
    anthropic = "anthropic"


class McpTransport(StrEnum):
    stdio = "stdio"
    http = "http"


def _settings() -> Settings:
    settings = get_settings()
    configure_logging(settings.log_level, json=settings.log_json)
    return settings


@app.command()
def api(
    host: Annotated[str | None, typer.Option(help="Bind address")] = None,
    port: Annotated[int | None, typer.Option(help="Port")] = None,
    reload: Annotated[bool, typer.Option(help="Reload on code changes")] = False,
) -> None:
    """Serve the HTTP API."""
    settings = _settings()
    uvicorn.run(
        "handoff.api.app:create_app",
        factory=True,
        host=host or settings.api_host,
        port=port or settings.api_port,
        reload=reload,
        log_config=None,
    )


@app.command()
def worker() -> None:
    """Run a worker that executes queued runs and resumes interrupted ones."""
    from handoff.telemetry.otel import setup_tracing, shutdown_tracing
    from handoff.worker.main import WorkerLoopDied
    from handoff.worker.runtime import worker_runtime

    settings = _settings()

    async def main() -> None:
        setup_tracing(settings)
        stop = asyncio.Event()
        loop = asyncio.get_running_loop()
        for sig in (signal.SIGINT, signal.SIGTERM):
            loop.add_signal_handler(sig, stop.set)
        try:
            async with worker_runtime(settings) as runtime:
                await runtime.worker.run(stop)
        finally:
            shutdown_tracing()

    try:
        asyncio.run(main())
    except WorkerLoopDied as exc:
        console.print(f"[red]Worker stopped: {exc}[/]")
        raise typer.Exit(code=1) from exc


@app.command("mcp-tools")
def mcp_tools(
    transport: Annotated[
        McpTransport, typer.Option(help="stdio for subprocess use, http for a network service")
    ] = (McpTransport.stdio),
) -> None:
    """Serve the due-diligence MCP tools."""
    from handoff.tools.server import build_server

    settings = get_settings()
    server = build_server()
    if transport is McpTransport.http:
        server.run("streamable-http", host=settings.mcp_http_host, port=settings.mcp_http_port)
    else:
        server.run("stdio")


@db_app.command("init")
def db_init() -> None:
    """Apply Alembic migrations and create the LangGraph checkpoint tables."""
    from handoff.db.engine import migrate
    from handoff.graph.persistence import postgres_checkpointer

    settings = _settings()

    async def main() -> None:
        await migrate(settings)
        async with postgres_checkpointer(settings.psycopg_url, max_size=1) as checkpointer:
            await checkpointer.setup()

    asyncio.run(main())
    console.print("[green]Database ready[/]")


@app.command()
def seed(reset: Annotated[bool, typer.Option(help="Wipe existing runs first")] = False) -> None:
    """Load demo runs, approvals, a fork and an eval report."""
    from handoff.demo.seed import seed as run_seed

    asyncio.run(run_seed(_settings(), reset=reset, console=console))


@eval_app.command("run")
def eval_run(
    suite: Annotated[str, typer.Option(help="Scenario suite name")] = "default",
    provider: Annotated[Provider | None, typer.Option(help="Override the configured LLM provider")] = None,
    save: Annotated[bool, typer.Option(help="Store the report so the UI can show it")] = True,
    min_score: Annotated[float, typer.Option(help="Exit non-zero when mean overall falls below this")] = 0.0,
    output: Annotated[Path | None, typer.Option(help="Write full results as JSON")] = None,
) -> None:
    """Run trajectory evals over a scenario suite and print a summary table."""
    from handoff.evals.report import render
    from handoff.evals.suite import run_suite

    settings = _settings().model_copy(update={"mcp_transport": "inprocess", "fake_latency_ms": 0})
    if provider is not None:
        settings = settings.model_copy(update={"llm_provider": provider.value})
    summary, results = asyncio.run(run_suite(settings, suite))
    render(console, summary, results)

    if output is not None:
        payload = {
            "summary": summary.model_dump(mode="json"),
            "results": [r.model_dump(mode="json") for r in results],
        }
        output.write_text(json.dumps(payload, indent=2))
    if save:
        _save_report(settings, summary, results)
    if summary.mean["overall"] < min_score:
        console.print(f"[red]Mean overall {summary.mean['overall']:.2f} is below {min_score:.2f}[/]")
        raise typer.Exit(code=1)


def _save_report(settings: Settings, summary: EvalSummary, results: list[ScenarioResult]) -> None:
    from sqlalchemy.exc import OperationalError

    from handoff.db.engine import make_engine, make_session_factory, migrate
    from handoff.db.models import EvalReportRow
    from handoff.db.repositories import EvalReportRepository

    async def main() -> None:
        await migrate(settings)
        engine = make_engine(settings)
        try:
            async with make_session_factory(engine).begin() as session:
                await EvalReportRepository(session).add(
                    EvalReportRow(
                        suite=summary.suite,
                        provider=summary.provider,
                        summary=summary.model_dump(mode="json"),
                        results={"scenarios": [r.model_dump(mode="json") for r in results]},
                    )
                )
        finally:
            await engine.dispose()

    try:
        asyncio.run(main())
        console.print("[dim]Report saved; it now shows on the Evals page.[/]")
    except (OperationalError, OSError) as exc:
        console.print(f"[yellow]Could not save the report ({type(exc).__name__}); is Postgres running?[/]")


@demo_app.command("crash")
def demo_crash(
    kill_after: Annotated[
        int, typer.Option(help="Kill the worker once the run has this many checkpoints")
    ] = 7,
    log_file: Annotated[Path, typer.Option(help="Where the demo worker writes its logs")] = Path(
        ".data/crash-demo-worker.log"
    ),
) -> None:
    """Kill a worker mid-run with SIGKILL, restart it, and watch the run resume from its checkpoint."""
    from handoff.demo.crash import crash_demo

    log_file.parent.mkdir(parents=True, exist_ok=True)
    ok = asyncio.run(crash_demo(_settings(), kill_after=kill_after, console=console, log_path=log_file))
    raise typer.Exit(code=0 if ok else 1)


if __name__ == "__main__":
    app()
