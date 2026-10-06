"""Unit tests for Vault-injected target-API auth in the testing agent (Track B2)."""

from __future__ import annotations

import uuid

from app.models.auth_config import AuthConfig, SecretRef
from app.models.enums import AuthScheme
from app.services.vault_service import FakeVaultClient
from app.workflows.agents import test_agent as test_agent_module
from app.workflows.agents.test_agent import _credential_from_auth, _resolve_target_auth
from tests.conftest import make_org, make_project


async def _project_with_auth(
    db,
    fake_vault: FakeVaultClient,
    *,
    scheme: AuthScheme = AuthScheme.API_KEY,
    secret: dict | None = None,
):
    org = await make_org(db, name=f"Vault Org {uuid.uuid4().hex[:6]}")
    project = await make_project(db, org=org, name="Authed Project")
    config = AuthConfig(
        project_id=project.id,
        scheme=scheme.value,
        config_json={"header_name": "X-Api-Key"},
    )
    db.add(config)
    await db.flush()
    vault_path = f"apiweaver/projects/{project.id}/auth"
    db.add(SecretRef(auth_config_id=config.id, vault_path=vault_path))
    if secret is not None:
        await fake_vault.write_secret(vault_path, secret)
    await db.commit()
    return project


async def test_resolve_target_auth_returns_scheme_and_credentials(
    session_factory, db, fake_vault, monkeypatch, test_settings
):
    project = await _project_with_auth(
        db,
        fake_vault,
        scheme=AuthScheme.API_KEY,
        secret={"api_key": "sk-live-xyz"},
    )
    monkeypatch.setattr(test_agent_module, "create_vault_client", lambda settings: fake_vault)

    auth = await _resolve_target_auth(session_factory, str(project.id), test_settings)

    assert auth is not None
    assert auth["scheme"] == AuthScheme.API_KEY.value
    assert auth["config"] == {"header_name": "X-Api-Key"}
    assert auth["credentials"] == {"api_key": "sk-live-xyz"}


async def test_resolve_target_auth_none_without_session_factory(test_settings):
    assert await _resolve_target_auth(None, "some-project", test_settings) is None


async def test_resolve_target_auth_none_without_config(
    session_factory, db, fake_vault, monkeypatch, test_settings
):
    org = await make_org(db, name=f"Bare Org {uuid.uuid4().hex[:6]}")
    project = await make_project(db, org=org)
    await db.commit()
    monkeypatch.setattr(test_agent_module, "create_vault_client", lambda settings: fake_vault)

    assert await _resolve_target_auth(session_factory, str(project.id), test_settings) is None


async def test_resolve_target_auth_none_when_vault_secret_missing(
    session_factory, db, fake_vault, monkeypatch, test_settings
):
    project = await _project_with_auth(db, fake_vault, secret=None)
    monkeypatch.setattr(test_agent_module, "create_vault_client", lambda settings: fake_vault)

    assert await _resolve_target_auth(session_factory, str(project.id), test_settings) is None


def test_credential_from_auth_prefers_api_key():
    auth = {
        "scheme": "api_key",
        "credentials": {"token": "fallback", "api_key": "primary"},
    }
    assert _credential_from_auth(auth) == "primary"


def test_credential_from_auth_skips_non_string_values():
    auth = {
        "scheme": "oauth2_client_credentials",
        "credentials": {"client_id": 123, "client_secret": "shh"},
    }
    assert _credential_from_auth(auth) == "shh"


def test_credential_from_auth_none_scheme_and_missing():
    assert _credential_from_auth(None) is None
    assert (
        _credential_from_auth({"scheme": "none", "credentials": {"api_key": "ignored"}})
        is None
    )
    assert _credential_from_auth({"scheme": "basic", "credentials": {"user": "u"}}) is None
