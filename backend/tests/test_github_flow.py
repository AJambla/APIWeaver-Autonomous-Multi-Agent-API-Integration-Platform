"""The GitHub OAuth consent round trip — audit finding L4.

Two routes in this flow could not run at all. Measured before the fix, with the production
wiring (`create_app`) and a member token:

- `POST /api/v1/github/connect` raised `AttributeError: 'State' object has no attribute
  'settings'` -- it read `request.app.state.settings` and `app.state.db_session_factory`,
  and `main.py` assigns only `app.state.redis` and `app.state.object_storage`. The catch-all
  handler turns that into a 500 with no detail, so the button in `SettingsPage.tsx` could
  never produce an authorization URL. The TTL it read (`github_oauth_state_ttl_seconds`)
  exists in no `Settings` class either, so the attribute chain was never going to resolve.
- `GET /api/v1/github/callback` answered `401 UNAUTHENTICATED` to the browser redirect
  GitHub performs, because `router.py` attaches `enforce_org_rate_limit` to the whole
  `github` router and that dependency resolves a principal. With a bearer token it reached
  the body and answered `409 Invalid or expired OAuth state.`, which is what showed the
  route itself was fine and only the gate was wrong.

The exchange the callback performs talks to `api.github.com` and needs a client secret from
Vault, so these tests override the two GitHub clients with stubs. Nothing here reaches a
real third party.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from fastapi import FastAPI
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.api.v1.github import (
    OAUTH_STATE_COOKIE,
    OAUTH_STATE_TTL_SECONDS,
    create_github_app_client,
    create_github_oauth_client,
)
from app.core.config import Settings
from app.core.ratelimit import ANONYMOUS_REQUESTS_PER_MINUTE
from app.core.security import create_access_token, hash_opaque_token
from app.models.enums import OrgRole
from app.models.github import GitHubConnection, GitHubOAuthState
from app.models.organization import OrganizationMember
from app.models.user import APIKey, User
from tests.conftest import add_org_member, make_org, make_user
from tests.fakes import FakeVaultClient


class StubOAuthClient:
    """`GitHubOAuthClient` without the network: records what was asked, answers it."""

    def __init__(self) -> None:
        self.authorization_states: list[str] = []
        self.exchanged_codes: list[str] = []

    def get_authorization_url(self, state: str, scopes: list[str] | None = None) -> str:
        self.authorization_states.append(state)
        return f"https://github.com/login/oauth/authorize?state={state}"

    async def exchange_code(self, code: str) -> dict[str, Any]:
        self.exchanged_codes.append(code)
        return {
            "access_token": "gho-under-test",
            "refresh_token": "ghr-under-test",
            "scope": "repo,read:user",
        }

    async def get_user_info(self, access_token: str) -> dict[str, Any]:
        return {"id": 4242, "login": "octoder-under-test"}


class StubAppClient:
    """`GitHubAppClient` without the network."""

    async def get_user_installations(self, user_token: str) -> list[dict[str, Any]]:
        return [{"id": 77, "account": {"login": "acme-under-test", "type": "Organization"}}]


@pytest.fixture
def stub_github_clients(app: FastAPI) -> tuple[StubOAuthClient, StubAppClient]:
    """Install the stubs and hand them back so a test can assert what was called."""
    oauth = StubOAuthClient()
    app_client = StubAppClient()
    app.dependency_overrides[create_github_oauth_client] = lambda: oauth
    app.dependency_overrides[create_github_app_client] = lambda: app_client
    return oauth, app_client


async def _member(
    session_factory: async_sessionmaker[AsyncSession],
    settings: Settings,
    *,
    role: str = OrgRole.MEMBER,
) -> tuple[dict[str, str], User]:
    """A bearer token for a fresh user holding `role` in their own organization."""
    async with session_factory() as session:
        user = await make_user(session, email=f"gh-{uuid.uuid4().hex[:10]}@example.com")
        org = await make_org(session, name=f"GH {uuid.uuid4().hex[:8]}")
        await add_org_member(session, org=org, user=user, role=role)
        await session.commit()

    token = create_access_token(user_id=user.id, org_id=org.id, role=role, settings=settings)
    return {"Authorization": f"Bearer {token.token}"}, user


async def _seed_state(
    session_factory: async_sessionmaker[AsyncSession],
    user_id: uuid.UUID,
    *,
    state: str,
    expires_at: datetime,
) -> None:
    async with session_factory() as session:
        session.add(GitHubOAuthState(user_id=user_id, state=state, expires_at=expires_at))
        await session.commit()


async def _api_key_for(
    session_factory: async_sessionmaker[AsyncSession],
    user: User,
) -> str:
    """Mint a live key for `user`'s organization and return its plaintext."""
    plaintext = f"apw_test_{uuid.uuid4().hex}"
    async with session_factory() as session:
        organization_id = await session.scalar(
            select(OrganizationMember.organization_id).where(OrganizationMember.user_id == user.id)
        )
        session.add(
            APIKey(
                organization_id=organization_id,
                name="l4-probe-key",
                key_prefix="apw_test_",
                key_hash=hash_opaque_token(plaintext),
                created_by=user.id,
            )
        )
        await session.commit()
    return plaintext


