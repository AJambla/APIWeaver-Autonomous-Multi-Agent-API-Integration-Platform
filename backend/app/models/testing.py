"""`test_runs`, `test_results`, `repair_attempts` — Database.md §3.20–§3.22."""

from __future__ import annotations

import datetime
import uuid
from typing import Any

from sqlalchemy import CheckConstraint, ForeignKey, Index, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import JSONB, Base, TZDateTime, UUIDPrimaryKeyMixin
from app.models.enums import RepairOutcome, TestEnvironment, TestResultStatus, check_in


class TestRun(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "test_runs"
    __table_args__ = (
        CheckConstraint(check_in("environment", TestEnvironment), name="environment_valid"),
        Index("idx_test_runs_project_id", "project_id"),
    )

    project_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    workflow_run_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("workflow_runs.id", ondelete="SET NULL"), nullable=True
    )
    status: Mapped[str] = mapped_column(String(50), nullable=False, default="pending")
    environment: Mapped[str] = mapped_column(String(20), nullable=False)
    started_at: Mapped[datetime.datetime | None] = mapped_column(
        TZDateTime(), nullable=True
    )
    completed_at: Mapped[datetime.datetime | None] = mapped_column(
        TZDateTime(), nullable=True
    )
    summary: Mapped[dict[str, Any] | None] = mapped_column(JSONB(), nullable=True)

    results: Mapped[list[TestResult]] = relationship(
        back_populates="test_run", cascade="all, delete-orphan"
    )


class TestResult(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "test_results"
    __table_args__ = (
        CheckConstraint(check_in("status", TestResultStatus), name="status_valid"),
        Index("idx_test_results_run_id", "test_run_id"),
        Index("idx_test_results_endpoint_id", "endpoint_id"),
    )

    test_run_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("test_runs.id", ondelete="CASCADE"), nullable=False
    )
    endpoint_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("endpoints.id", ondelete="SET NULL"), nullable=True
    )
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    status_code: Mapped[int | None] = mapped_column(Integer, nullable=True)
    latency_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    response_snapshot: Mapped[dict[str, Any] | None] = mapped_column(JSONB(), nullable=True)

    test_run: Mapped[TestRun] = relationship(back_populates="results")
    repair_attempts: Mapped[list[RepairAttempt]] = relationship(
        back_populates="test_result", cascade="all, delete-orphan"
    )


class RepairAttempt(UUIDPrimaryKeyMixin, Base):
    """One iteration of the self-healing loop (Feature.md §13-14, Architecture.md §5)."""

    __tablename__ = "repair_attempts"
    __table_args__ = (
        CheckConstraint(
            "outcome IS NULL OR " + check_in("outcome", RepairOutcome), name="outcome_valid"
        ),
        Index("idx_repair_attempts_test_result_id", "test_result_id"),
    )

    test_result_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("test_results.id", ondelete="CASCADE"), nullable=False
    )
    attempt_number: Mapped[int] = mapped_column(Integer, nullable=False)
    failure_classification: Mapped[str | None] = mapped_column(String(50), nullable=True)
    diff_summary: Mapped[dict[str, Any] | None] = mapped_column(JSONB(), nullable=True)
    outcome: Mapped[str | None] = mapped_column(String(20), nullable=True)

    test_result: Mapped[TestResult] = relationship(back_populates="repair_attempts")
