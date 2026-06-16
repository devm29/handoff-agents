"""initial schema

Revision ID: 0001
Revises:
Create Date: 2026-10-04
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "eval_reports",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("suite", sa.String(length=64), nullable=False),
        sa.Column("provider", sa.String(length=32), nullable=False),
        sa.Column("summary", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("results", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "runs",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("thread_id", sa.String(length=64), nullable=False),
        sa.Column("vendor_name", sa.String(length=200), nullable=False),
        sa.Column("vendor_country", sa.String(length=2), nullable=False),
        sa.Column("vendor", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("budget_max_tokens", sa.Integer(), nullable=False),
        sa.Column("budget_max_usd", sa.Float(), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("current_node", sa.String(length=64), nullable=True),
        sa.Column("input_tokens", sa.Integer(), nullable=False),
        sa.Column("output_tokens", sa.Integer(), nullable=False),
        sa.Column("cost_usd", sa.Float(), nullable=False),
        sa.Column("llm_calls", sa.Integer(), nullable=False),
        sa.Column("tool_calls", sa.Integer(), nullable=False),
        sa.Column("risk_rating", sa.String(length=16), nullable=True),
        sa.Column("decision", sa.String(length=32), nullable=True),
        sa.Column("error", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("report", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("resume_payload", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("initial_state", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("trace_context", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("parent_run_id", sa.Uuid(), nullable=True),
        sa.Column("forked_from_checkpoint", sa.String(length=64), nullable=True),
        sa.Column("cancel_requested", sa.Boolean(), nullable=False),
        sa.Column("claims", sa.Integer(), nullable=False),
        sa.Column("worker_id", sa.String(length=64), nullable=True),
        sa.Column("heartbeat_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "status IN ('queued', 'running', 'awaiting_approval', "
            "'completed', 'rejected', 'failed', 'cancelled')",
            name="runs_status_valid",
        ),
        sa.ForeignKeyConstraint(["parent_run_id"], ["runs.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("thread_id"),
    )
    op.create_index("ix_runs_created_id", "runs", ["created_at", "id"], unique=False)
    op.create_index("ix_runs_status_created", "runs", ["status", "created_at"], unique=False)
    op.create_table(
        "approvals",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("run_id", sa.Uuid(), nullable=False),
        sa.Column("interrupt_id", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("request", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("response_schema", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("assignee", sa.String(length=64), nullable=False),
        sa.Column("escalation_level", sa.Integer(), nullable=False),
        sa.Column("due_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("decision", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("decided_by", sa.String(length=120), nullable=True),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint(
            "status IN ('pending', 'approved', 'rejected', 'expired')", name="approvals_status_valid"
        ),
        sa.ForeignKeyConstraint(["run_id"], ["runs.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("run_id", "interrupt_id", name="uq_approvals_run_interrupt"),
    )
    op.create_index(op.f("ix_approvals_run_id"), "approvals", ["run_id"], unique=False)
    op.create_index("ix_approvals_status_due", "approvals", ["status", "due_at"], unique=False)
    op.create_table(
        "run_events",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=True), nullable=False),
        sa.Column("run_id", sa.Uuid(), nullable=False),
        sa.Column("type", sa.String(length=40), nullable=False),
        sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["run_id"], ["runs.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_run_events_run_id_id", "run_events", ["run_id", "id"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_run_events_run_id_id", table_name="run_events")
    op.drop_table("run_events")
    op.drop_index("ix_approvals_status_due", table_name="approvals")
    op.drop_index(op.f("ix_approvals_run_id"), table_name="approvals")
    op.drop_table("approvals")
    op.drop_index("ix_runs_status_created", table_name="runs")
    op.drop_index("ix_runs_created_id", table_name="runs")
    op.drop_table("runs")
    op.drop_table("eval_reports")
