"""Project routes — `API.md §6.1`."""

from __future__ import annotations

import datetime
import uuid

from fastapi import APIRouter, Depends, Query, Request, status
from sqlalchemy import Select, func, select, tuple_
from sqlalchemy import false as sa_false
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import client_ip, get_current_principal, get_db, utc_now
from app.core.errors import ConflictError
from app.models.audit import AuditAction
from app.models.enums import ActorType, OrgRole, ProjectRole, ProjectStatus
from app.models.organization import OrganizationMember
from app.models.project import Project, ProjectMember
from app.models.spec import APISpec, Endpoint
from app.models.workflow import WorkflowRun
from app.rbac.enforce import assert_org_permission, require_project_permission
from app.rbac.policy import Permission, Principal
from app.schemas.common import Page, PaginationMeta, decode_cursor, encode_cursor
from app.schemas.project import (
    CreateProjectRequest,
    ProjectResponse,
    ProjectSummaryResponse,
)
from app.services import audit_service

router = APIRouter(prefix="/projects", tags=["projects"])


@router.post(
    "",
    response_model=ProjectResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a project",
)
async def create_project(
    payload: CreateProjectRequest,
    request: Request,
    principal: Principal = Depends(get_current_principal),
    session: AsyncSession = Depends(get_db),
) -> ProjectResponse:
    """The org id comes from the body here (per `API.md §6.1`), so it is checked against
    the principal's actual membership rather than trusted."""
    await assert_org_permission(
        session, principal, Permission.PROJECT_CREATE, payload.organization_id
    )

    # API.md §5 lists 409 for a duplicate project name.
    existing = await session.execute(
        select(Project.id).where(
            Project.organization_id == payload.organization_id,
            Project.name == payload.name,
            Project.archived_at.is_(None),
        )
    )
    if existing.scalar_one_or_none() is not None:
        raise ConflictError(f"A project named {payload.name!r} already exists.")

    project = Project(
        organization_id=payload.organization_id,
        name=payload.name,
        status=ProjectStatus.DRAFT,
        created_by=principal.user_id,
    )
    session.add(project)
    await session.flush()

    # The creator becomes project owner so they can act without relying on org seniority.
    if principal.user_id is not None:
        session.add(
            ProjectMember(project_id=project.id, user_id=principal.user_id, role=ProjectRole.OWNER)
        )

    await audit_service.record(
        session,
        action=AuditAction.PROJECT_CREATED,
        actor_type=ActorType.SYSTEM if principal.is_api_key else ActorType.USER,
        organization_id=payload.organization_id,
        actor_user_id=principal.user_id,
        resource_type="project",
        resource_id=str(project.id),
        ip_address=client_ip(request),
        user_agent=request.headers.get("user-agent"),
    )
    return ProjectResponse.model_validate(project)


def _visible_projects(principal: Principal) -> Select[tuple[Project]]:
    """Base query restricted to projects the principal can see.

    Multi-tenant isolation lives in the query, not in a post-filter — `Security.md §2`
    requires org-scoped queries so a missing application-level check cannot leak rows.
    A user sees a project when they are an explicit project member, or when their org
    role is owner/admin (which administers the whole org).
    """
    stmt = select(Project)

    if principal.is_api_key:
        # An org-scoped key sees its own org; a project-restricted key sees one project.
        stmt = stmt.where(Project.organization_id == principal.organization_id)
        if principal.restricted_to_project_id is not None:
            stmt = stmt.where(Project.id == principal.restricted_to_project_id)
        return stmt

    if principal.user_id is None:
        # Unreachable for an authenticated principal, but deny-by-default beats an
        # accidentally unfiltered query if a future auth mode forgets to set user_id.
        return stmt.where(sa_false())

    member_of = select(ProjectMember.project_id).where(ProjectMember.user_id == principal.user_id)
    admin_orgs = select(OrganizationMember.organization_id).where(
        OrganizationMember.user_id == principal.user_id,
        OrganizationMember.role.in_([OrgRole.OWNER, OrgRole.ADMIN]),
    )
    return stmt.where(Project.id.in_(member_of) | Project.organization_id.in_(admin_orgs))


