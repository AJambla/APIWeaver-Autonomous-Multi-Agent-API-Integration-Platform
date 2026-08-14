"""Tests for Auth Config routes and Vault/Qdrant integrations (Phase 2)."""

from __future__ import annotations

import uuid

from httpx import AsyncClient

from app.models.enums import AuthScheme
from app.services.qdrant_service import FakeQdrantClient
from app.services.vault_service import FakeVaultClient
from tests.conftest import TEST_PASSWORD


async def _setup_project(client: AsyncClient) -> tuple[str, str, dict[str, str]]:
    res = await client.post(
        "/api/v1/auth/register",
        json={
            "email": "vault_user@example.com",
            "password": TEST_PASSWORD,
            "full_name": "Vault Tester",
            "organization_name": "Vault Org",
        },
    )
    assert res.status_code == 201
    token = res.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    me = await client.get("/api/v1/auth/me", headers=headers)
    org_id = me.json()["organizations"][0]["organization_id"]

    proj = await client.post(
        "/api/v1/projects",
        json={"name": "Auth Config Test Project", "organization_id": org_id},
        headers=headers,
    )
    assert proj.status_code == 201
    return proj.json()["id"], org_id, headers


async def test_put_and_get_auth_config(client: AsyncClient) -> None:
    project_id, _, headers = await _setup_project(client)

    # 1. Put auth configuration with credentials
    put_payload = {
        "scheme": AuthScheme.OAUTH2_CLIENT_CREDENTIALS,
        "config_json": {
            "token_url": "https://api.target.example/oauth/token",
            "scopes": ["read", "write"],
        },
        "credentials": {
            "client_id": "client_abc_123",
            "client_secret": "super_secret_key_xyz",
        },
    }

    put_res = await client.put(
        f"/api/v1/projects/{project_id}/auth",
        json=put_payload,
        headers=headers,
    )
    assert put_res.status_code == 200, put_res.text
    put_data = put_res.json()
    assert put_data["scheme"] == AuthScheme.OAUTH2_CLIENT_CREDENTIALS
    assert "credentials" not in put_data

    # 2. Get auth configuration
    get_res = await client.get(f"/api/v1/projects/{project_id}/auth", headers=headers)
    assert get_res.status_code == 200
    get_data = get_res.json()
    assert get_data["scheme"] == AuthScheme.OAUTH2_CLIENT_CREDENTIALS
    assert get_data["config_json"]["token_url"] == "https://api.target.example/oauth/token"
    assert "credentials" not in get_data


async def test_vault_service_mock() -> None:
    vault = FakeVaultClient()
    path = "apiweaver/projects/test-proj/auth"
    secrets = {"client_id": "id1", "client_secret": "sec1"}

    await vault.write_secret(path, secrets)
    read_back = await vault.read_secret(path)
    assert read_back == secrets

    await vault.delete_secret(path)
    assert await vault.read_secret(path) is None


async def test_qdrant_service_mock() -> None:
    qdrant = FakeQdrantClient()
    proj_id = uuid.uuid4()
    doc_id = uuid.uuid4()

    chunks = [
        {"id": "c1", "vector": [1.0, 0.0, 0.0], "text": "GET /orders - list orders"},
        {"id": "c2", "vector": [0.0, 1.0, 0.0], "text": "POST /orders - create order"},
    ]

    await qdrant.upsert_chunks(project_id=proj_id, document_id=doc_id, chunks=chunks)
    search_results = await qdrant.search(project_id=proj_id, query_vector=[1.0, 0.1, 0.0], limit=1)

    assert len(search_results) == 1
    assert search_results[0].chunk_id == "c1"
    assert "orders" in search_results[0].text
