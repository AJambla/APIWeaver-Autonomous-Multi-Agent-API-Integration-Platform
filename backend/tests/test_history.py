"""Tests for History & Versioning routes (`API.md §6.9`)."""

from __future__ import annotations

import uuid

from httpx import AsyncClient

from app.models.enums import WorkflowStatus
from app.models.versioning import ArtifactVersion
from app.models.workflow import WorkflowRun
from tests.conftest import TEST_PASSWORD


async def _setup_project_with_runs(client: AsyncClient) -> tuple[str, dict[str, str]]:
    """Create a user, org, project, and some workflow runs + artifact versions."""
    res = await client.post(
        "/api/v1/auth/register",
        json={
            "email": "history_user@example.com",
            "password": TEST_PASSWORD,
            "full_name": "History Tester",
            "organization_name": "History Org",
        },
    )
    assert res.status_code == 201
    token = res.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    me = await client.get("/api/v1/auth/me", headers=headers)
    org_id = me.json()["organizations"][0]["organization_id"]

    proj = await client.post(
        "/api/v1/projects",
        json={"name": "History Test Project", "organization_id": org_id},
        headers=headers,
    )
    assert proj.status_code == 201
    project_id = proj.json()["id"]

    # Create workflow runs directly in DB via test helpers
    # (We'll use the app's session fixture in actual tests)

    return project_id, headers


async def test_get_project_history(client: AsyncClient, db) -> None:
    project_id, headers = await _setup_project_with_runs(client)

    # Create some workflow runs
    async with db as session:
        for i in range(3):
            run = WorkflowRun(
                project_id=uuid.UUID(project_id),
                status=WorkflowStatus.COMPLETED if i < 2 else WorkflowStatus.FAILED,
                total_tokens_used=100 * (i + 1),
            )
            session.add(run)
        await session.commit()

    # Fetch history
    res = await client.get(f"/api/v1/projects/{project_id}/history", headers=headers)
    assert res.status_code == 200
    data = res.json()
    assert "data" in data
    assert "pagination" in data
    assert len(data["data"]) == 3
    assert data["pagination"]["has_more"] is False


async def test_get_project_versions(client: AsyncClient, db) -> None:
    project_id, headers = await _setup_project_with_runs(client)

    # Create some artifact versions
    async with db as session:
        for i in range(3):
            version = ArtifactVersion(
                project_id=uuid.UUID(project_id),
                artifact_type="sdk",
                version_number=i + 1,
                diff_ref=f"diff_{i}",
            )
            session.add(version)
        await session.commit()

    # Fetch versions
    res = await client.get(f"/api/v1/projects/{project_id}/versions", headers=headers)
    assert res.status_code == 200
    data = res.json()
    assert "data" in data
    assert len(data["data"]) == 3
    # Latest first
    assert data["data"][0]["version_number"] == 3


async def test_rollback_version(client: AsyncClient, db) -> None:
    project_id, headers = await _setup_project_with_runs(client)

    async with db as session:
        v1 = ArtifactVersion(
            project_id=uuid.UUID(project_id),
            artifact_type="sdk",
            version_number=1,
            is_active=True,
        )
        v2 = ArtifactVersion(
            project_id=uuid.UUID(project_id),
            artifact_type="sdk",
            version_number=2,
            is_active=False,
        )
        session.add_all([v1, v2])
        await session.commit()
        await session.refresh(v1)
        await session.refresh(v2)

    # Rollback to v1 (already active, should still work)
    res = await client.post(
        f"/api/v1/projects/{project_id}/versions/{v1.id}/rollback",
        json={"confirm": True},
        headers=headers,
    )
    assert res.status_code == 200
    data = res.json()
    assert data["is_active"] is True

    # Rollback to v2
    res = await client.post(
        f"/api/v1/projects/{project_id}/versions/{v2.id}/rollback",
        json={"confirm": True},
        headers=headers,
    )
    assert res.status_code == 200
    data = res.json()
    assert data["is_active"] is True
    assert data["version_number"] == 2

    # Verify v1 is now inactive
    async with db as session:
        refreshed_v1 = await session.get(ArtifactVersion, v1.id)
        refreshed_v2 = await session.get(ArtifactVersion, v2.id)
        assert refreshed_v1.is_active is False
        assert refreshed_v2.is_active is True


async def test_rollback_requires_confirmation(client: AsyncClient, db) -> None:
    project_id, headers = await _setup_project_with_runs(client)

    async with db as session:
        version = ArtifactVersion(
            project_id=uuid.UUID(project_id),
            artifact_type="sdk",
            version_number=1,
        )
        session.add(version)
        await session.commit()
        await session.refresh(version)

    # Without confirm
    res = await client.post(
        f"/api/v1/projects/{project_id}/versions/{version.id}/rollback",
        json={"confirm": False},
        headers=headers,
    )
    assert res.status_code == 409  # ConflictError

    # With confirm
    res = await client.post(
        f"/api/v1/projects/{project_id}/versions/{version.id}/rollback",
        json={"confirm": True},
        headers=headers,
    )
    assert res.status_code == 200