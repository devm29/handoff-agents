from __future__ import annotations

import anthropic

from handoff.config import Settings
from handoff.llm.anthropic_provider import AnthropicProvider
from handoff.llm.fake import ScriptedFakeProvider
from handoff.llm.traced import TracedProvider
from handoff.llm.types import LLMProvider


def build_provider(settings: Settings, *, model: str | None = None) -> LLMProvider:
    match settings.llm_provider:
        case "fake":
            inner: LLMProvider = ScriptedFakeProvider(latency_ms=settings.fake_latency_ms)
        case "anthropic":
            key = settings.anthropic_api_key.get_secret_value() if settings.anthropic_api_key else None
            client = anthropic.AsyncAnthropic(api_key=key) if key else anthropic.AsyncAnthropic()
            inner = AnthropicProvider(
                client,
                model=model or settings.model,
                effort=settings.effort,
                refusal_fallback=settings.refusal_fallback,
            )
    return TracedProvider(inner)
