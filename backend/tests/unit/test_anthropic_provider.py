from __future__ import annotations

from typing import Any, cast

import anthropic
import pytest
from anthropic.types.beta import BetaMessage

from handoff.errors import ModelError
from handoff.llm.anthropic_provider import AnthropicProvider
from handoff.llm.types import (
    AssistantMessage,
    ChatRequest,
    ToolCall,
    ToolResult,
    ToolResultMessage,
    ToolSpec,
    UserMessage,
)


def _message(content: list[dict[str, Any]], stop_reason: str = "tool_use", **extra: Any) -> BetaMessage:
    return BetaMessage.model_validate(
        {
            "id": "msg_1",
            "type": "message",
            "role": "assistant",
            "model": "claude-opus-5-5",
            "content": content,
            "stop_reason": stop_reason,
            "stop_sequence": None,
            "usage": {"input_tokens": 120, "output_tokens": 40},
            **extra,
        }
    )


class StubMessages:
    def __init__(self, response: BetaMessage) -> None:
        self.response = response
        self.calls: list[dict[str, Any]] = []

    async def create(self, **kwargs: Any) -> BetaMessage:
        self.calls.append(kwargs)
        return self.response


class StubClient:
    def __init__(self, response: BetaMessage) -> None:
        self.messages = StubMessages(response)
        self.beta = self


def _provider(response: BetaMessage, **kwargs: Any) -> tuple[AnthropicProvider, StubMessages]:
    client = StubClient(response)
    provider = AnthropicProvider(cast("anthropic.AsyncAnthropic", client), model="claude-opus-5-5", **kwargs)
    return provider, client.messages


REQUEST = ChatRequest(
    agent="researcher",
    system="sys",
    messages=[
        UserMessage(text="find Acme"),
        AssistantMessage(
            tool_calls=[ToolCall(id="toolu_1", name="news_search", arguments={"query": "Acme"})],
            native_content=[
                {"type": "thinking", "thinking": "", "signature": "sig"},
                {"type": "tool_use", "id": "toolu_1", "name": "news_search", "input": {"query": "Acme"}},
            ],
        ),
        ToolResultMessage(results=[ToolResult(call_id="toolu_1", content="{}", is_error=False)]),
    ],
    tools=[ToolSpec(name="news_search", description="d", input_schema={"type": "object", "properties": {}})],
    max_tokens=2_000,
)


async def test_request_shape_replays_native_blocks_and_enables_fallback() -> None:
    response = _message(
        [
            {"type": "thinking", "thinking": "", "signature": "abc"},
            {"type": "text", "text": "Looking it up."},
            {"type": "tool_use", "id": "toolu_2", "name": "news_search", "input": {"query": "Acme Corp"}},
        ]
    )
    provider, messages = _provider(response)
    result = await provider.chat(REQUEST)

    call = messages.calls[0]
    assert call["model"] == "claude-opus-5-5"
    assert call["betas"] == ["server-side-fallback-2026-07-01"]
    assert call["fallbacks"] == "default"
    assert call["output_config"] == {"effort": "medium"}
    assert call["messages"][1]["content"][0]["type"] == "thinking", "thinking blocks are echoed unchanged"
    assert call["messages"][2]["content"][0]["tool_use_id"] == "toolu_1"

    assert result.stop_reason == "tool_use"
    assert result.message.text == "Looking it up."
    assert result.message.tool_calls == [
        ToolCall(id="toolu_2", name="news_search", arguments={"query": "Acme Corp"})
    ]
    assert result.message.native_content is not None
    assert result.message.native_content[0]["signature"] == "abc"
    assert result.usage.input_tokens == 120


async def test_fallback_is_omitted_when_disabled() -> None:
    provider, messages = _provider(
        _message([{"type": "text", "text": "ok"}], "end_turn"), refusal_fallback=False
    )
    await provider.chat(REQUEST)
    assert messages.calls[0]["betas"] is anthropic.omit


async def test_refusal_becomes_a_non_retryable_model_error() -> None:
    refusal = _message(
        [], "refusal", stop_details={"type": "refusal", "category": "cyber", "explanation": "declined"}
    )
    provider, _ = _provider(refusal)
    with pytest.raises(ModelError) as caught:
        await provider.chat(REQUEST)
    assert not caught.value.retryable
