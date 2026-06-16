"""OpenTelemetry setup and GenAI semantic-convention span helpers.

Span names and attributes follow the OpenTelemetry GenAI conventions:
`invoke_agent {agent}`, `chat {model}` and `execute_tool {tool}`.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import SpanProcessor, TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor, ConsoleSpanExporter, SimpleSpanProcessor
from opentelemetry.trace import Link, Span, SpanContext, SpanKind, Status, StatusCode, TraceFlags

from handoff.config import Settings

TRACER_NAME = "handoff.agents"

_provider: TracerProvider | None = None


def setup_tracing(
    settings: Settings, *, extra_processors: list[SpanProcessor] | None = None
) -> TracerProvider:
    global _provider
    if _provider is not None:
        return _provider
    provider = TracerProvider(
        resource=Resource.create(
            {"service.name": settings.otel_service_name, "deployment.environment": settings.environment}
        )
    )
    if settings.otel_exporter_otlp_endpoint:
        endpoint = settings.otel_exporter_otlp_endpoint.rstrip("/") + "/v1/traces"
        provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter(endpoint=endpoint)))
    if settings.otel_console:
        provider.add_span_processor(SimpleSpanProcessor(ConsoleSpanExporter()))
    for processor in extra_processors or []:
        provider.add_span_processor(processor)
    trace.set_tracer_provider(provider)
    _provider = provider
    return provider


def shutdown_tracing() -> None:
    global _provider
    if _provider is not None:
        _provider.shutdown()
        _provider = None


def tracer() -> trace.Tracer:
    return trace.get_tracer(TRACER_NAME)


def span_reference(span: Span) -> dict[str, str] | None:
    context = span.get_span_context()
    if not context.is_valid:
        return None
    return {"trace_id": f"{context.trace_id:032x}", "span_id": f"{context.span_id:016x}"}


def _link(reference: dict[str, Any] | None) -> list[Link]:
    if not reference:
        return []
    try:
        context = SpanContext(
            trace_id=int(str(reference["trace_id"]), 16),
            span_id=int(str(reference["span_id"]), 16),
            is_remote=True,
            trace_flags=TraceFlags(TraceFlags.SAMPLED),
        )
    except (KeyError, ValueError):
        return []
    return [Link(context, {"handoff.link": "previous_execution"})] if context.is_valid else []


@contextmanager
def run_span(
    run_id: str, *, vendor: str, claims: int, first_execution: dict[str, Any] | None
) -> Iterator[Span]:
    """Root span for one execution of a run. Executions after a crash or an approval pause start
    new traces and link back to the first one, so a run reads as one story in the trace UI."""
    with tracer().start_as_current_span(
        "invoke_workflow due_diligence", kind=SpanKind.INTERNAL, links=_link(first_execution)
    ) as span:
        span.set_attribute("gen_ai.operation.name", "invoke_workflow")
        span.set_attribute("gen_ai.conversation.id", run_id)
        span.set_attribute("handoff.run.id", run_id)
        span.set_attribute("handoff.vendor", vendor)
        span.set_attribute("handoff.run.claims", claims)
        yield span


@contextmanager
def agent_span(agent: str, *, run_id: str, provider: str) -> Iterator[Span]:
    with tracer().start_as_current_span(f"invoke_agent {agent}", kind=SpanKind.INTERNAL) as span:
        span.set_attribute("gen_ai.operation.name", "invoke_agent")
        span.set_attribute("gen_ai.agent.name", agent)
        span.set_attribute("gen_ai.conversation.id", run_id)
        span.set_attribute("gen_ai.provider.name", provider)
        yield span


@contextmanager
def chat_span(model: str, *, provider: str, max_tokens: int) -> Iterator[Span]:
    with tracer().start_as_current_span(f"chat {model}", kind=SpanKind.CLIENT) as span:
        span.set_attribute("gen_ai.operation.name", "chat")
        span.set_attribute("gen_ai.provider.name", provider)
        span.set_attribute("gen_ai.request.model", model)
        span.set_attribute("gen_ai.request.max_tokens", max_tokens)
        yield span


@contextmanager
def tool_span(tool: str, *, call_id: str) -> Iterator[Span]:
    with tracer().start_as_current_span(f"execute_tool {tool}", kind=SpanKind.INTERNAL) as span:
        span.set_attribute("gen_ai.operation.name", "execute_tool")
        span.set_attribute("gen_ai.tool.name", tool)
        span.set_attribute("gen_ai.tool.call.id", call_id)
        span.set_attribute("gen_ai.tool.type", "extension")
        yield span


def mark_error(span: Span, exc: BaseException) -> None:
    span.set_status(Status(StatusCode.ERROR, str(exc)))
    span.set_attribute("error.type", type(exc).__name__)
