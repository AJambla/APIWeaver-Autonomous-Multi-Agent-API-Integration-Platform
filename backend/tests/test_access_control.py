"""Authorization gaps closed in the production-hardening pass.

- Workflow detail, tool calls and the live event stream checked only org membership.
- Project-restricted API keys could act on the whole organization; keys backed by a
  member (or by nobody) still listed every project.
- The pre-auth limiter keyed on any X-API-Key value, so rotating junk values bypassed the
  per-IP limit on login.
- Deleting auth config swallowed a Vault failure and orphaned the secret.
- /health/llm/test let any authenticated principal spend LLM tokens.
"""

from __future__ import annotations

import uuid

from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config import Settings
from app.core.ratelimit import ANONYMOUS_REQUESTS_PER_MINUTE
from app.core.security import create_access_token, hash_opaque_token
from app.models.auth_config import AuthConfig, SecretRef
from app.models.enums import OrgRole, ProjectRole, WorkflowStatus
from app.models.user import APIKey
from app.models.workflow import WorkflowRun
from tests.conftest import (
    add_org_member,
    add_project_member,
    make_org,
    make_project,
    make_user,
)
from tests.fakes import FakeVaultClient


async def _seed(
    session_factory: async_sessionmaker[AsyncSession], settings: Settings
) -> dict:
    """One org, two projects, an owner, and a plain member with no project access."""
    async with session_factory() as session:
        owner = await make_user(session, email=f"own-{uuid.uuid4().hex[:8]}@example.com")
        member = await make_user(session, email=f"mem-{uuid.uuid4().hex[:8]}@example.com")
        org = await make_org(session, name=f"AC {uuid.uuid4().hex[:6]}")
        await add_org_member(session, org=org, user=owner, role=OrgRole.OWNER)
        await add_org_member(session, org=org, user=member, role=OrgRole.MEMBER)
        project_a = await make_project(session, org=org, name="A")
        project_b = await make_project(session, org=org, name="B")
        run = WorkflowRun(project_id=project_a.id, status=WorkflowStatus.COMPLETED)
        session.add(run)
        await session.commit()

    def bearer(user, role):
        token = create_access_token(user_id=user.id, org_id=org.id, role=role, settings=settings)
        return {"Authorization": f"Bearer {token.token}"}

    return {
        "org": org,
        "owner": owner,
        "member": member,
        "project_a": project_a,
        "project_b": project_b,
        "run": run,
        "owner_headers": bearer(owner, OrgRole.OWNER),
        "member_headers": bearer(member, OrgRole.MEMBER),
    }


async def _key(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    org_id: uuid.UUID,
    creator_id: uuid.UUID,
    project_id: uuid.UUID | None = None,
) -> dict[str, str]:
    plaintext = f"apw_test_{uuid.uuid4().hex}"
    async with session_factory() as session:
        session.add(
            APIKey(
                organization_id=org_id,
                project_id=project_id,
                name="ac-key",
                key_prefix="apw_test_",
                key_hash=hash_opaque_token(plaintext),
                created_by=creator_id,
            )
        )
        await session.commit()
    return {"X-API-Key": plaintext}


async def test_run_details_need_a_project_role_not_just_org_membership(
    client: AsyncClient, session_factory, test_settings
) -> None:
    seed = await _seed(session_factory, test_settings)
    run_id = seed["run"].id

    for path in (f"/api/v1/workflows/{run_id}", f"/api/v1/workflows/{run_id}/tool-calls"):
        denied = await client.get(path, headers=seed["member_headers"])
        assert denied.status_code == 403, (path, denied.text)
        allowed = await client.get(path, headers=seed["owner_headers"])
        assert allowed.status_code == 200, (path, allowed.text)

    async with session_factory() as session:
        await add_project_member(
            session,
            project=seed["project_a"],
            user=seed["member"],
            role=ProjectRole.VIEWER,
        )
        await session.commit()
    viewer = await client.get(f"/api/v1/workflows/{run_id}", headers=seed["member_headers"])
    assert viewer.status_code == 200, viewer.text


async def test_event_stream_needs_a_project_role(
    client: AsyncClient, session_factory, test_settings
) -> None:
    seed = await _seed(session_factory, test_settings)
    res = await client.get(
        f"/api/v1/workflows/{seed['run'].id}/sse", headers=seed["member_headers"]
    )
    assert res.status_code == 403, res.text

    malformed = await client.get("/api/v1/workflows/not-a-uuid/sse", headers=seed["owner_headers"])
    assert malformed.status_code in (400, 404), malformed.text


