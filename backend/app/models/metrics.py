"""`usage_metrics` — Database.md §3.28.

Partitioned by day with a 90-day TTL. Like `agent_events`, the table itself is created by
raw DDL in migration 0002; this model exists so the ORM can read and write it.
"""

from __future__ import annotations

import datetime
import decimal
import uuid

from sqlalchemy import BigInteger, ForeignKey, Index, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TZDateTime, bigint_pk, utcnow


class UsageMetric(Base):
    """Usage metrics per organization."""

    __tablename__ = "usage_metrics"
    __table_args__ = (
        Index("idx_usage_metrics_org_id", "organization_id"),
        Index("idx_usage_metrics_metric_name", "metric_name"),
    )

    id: Mapped[int] = bigint_pk()
    recorded_at: Mapped[datetime.datetime] = mapped_column(
        TZDateTime(),
        nullable=False,
        server_default=utcnow(),
        default=lambda: datetime.datetime.now(datetime.UTC),
    )
    organization_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False
    )
    metric_name: Mapped[str] = mapped_column(String(100), nullable=False)
    value: Mapped[decimal.Decimal] = mapped_column(Numeric(18, 4), nullable=False)
