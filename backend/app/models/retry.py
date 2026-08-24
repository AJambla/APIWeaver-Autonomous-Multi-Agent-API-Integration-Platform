"""Retry policy configuration model — `Feature.md §15`."""

from __future__ import annotations

import uuid

from sqlalchemy import JSON, ForeignKey, text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class RetryConfig(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Per-project retry policy configuration.

    Matches frontend `RetryPolicy` interface:
    - max_attempts: maximum retry attempts (default 3)
    - backoff_base_seconds: exponential backoff base (default 2)
    - retryable_status_codes: HTTP status codes to retry (default [429, 500, 502, 503, 504])
    """

    __tablename__ = "retry_configs"

    project_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, unique=True
    )
    max_attempts: Mapped[int] = mapped_column(nullable=False, server_default=text("3"), default=3)
    backoff_base_seconds: Mapped[int] = mapped_column(
        nullable=False, server_default=text("2"), default=2
    )
    retryable_status_codes: Mapped[list[int]] = mapped_column(
        JSON,
        nullable=False,
        default=lambda: [429, 500, 502, 503, 504],
    )