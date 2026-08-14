"""`organizations`, `organization_members` — Database.md §3.1, §3.3."""

from __future__ import annotations

import datetime
import uuid
from typing import TYPE_CHECKING

from sqlalchemy import CheckConstraint, ForeignKey, String, text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin, TZDateTime, UUIDPrimaryKeyMixin, utcnow
from app.models.enums import OrgRole, PlanTier, check_in

if TYPE_CHECKING:
    from app.models.project import Project
    from app.models.user import User


class Organization(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "organizations"
    __table_args__ = (CheckConstraint(check_in("plan_tier", PlanTier), name="plan_tier_valid"),)

    name: Mapped[str] = mapped_column(String(255), nullable=False)
    slug: Mapped[str] = mapped_column(String(100), nullable=False, unique=True)
    plan_tier: Mapped[str] = mapped_column(
        String(50), nullable=False, server_default=text("'free'"), default=PlanTier.FREE
    )

    members: Mapped[list[OrganizationMember]] = relationship(
        back_populates="organization", cascade="all, delete-orphan"
    )
    projects: Mapped[list[Project]] = relationship(back_populates="organization")


class OrganizationMember(Base):
    """Composite-PK join table carrying the org-level RBAC role (`Security.md §2`)."""

    __tablename__ = "organization_members"
    __table_args__ = (CheckConstraint(check_in("role", OrgRole), name="role_valid"),)

    organization_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), primary_key=True
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    role: Mapped[str] = mapped_column(String(50), nullable=False)
    joined_at: Mapped[datetime.datetime] = mapped_column(
        TZDateTime(),
        nullable=False,
        server_default=utcnow(),
        default=lambda: datetime.datetime.now(datetime.UTC),
    )

    organization: Mapped[Organization] = relationship(back_populates="members")
    user: Mapped[User] = relationship(back_populates="organization_memberships")
