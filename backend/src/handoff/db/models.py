from __future__ import annotations

from datetime import datetime
from typing import Any, Literal, get_args
from uuid import UUID, uuid4

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    Identity,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

RunStatus = Literal["queued", "running", "awaiting_approval", "completed", "rejected", "failed", "cancelled"]
ApprovalStatus = Literal["pending", "approved", "rejected", "expired"]

TERMINAL_STATUSES: frozenset[RunStatus] = frozenset({"completed", "rejected", "failed", "cancelled"})


def _in(column: str, literal: Any) -> str:
    values = ", ".join(f"'{v}'" for v in get_args(literal))
    return f"{column} IN ({values})"


class Base(DeclarativeBase):
    type_annotation_map = {dict[str, Any]: JSONB}


class RunRow(Base):
    __tablename__ = "runs"
    __table_args__ = (
        CheckConstraint(_in("status", RunStatus), name="runs_status_valid"),
        Index("ix_runs_status_created", "status", "created_at"),
        Index("ix_runs_created_id", "created_at", "id"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    thread_id: Mapped[str] = mapped_column(String(64), unique=True)
    vendor_name: Mapped[str] = mapped_column(String(200))
    vendor_country: Mapped[str] = mapped_column(String(2))
    vendor: Mapped[dict[str, Any]]
    budget_max_tokens: Mapped[int] = mapped_column(Integer)
    budget_max_usd: Mapped[float] = mapped_column(Float)
    status: Mapped[RunStatus] = mapped_column(String(32), default="queued")
    current_node: Mapped[str | None] = mapped_column(String(64))
    input_tokens: Mapped[int] = mapped_column(Integer, default=0)
    output_tokens: Mapped[int] = mapped_column(Integer, default=0)
    cost_usd: Mapped[float] = mapped_column(Float, default=0.0)
    llm_calls: Mapped[int] = mapped_column(Integer, default=0)
    tool_calls: Mapped[int] = mapped_column(Integer, default=0)
    risk_rating: Mapped[str | None] = mapped_column(String(16))
    decision: Mapped[str | None] = mapped_column(String(32))
    error: Mapped[dict[str, Any] | None]
    report: Mapped[dict[str, Any] | None]
    resume_payload: Mapped[dict[str, Any] | None]
    initial_state: Mapped[dict[str, Any] | None]
    trace_context: Mapped[dict[str, Any] | None]
    parent_run_id: Mapped[UUID | None] = mapped_column(ForeignKey("runs.id", ondelete="SET NULL"))
    forked_from_checkpoint: Mapped[str | None] = mapped_column(String(64))
    cancel_requested: Mapped[bool] = mapped_column(Boolean, default=False)
    claims: Mapped[int] = mapped_column(Integer, default=0)
    worker_id: Mapped[str | None] = mapped_column(String(64))
    heartbeat_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class ApprovalRow(Base):
    __tablename__ = "approvals"
    __table_args__ = (
        CheckConstraint(_in("status", ApprovalStatus), name="approvals_status_valid"),
        Index("ix_approvals_status_due", "status", "due_at"),
        UniqueConstraint("run_id", "interrupt_id", name="uq_approvals_run_interrupt"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    run_id: Mapped[UUID] = mapped_column(ForeignKey("runs.id", ondelete="CASCADE"), index=True)
    interrupt_id: Mapped[str] = mapped_column(String(64))
    status: Mapped[ApprovalStatus] = mapped_column(String(16), default="pending")
    request: Mapped[dict[str, Any]]
    response_schema: Mapped[dict[str, Any] | None]
    assignee: Mapped[str] = mapped_column(String(64))
    escalation_level: Mapped[int] = mapped_column(Integer, default=0)
    due_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    decision: Mapped[dict[str, Any] | None]
    decided_by: Mapped[str | None] = mapped_column(String(120))
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class RunEventRow(Base):
    __tablename__ = "run_events"
    __table_args__ = (Index("ix_run_events_run_id_id", "run_id", "id"),)

    id: Mapped[int] = mapped_column(BigInteger, Identity(always=True), primary_key=True)
    run_id: Mapped[UUID] = mapped_column(ForeignKey("runs.id", ondelete="CASCADE"))
    type: Mapped[str] = mapped_column(String(40))
    payload: Mapped[dict[str, Any]]
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class EvalReportRow(Base):
    __tablename__ = "eval_reports"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    suite: Mapped[str] = mapped_column(String(64))
    provider: Mapped[str] = mapped_column(String(32))
    summary: Mapped[dict[str, Any]]
    results: Mapped[dict[str, Any]]
    notes: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
