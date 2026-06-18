from __future__ import annotations

import pytest
from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from handoff.agents.runner import AgentRunner
from handoff.agents.schemas import VendorProfile
from handoff.agents.specs import RESEARCHER
from handoff.events.sink import MemorySink
from handoff.graph.budget import BudgetGuard
from handoff.graph.contracts import ResearcherInput
from handoff.graph.state import Budget, Usage
from handoff.llm.fake import ScriptedFakeProvider
from handoff.llm.traced import TracedProvider
from handoff.tools.gateway import MCPToolGateway

_exporter = InMemorySpanExporter()
_provider = TracerProvider()
_provider.add_span_processor(SimpleSpanProcessor(_exporter))
trace.set_tracer_provider(_provider)


@pytest.fixture
def spans() -> InMemorySpanExporter:
    _exporter.clear()
    return _exporter


async def test_mcp_gateway_exposes_tools_and_structured_results(tools: MCPToolGateway) -> None:
    names = {t.name for t in await tools.list_tools()}
    assert names == {"company_registry_lookup", "sanctions_check", "news_search"}
    outcome = await tools.call("sanctions_check", {"name": "Marek Dravik", "kind": "person"})
    assert not outcome.is_error
    assert outcome.structured["result"] == "match"
    bad = await tools.call("sanctions_check", {"name": "x", "kind": "robot"})
    assert bad.is_error


async def test_agent_run_emits_genai_spans(tools: MCPToolGateway, spans: InMemorySpanExporter) -> None:
    runner = AgentRunner(
        run_id="run-1",
        llm=TracedProvider(ScriptedFakeProvider()),
        tools=tools,
        events=MemorySink(),
        budget=BudgetGuard(Budget(max_tokens=100_000, max_usd=1), Usage()),
        max_turns=6,
        max_output_tokens=2_000,
    )
    result = await runner.run(
        RESEARCHER,
        "Research the vendor",
        ResearcherInput(vendor=VendorProfile(name="Northwind Logistics", country="DE")),
    )
    assert result.output.legal_name == "Northwind Logistics GmbH"

    finished = spans.get_finished_spans()
    names = [s.name for s in finished]
    assert "invoke_agent researcher" in names
    assert names.count("chat scripted-fake") == 3
    assert {"execute_tool company_registry_lookup", "execute_tool news_search"} <= set(names)

    agent = next(s for s in finished if s.name == "invoke_agent researcher")
    chat = next(s for s in finished if s.name.startswith("chat"))
    assert agent.attributes is not None and agent.attributes["gen_ai.conversation.id"] == "run-1"
    assert chat.attributes is not None and chat.attributes["gen_ai.usage.input_tokens"] > 0
    assert chat.parent is not None and chat.parent.span_id == agent.context.span_id