@router.get("", response_model=Page[ProjectResponse], summary="List projects")
async def list_projects(
    principal: Principal = Depends(get_current_principal),
    session: AsyncSession = Depends(get_db),
    limit: int = Query(default=25, ge=1, le=100),
    cursor: str | None = Query(default=None),
    project_status: ProjectStatus | None = Query(default=None, alias="status"),
    organization_id: uuid.UUID | None = Query(default=None),
) -> Page[ProjectResponse]:
    """Cursor-paginated per `API.md §4`.

    The cursor is a `(created_at, id)` pair rather than an offset: an offset would skip or
    repeat rows when a project is created mid-pagination, and `created_at` alone is not
    unique enough to break ties deterministically.
    """
    stmt = _visible_projects(principal)

    if project_status is not None:
        stmt = stmt.where(Project.status == project_status)
    if organization_id is not None:
        # Narrows within what is already visible — it cannot widen the scope.
        stmt = stmt.where(Project.organization_id == organization_id)

    if cursor and (position := decode_cursor(cursor)):
        try:
            last_created = datetime.datetime.fromisoformat(position["created_at"])
            last_id = uuid.UUID(position["id"])
            # Row-value comparison, matching the ORDER BY exactly. Comparing the columns
            # separately would either skip rows sharing a timestamp or need an OR that
            # the planner handles worse.
            stmt = stmt.where(
                tuple_(Project.created_at, Project.id) < tuple_(last_created, last_id)
            )
        except (KeyError, TypeError, ValueError):
            pass  # Malformed cursor: start from the beginning rather than 400.

    stmt = stmt.order_by(Project.created_at.desc(), Project.id.desc()).limit(limit + 1)

    rows = list((await session.execute(stmt)).scalars().all())
    has_more = len(rows) > limit
    page_rows = rows[:limit]

    next_cursor = None
    if has_more and page_rows:
        last = page_rows[-1]
        next_cursor = encode_cursor({"created_at": last.created_at.isoformat(), "id": str(last.id)})

    return Page[ProjectResponse](
        data=[ProjectResponse.model_validate(row) for row in page_rows],
        pagination=PaginationMeta(next_cursor=next_cursor, has_more=has_more, limit=limit),
    )


@router.get(
    "/{id}",
    response_model=ProjectSummaryResponse,
    summary="Retrieve a project with summary counts",
)
async def get_project(
    project: Project = Depends(require_project_permission(Permission.PROJECT_READ)),
    session: AsyncSession = Depends(get_db),
) -> ProjectSummaryResponse:
    endpoint_count = await session.scalar(
        select(func.count(Endpoint.id))
        .join(APISpec, APISpec.id == Endpoint.api_spec_id)
        .where(APISpec.project_id == project.id)
    )
    last_run_status = await session.scalar(
        select(WorkflowRun.status)
        .where(WorkflowRun.project_id == project.id)
        .order_by(WorkflowRun.id.desc())
        .limit(1)
    )

    summary = ProjectSummaryResponse.model_validate(project)
    return summary.model_copy(
        update={
            "endpoint_count": endpoint_count or 0,
            "last_run_status": last_run_status,
        }
    )


@router.delete(
    "/{id}",
    response_model=ProjectResponse,
    summary="Archive a project (soft delete)",
)
async def archive_project(
    request: Request,
    project: Project = Depends(require_project_permission(Permission.PROJECT_ARCHIVE)),
    principal: Principal = Depends(get_current_principal),
    session: AsyncSession = Depends(get_db),
) -> ProjectResponse:
    """Soft-deletes per `API.md §6.1`. Idempotent: archiving an archived project returns
    it unchanged rather than erroring, so a retried request is harmless."""
    if project.archived_at is None:
        project.archived_at = utc_now()
        project.status = ProjectStatus.ARCHIVED

        await audit_service.record(
            session,
            action=AuditAction.PROJECT_ARCHIVED,
            actor_type=ActorType.SYSTEM if principal.is_api_key else ActorType.USER,
            organization_id=project.organization_id,
            actor_user_id=principal.user_id,
            resource_type="project",
            resource_id=str(project.id),
            ip_address=client_ip(request),
            user_agent=request.headers.get("user-agent"),
        )

    return ProjectResponse.model_validate(project)