# --- POST /github/connect ---------------------------------------------------------------


async def test_connect_returns_an_authorization_url_and_persists_the_state(
    client: AsyncClient,
    app: FastAPI,
    session_factory: async_sessionmaker[AsyncSession],
    test_settings: Settings,
    stub_github_clients: tuple[StubOAuthClient, StubAppClient],
) -> None:
    """The route has to work on the wiring `main.py` actually builds.

    Asserted here rather than assumed, so this test cannot be satisfied by someone
    "fixing" the 500 with `app.state.settings = settings` in the lifespan: injecting the
    session is the point, and the state row is what the callback authenticates against.
    """
    assert "settings" not in app.state.__dict__
    assert "db_session_factory" not in app.state.__dict__

    oauth, _ = stub_github_clients
    headers, user = await _member(session_factory, test_settings)

    response = await client.post("/api/v1/github/connect", headers=headers)

    assert response.status_code == 200, response.text
    state = response.json()["state"]
    assert response.json()["auth_url"] == f"https://github.com/login/oauth/authorize?state={state}"
    assert oauth.authorization_states == [state]

    async with session_factory() as session:
        row = await session.scalar(select(GitHubOAuthState).where(GitHubOAuthState.state == state))
    assert row is not None
    assert row.user_id == user.id
    # The ten minutes `GitHubOAuthState` documents, which is what the route now uses.
    remaining = row.expires_at - datetime.now(UTC)
    assert (
        timedelta(seconds=OAUTH_STATE_TTL_SECONDS - 60)
        < remaining
        <= timedelta(seconds=OAUTH_STATE_TTL_SECONDS)
    )


async def test_an_api_key_cannot_open_the_consent_flow(
    client: AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
    test_settings: Settings,
    stub_github_clients: tuple[StubOAuthClient, StubAppClient],
) -> None:
    """An API key has no user behind it (`deps.py` builds `user_id=None`), and both the
    state row and the connection it becomes belong to a user -- `github_oauth_states.user_id
    is NOT NULL`. Without the guard that insert aborts with an integrity error, which is
    this same finding's 500 reached by a different credential.
    """
    oauth, _ = stub_github_clients
    headers, user = await _member(session_factory, test_settings, role=OrgRole.OWNER)
    plaintext = await _api_key_for(session_factory, user)

    response = await client.post("/api/v1/github/connect", headers={"X-API-Key": plaintext})

    assert response.status_code == 403, response.text
    assert "interactive" in response.json()["error"]["message"]
    assert oauth.authorization_states == []
    async with session_factory() as session:
        assert await session.scalar(select(GitHubOAuthState.state)) is None


# --- GET /github/callback ---------------------------------------------------------------


