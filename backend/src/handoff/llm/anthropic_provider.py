from __future__ import annotations

from typing import Any, cast

import anthropic
from anthropic.types.beta import BetaMessage, BetaMessageParam, BetaTextBlockParam, BetaToolParam

from handoff.config import Effort
from handoff.errors import ModelError
from handoff.llm.types import (
    AssistantMessage,
    ChatRequest,
    ChatResponse,
    Message,
    StopReason,
    TokenUsage,
    ToolCall,
    ToolResultMessage,
    UserMessage,
)

# Server-side refusal fallback ("default" routing) is accepted on these models only.
_FALLBACK_MODELS = frozenset({"claude-opus-5-5", "claude-opus-5", "claude-fable-5-1", "claude-sonnet-5-5"})
_FALLBACK_BETA = "server-side-fallback-2026-07-01"

_STOP_REASONS: dict[str, StopReason] = {
    "end_turn": "end_turn",
    "tool_use": "tool_use",
    "max_tokens": "max_tokens",
    "refusal": "refusal",
}


class AnthropicProvider:
    def __init__(
        self,
        client: anthropic.AsyncAnthropic,
        *,
        model: str,
        effort: Effort = "medium",
        refusal_fallback: bool = True,
    ) -> None:
        self._client = client
        self._model = model
        self._effort = effort
        self._refusal_fallback = refusal_fallback

    @property
    def provider_name(self) -> str:
        return "anthropic"

    @property
    def default_model(self) -> str:
        return self._model

    async def chat(self, request: ChatRequest) -> ChatResponse:
        model = request.model or self._model
        use_fallback = self._refusal_fallback and model in _FALLBACK_MODELS
        # Tools render before the system prompt, so one breakpoint on each caches both stable
        # prefixes that every turn of an agent loop re-sends.
        tools: list[BetaToolParam] = [
            {"name": t.name, "description": t.description, "input_schema": t.input_schema}
            for t in request.tools
        ]
        if tools:
            tools[-1]["cache_control"] = {"type": "ephemeral"}
        system: list[BetaTextBlockParam] = [
            {"type": "text", "text": request.system, "cache_control": {"type": "ephemeral"}}
        ]
        try:
            response = await self._client.beta.messages.create(
                model=model,
                max_tokens=request.max_tokens,
                system=system,
                messages=[_to_param(m) for m in request.messages],
                tools=tools if tools else anthropic.omit,
                output_config={"effort": self._effort},
                betas=[_FALLBACK_BETA] if use_fallback else anthropic.omit,
                fallbacks="default" if use_fallback else anthropic.omit,
            )
        except (anthropic.RateLimitError, anthropic.InternalServerError) as exc:
            raise ModelError(f"Anthropic API unavailable: {exc.message}", retryable=True) from exc
        except (anthropic.APITimeoutError, anthropic.APIConnectionError) as exc:
            raise ModelError(f"Anthropic API connection failed: {exc}", retryable=True) from exc
        except anthropic.APIStatusError as exc:
            raise ModelError(
                f"Anthropic API rejected the request ({exc.status_code}): {exc.message}", retryable=False
            ) from exc

        if response.stop_reason == "refusal":
            category = response.stop_details.category if response.stop_details else None
            raise ModelError(
                "Model declined the request", retryable=False, details={"category": str(category)}
            )
        return _from_message(response)


def _to_param(message: Message) -> BetaMessageParam:
    match message:
        case UserMessage(text=text):
            return {"role": "user", "content": text}
        case AssistantMessage(native_content=list() as native):
            return {"role": "assistant", "content": cast("Any", native)}
        case AssistantMessage(text=text, tool_calls=calls):
            blocks: list[dict[str, Any]] = [{"type": "text", "text": text}] if text else []
            blocks.extend(
                {"type": "tool_use", "id": c.id, "name": c.name, "input": c.arguments} for c in calls
            )
            return {"role": "assistant", "content": cast("Any", blocks)}
        case ToolResultMessage(results=results):
            return {
                "role": "user",
                "content": [
                    {
                        "type": "tool_result",
                        "tool_use_id": r.call_id,
                        "content": r.content,
                        "is_error": r.is_error,
                    }
                    for r in results
                ],
            }
    raise TypeError(f"unsupported message {type(message).__name__}")


def _from_message(response: BetaMessage) -> ChatResponse:
    text_parts: list[str] = []
    calls: list[ToolCall] = []
    for block in response.content:
        if block.type == "text":
            text_parts.append(block.text)
        elif block.type == "tool_use":
            calls.append(ToolCall(id=block.id, name=block.name, arguments=dict(block.input)))
    return ChatResponse(
        message=AssistantMessage(
            text="\n".join(text_parts),
            tool_calls=calls,
            native_content=[b.model_dump(mode="json", exclude_none=True) for b in response.content],
        ),
        stop_reason=_STOP_REASONS.get(response.stop_reason or "", "other"),
        usage=TokenUsage(
            input_tokens=response.usage.input_tokens,
            output_tokens=response.usage.output_tokens,
            cache_creation_input_tokens=response.usage.cache_creation_input_tokens or 0,
            cache_read_input_tokens=response.usage.cache_read_input_tokens or 0,
        ),
        model=response.model,
        response_id=response.id,
    )
