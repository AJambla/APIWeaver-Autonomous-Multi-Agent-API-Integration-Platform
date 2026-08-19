"""Tests for Spec Patch endpoint (`API.md §6.5`)."""

from __future__ import annotations

import uuid

from httpx import AsyncClient

from app.models.spec import APISpec, Endpoint, EndpointParameter
from tests.conftest import TEST_PASSWORD


async def _setup_project_with_endpoint(client: AsyncClient, db) -> tuple[str, str, dict[str, str]]:
    """Create a user, org, project, spec, and an endpoint to patch."""
    res = await client.post(
        "/api/v1/auth/register",
        json={
            "email": "patch_user@example.com",
            "password": TEST_PASSWORD,
            "full_name": "Patch Tester",
            "organization_name": "Patch Org",
        },
    )
    assert res.status_code == 201
    token = res.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    me = await client.get("/api/v1/auth/me", headers=headers)
    org_id = me.json()["organizations"][0]["organization_id"]

    proj = await client.post(
        "/api/v1/projects",
        json={"name": "Patch Test Project", "organization_id": org_id},
        headers=headers,
    )
    assert proj.status_code == 201
    project_id = proj.json()["id"]

    # Create a spec and endpoint directly
    async with db as session:
        spec = APISpec(
            project_id=uuid.UUID(project_id),
            raw_normalized={},
        )
        session.add(spec)
        await session.flush()

        endpoint = Endpoint(
            api_spec_id=spec.id,
            method="GET",
            path="/items/{id}",
            summary="Get item",
            request_schema=None,
            response_schemas={"200": {"type": "object", "properties": {"id": {"type": "string"}}}},
            deprecated=False,
            is_destructive=False,
        )
        session.add(endpoint)
        await session.flush()

        param = EndpointParameter(
            endpoint_id=endpoint.id,
            name="id",
            location="path",
            type="string",
            required=True,
        )
        session.add(param)
        await session.commit()
        await session.refresh(endpoint)

    return project_id, str(endpoint.id), headers


async def test_patch_endpoint_method_path(client: AsyncClient, db) -> None:
    project_id, endpoint_id, headers = await _setup_project_with_endpoint(client, db)

    # Patch method and path
    res = await client.patch(
        f"/api/v1/projects/{project_id}/spec/endpoints/{endpoint_id}",
        json={"method": "POST", "path": "/items"},
        headers=headers,
    )
    assert res.status_code == 200
    data = res.json()
    assert data["method"] == "POST"
    assert data["path"] == "/items"


async def test_patch_endpoint_summary_deprecated(client: AsyncClient, db) -> None:
    project_id, endpoint_id, headers = await _setup_project_with_endpoint(client, db)

    res = await client.patch(
        f"/api/v1/projects/{project_id}/spec/endpoints/{endpoint_id}",
        json={"summary": "Updated summary", "deprecated": True},
        headers=headers,
    )
    assert res.status_code == 200
    data = res.json()
    assert data["summary"] == "Updated summary"
    assert data["deprecated"] is True


async def test_patch_endpoint_parameters(client: AsyncClient, db) -> None:
    project_id, endpoint_id, headers = await _setup_project_with_endpoint(client, db)

    # Replace parameters
    res = await client.patch(
        f"/api/v1/projects/{project_id}/spec/endpoints/{endpoint_id}",
        json={
            "parameters": [
                {"name": "id", "location": "path", "type": "string", "required": True},
                {"name": "include", "location": "query", "type": "string", "required": False},
            ]
        },
        headers=headers,
    )
    assert res.status_code == 200
    _ = res.json()

    # Verify in DB
    async with db as session:
        from sqlalchemy import select
        params = await session.scalars(
            select(EndpointParameter).where(EndpointParameter.endpoint_id == uuid.UUID(endpoint_id))
        )
        param_list = list(params.all())
        assert len(param_list) == 2
        assert {p.name for p in param_list} == {"id", "include"}


async def test_patch_endpoint_is_destructive(client: AsyncClient, db) -> None:
    project_id, endpoint_id, headers = await _setup_project_with_endpoint(client, db)

    res = await client.patch(
        f"/api/v1/projects/{project_id}/spec/endpoints/{endpoint_id}",
        json={"is_destructive": True},
        headers=headers,
    )
    assert res.status_code == 200
    data = res.json()
    assert data["is_destructive"] is True


async def test_patch_endpoint_confidence_score(client: AsyncClient, db) -> None:
    project_id, endpoint_id, headers = await _setup_project_with_endpoint(client, db)

    res = await client.patch(
        f"/api/v1/projects/{project_id}/spec/endpoints/{endpoint_id}",
        json={"confidence_score": 0.95},
        headers=headers,
    )
    assert res.status_code == 200
    data = res.json()
    assert data["confidence_score"] == 0.95

    # Invalid score
    res = await client.patch(
        f"/api/v1/projects/{project_id}/spec/endpoints/{endpoint_id}",
        json={"confidence_score": 1.5},
        headers=headers,
    )
    assert res.status_code == 422  # Validation error


async def test_patch_endpoint_not_found(client: AsyncClient, db) -> None:
    project_id, _, headers = await _setup_project_with_endpoint(client, db)

    fake_id = uuid.uuid4()
    res = await client.patch(
        f"/api/v1/projects/{project_id}/spec/endpoints/{fake_id}",
        json={"summary": "Won't work"},
        headers=headers,
    )
    assert res.status_code == 404