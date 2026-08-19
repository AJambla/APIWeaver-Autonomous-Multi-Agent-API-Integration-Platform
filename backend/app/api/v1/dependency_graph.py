"""Dependency Graph API route (`API.md §6.5`)."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_db
from app.models.enums import DependencyRelationship
from app.models.project import Project
from app.models.spec import Endpoint, EndpointDependency
from app.rbac.enforce import require_project_permission
from app.rbac.policy import Permission
from app.schemas.dependency_graph import DependencyEdge, DependencyGraphResponse, DependencyNode

router = APIRouter(tags=["dependency_graph"])


@router.get("/projects/{id}/dependency-graph", response_model=DependencyGraphResponse)
async def get_dependency_graph(
    project: Project = Depends(require_project_permission(Permission.SPEC_READ)),
    session: AsyncSession = Depends(get_db),
) -> DependencyGraphResponse:
    """Get the dependency graph for a project's endpoints."""
    # Get all endpoints for the project's latest spec
    from app.models.spec import APISpec
    latest_spec = await session.scalar(
        select(APISpec)
        .where(APISpec.project_id == project.id)
        .order_by(APISpec.created_at.desc())
        .limit(1)
    )
    if not latest_spec:
        return DependencyGraphResponse(nodes=[], edges=[])

    endpoints = await session.scalars(
        select(Endpoint).where(Endpoint.api_spec_id == latest_spec.id)
    )
    endpoint_list = list(endpoints.all())

    # Map endpoint ID to node
    endpoint_map = {ep.id: ep for ep in endpoint_list}

    # Build nodes
    nodes = [
        DependencyNode(
            id=f"ep_{ep.id}",
            label=ep.summary or f"{ep.method} {ep.path}",
            method=ep.method,
            path=ep.path,
            is_destructive=ep.is_destructive,
        )
        for ep in endpoint_list
    ]

    # Get dependencies for this project
    deps = await session.scalars(
        select(EndpointDependency).where(EndpointDependency.project_id == project.id)
    )
    dep_list = list(deps.all())

    # Build edges
    edges = []
    for dep in dep_list:
        from_ep = endpoint_map.get(dep.from_endpoint_id)
        to_ep = endpoint_map.get(dep.to_endpoint_id)
        if from_ep and to_ep:
            rel = dep.relationship or DependencyRelationship.OPTIONAL_PRECEDES
            edges.append(
                DependencyEdge(
                    from_id=f"ep_{from_ep.id}",
                    to_id=f"ep_{to_ep.id}",
                    relationship=rel,
                )
            )

    return DependencyGraphResponse(nodes=nodes, edges=edges)