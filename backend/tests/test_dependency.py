"""Tests for dependency graph routes."""

from __future__ import annotations

import uuid

import pytest
from httpx import AsyncClient

from app.core.security import create_access_token
from app.models.enums import DependencyRelationship, OrgRole, ProjectRole
from app.models.spec import APISpec, Endpoint, EndpointDependency
from tests.conftest import (
    add_org_member,
    add_project_member,
    make_org,
    make_project,
    make_user,
)


@pytest.fixture
async def setup_project_with_spec(db):
    org = await make_org(db, name="Dep Org")
    user = await make_user(db, email="dep@example.com", name="Dep User")
    await add_org_member(db, org=org, user=user, role=OrgRole.MEMBER)
    project = await make_project(db, org=org, name="Dep Project")
    await add_project_member(db, project=project, user=user, role=ProjectRole.VIEWER)

    spec = APISpec(
        project_id=project.id,
        raw_normalized={"openapi": "3.0.0"},
    )
    db.add(spec)
    await db.flush()

    endpoint1 = Endpoint(
        api_spec_id=spec.id,
        method="POST",
        path="/users",
        summary="Create user",
        response_schemas={"201": {"type": "object"}},
    )
    endpoint2 = Endpoint(
        api_spec_id=spec.id,
        method="GET",
        path="/users/{id}",
        summary="Get user",
        response_schemas={"200": {"type": "object"}},
    )
    db.add(endpoint1)
    db.add(endpoint2)
    await db.flush()

    return org, user, project, spec, endpoint1, endpoint2


@pytest.mark.asyncio
async def test_dependency_graph_unauthenticated(client: AsyncClient) -> None:
    response = await client.get(f"/api/v1/projects/{uuid.uuid4()}/dependency-graph")
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_dependency_graph_empty(client: AsyncClient, db, test_settings) -> None:
    org = await make_org(db, name="Empty Org")
    user = await make_user(db, email="empty@example.com", name="Empty User")
    await add_org_member(db, org=org, user=user, role=OrgRole.MEMBER)
    project = await make_project(db, org=org, name="Empty Project")
    await add_project_member(db, project=project, user=user, role=ProjectRole.VIEWER)

    token = create_access_token(
        user_id=user.id,
        org_id=org.id,
        role=OrgRole.MEMBER,
        settings=test_settings,
    )
    headers = {"Authorization": f"Bearer {token.token}"}

    response = await client.get(
        f"/api/v1/projects/{project.id}/dependency-graph",
        headers=headers,
    )
    assert response.status_code == 200
    data = response.json()
    assert data["nodes"] == []
    assert data["edges"] == []


@pytest.mark.asyncio
async def test_dependency_graph_with_endpoints(
    client: AsyncClient, db, test_settings, setup_project_with_spec
) -> None:
    org, user, project, spec, endpoint1, endpoint2 = setup_project_with_spec

    dep = EndpointDependency(
        project_id=project.id,
        from_endpoint_id=endpoint2.id,
        to_endpoint_id=endpoint1.id,
        relationship=DependencyRelationship.REQUIRES_CREATED_RESOURCE,
    )
    db.add(dep)
    await db.commit()

    token = create_access_token(
        user_id=user.id,
        org_id=org.id,
        role=OrgRole.MEMBER,
        settings=test_settings,
    )
    headers = {"Authorization": f"Bearer {token.token}"}

    response = await client.get(
        f"/api/v1/projects/{project.id}/dependency-graph",
        headers=headers,
    )
    assert response.status_code == 200
    data = response.json()
    assert len(data["nodes"]) == 2
    assert len(data["edges"]) == 1

    node_ids = {n["id"] for n in data["nodes"]}
    assert str(endpoint1.id) in node_ids
    assert str(endpoint2.id) in node_ids

    edge = data["edges"][0]
    assert edge["from"] == str(endpoint2.id)
    assert edge["to"] == str(endpoint1.id)