async def test_project_restricted_keys_cannot_act_on_the_organization(
    client: AsyncClient, session_factory, test_settings
) -> None:
    seed = await _seed(session_factory, test_settings)
    org_id = seed["org"].id
    headers = await _key(
        session_factory, org_id=org_id, creator_id=seed["owner"].id, project_id=seed["project_a"].id
    )

    created = await client.post(
        "/api/v1/projects", json={"name": "Nope", "organization_id": str(org_id)}, headers=headers
    )
    assert created.status_code == 403, created.text
    keys = await client.get(f"/api/v1/org/{org_id}/api-keys", headers=headers)
    assert keys.status_code == 403, keys.text

    listed = await client.get("/api/v1/projects", headers=headers)
    assert listed.status_code == 200, listed.text
    assert [p["id"] for p in listed.json()["data"]] == [str(seed["project_a"].id)]


async def test_member_backed_keys_see_no_projects(
    client: AsyncClient, session_factory, test_settings
) -> None:
    seed = await _seed(session_factory, test_settings)
    headers = await _key(session_factory, org_id=seed["org"].id, creator_id=seed["member"].id)

    listed = await client.get("/api/v1/projects", headers=headers)

    assert listed.status_code == 200, listed.text
    assert listed.json()["data"] == []


async def test_rotating_api_key_headers_do_not_bypass_the_login_limit(client: AsyncClient) -> None:
    statuses = []
    for _ in range(ANONYMOUS_REQUESTS_PER_MINUTE + 1):
        res = await client.post(
            "/api/v1/auth/login",
            json={"email": "nobody@example.com", "password": "wrong-password"},
            headers={"X-API-Key": f"junk-{uuid.uuid4().hex}"},
        )
        statuses.append(res.status_code)
    assert statuses[-1] == 429, statuses[-5:]


async def test_auth_config_delete_keeps_the_secret_when_vault_fails(
    client: AsyncClient, session_factory, test_settings, fake_vault: FakeVaultClient, monkeypatch
) -> None:
    seed = await _seed(session_factory, test_settings)
    project_id = seed["project_a"].id
    async with session_factory() as session:
        config = AuthConfig(project_id=project_id, scheme="api_key", config_json={})
        session.add(config)
        await session.flush()
        session.add(SecretRef(auth_config_id=config.id, vault_path=f"apiweaver/projects/{project_id}/auth"))
        await session.commit()

    async def broken_delete(path: str) -> None:
        raise ConnectionError("vault sealed")

    monkeypatch.setattr(fake_vault, "delete_secret", broken_delete)
    res = await client.delete(f"/api/v1/projects/{project_id}/auth", headers=seed["owner_headers"])

    assert res.status_code == 503, res.text
    async with session_factory() as session:
        assert await session.scalar(select(SecretRef)) is not None
        assert await session.scalar(select(AuthConfig)) is not None


async def test_llm_probe_requires_an_org_admin(
    client: AsyncClient, session_factory, test_settings
) -> None:
    seed = await _seed(session_factory, test_settings)
    res = await client.post("/api/v1/health/llm/test", headers=seed["member_headers"])
    assert res.status_code == 403, res.text
    status = await client.get("/api/v1/health/llm")
    assert status.status_code == 401


async def test_an_owner_backed_api_key_cannot_pass_owner_only_gates(
    client: AsyncClient, session_factory, test_settings
) -> None:
    """Owner-only gates (approval, export, credential writes) need a human session."""
    seed = await _seed(session_factory, test_settings)
    project_id = seed["project_a"].id
    key_headers = await _key(
        session_factory, org_id=seed["project_a"].organization_id, creator_id=seed["owner"].id
    )

    # Editor-level work still succeeds with the key.
    listed = await client.get(f"/api/v1/projects/{project_id}", headers=key_headers)
    assert listed.status_code == 200, listed.text

    credentials = await client.put(
        f"/api/v1/projects/{project_id}/auth",
        json={"scheme": "api_key", "config_json": {"header_name": "X-Key"}, "credentials": {"api_key": "x"}},
        headers=key_headers,
    )
    assert credentials.status_code == 403, credentials.text

    export = await client.post(
        f"/api/v1/projects/{project_id}/export",
        json={"export_types": ["sdk"]},
        headers=key_headers,
    )
    assert export.status_code == 403, export.text


async def test_api_keys_cannot_manage_the_org_api_keys(
    client: AsyncClient, session_factory, test_settings
) -> None:
    """A leaked key must not be able to list, mint or revoke every other org credential."""
    seed = await _seed(session_factory, test_settings)
    org_id = seed["project_a"].organization_id
    key_headers = await _key(session_factory, org_id=org_id, creator_id=seed["owner"].id)

    listed = await client.get(f"/api/v1/org/{org_id}/api-keys", headers=key_headers)
    assert listed.status_code == 403, listed.text
    minted = await client.post(
        f"/api/v1/org/{org_id}/api-keys", json={"name": "child"}, headers=key_headers
    )
    assert minted.status_code == 403, minted.text

    # The human owner still manages keys.
    human = await client.get(f"/api/v1/org/{org_id}/api-keys", headers=seed["owner_headers"])
    assert human.status_code == 200, human.text
