"""Applying the policy — resolves the resource's scope and compares it to the principal.

The important property here is that authorization is checked against the **resource's**
org/project, loaded from the database, never against an org id supplied by the caller.
Trusting a caller-supplied `organization_id` is precisely the horizontal privilege
escalation `Security.md §2` calls out.
"""

from __future__ import annotations

import uuid
from collections.abc import Awaitable, Callable

from fastapi import Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_current_principal, get_db
from app.core.errors import ForbiddenError, NotFoundError
from app.core.logging import get_logger
from app.models.enums import OrgRole, ProjectRole
from app.models.organization import OrganizationMember
from app.models.project import Project, ProjectMember
from app.rbac.policy import (
    PERMISSIONS,
    PROJECT_ROLE_RANK,
    Permission,
    Principal,
    org_role_satisfies,
    project_role_satisfies,
)

logger = get_logger(__name__)


async def resolve_org_role(
    session: AsyncSession, principal: Principal, organization_id: uuid.UUID
) -> str | None:
    """The principal's role in `organization_id`, or None if not a member.

    An API-key principal is bound to exactly one organization at mint time, so it carries
    its role directly; asking the DB for a membership row would find none.
    """
    if principal.is_api_key:
        return principal.org_role if principal.organization_id == organization_id else None
    if principal.user_id is None:
        return None
    result = await session.execute(
        select(OrganizationMember.role).where(
            OrganizationMember.organization_id == organization_id,
            OrganizationMember.user_id == principal.user_id,
        )
    )
    return result.scalar_one_or_none()


async def resolve_project_role(
    session: AsyncSession, principal: Principal, project: Project
) -> str | None:
    """The principal's effective role on `project`.

    Two paths grant access, and the stronger of the two wins:

    1. An explicit `project_members` row.
    2. Org-level seniority — an org `owner`/`admin` administers every project in their
       org without needing a per-project row, which is what makes
       `PROJECT_ARCHIVE: org_role=admin` in the matrix workable.

    A `member`-only org role grants nothing by itself: project access must be explicit.
    """
    org_role = await resolve_org_role(session, principal, project.organization_id)
    if org_role is None:
        # Not in the owning org at all — no project access by any route.
        return None

    if principal.is_api_key:
        # API keys have no per-project membership rows, so the org role governs. An
        # org-owner key gets owner rights; an admin key gets editor rights, deliberately
        # short of owner so the owner-only gates (export, plan approval, credential
        # writes) still require an interactive human session.
        if org_role == OrgRole.OWNER:
            return ProjectRole.OWNER
        if org_role == OrgRole.ADMIN:
            return ProjectRole.EDITOR
        return None

    explicit: str | None = None
    if principal.user_id is not None:
        result = await session.execute(
            select(ProjectMember.role).where(
                ProjectMember.project_id == project.id,
                ProjectMember.user_id == principal.user_id,
            )
        )
        explicit = result.scalar_one_or_none()

    implied = ProjectRole.OWNER if org_role in (OrgRole.OWNER, OrgRole.ADMIN) else None

    if explicit is None:
        return implied
    if implied is None:
        return explicit
    # Take the stronger of the two.
    return explicit if PROJECT_ROLE_RANK[explicit] >= PROJECT_ROLE_RANK[implied] else implied


async def load_project_for_principal(
    session: AsyncSession, principal: Principal, project_id: uuid.UUID
) -> Project:
    """Fetch a project the principal is allowed to know exists.

    Raises `NotFoundError` — not `ForbiddenError` — when the project belongs to another
    organization. A 403 would confirm the id is real, letting an attacker enumerate other
    tenants' project ids; 404 leaks nothing. A principal who *is* in the owning org but
    lacks the needed role still gets a 403 from the permission check, since existence is
    not a secret from them.
    """
    if not principal.may_touch_project(project_id):
        # API key scoped to a different project — same reasoning as above.
        raise NotFoundError()

    project = await session.get(Project, project_id)
    if project is None:
        raise NotFoundError()

    org_role = await resolve_org_role(session, principal, project.organization_id)
    if org_role is None:
        logger.warning(
            "cross_tenant_project_access_blocked",
            project_id=str(project_id),
            principal_org_id=str(principal.organization_id),
            resource_org_id=str(project.organization_id),
        )
        raise NotFoundError()
    return project


def require_org_permission(
    permission: Permission,
) -> Callable[..., Awaitable[Principal]]:
    """Dependency factory for org-scoped routes with an `org_id` path parameter."""
    requirement = PERMISSIONS[permission]

    async def dependency(
        org_id: uuid.UUID,
        principal: Principal = Depends(get_current_principal),
        session: AsyncSession = Depends(get_db),
    ) -> Principal:
        if requirement.org_role is None:
            # A project-scoped permission cannot be enforced on an org route.
            raise ForbiddenError()

        actual = await resolve_org_role(session, principal, org_id)
        if not org_role_satisfies(actual, requirement.org_role):
            logger.info(
                "authorization_denied",
                permission=str(permission),
                scope="organization",
                organization_id=str(org_id),
                actual_role=actual,
                required_role=requirement.org_role,
            )
            # Not a member at all: don't confirm the org exists.
            if actual is None:
                raise NotFoundError()
            raise ForbiddenError()
        return principal

    return dependency


def require_project_permission(
    permission: Permission,
) -> Callable[..., Awaitable[Project]]:
    """Dependency factory for project-scoped routes with an `id` path parameter.

    Returns the loaded `Project` so the route does not re-query it — the resource has
    already been fetched to determine its owning org.
    """
    requirement = PERMISSIONS[permission]

    async def dependency(
        id: uuid.UUID,  # noqa: A002 — matches the `{id}` path param in API.md §6
        principal: Principal = Depends(get_current_principal),
        session: AsyncSession = Depends(get_db),
    ) -> Project:
        project = await load_project_for_principal(session, principal, id)

        if requirement.project_role is not None:
            actual = await resolve_project_role(session, principal, project)
            if not project_role_satisfies(actual, requirement.project_role):
                logger.info(
                    "authorization_denied",
                    permission=str(permission),
                    scope="project",
                    project_id=str(id),
                    actual_role=actual,
                    required_role=requirement.project_role,
                )
                raise ForbiddenError()

        if requirement.org_role is not None:
            actual_org = await resolve_org_role(session, principal, project.organization_id)
            if not org_role_satisfies(actual_org, requirement.org_role):
                logger.info(
                    "authorization_denied",
                    permission=str(permission),
                    scope="project_via_org",
                    project_id=str(id),
                    actual_role=actual_org,
                    required_role=requirement.org_role,
                )
                raise ForbiddenError()

        return project

    return dependency


async def assert_org_permission(
    session: AsyncSession,
    principal: Principal,
    permission: Permission,
    organization_id: uuid.UUID,
) -> None:
    """Imperative form, for routes that take the org id from the body rather than the path
    (e.g. `POST /projects`, API.md §6.1)."""
    requirement = PERMISSIONS[permission]
    if requirement.org_role is None:
        raise ForbiddenError()
    actual = await resolve_org_role(session, principal, organization_id)
    if not org_role_satisfies(actual, requirement.org_role):
        logger.info(
            "authorization_denied",
            permission=str(permission),
            scope="organization",
            organization_id=str(organization_id),
            actual_role=actual,
            required_role=requirement.org_role,
        )
        if actual is None:
            raise NotFoundError()
        raise ForbiddenError()
