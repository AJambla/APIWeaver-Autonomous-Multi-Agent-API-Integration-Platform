"""Dependency graph API routes."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_db
from app.models.project import Project
from app.models.spec import APISpec, Endpoint, EndpointDependency
from app.rbac.enforce import require_project_permission
from app.rbac.policy import Permission
from app.schemas.dependency import DependencyEdge, DependencyGraphResponse, DependencyNode

router = APIRouter(prefix="/projects", tags=["dependency"])


@router.get("/{id}/dependency-graph", response_model=DependencyGraphResponse)
async def get_dependency_graph(
    project: Project = Depends(require_project_permission(Permission.SPEC_READ)),
    session: AsyncSession = Depends(get_db),
) -> DependencyGraphResponse:
    """Get the dependency graph for a project's current spec."""
    spec = await session.scalar(
        select(APISpec)
        .where(APISpec.project_id == project.id)
        .order_by(APISpec.created_at.desc())
        .limit(1)
    )

    if spec is None:
        return DependencyGraphResponse(nodes=[], edges=[])

    endpoints = list(
        (await session.execute(
            select(Endpoint).where(Endpoint.api_spec_id == spec.id)
        )).scalars()
    )

    endpoint_ids = [e.id for e in endpoints]

    nodes = [
        DependencyNode(
            id=e.id,
            label=f"{e.method} {e.path}",
            method=e.method,
            path=e.path,
        )
        for e in endpoints
    ]

    dependencies = list(
        (await session.execute(
            select(EndpointDependency)
            .where(EndpointDependency.project_id == project.id)
            .where(EndpointDependency.from_endpoint_id.in_(endpoint_ids))
        )).scalars()
    )

    edges = [
        DependencyEdge(
            from_=d.from_endpoint_id,
            to=d.to_endpoint_id,
            relationship=d.relationship,
        )
        for d in dependencies
    ]

    return DependencyGraphResponse(nodes=nodes, edges=edges)
