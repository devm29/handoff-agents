from __future__ import annotations

import time
from dataclasses import dataclass, field

from pydantic import BaseModel, ValidationError

from handoff.agents.briefing import render_briefing
from handoff.agents.specs import AgentSpec
from handoff.errors import ModelError, PolicyViolation
from handoff.events.sink import EventSink
from handoff.graph.budget import BudgetGuard
from handoff.graph.state import TrajectoryStep
from handoff.llm.types import (
    ChatRequest,
    LLMProvider,
    Message,
    ToolCall,
    ToolResult,
    ToolResultMessage,
    UserMessage,
)
from handoff.telemetry.otel import agent_span, mark_error, tool_span
from handoff.tools.gateway import ToolGateway

MAX_INVALID_SUBMISSIONS = 2
_PREVIEW_CHARS = 280


@dataclass
class AgentResult[T: BaseModel]:
    output: T
    steps: list[TrajectoryStep] = field(default_factory=list)


class AgentRunner:
    """Runs one specialist's tool-use loop until it submits a schema-valid answer."""

    def __init__(
        self,
        *,
        run_id: str,
        llm: LLMProvider,
        tools: ToolGateway,
        events: EventSink,
        budget: BudgetGuard,
        max_turns: int,
        max_output_tokens: int,
    ) -> None:
        self._run_id = run_id
        self._llm = llm
        self._tools = tools
        self._events = events
        self._budget = budget
        self._max_turns = max_turns
        self._max_output_tokens = max_output_tokens

    async def run[T: BaseModel](self, spec: AgentSpec[T], task: str, payload: BaseModel) -> AgentResult[T]:
        with agent_span(spec.name, run_id=self._run_id, provider=self._llm.provider_name) as span:
            try:
                result = await self._loop(spec, task, payload)
            except Exception as exc:
                mark_error(span, exc)
                raise
            span.set_attribute("gen_ai.usage.input_tokens", self._budget.delta.input_tokens)
            span.set_attribute("gen_ai.usage.output_tokens", self._budget.delta.output_tokens)
            return result

    async def _loop[T: BaseModel](self, spec: AgentSpec[T], task: str, payload: BaseModel) -> AgentResult[T]:
        available = {t.name: t for t in await self._tools.list_tools()} if spec.tools else {}
        missing = spec.tools - available.keys()
        if missing:
            raise PolicyViolation(
                f"{spec.name} requires tools the MCP server does not expose: {', '.join(sorted(missing))}"
            )
        tool_specs = [available[name] for name in sorted(spec.tools)] + [spec.submit_spec()]
        messages: list[Message] = [UserMessage(text=render_briefing(task, payload))]
        steps: list[TrajectoryStep] = []
        invalid_submissions = 0
        refused_submissions = 0

        for turn in range(1, self._max_turns + 1):
            self._budget.ensure_headroom()
            response = await self._llm.chat(
                ChatRequest(
                    agent=spec.name,
                    system=spec.system_prompt,
                    messages=messages,
                    tools=tool_specs,
                    max_tokens=self._budget.output_cap(self._max_output_tokens),
                )
            )
            spent = self._budget.record_llm(response.model, response.usage)
            steps.append(
                TrajectoryStep(
                    kind="llm_call",
                    agent=spec.name,
                    name=response.model,
                    detail=response.stop_reason,
                    tokens=response.usage.total,
                )
            )
            await self._events.emit(
                self._run_id,
                "llm.call",
                {
                    "agent": spec.name,
                    "model": response.model,
                    "turn": turn,
                    "stop_reason": response.stop_reason,
                    "input_tokens": spent.input_tokens,
                    "output_tokens": spent.output_tokens,
                    "cost_usd": spent.cost_usd,
                },
            )
            messages.append(response.message)

            if not response.message.tool_calls:
                if response.stop_reason == "max_tokens":
                    # A truncated reply is retried; a retry the budget cannot pay for is not.
                    self._budget.ensure_headroom()
                    raise ModelError(f"{spec.name} hit the output token limit", retryable=True)
                messages.append(
                    UserMessage(
                        text=f"Call {spec.submit_tool} with your final answer to finish this handoff."
                    )
                )
                continue

            results: list[ToolResult] = []
            submitted: T | None = None
            for call in response.message.tool_calls:
                if call.name == spec.submit_tool:
                    try:
                        candidate = spec.output_model.model_validate(call.arguments)
                    except ValidationError as exc:
                        invalid_submissions += 1
                        if invalid_submissions > MAX_INVALID_SUBMISSIONS:
                            raise ModelError(
                                f"{spec.name} kept submitting invalid {spec.output_model.__name__}",
                                retryable=True,
                            ) from exc
                        results.append(
                            ToolResult(call_id=call.id, content=f"Invalid submission: {exc}", is_error=True)
                        )
                        continue
                    problems = spec.check(candidate, payload) if spec.check else []
                    if problems:
                        refused_submissions += 1
                        if refused_submissions > MAX_INVALID_SUBMISSIONS:
                            detail = "; ".join(problems)
                            raise PolicyViolation(
                                f"{spec.name} submitted output that contradicts the record: {detail}",
                                details={"agent": spec.name},
                            )
                        results.append(
                            ToolResult(
                                call_id=call.id,
                                content="Submission refused: " + "; ".join(problems),
                                is_error=True,
                            )
                        )
                        continue
                    submitted = candidate
                    steps.append(TrajectoryStep(kind="submit", agent=spec.name, name=call.name))
                    results.append(ToolResult(call_id=call.id, content="Submission accepted."))
                elif call.name not in spec.tools:
                    raise PolicyViolation(
                        f"{spec.name} called {call.name}, which is outside its tool allowlist",
                        details={"agent": spec.name, "tool": call.name},
                    )
                else:
                    result, step = await self._execute(spec.name, call)
                    results.append(result)
                    steps.append(step)

            if submitted is not None:
                return AgentResult(output=submitted, steps=steps)
            messages.append(ToolResultMessage(results=results))

        raise ModelError(f"{spec.name} did not finish within {self._max_turns} turns", retryable=False)

    async def _execute(self, agent: str, call: ToolCall) -> tuple[ToolResult, TrajectoryStep]:
        started = time.perf_counter()
        with tool_span(call.name, call_id=call.id) as span:
            try:
                outcome = await self._tools.call(call.name, call.arguments)
            except Exception as exc:
                mark_error(span, exc)
                raise
            if outcome.is_error:
                span.set_attribute("error.type", "tool_error")
        self._budget.record_tool()
        duration_ms = round((time.perf_counter() - started) * 1000)
        await self._events.emit(
            self._run_id,
            "tool.call",
            {
                "agent": agent,
                "tool": call.name,
                "arguments": call.arguments,
                "ok": not outcome.is_error,
                "duration_ms": duration_ms,
                "preview": outcome.content[:_PREVIEW_CHARS],
            },
        )
        step = TrajectoryStep(
            kind="tool_call",
            agent=agent,
            name=call.name,
            ok=not outcome.is_error,
            arguments=call.arguments,
            result_preview=outcome.content[:_PREVIEW_CHARS],
            detail=None if not outcome.is_error else outcome.content[:_PREVIEW_CHARS],
        )
        return ToolResult(call_id=call.id, content=outcome.content, is_error=outcome.is_error), step
