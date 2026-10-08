"""Tests for Auth Config routes and Vault/Qdrant integrations (Phase 2)."""

from __future__ import annotations

import uuid

import pytest
from httpx import AsyncClient

from app.models.enums import AuthScheme
from tests.conftest import TEST_PASSWORD
from tests.fakes import FakeQdrantClient, FakeVaultClient


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


async def test_delete_auth_config_purges_vault_and_database(
    client: AsyncClient, fake_vault: FakeVaultClient, session_factory
) -> None:
    """DELETE /projects/{id}/auth purges Vault secrets and removes DB rows."""
    from sqlalchemy import select
    from app.models.auth_config import AuthConfig, SecretRef

    project_id, _, headers = await _setup_project(client)

    # 1. Create auth config with credentials in Vault
    put_payload = {
        "scheme": AuthScheme.API_KEY,
        "config_json": {"header_name": "X-API-Key"},
        "credentials": {"api_key": "target_secret_token_abc"},
    }
    put_res = await client.put(
        f"/api/v1/projects/{project_id}/auth",
        json=put_payload,
        headers=headers,
    )
    assert put_res.status_code == 200

    vault_path = f"apiweaver/projects/{project_id}/auth"
    # Verify secret was written to Vault
    stored = await fake_vault.read_secret(vault_path)
    assert stored == {"api_key": "target_secret_token_abc"}

    # 2. Delete auth config via DELETE endpoint
    del_res = await client.delete(f"/api/v1/projects/{project_id}/auth", headers=headers)
    assert del_res.status_code == 204

    # 3. Verify secret is completely purged from Vault (no orphaned secrets)
    assert await fake_vault.read_secret(vault_path) is None

    # 4. Verify GET now returns 404
    get_res = await client.get(f"/api/v1/projects/{project_id}/auth", headers=headers)
    assert get_res.status_code == 404

    # 5. Verify DB rows are deleted
    async with session_factory() as session:
        auth_row = await session.scalar(
            select(AuthConfig).where(AuthConfig.project_id == uuid.UUID(project_id))
        )
        assert auth_row is None

        ref_rows = (
            await session.scalars(select(SecretRef).where(SecretRef.vault_path == vault_path))
        ).all()
        assert len(ref_rows) == 0


def test_auth_credentials_schema_validation_unit() -> None:
    """Verify schema-level credential validation rules for each auth scheme."""
    from pydantic import ValidationError

    from app.schemas.auth_config import (
        ApiKeyCredentials,
        AuthConfigRequest,
        BasicAuthCredentials,
        BearerJwtCredentials,
        HmacCredentials,
        OAuth2AuthCodeCredentials,
        OAuth2ClientCredentials,
    )

    # API Key: valid & alias
    k1 = ApiKeyCredentials.model_validate({"api_key": "secret-123"})
    assert k1.api_key == "secret-123"
    k2 = ApiKeyCredentials.model_validate({"key": "secret-456"})
    assert k2.api_key == "secret-456"

    # API Key: empty or extra forbidden
    with pytest.raises(ValidationError):
        ApiKeyCredentials.model_validate({"api_key": ""})
    with pytest.raises(ValidationError):
        ApiKeyCredentials.model_validate({"api_key": "valid", "extra_bad": "no"})

    # Bearer JWT: valid & alias
    b1 = BearerJwtCredentials.model_validate({"token": "jwt.header.body"})
    assert b1.token == "jwt.header.body"
    b2 = BearerJwtCredentials.model_validate({"bearer_token": "jwt.header.body"})
    assert b2.token == "jwt.header.body"
    with pytest.raises(ValidationError):
        BearerJwtCredentials.model_validate({"token": ""})

    # OAuth2 Client Credentials
    o1 = OAuth2ClientCredentials.model_validate({"client_id": "cid", "client_secret": "csec"})
    assert o1.client_id == "cid"
    assert o1.client_secret == "csec"
    with pytest.raises(ValidationError):
        OAuth2ClientCredentials.model_validate({"client_id": "cid"})  # missing secret

    # OAuth2 Auth Code
    ac = OAuth2AuthCodeCredentials.model_validate({
        "client_id": "cid",
        "client_secret": "csec",
        "access_token": "at",
        "refresh_token": "rt",
    })
    assert ac.refresh_token == "rt"

    # Basic Auth
    ba = BasicAuthCredentials.model_validate({"username": "user", "password": "pwd"})
    assert ba.username == "user"
    with pytest.raises(ValidationError):
        BasicAuthCredentials.model_validate({"username": "user"})  # missing password

    # HMAC
    hm = HmacCredentials.model_validate({"secret_key": "hmac_secret", "key_id": "kid1"})
    assert hm.secret == "hmac_secret"
    assert hm.key_id == "kid1"

    # AuthConfigRequest validations
    req_api = AuthConfigRequest.model_validate({
        "scheme": "api_key",
        "credentials": {"api_key": "my-key"},
    })
    assert req_api.credentials == {"api_key": "my-key"}

    req_none = AuthConfigRequest.model_validate({
        "scheme": "none",
        "credentials": None,
    })
    assert req_none.credentials is None

    # Scheme 'none' with credentials must fail
    with pytest.raises(ValidationError):
        AuthConfigRequest.model_validate({
            "scheme": "none",
            "credentials": {"api_key": "forbidden"},
        })

    # Scheme 'basic' with incomplete credentials must fail
    with pytest.raises(ValidationError):
        AuthConfigRequest.model_validate({
            "scheme": "basic",
            "credentials": {"username": "admin"},
        })


async def test_endpoint_rejects_invalid_credentials(client: AsyncClient) -> None:
    """Verify HTTP endpoint enforces 400 VALIDATION_ERROR for malformed or incomplete credentials."""
    project_id, _, headers = await _setup_project(client)

    # 1. Empty API key
    res = await client.put(
        f"/api/v1/projects/{project_id}/auth",
        json={"scheme": "api_key", "credentials": {"api_key": ""}},
        headers=headers,
    )
    assert res.status_code == 400
    assert res.json()["error"]["code"] == "VALIDATION_ERROR"

    # 2. Extra forbidden fields
    res = await client.put(
        f"/api/v1/projects/{project_id}/auth",
        json={"scheme": "api_key", "credentials": {"api_key": "valid", "injected": "bad"}},
        headers=headers,
    )
    assert res.status_code == 400
    assert res.json()["error"]["code"] == "VALIDATION_ERROR"

    # 3. Basic auth missing password
    res = await client.put(
        f"/api/v1/projects/{project_id}/auth",
        json={"scheme": "basic", "credentials": {"username": "admin"}},
        headers=headers,
    )
    assert res.status_code == 400
    assert res.json()["error"]["code"] == "VALIDATION_ERROR"

    # 4. Scheme 'none' with credentials
    res = await client.put(
        f"/api/v1/projects/{project_id}/auth",
        json={"scheme": "none", "credentials": {"token": "should-not-exist"}},
        headers=headers,
    )
    assert res.status_code == 400
    assert res.json()["error"]["code"] == "VALIDATION_ERROR"

    # 5. Valid basic auth succeeds
    res = await client.put(
        f"/api/v1/projects/{project_id}/auth",
        json={"scheme": "basic", "credentials": {"username": "admin", "password": "secure"}},
        headers=headers,
    )
    assert res.status_code == 200
    assert res.json()["scheme"] == "basic"


