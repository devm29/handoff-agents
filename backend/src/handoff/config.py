from __future__ import annotations

import os
import socket
from functools import lru_cache
from typing import Literal, Self
from uuid import uuid4

from pydantic import BaseModel, Field, PostgresDsn, SecretStr, computed_field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

LLMProviderName = Literal["anthropic", "fake"]
RiskLevel = Literal["low", "medium", "high", "critical"]
Effort = Literal["low", "medium", "high", "xhigh", "max"]

DEMO_TOKEN_PREFIX = "demo-"


def default_worker_id() -> str:
    """Unique per process, so two workers never mistake each other's runs for their own."""
    host = socket.gethostname().split(".")[0][:32]
    return f"{host}-{os.getpid()}-{uuid4().hex[:6]}"


class ReviewerAccount(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    role: str = Field(min_length=1, max_length=64)
    token: SecretStr = Field(min_length=12)


DEMO_REVIEWERS: list[ReviewerAccount] = [
    ReviewerAccount(name="Priya Raman", role="analyst", token=SecretStr("demo-analyst-token")),
    ReviewerAccount(
        name="Sofia Marin", role="compliance-lead", token=SecretStr("demo-compliance-lead-token")
    ),
    ReviewerAccount(name="James Whitaker", role="chief-risk-officer", token=SecretStr("demo-cro-token")),
]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(".env", "../.env"),
        env_prefix="HANDOFF_",
        extra="ignore",
    )

    environment: Literal["development", "test", "production"] = "development"
    log_level: str = "INFO"
    log_json: bool = False

    database_url: PostgresDsn = Field(
        default=PostgresDsn("postgresql://handoff@127.0.0.1:5504/handoff"),
        description="Plain postgresql:// URL; drivers are chosen per consumer.",
    )
    auto_migrate: bool = True

    api_host: str = "127.0.0.1"
    api_port: int = 8104
    cors_origins: list[str] = ["http://localhost:3104", "http://127.0.0.1:3104"]

    llm_provider: LLMProviderName = "fake"
    anthropic_api_key: SecretStr | None = Field(default=None, validation_alias="ANTHROPIC_API_KEY")
    model: str = "claude-opus-5-5"
    judge_model: str = "claude-opus-5-5"
    effort: Effort = "medium"
    max_output_tokens: int = 8_000
    refusal_fallback: bool = True
    fake_latency_ms: int = 350

    mcp_transport: Literal["inprocess", "stdio", "http"] = "stdio"
    mcp_url: str = "http://127.0.0.1:8000/mcp"
    mcp_http_host: str = "127.0.0.1"
    mcp_http_port: int = 8000

    default_max_tokens: int = 120_000
    default_max_usd: float = 1.50
    node_max_attempts: int = 3
    agent_max_turns: int = 8

    approval_timeout_seconds: int = 3_600
    escalation_tiers: list[str] = ["analyst", "compliance-lead", "chief-risk-officer"]
    auto_approve_max_risk: RiskLevel | None = "low"

    reviewers: list[ReviewerAccount] = Field(default_factory=lambda: list(DEMO_REVIEWERS))
    session_cookie_secure: bool = False

    worker_id: str = Field(default_factory=default_worker_id, max_length=64)
    worker_concurrency: int = 4
    worker_poll_seconds: float = 2.0
    worker_lease_seconds: int = 30
    worker_heartbeat_seconds: float = 5.0
    sweep_interval_seconds: float = 5.0

    otel_service_name: str = "handoff"
    otel_exporter_otlp_endpoint: str | None = Field(
        default=None, validation_alias="OTEL_EXPORTER_OTLP_ENDPOINT"
    )
    otel_console: bool = False

    @model_validator(mode="after")
    def _check(self) -> Self:
        if self.worker_heartbeat_seconds * 2 > self.worker_lease_seconds:
            raise ValueError("worker_heartbeat_seconds must be at most half of worker_lease_seconds")
        unknown = {r.role for r in self.reviewers} - set(self.escalation_tiers)
        if unknown:
            raise ValueError(f"reviewer roles {sorted(unknown)} are not escalation tiers")
        tokens = [r.token.get_secret_value() for r in self.reviewers]
        if len(set(tokens)) != len(tokens):
            raise ValueError("reviewer tokens must be unique")
        if self.environment == "production" and any(t.startswith(DEMO_TOKEN_PREFIX) for t in tokens):
            raise ValueError("demo reviewer tokens are not allowed in production; set HANDOFF_REVIEWERS")
        return self

    @property
    def demo_accounts_enabled(self) -> bool:
        return self.environment == "development" and all(
            r.token.get_secret_value().startswith(DEMO_TOKEN_PREFIX) for r in self.reviewers
        )

    @computed_field  # type: ignore[prop-decorator]
    @property
    def sqlalchemy_url(self) -> str:
        return str(self.database_url).replace("postgresql://", "postgresql+psycopg://", 1)

    @computed_field  # type: ignore[prop-decorator]
    @property
    def psycopg_url(self) -> str:
        return str(self.database_url)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
