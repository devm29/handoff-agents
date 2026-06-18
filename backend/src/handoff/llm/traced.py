from __future__ import annotations

from handoff.llm.types import ChatRequest, ChatResponse, LLMProvider
from handoff.telemetry.otel import chat_span, mark_error


class TracedProvider:
    """Wraps any provider with an OpenTelemetry GenAI `chat` span per call."""

    def __init__(self, inner: LLMProvider) -> None:
        self._inner = inner

    @property
    def provider_name(self) -> str:
        return self._inner.provider_name

    @property
    def default_model(self) -> str:
        return self._inner.default_model

    async def chat(self, request: ChatRequest) -> ChatResponse:
        model = request.model or self._inner.default_model
        with chat_span(model, provider=self.provider_name, max_tokens=request.max_tokens) as span:
            span.set_attribute("gen_ai.agent.name", request.agent)
            try:
                response = await self._inner.chat(request)
            except Exception as exc:
                mark_error(span, exc)
                raise
            span.set_attribute("gen_ai.response.model", response.model)
            if response.response_id:
                span.set_attribute("gen_ai.response.id", response.response_id)
            span.set_attribute("gen_ai.response.finish_reasons", [response.stop_reason])
            span.set_attribute("gen_ai.usage.input_tokens", response.usage.input_tokens)
            span.set_attribute("gen_ai.usage.output_tokens", response.usage.output_tokens)
            usage = response.usage
            span.set_attribute("gen_ai.usage.cache_read.input_tokens", usage.cache_read_input_tokens)
            span.set_attribute("gen_ai.usage.cache_creation.input_tokens", usage.cache_creation_input_tokens)
            return response
