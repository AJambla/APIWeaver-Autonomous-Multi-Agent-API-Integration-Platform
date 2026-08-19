"""Tests for spec patch endpoint."""

from __future__ import annotations

import uuid

import pytest
from httpx import AsyncClient

from app.core.security import create_access_token
from app.models.enums import OrgRole, ProjectRole
from app.models.spec import APISpec, Endpoint
from tests.conftest import (
    add_org_member,
    add_project_member,
    make_org,
    make_project,
    make_user,
)


@pytest.fixture
async def setup_project_with_endpoint(db):
    org = await make_org(db, name="Patch Org")
    user = await make_user(db, email="patch@example.com", name="Patch User")
    await add_org_member(db, org=org, user=user, role=OrgRole.MEMBER)
    project = await make_project(db, org=org, name="Patch Project")
    await add_project_member(db, project=project, user=user, role=ProjectRole.EDITOR)

    spec = APISpec(
        project_id=project.id,
        raw_normalized={"openapi": "3.0.0"},
    )
    db.add(spec)
    await db.flush()

    endpoint = Endpoint(
        api_spec_id=spec.id,
        method="GET",
        path="/users",
        summary="List users",
        response_schemas={"200": {"type": "array"}},
        confidence_score=0.75,
    )
    db.add(endpoint)
    await db.commit()

    return org, user, project, spec, endpoint


@pytest.mark.asyncio
async def test_patch_endpoint_unauthenticated(client: AsyncClient) -> None:
    response = await client.patch(
        f"/api/v1/projects/{uuid.uuid4()}/spec/endpoints/{uuid.uuid4()}",
        json={"summary": "New summary"},
    )
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_patch_endpoint_requires_editor(
    client: AsyncClient, db, test_settings, setup_project_with_endpoint
) -> None:
    org, user, project, spec, endpoint = setup_project_with_endpoint

    viewer = await make_user(db, email="viewer@example.com", name="Viewer")
    await add_org_member(db, org=org, user=viewer, role=OrgRole.MEMBER)
    await add_project_member(db, project=project, user=viewer, role=ProjectRole.VIEWER)

    token = create_access_token(
        user_id=viewer.id,
        org_id=org.id,
        role=OrgRole.MEMBER,
        settings=test_settings,
    )
    headers = {"Authorization": f"Bearer {token.token}"}

    response = await client.patch(
        f"/api/v1/projects/{project.id}/spec/endpoints/{endpoint.id}",
        headers=headers,
        json={"summary": "New summary"},
    )
    assert response.status_code == 403


@pytest.mark.asyncio
async def test_patch_endpoint_not_found(
    client: AsyncClient, test_settings, setup_project_with_endpoint
) -> None:
    org, user, project, spec, endpoint = setup_project_with_endpoint

    token = create_access_token(
        user_id=user.id,
        org_id=org.id,
        role=OrgRole.MEMBER,
        settings=test_settings,
    )
    headers = {"Authorization": f"Bearer {token.token}"}

    response = await client.patch(
        f"/api/v1/projects/{project.id}/spec/endpoints/{uuid.uuid4()}",
        headers=headers,
        json={"summary": "New summary"},
    )
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_patch_endpoint_summary(
    client: AsyncClient, db, test_settings, setup_project_with_endpoint
) -> None:
    org, user, project, spec, endpoint = setup_project_with_endpoint

    token = create_access_token(
        user_id=user.id,
        org_id=org.id,
        role=OrgRole.MEMBER,
        settings=test_settings,
    )
    headers = {"Authorization": f"Bearer {token.token}"}

    response = await client.patch(
        f"/api/v1/projects/{project.id}/spec/endpoints/{endpoint.id}",
        headers=headers,
        json={"summary": "Updated summary"},
    )
    assert response.status_code == 200
    data = response.json()
    assert "summary" in data["updated_fields"]
    assert data["confidence_score"] == 1.0

    await db.refresh(endpoint)
    assert endpoint.summary == "Updated summary"
    assert float(endpoint.confidence_score) == 1.0


@pytest.mark.asyncio
async def test_patch_endpoint_path_and_method(
    client: AsyncClient, db, test_settings, setup_project_with_endpoint
) -> None:
    org, user, project, spec, endpoint = setup_project_with_endpoint

    token = create_access_token(
        user_id=user.id,
        org_id=org.id,
        role=OrgRole.MEMBER,
        settings=test_settings,
    )
    headers = {"Authorization": f"Bearer {token.token}"}

    response = await client.patch(
        f"/api/v1/projects/{project.id}/spec/endpoints/{endpoint.id}",
        headers=headers,
        json={"path": "/users/{id}", "method": "POST"},
    )
    assert response.status_code == 200
    data = response.json()
    assert "path" in data["updated_fields"]
    assert "method" in data["updated_fields"]

    await db.refresh(endpoint)
    assert endpoint.path == "/users/{id}"
    assert endpoint.method == "POST"


@pytest.mark.asyncio
async def test_patch_endpoint_no_changes(
    client: AsyncClient, test_settings, setup_project_with_endpoint
) -> None:
    org, user, project, spec, endpoint = setup_project_with_endpoint

    token = create_access_token(
        user_id=user.id,
        org_id=org.id,
        role=OrgRole.MEMBER,
        settings=test_settings,
    )
    headers = {"Authorization": f"Bearer {token.token}"}

    response = await client.patch(
        f"/api/v1/projects/{project.id}/spec/endpoints/{endpoint.id}",
        headers=headers,
        json={"summary": "List users"},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["updated_fields"] == []
