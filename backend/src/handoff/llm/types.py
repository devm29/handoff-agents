from __future__ import annotations

from typing import Annotated, Any, Literal, Protocol

from pydantic import BaseModel, Field

JsonObject = dict[str, Any]


class ToolSpec(BaseModel):
    name: str
    description: str
    input_schema: JsonObject


class ToolCall(BaseModel):
    id: str
    name: str
    arguments: JsonObject = Field(default_factory=dict)


class ToolResult(BaseModel):
    call_id: str
    content: str
    is_error: bool = False


class UserMessage(BaseModel):
    role: Literal["user"] = "user"
    text: str


class AssistantMessage(BaseModel):
    role: Literal["assistant"] = "assistant"
    text: str = ""
    tool_calls: list[ToolCall] = Field(default_factory=list)
    native_content: list[JsonObject] | None = Field(
        default=None,
        description="Provider-native content blocks, replayed verbatim so thinking blocks stay valid.",
    )


class ToolResultMessage(BaseModel):
    role: Literal["tool"] = "tool"
    results: list[ToolResult]


Message = Annotated[UserMessage | AssistantMessage | ToolResultMessage, Field(discriminator="role")]

StopReason = Literal["end_turn", "tool_use", "max_tokens", "refusal", "other"]


class TokenUsage(BaseModel):
    input_tokens: int = Field(default=0, description="Uncached input tokens")
    output_tokens: int = 0
    cache_creation_input_tokens: int = 0
    cache_read_input_tokens: int = 0

    @property
    def billable_input_tokens(self) -> int:
        return self.input_tokens + self.cache_creation_input_tokens + self.cache_read_input_tokens

    @property
    def total(self) -> int:
        return self.billable_input_tokens + self.output_tokens


class ChatRequest(BaseModel):
    agent: str
    system: str
    messages: list[Message]
    tools: list[ToolSpec] = Field(default_factory=list)
    max_tokens: int = 4_000
    model: str | None = None


class ChatResponse(BaseModel):
    message: AssistantMessage
    stop_reason: StopReason
    usage: TokenUsage
    model: str
    response_id: str | None = None


class LLMProvider(Protocol):
    @property
    def provider_name(self) -> str: ...

    @property
    def default_model(self) -> str: ...

    async def chat(self, request: ChatRequest) -> ChatResponse: ...
