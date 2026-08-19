"""Tests for API key management routes."""

from __future__ import annotations

import uuid

import pytest
from httpx import AsyncClient

from app.core.security import create_access_token
from app.models.enums import OrgRole
from app.models.user import APIKey
from tests.conftest import (
    add_org_member,
    make_org,
    make_user,
)


@pytest.fixture
async def admin_user(db, test_settings):
    org = await make_org(db, name="API Key Org")
    user = await make_user(db, email="admin@example.com", name="Admin User")
    await add_org_member(db, org=org, user=user, role=OrgRole.ADMIN)

    token = create_access_token(
        user_id=user.id,
        org_id=org.id,
        role=OrgRole.ADMIN,
        settings=test_settings,
    )
    return {
        "user": user,
        "org": org,
        "headers": {"Authorization": f"Bearer {token.token}"},
    }


@pytest.mark.asyncio
async def test_create_api_key_unauthenticated(client: AsyncClient) -> None:
    response = await client.post(
        f"/api/v1/org/{uuid.uuid4()}/api-keys",
        json={"name": "Test Key"},
    )
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_create_api_key_requires_admin(client: AsyncClient, db, test_settings) -> None:
    org = await make_org(db, name="Member Org")
    user = await make_user(db, email="member@example.com", name="Member User")
    await add_org_member(db, org=org, user=user, role=OrgRole.MEMBER)

    token = create_access_token(
        user_id=user.id,
        org_id=org.id,
        role=OrgRole.MEMBER,
        settings=test_settings,
    )
    headers = {"Authorization": f"Bearer {token.token}"}

    response = await client.post(
        f"/api/v1/org/{org.id}/api-keys",
        headers=headers,
        json={"name": "Test Key"},
    )
    assert response.status_code == 403


@pytest.mark.asyncio
async def test_create_api_key(client: AsyncClient, admin_user) -> None:
    org = admin_user["org"]
    headers = admin_user["headers"]

    response = await client.post(
        f"/api/v1/org/{org.id}/api-keys",
        headers=headers,
        json={"name": "Test Key", "live": True},
    )
    assert response.status_code == 201
    data = response.json()
    assert data["name"] == "Test Key"
    assert data["key"].startswith("apw_live_")
    assert data["key_prefix"] == "apw_live_"
    assert "id" in data


@pytest.mark.asyncio
async def test_create_test_api_key(client: AsyncClient, admin_user) -> None:
    org = admin_user["org"]
    headers = admin_user["headers"]

    response = await client.post(
        f"/api/v1/org/{org.id}/api-keys",
        headers=headers,
        json={"name": "Test Key", "live": False},
    )
    assert response.status_code == 201
    data = response.json()
    assert data["key"].startswith("apw_test_")
    assert data["key_prefix"] == "apw_test_"


@pytest.mark.asyncio
async def test_list_api_keys(client: AsyncClient, db, admin_user) -> None:
    org = admin_user["org"]
    user = admin_user["user"]
    headers = admin_user["headers"]

    from app.core.security import generate_api_key
    generated = generate_api_key(live=True)

    key = APIKey(
        organization_id=org.id,
        name="Existing Key",
        key_prefix=generated.prefix,
        key_hash=generated.key_hash,
        created_by=user.id,
    )
    db.add(key)
    await db.commit()

    response = await client.get(
        f"/api/v1/org/{org.id}/api-keys",
        headers=headers,
    )
    assert response.status_code == 200
    data = response.json()
    assert "data" in data
    assert len(data["data"]) >= 1


@pytest.mark.asyncio
async def test_revoke_api_key(client: AsyncClient, db, admin_user) -> None:
    org = admin_user["org"]
    user = admin_user["user"]
    headers = admin_user["headers"]

    from app.core.security import generate_api_key
    generated = generate_api_key(live=True)

    key = APIKey(
        organization_id=org.id,
        name="Key to Revoke",
        key_prefix=generated.prefix,
        key_hash=generated.key_hash,
        created_by=user.id,
    )
    db.add(key)
    await db.commit()

    response = await client.delete(
        f"/api/v1/org/{org.id}/api-keys/{key.id}",
        headers=headers,
    )
    assert response.status_code == 204

    await db.refresh(key)
    assert key.revoked_at is not None


@pytest.mark.asyncio
async def test_revoke_api_key_not_found(client: AsyncClient, admin_user) -> None:
    org = admin_user["org"]
    headers = admin_user["headers"]

    response = await client.delete(
        f"/api/v1/org/{org.id}/api-keys/{uuid.uuid4()}",
        headers=headers,
    )
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_api_key_list_excludes_key(client: AsyncClient, db, admin_user) -> None:
    org = admin_user["org"]
    user = admin_user["user"]
    headers = admin_user["headers"]

    from app.core.security import generate_api_key
    generated = generate_api_key(live=True)

    key = APIKey(
        organization_id=org.id,
        name="Key Without Plaintext",
        key_prefix=generated.prefix,
        key_hash=generated.key_hash,
        created_by=user.id,
    )
    db.add(key)
    await db.commit()

    response = await client.get(
        f"/api/v1/org/{org.id}/api-keys",
        headers=headers,
    )
    data = response.json()
    for item in data["data"]:
        assert "key" not in item or item.get("key") is None
