"""`api_specs`, `endpoints`, `endpoint_parameters`, `endpoint_dependencies`.

Database.md §3.8–§3.11.
"""

from __future__ import annotations

import decimal
import uuid
from typing import Any

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    ForeignKey,
    Index,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import JSONB, Base, CreatedAtMixin, UUIDPrimaryKeyMixin, false_
from app.models.enums import DependencyRelationship, HTTPMethod, ParameterLocation, check_in

# Reused on every confidence column (Database.md §3.8, §3.9).
CONFIDENCE_TYPE = Numeric(3, 2)


class APISpec(UUIDPrimaryKeyMixin, CreatedAtMixin, Base):
    """Canonical normalized spec produced by the Documentation Agent (Phase 2)."""

    __tablename__ = "api_specs"
    __table_args__ = (
        CheckConstraint(
            "confidence_score IS NULL OR (confidence_score >= 0 AND confidence_score <= 1)",
            name="confidence_score_range",
        ),
        Index("idx_api_specs_project_id", "project_id"),
    )

    project_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    source_document_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("documents.id", ondelete="SET NULL"), nullable=True
    )
    title: Mapped[str | None] = mapped_column(String(255), nullable=True)
    base_url: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    raw_normalized: Mapped[dict[str, Any]] = mapped_column(JSONB(), nullable=False)
    confidence_score: Mapped[decimal.Decimal | None] = mapped_column(CONFIDENCE_TYPE, nullable=True)

    endpoints: Mapped[list[Endpoint]] = relationship(
        back_populates="api_spec", cascade="all, delete-orphan"
    )


class Endpoint(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "endpoints"
    __table_args__ = (
        CheckConstraint(check_in("method", HTTPMethod), name="method_valid"),
        CheckConstraint(
            "confidence_score IS NULL OR (confidence_score >= 0 AND confidence_score <= 1)",
            name="confidence_score_range",
        ),
        Index("idx_endpoints_spec_id", "api_spec_id"),
        UniqueConstraint("api_spec_id", "method", "path", name="uniq_endpoint_method_path"),
    )

    api_spec_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("api_specs.id", ondelete="CASCADE"), nullable=False
    )
    method: Mapped[str] = mapped_column(String(10), nullable=False)
    path: Mapped[str] = mapped_column(String(1000), nullable=False)
    summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    request_schema: Mapped[dict[str, Any] | None] = mapped_column(JSONB(), nullable=True)
    # Keyed by status code (Database.md §3.9).
    response_schemas: Mapped[dict[str, Any]] = mapped_column(JSONB(), nullable=False)
    deprecated: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=false_(), default=False
    )
    # Drives the MCP `requires_confirmation` flag on export (Feature.md §19-24).
    is_destructive: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=false_(), default=False
    )
    confidence_score: Mapped[decimal.Decimal | None] = mapped_column(CONFIDENCE_TYPE, nullable=True)

    api_spec: Mapped[APISpec] = relationship(back_populates="endpoints")
    parameters: Mapped[list[EndpointParameter]] = relationship(
        back_populates="endpoint", cascade="all, delete-orphan"
    )


class EndpointParameter(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "endpoint_parameters"
    __table_args__ = (
        CheckConstraint(check_in("location", ParameterLocation), name="location_valid"),
        Index("idx_endpoint_parameters_endpoint_id", "endpoint_id"),
    )

    endpoint_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("endpoints.id", ondelete="CASCADE"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    location: Mapped[str] = mapped_column(String(20), nullable=False)
    type: Mapped[str] = mapped_column(String(50), nullable=False)
    required: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=false_(), default=False
    )

    endpoint: Mapped[Endpoint] = relationship(back_populates="parameters")


class EndpointDependency(UUIDPrimaryKeyMixin, Base):
    """Self-referencing M:N edge built by the Planner Agent (Phase 3)."""

    __tablename__ = "endpoint_dependencies"
    __table_args__ = (
        CheckConstraint(
            check_in("relationship", DependencyRelationship), name="relationship_valid"
        ),
        # Database.md §3.11 — prevents a trivial self-loop in the dependency graph.
        CheckConstraint("from_endpoint_id <> to_endpoint_id", name="no_self_loop"),
        Index("idx_endpoint_dependencies_project_id", "project_id"),
        Index("idx_endpoint_dependencies_from", "from_endpoint_id"),
    )

    project_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    from_endpoint_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("endpoints.id", ondelete="CASCADE"), nullable=False
    )
    to_endpoint_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("endpoints.id", ondelete="CASCADE"), nullable=False
    )
    # `relationship` shadows nothing on the model, but is a SQLAlchemy import name —
    # kept as the spec names it since the column name is what Database.md §3.11 defines.
    relationship: Mapped[str | None] = mapped_column(String(50), nullable=True)