async def test_the_callback_completes_on_the_browser_redirect_alone(
    client: AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
    test_settings: Settings,
    stub_github_clients: tuple[StubOAuthClient, StubAppClient],
    fake_vault: FakeVaultClient,
) -> None:
    """No `Authorization`, no API key: the only credential is the `state` row `/connect`
    created. This is the flow `SettingsPage.tsx` opens in a popup, and it used to die at 401.
    """
    oauth, _ = stub_github_clients
    _, user = await _member(session_factory, test_settings)
    state = uuid.uuid4().hex
    await _seed_state(
        session_factory, user.id, state=state, expires_at=datetime.now(UTC) + timedelta(minutes=5)
    )

    response = await client.get(
        f"/api/v1/github/callback?code=code-under-test&state={state}",
        cookies={OAUTH_STATE_COOKIE: state},
    )

    assert response.status_code == 200, response.text
    assert response.json() == {
        "connected": True,
        "github_username": "octoder-under-test",
        "installations": [{"id": 77, "account": "acme-under-test", "account_type": "Organization"}],
    }
    assert oauth.exchanged_codes == ["code-under-test"]

    async with session_factory() as session:
        connection = await session.scalar(select(GitHubConnection))
        used = await session.scalar(select(GitHubOAuthState).where(GitHubOAuthState.state == state))
    assert connection is not None
    # Bound to the user who started the flow, not to whoever presented the state.
    assert connection.user_id == user.id
    assert connection.github_user_id == "4242"
    assert connection.revoked_at is None
    assert used is None, "a completed state must not be replayable"

    assert await fake_vault.read_secret(connection.access_token_vault_path) == {
        "token": "gho-under-test"
    }
    assert await fake_vault.read_secret(connection.refresh_token_vault_path) == {
        "token": "ghr-under-test"
    }


async def test_connect_binds_the_state_to_the_browser(
    client: AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
    test_settings: Settings,
    stub_github_clients: tuple[StubOAuthClient, StubAppClient],
) -> None:
    """`/connect` sets an HttpOnly cookie carrying the state, scoped to the callback path."""
    headers, _ = await _member(session_factory, test_settings)

    response = await client.post("/api/v1/github/connect", headers=headers)

    assert response.status_code == 200, response.text
    set_cookie = response.headers["set-cookie"]
    assert f"{OAUTH_STATE_COOKIE}={response.json()['state']}" in set_cookie
    assert "HttpOnly" in set_cookie
    assert "Path=/api/v1/github/callback" in set_cookie
    assert "samesite=lax" in set_cookie.lower()


async def test_a_state_presented_by_another_browser_is_refused(
    client: AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
    test_settings: Settings,
    stub_github_clients: tuple[StubOAuthClient, StubAppClient],
) -> None:
    """Login-CSRF: an attacker's state completed in the victim's browser (no cookie, or a
    different one) must not bind the victim's GitHub token to the attacker's account."""
    oauth, _ = stub_github_clients
    _, attacker = await _member(session_factory, test_settings)
    state = uuid.uuid4().hex
    await _seed_state(
        session_factory, attacker.id, state=state, expires_at=datetime.now(UTC) + timedelta(minutes=5)
    )

    for cookies in ({}, {OAUTH_STATE_COOKIE: uuid.uuid4().hex}):
        response = await client.get(
            f"/api/v1/github/callback?code=victim-code&state={state}", cookies=cookies
        )
        assert response.status_code == 409, response.text
        assert "not issued to this browser" in response.json()["error"]["message"]

    assert oauth.exchanged_codes == []
    async with session_factory() as session:
        assert await session.scalar(select(GitHubConnection)) is None


