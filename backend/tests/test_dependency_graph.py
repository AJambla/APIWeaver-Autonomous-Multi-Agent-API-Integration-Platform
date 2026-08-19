"""Tests for Dependency Graph endpoint (`API.md §6.5`)."""

from __future__ import annotations

import uuid

from httpx import AsyncClient

from app.models.spec import APISpec, Endpoint, EndpointDependency
from tests.conftest import TEST_PASSWORD


async def _setup_project_with_spec(client: AsyncClient, db) -> tuple[str, dict[str, str]]:
    """Create a user, org, project, and a normalized spec with endpoints + dependencies."""
    res = await client.post(
        "/api/v1/auth/register",
        json={
            "email": "dep_user@example.com",
            "password": TEST_PASSWORD,
            "full_name": "Dependency Tester",
            "organization_name": "Dependency Org",
        },
    )
    assert res.status_code == 201
    token = res.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    me = await client.get("/api/v1/auth/me", headers=headers)
    org_id = me.json()["organizations"][0]["organization_id"]

    proj = await client.post(
        "/api/v1/projects",
        json={"name": "Dependency Test Project", "organization_id": org_id},
        headers=headers,
    )
    assert proj.status_code == 201
    project_id = proj.json()["id"]

    # Create a spec and endpoints directly
    async with db as session:
        spec = APISpec(
            project_id=uuid.UUID(project_id),
            raw_normalized={},
        )
        session.add(spec)
        await session.flush()

        ep1 = Endpoint(
            api_spec_id=spec.id,
            method="POST",
            path="/orders",
            summary="Create order",
            response_schemas={"201": {"type": "object"}},
            is_destructive=False,
        )
        ep2 = Endpoint(
            api_spec_id=spec.id,
            method="GET",
            path="/orders/{id}",
            summary="Get order",
            response_schemas={"200": {"type": "object"}},
            is_destructive=False,
        )
        session.add_all([ep1, ep2])
        await session.flush()

        dep = EndpointDependency(
            project_id=uuid.UUID(project_id),
            from_endpoint_id=ep1.id,
            to_endpoint_id=ep2.id,
            relationship="requires_created_resource",
        )
        session.add(dep)
        await session.commit()

    return project_id, headers


async def test_get_dependency_graph(client: AsyncClient, db) -> None:
    project_id, headers = await _setup_project_with_spec(client, db)

    # Fetch dependency graph
    res = await client.get(f"/api/v1/projects/{project_id}/dependency-graph", headers=headers)
    assert res.status_code == 200
    data = res.json()
    assert "nodes" in data
    assert "edges" in data
    assert len(data["nodes"]) == 2
    assert len(data["edges"]) == 1

    # Verify node structure
    node = data["nodes"][0]
    assert "id" in node
    assert node["id"].startswith("ep_")
    assert "method" in node
    assert "path" in node

    # Verify edge structure
    edge = data["edges"][0]
    assert edge["from_id"].startswith("ep_")
    assert edge["to_id"].startswith("ep_")
    assert edge["relationship"] == "requires_created_resource"


async def test_get_dependency_graph_empty(client: AsyncClient, db) -> None:
    """When no spec exists, return empty graph."""
    res = await client.post(
        "/api/v1/auth/register",
        json={
            "email": "dep_empty@example.com",
            "password": TEST_PASSWORD,
            "full_name": "Empty Dep Tester",
            "organization_name": "Empty Dep Org",
        },
    )
    assert res.status_code == 201
    token = res.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    me = await client.get("/api/v1/auth/me", headers=headers)
    org_id = me.json()["organizations"][0]["organization_id"]

    proj = await client.post(
        "/api/v1/projects",
        json={"name": "Empty Dep Project", "organization_id": org_id},
        headers=headers,
    )
    assert proj.status_code == 201
    project_id = proj.json()["id"]

    res = await client.get(f"/api/v1/projects/{project_id}/dependency-graph", headers=headers)
    assert res.status_code == 200
    data = res.json()
    assert data["nodes"] == []
    assert data["edges"] == []