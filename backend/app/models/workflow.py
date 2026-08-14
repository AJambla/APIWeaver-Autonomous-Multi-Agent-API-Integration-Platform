"""`workflow_runs`, `workflow_checkpoints`, `agent_events`, `tool_calls`.

Database.md §3.14–§3.17.
"""

from __future__ import annotations

import datetime
import decimal
import uuid
from typing import Any

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import (
    JSONB,
    Base,
    CreatedAtMixin,
    TZDateTime,
    UUIDPrimaryKeyMixin,
    bigint_pk,
    utcnow,
)
from app.models.enums import WorkflowStatus, check_in

# Tables created by raw DDL in migration 0002 because they are natively partitioned.
# `alembic/env.py` reads this marker in its `include_object` hook so autogenerate never
# tries to "correct" them back into plain tables.
PARTITIONED_TABLE_INFO = {"managed_by_migration": "0002_partitioned_tables"}


class WorkflowRun(UUIDPrimaryKeyMixin, Base):
    """One execution of the LangGraph state machine (Architecture.md §4)."""

    __tablename__ = "workflow_runs"
    __table_args__ = (
        CheckConstraint(check_in("status", WorkflowStatus), name="status_valid"),
        Index("idx_workflow_runs_project_id", "project_id"),
        Index("idx_workflow_runs_status", "status"),
    )

    project_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    triggered_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    status: Mapped[str] = mapped_column(String(50), nullable=False, default=WorkflowStatus.QUEUED)
    started_at: Mapped[datetime.datetime | None] = mapped_column(
        TZDateTime(), nullable=True
    )
    completed_at: Mapped[datetime.datetime | None] = mapped_column(
        TZDateTime(), nullable=True
    )
    # Per-project token budget enforcement reads these (Security.md §15).
    total_tokens_used: Mapped[int] = mapped_column(
        BigInteger, nullable=False, server_default=text("0"), default=0
    )
    estimated_cost_usd: Mapped[decimal.Decimal] = mapped_column(
        Numeric(10, 4), nullable=False, server_default=text("0"), default=decimal.Decimal("0")
    )

    checkpoints: Mapped[list[WorkflowCheckpoint]] = relationship(
        back_populates="workflow_run", cascade="all, delete-orphan"
    )


class WorkflowCheckpoint(UUIDPrimaryKeyMixin, CreatedAtMixin, Base):
    """LangGraph checkpoint — a crashed orchestrator resumes from here
    (Architecture.md §10)."""

    __tablename__ = "workflow_checkpoints"
    __table_args__ = (Index("idx_workflow_checkpoints_run_id", "workflow_run_id"),)

    workflow_run_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("workflow_runs.id", ondelete="CASCADE"), nullable=False
    )
    node_name: Mapped[str] = mapped_column(String(100), nullable=False)
    state_snapshot: Mapped[dict[str, Any]] = mapped_column(JSONB(), nullable=False)

    workflow_run: Mapped[WorkflowRun] = relationship(back_populates="checkpoints")


class AgentEvent(Base):
    """High-write agent trace, partitioned monthly by `created_at` (Database.md §3.16).

    The primary key is composite `(id, created_at)`: Postgres requires the partition key
    to participate in every unique constraint on a partitioned table, so `id` alone
    cannot be the PK. `id` is still globally unique via the shared sequence.

    Created by migration 0002 (raw DDL) — SQLAlchemy cannot express `PARTITION BY` here.
    """

    __tablename__ = "agent_events"
    __table_args__ = (
        Index("idx_agent_events_run_id", "workflow_run_id"),
        Index("idx_agent_events_created_at", "created_at"),
        {"info": PARTITIONED_TABLE_INFO},
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    created_at: Mapped[datetime.datetime] = mapped_column(
        TZDateTime(),
        primary_key=True,
        nullable=False,
        server_default=utcnow(),
        default=lambda: datetime.datetime.now(datetime.UTC),
    )
    workflow_run_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("workflow_runs.id", ondelete="CASCADE"), nullable=False
    )
    agent_name: Mapped[str] = mapped_column(String(100), nullable=False)
    event_type: Mapped[str] = mapped_column(String(50), nullable=False)
    payload: Mapped[dict[str, Any] | None] = mapped_column(JSONB(), nullable=True)


class ToolCall(Base):
    """Per-tool-invocation trace backing `GET /workflows/{run_id}/tool-calls` (API.md §6.4).

    `agent_event_id` is an indexed BIGINT rather than a foreign key: `agent_events` is
    partitioned with a composite `(id, created_at)` primary key, so `id` alone is not a
    valid FK target. Integrity is maintained by the orchestrator, which writes the event
    and its tool calls in one transaction. See ADDENDUM-Phase1.md §A.4.
    """

    __tablename__ = "tool_calls"
    __table_args__ = (Index("idx_tool_calls_agent_event_id", "agent_event_id"),)

    id: Mapped[int] = bigint_pk()
    agent_event_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    tool_name: Mapped[str] = mapped_column(String(100), nullable=False)
    arguments: Mapped[dict[str, Any] | None] = mapped_column(JSONB(), nullable=True)
    result: Mapped[dict[str, Any] | None] = mapped_column(JSONB(), nullable=True)
    duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