async def test_each_new_connection_gets_its_own_vault_path(
    client: AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
    test_settings: Settings,
    stub_github_clients: tuple[StubOAuthClient, StubAppClient],
    fake_vault: FakeVaultClient,
) -> None:
    """Regression: the id default fires at flush, so paths were built from `None` and every
    user's token landed on `secret/github/connections/None/...`, overwriting the last."""
    oauth, _ = stub_github_clients
    paths: list[str] = []
    for token in ("gho-first-user", "gho-second-user"):
        oauth_token = token

        async def exchange(code: str, _token: str = oauth_token) -> dict[str, Any]:
            return {"access_token": _token, "scope": "repo"}

        oauth.exchange_code = exchange  # type: ignore[method-assign]
        _, user = await _member(session_factory, test_settings)
        state = uuid.uuid4().hex
        await _seed_state(
            session_factory, user.id, state=state, expires_at=datetime.now(UTC) + timedelta(minutes=5)
        )
        response = await client.get(
            f"/api/v1/github/callback?code=c&state={state}", cookies={OAUTH_STATE_COOKIE: state}
        )
        assert response.status_code == 200, response.text
        async with session_factory() as session:
            connection = await session.scalar(
                select(GitHubConnection).where(GitHubConnection.user_id == user.id)
            )
        assert connection is not None
        assert "None" not in connection.access_token_vault_path
        assert str(connection.id) in connection.access_token_vault_path
        paths.append(connection.access_token_vault_path)

    assert paths[0] != paths[1]
    assert await fake_vault.read_secret(paths[0]) == {"token": "gho-first-user"}
    assert await fake_vault.read_secret(paths[1]) == {"token": "gho-second-user"}


async def test_an_unknown_state_opens_nothing_and_exchanges_no_code(
    client: AsyncClient,
    stub_github_clients: tuple[StubOAuthClient, StubAppClient],
) -> None:
    """Refusal happens before `exchange_code`, so an anonymous caller cannot make this
    server talk to GitHub on demand, nor burn a single-use code that is not theirs.
    """
    oauth, _ = stub_github_clients

    response = await client.get(f"/api/v1/github/callback?code=not-yours&state={uuid.uuid4().hex}")

    assert response.status_code == 409, response.text
    assert "Invalid or expired" in response.json()["error"]["message"]
    assert oauth.exchanged_codes == []


async def test_an_expired_state_is_refused_and_consumed(
    client: AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
    test_settings: Settings,
    stub_github_clients: tuple[StubOAuthClient, StubAppClient],
) -> None:
    """The other half of the state's lifetime: past its expiry it is deleted on the way
    out, so a state that leaked into a browser history or a proxy log cannot be replayed.
    """
    oauth, _ = stub_github_clients
    _, user = await _member(session_factory, test_settings)
    state = uuid.uuid4().hex
    await _seed_state(
        session_factory, user.id, state=state, expires_at=datetime.now(UTC) - timedelta(minutes=1)
    )

    response = await client.get(f"/api/v1/github/callback?code=not-yours&state={state}")

    assert response.status_code == 409, response.text
    assert "expired" in response.json()["error"]["message"]
    assert oauth.exchanged_codes == []
    async with session_factory() as session:
        assert (
            await session.scalar(select(GitHubOAuthState).where(GitHubOAuthState.state == state))
            is None
        )
        assert await session.scalar(select(GitHubConnection)) is None


async def test_the_public_callback_is_bounded_per_ip(
    client: AsyncClient,
    stub_github_clients: tuple[StubOAuthClient, StubAppClient],
) -> None:
    """Anonymous is not the same as unbounded.

    The router split leans on this: `router.py` drops the org-tier limiter for
    `public_router`, and the per-IP `RateLimitMiddleware` is what stands in front of it.
    Filling the bucket by request rather than by writing a Redis key keeps the test honest
    about the real limit, and cannot straddle a window boundary mid-run.
    """
    oauth, _ = stub_github_clients

    statuses = []
    for _ in range(ANONYMOUS_REQUESTS_PER_MINUTE + 1):
        response = await client.get(
            f"/api/v1/github/callback?code=not-yours&state={uuid.uuid4().hex}"
        )
        statuses.append((response.status_code, response.headers.get("X-RateLimit-Limit")))

    limit = str(ANONYMOUS_REQUESTS_PER_MINUTE)
    assert {status[1] for status in statuses} == {limit}, "not governed by the anonymous bucket"
    assert [status[0] for status in statuses[:ANONYMOUS_REQUESTS_PER_MINUTE]] == (
        [409] * ANONYMOUS_REQUESTS_PER_MINUTE
    )
    assert statuses[-1][0] == 429, statuses[-1]
    assert oauth.exchanged_codes == [], "the middleware must reject before the exchange"
