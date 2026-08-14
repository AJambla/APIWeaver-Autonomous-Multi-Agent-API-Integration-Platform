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

from app.db.base import Base, TZDateTime, utcnow
from app.models.workflow import PARTITIONED_TABLE_INFO


class UsageMetric(Base):
    """Composite `(id, recorded_at)` PK — `recorded_at` is the partition key, and
    Postgres requires it in every unique constraint on a partitioned table."""

    __tablename__ = "usage_metrics"
    __table_args__ = (
        Index("idx_usage_metrics_org_id", "organization_id"),
        Index("idx_usage_metrics_metric_name", "metric_name"),
        {"info": PARTITIONED_TABLE_INFO},
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    recorded_at: Mapped[datetime.datetime] = mapped_column(
        TZDateTime(),
        primary_key=True,
        nullable=False,
        server_default=utcnow(),
        default=lambda: datetime.datetime.now(datetime.UTC),
    )
    organization_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False
    )
    metric_name: Mapped[str] = mapped_column(String(100), nullable=False)
    value: Mapped[decimal.Decimal] = mapped_column(Numeric(18, 4), nullable=False)
