"""Tests for history and versioning routes."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from httpx import AsyncClient

from app.core.security import create_access_token
from app.models.enums import OrgRole, ProjectRole, WorkflowStatus
from app.models.versioning import ArtifactVersion
from app.models.workflow import WorkflowRun
from tests.conftest import (
    add_org_member,
    add_project_member,
    make_org,
    make_project,
    make_user,
)


@pytest.fixture
async def auth_headers(db, test_settings) -> dict[str, str]:
    user = await make_user(db, email="test@example.com", name="Test User")
    org = await make_org(db, name="Test Org")
    await add_org_member(db, org=org, user=user, role=OrgRole.OWNER)
    project = await make_project(db, org=org, name="Test Project")
    await add_project_member(db, project=project, user=user, role=ProjectRole.OWNER)

    token = create_access_token(
        user_id=user.id,
        org_id=org.id,
        role=OrgRole.OWNER,
        settings=test_settings,
    )
    return {"Authorization": f"Bearer {token.token}"}


@pytest.mark.asyncio
async def test_get_history_unauthenticated(client: AsyncClient) -> None:
    response = await client.get(f"/api/v1/projects/{uuid.uuid4()}/history")
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_get_project_history(client: AsyncClient, db, test_settings) -> None:
    org = await make_org(db, name="Org1")
    user = await make_user(db, email="u1@example.com")
    await add_org_member(db, org=org, user=user, role=OrgRole.MEMBER)
    project = await make_project(db, org=org, name="P1")
    await add_project_member(db, project=project, user=user, role=ProjectRole.VIEWER)

    run1 = WorkflowRun(
        project_id=project.id,
        triggered_by=user.id,
        status=WorkflowStatus.COMPLETED,
        started_at=datetime.now(UTC) - timedelta(hours=2),
        completed_at=datetime.now(UTC) - timedelta(hours=1),
    )
    db.add(run1)
    await db.commit()

    token = create_access_token(
        user_id=user.id,
        org_id=org.id,
        role=OrgRole.MEMBER,
        settings=test_settings,
    )
    headers = {"Authorization": f"Bearer {token.token}"}

    response = await client.get(f"/api/v1/projects/{project.id}/history", headers=headers)
    assert response.status_code == 200
    data = response.json()
    assert "data" in data
    assert "pagination" in data


@pytest.mark.asyncio
async def test_list_artifact_versions(client: AsyncClient, db, test_settings) -> None:
    org = await make_org(db, name="Org2")
    user = await make_user(db, email="u2@example.com")
    await add_org_member(db, org=org, user=user, role=OrgRole.MEMBER)
    project = await make_project(db, org=org, name="P2")
    await add_project_member(db, project=project, user=user, role=ProjectRole.VIEWER)

    version = ArtifactVersion(
        project_id=project.id,
        artifact_type="sdk",
        version_number=1,
        diff_ref="v1.0.0",
    )
    db.add(version)
    await db.commit()

    token = create_access_token(
        user_id=user.id,
        org_id=org.id,
        role=OrgRole.MEMBER,
        settings=test_settings,
    )
    headers = {"Authorization": f"Bearer {token.token}"}

    response = await client.get(f"/api/v1/projects/{project.id}/versions", headers=headers)
    assert response.status_code == 200
    data = response.json()
    assert "data" in data
    assert len(data["data"]) == 1
    assert data["data"][0]["artifact_type"] == "sdk"


@pytest.mark.asyncio
async def test_rollback_artifact_version_requires_owner(
    client: AsyncClient, db, test_settings
) -> None:
    org = await make_org(db, name="Org3")
    user = await make_user(db, email="u3@example.com")
    await add_org_member(db, org=org, user=user, role=OrgRole.MEMBER)
    project = await make_project(db, org=org, name="P3")
    await add_project_member(db, project=project, user=user, role=ProjectRole.VIEWER)

    version = ArtifactVersion(
        project_id=project.id,
        artifact_type="sdk",
        version_number=1,
        diff_ref="v1.0.0",
    )
    db.add(version)
    await db.commit()

    token = create_access_token(
        user_id=user.id,
        org_id=org.id,
        role=OrgRole.MEMBER,
        settings=test_settings,
    )
    headers = {"Authorization": f"Bearer {token.token}"}

    response = await client.post(
        f"/api/v1/projects/{project.id}/versions/{version.id}/rollback",
        headers=headers,
    )
    assert response.status_code == 403


@pytest.mark.asyncio
async def test_rollback_artifact_version(client: AsyncClient, db, test_settings) -> None:
    org = await make_org(db, name="Org4")
    user = await make_user(db, email="u4@example.com")
    await add_org_member(db, org=org, user=user, role=OrgRole.MEMBER)
    project = await make_project(db, org=org, name="P4")
    await add_project_member(db, project=project, user=user, role=ProjectRole.OWNER)

    version = ArtifactVersion(
        project_id=project.id,
        artifact_type="sdk",
        version_number=1,
        diff_ref="v1.0.0",
    )
    db.add(version)
    await db.commit()

    token = create_access_token(
        user_id=user.id,
        org_id=org.id,
        role=OrgRole.MEMBER,
        settings=test_settings,
    )
    headers = {"Authorization": f"Bearer {token.token}"}

    response = await client.post(
        f"/api/v1/projects/{project.id}/versions/{version.id}/rollback",
        headers=headers,
    )
    assert response.status_code == 201
    data = response.json()
    assert "version_id" in data
    assert data["status"] == "rolled_back"
