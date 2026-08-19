"""Tests for Organization API Key management (`API.md §1`, `Security.md §5`)."""

from __future__ import annotations

import uuid

from httpx import AsyncClient
from sqlalchemy import select

from app.models.enums import OrgRole
from app.models.user import APIKey
from tests.conftest import TEST_PASSWORD


async def _setup_org(client: AsyncClient) -> tuple[str, dict[str, str]]:
    """Create a user, org, and return org_id + headers."""
    res = await client.post(
        "/api/v1/auth/register",
        json={
            "email": "apikey_user@example.com",
            "password": TEST_PASSWORD,
            "full_name": "API Key Tester",
            "organization_name": "API Key Org",
        },
    )
    assert res.status_code == 201
    token = res.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    me = await client.get("/api/v1/auth/me", headers=headers)
    org_id = me.json()["organizations"][0]["organization_id"]

    return org_id, headers


async def test_create_api_key(client: AsyncClient, db) -> None:
    org_id, headers = await _setup_org(client)

    # Create API key
    res = await client.post(
        f"/api/v1/org/{org_id}/api-keys",
        json={"name": "Test Key", "expires_in_days": 30},
        headers=headers,
    )
    assert res.status_code == 201
    data = res.json()
    assert "key" in data
    assert data["key"].startswith("apw_live_")
    assert data["prefix"] == "apw_live_"
    assert data["name"] == "Test Key"
    assert data["expires_at"] is not None
    assert data["project_id"] is None

    # Verify key is stored hashed in DB
    async with db as session:
        api_key = await session.get(APIKey, uuid.UUID(data["id"]))
        assert api_key is not None
        assert api_key.key_hash != data["key"]  # Should be hashed
        assert api_key.key_prefix == "apw_live_"


async def test_create_api_key_with_project(client: AsyncClient, db) -> None:
    org_id, headers = await _setup_org(client)

    # Create a project first
    proj_res = await client.post(
        "/api/v1/projects",
        json={"name": "Test Project", "organization_id": org_id},
        headers=headers,
    )
    assert proj_res.status_code == 201
    project_id = proj_res.json()["id"]

    # Create API key scoped to project
    res = await client.post(
        f"/api/v1/org/{org_id}/api-keys",
        json={"name": "Project Key", "project_id": project_id},
        headers=headers,
    )
    assert res.status_code == 201
    data = res.json()
    assert data["project_id"] == project_id


async def test_list_api_keys(client: AsyncClient, db) -> None:
    org_id, headers = await _setup_org(client)

    # Create a few keys
    for i in range(3):
        res = await client.post(
            f"/api/v1/org/{org_id}/api-keys",
            json={"name": f"Key {i}"},
            headers=headers,
        )
        assert res.status_code == 201

    # List keys
    res = await client.get(f"/api/v1/org/{org_id}/api-keys", headers=headers)
    assert res.status_code == 200
    data = res.json()
    assert "data" in data
    assert len(data["data"]) == 3

    # Verify full key is NOT returned in list
    for key in data["data"]:
        assert "key" not in key
        assert key["prefix"] == "apw_live_"
        assert "name" in key
        assert "created_at" in key


async def test_revoke_api_key(client: AsyncClient, db) -> None:
    org_id, headers = await _setup_org(client)

    # Create key
    res = await client.post(
        f"/api/v1/org/{org_id}/api-keys",
        json={"name": "To Revoke"},
        headers=headers,
    )
    assert res.status_code == 201
    key_id = res.json()["id"]

    # Revoke key
    res = await client.delete(f"/api/v1/org/{org_id}/api-keys/{key_id}", headers=headers)
    assert res.status_code == 204

    # Verify revoked in DB
    async with db as session:
        api_key = await session.get(APIKey, uuid.UUID(key_id))
        assert api_key is not None
        assert api_key.revoked_at is not None

    # List should show revoked_at
    res = await client.get(f"/api/v1/org/{org_id}/api-keys", headers=headers)
    assert res.status_code == 200
    data = res.json()
    revoked_key = next(k for k in data["data"] if k["id"] == key_id)
    assert revoked_key["revoked_at"] is not None

    # Idempotent revoke
    res = await client.delete(f"/api/v1/org/{org_id}/api-keys/{key_id}", headers=headers)
    assert res.status_code == 204


async def test_api_key_permissions(client: AsyncClient, db) -> None:
    """Only org admins/owners can manage API keys."""
    org_id, headers = await _setup_org(client)

    # Create a second user
    res = await client.post(
        "/api/v1/auth/register",
        json={
            "email": "apikey_member@example.com",
            "password": TEST_PASSWORD,
            "full_name": "Member User",
            "organization_name": "Member Org",  # Different org
        },
    )
    assert res.status_code == 201
    member_token = res.json()["access_token"]
    member_headers = {"Authorization": f"Bearer {member_token}"}

    # User from a different org is not a member -> cross-tenant access returns 404
    # (RBAC design hides tenant existence rather than confirming it with a 403).
    res = await client.get(f"/api/v1/org/{org_id}/api-keys", headers=member_headers)
    assert res.status_code == 404

    # Add member to the original org
    async with db as session:
        from app.models.organization import Organization, OrganizationMember
        from app.models.user import User

        member_user = await session.scalar(
            select(User).where(User.email == "apikey_member@example.com")
        )
        org = await session.get(Organization, uuid.UUID(org_id))
        session.add(OrganizationMember(organization_id=org.id, user_id=member_user.id, role=OrgRole.MEMBER))
        await session.commit()

    # Member (not admin) should not manage API keys
    res = await client.post(
        f"/api/v1/org/{org_id}/api-keys",
        json={"name": "Unauthorized"},
        headers=member_headers,
    )
    assert res.status_code == 403