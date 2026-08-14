"""Auth flows — `API.md §1`, `Security.md §1` and `§4`."""

from __future__ import annotations

import datetime

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.security import decode_access_token, hash_opaque_token
from app.models.audit import AuditAction, AuditLog
from app.models.user import RefreshToken, User
from tests.conftest import TEST_PASSWORD

REGISTRATION = {
    "email": "maya@example.com",
    "password": TEST_PASSWORD,
    "full_name": "Maya Patel",
    "organization_name": "Acme Payments",
}


async def register(client: AsyncClient, **overrides: object) -> dict[str, str]:
    response = await client.post("/api/v1/auth/register", json={**REGISTRATION, **overrides})
    assert response.status_code == 201, response.text
    tokens: dict[str, str] = response.json()
    return tokens


# --- Registration -------------------------------------------------------------------


async def test_register_returns_token_pair(client: AsyncClient) -> None:
    tokens = await register(client)
    assert set(tokens) == {"access_token", "refresh_token", "expires_in", "token_type"}
    assert tokens["token_type"] == "bearer"
    # 1 hour, per Security.md §1 and JWT_ACCESS_TOKEN_EXPIRE_MINUTES.
    assert tokens["expires_in"] == 3600


async def test_register_creates_owner_membership(client: AsyncClient) -> None:
    tokens = await register(client)
    response = await client.get(
        "/api/v1/auth/me", headers={"Authorization": f"Bearer {tokens['access_token']}"}
    )
    assert response.status_code == 200
    body = response.json()
    assert body["user"]["email"] == "maya@example.com"
    assert len(body["organizations"]) == 1
    assert body["organizations"][0]["role"] == "owner"
    assert body["organizations"][0]["organization_name"] == "Acme Payments"


async def test_access_token_carries_the_specified_claims(
    client: AsyncClient, test_settings: object
) -> None:
    """`Security.md §4` names the claim set exactly: sub, org_id, role, exp, iat, jti."""
    tokens = await register(client)
    claims = decode_access_token(tokens["access_token"], test_settings)  # type: ignore[arg-type]
    for claim in ("sub", "org_id", "role", "exp", "iat", "jti"):
        assert claim in claims, f"missing claim: {claim}"
    assert claims["role"] == "owner"


async def test_duplicate_email_is_a_conflict_without_confirming_the_email(
    client: AsyncClient,
) -> None:
    await register(client)
    response = await client.post(
        "/api/v1/auth/register", json={**REGISTRATION, "organization_name": "Other Co"}
    )
    assert response.status_code == 409
    # The message must not confirm which field collided — that is an enumeration oracle.
    assert "maya@example.com" not in response.text


async def test_short_password_is_rejected(client: AsyncClient) -> None:
    response = await client.post(
        "/api/v1/auth/register", json={**REGISTRATION, "password": "short"}
    )
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"


async def test_password_is_never_stored_in_plaintext(
    client: AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    await register(client)
    async with session_factory() as session:
        stored = await session.scalar(select(User.password_hash))
    assert stored is not None
    assert TEST_PASSWORD not in stored
    # Argon2id, per Security.md §1.
    assert stored.startswith("$argon2id$")


# --- Login --------------------------------------------------------------------------


async def test_login_succeeds_with_correct_password(client: AsyncClient) -> None:
    await register(client)
    response = await client.post(
        "/api/v1/auth/login",
        json={"email": "maya@example.com", "password": TEST_PASSWORD},
    )
    assert response.status_code == 200
    assert response.json()["access_token"]


async def test_login_is_case_insensitive_on_email(client: AsyncClient) -> None:
    await register(client)
    response = await client.post(
        "/api/v1/auth/login",
        json={"email": "MAYA@Example.COM", "password": TEST_PASSWORD},
    )
    assert response.status_code == 200


@pytest.mark.parametrize(
    ("email", "password"),
    [
        ("maya@example.com", "wrong-password-entirely"),
        ("nobody@example.com", TEST_PASSWORD),
    ],
    ids=["wrong_password", "unknown_email"],
)
async def test_bad_credentials_are_indistinguishable(
    client: AsyncClient, email: str, password: str
) -> None:
    """Both failures return the same code and message so neither reveals whether the
    account exists."""
    await register(client)
    response = await client.post("/api/v1/auth/login", json={"email": email, "password": password})
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "INVALID_CREDENTIALS"
    assert response.json()["error"]["message"] == "Email or password is incorrect."


async def test_failed_login_is_audited(
    client: AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    await register(client)
    await client.post(
        "/api/v1/auth/login", json={"email": "maya@example.com", "password": "wrong-password-x"}
    )
    async with session_factory() as session:
        actions = list(
            (await session.execute(select(AuditLog.action))).scalars().all()
        )
    assert AuditAction.USER_LOGIN_FAILED in actions


# --- Refresh rotation (Security.md §1) ----------------------------------------------


async def test_refresh_returns_a_new_pair(client: AsyncClient) -> None:
    tokens = await register(client)
    response = await client.post(
        "/api/v1/auth/refresh", json={"refresh_token": tokens["refresh_token"]}
    )
    assert response.status_code == 200
    rotated = response.json()
    # Single-use: the successor must differ from the token just spent.
    assert rotated["refresh_token"] != tokens["refresh_token"]


async def test_refresh_keeps_the_successor_in_the_same_family(
    client: AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    tokens = await register(client)
    await client.post("/api/v1/auth/refresh", json={"refresh_token": tokens["refresh_token"]})

    async with session_factory() as session:
        families = set(
            (await session.execute(select(RefreshToken.family_id))).scalars().all()
        )
    # Two token rows, one family — the family is what reuse detection revokes.
    assert len(families) == 1


async def test_replaying_a_spent_refresh_token_revokes_the_whole_family(
    client: AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    """The core of `Security.md §1`: reuse is treated as a compromise signal.

    A spent token being presented again means either a buggy client or a stolen token.
    Indistinguishable from the server, so the safe reading is theft — kill the family.
    """
    tokens = await register(client)
    original = tokens["refresh_token"]

    first = await client.post("/api/v1/auth/refresh", json={"refresh_token": original})
    assert first.status_code == 200
    successor = first.json()["refresh_token"]

    # Replay the already-redeemed token.
    replay = await client.post("/api/v1/auth/refresh", json={"refresh_token": original})
    assert replay.status_code == 401
    assert replay.json()["error"]["code"] == "TOKEN_REUSE_DETECTED"

    # Every token in the family is now revoked, including the legitimate successor.
    async with session_factory() as session:
        rows = list((await session.execute(select(RefreshToken))).scalars().all())
    assert rows, "expected refresh token rows"
    assert all(row.revoked_at is not None for row in rows), (
        "reuse must revoke the entire family, not just the replayed token"
    )

    # And the successor no longer works, so the attacker gains nothing by racing.
    after = await client.post("/api/v1/auth/refresh", json={"refresh_token": successor})
    assert after.status_code == 401


async def test_reuse_detection_writes_an_audit_entry(
    client: AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    """`Security.md §17` — a compromise signal must be attributable after the fact."""
    tokens = await register(client)
    original = tokens["refresh_token"]
    await client.post("/api/v1/auth/refresh", json={"refresh_token": original})
    await client.post("/api/v1/auth/refresh", json={"refresh_token": original})

    async with session_factory() as session:
        entry = await session.scalar(
            select(AuditLog).where(AuditLog.action == AuditAction.TOKEN_REUSE_DETECTED)
        )
    assert entry is not None
    assert entry.resource_type == "refresh_token_family"
    assert entry.event_metadata == {"revoked_family": True}


async def test_unknown_refresh_token_is_rejected(client: AsyncClient) -> None:
    response = await client.post(
        "/api/v1/auth/refresh", json={"refresh_token": "not-a-real-token"}
    )
    assert response.status_code == 401


async def test_expired_refresh_token_is_rejected(
    client: AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    tokens = await register(client)

    async with session_factory() as session:
        stored = await session.scalar(
            select(RefreshToken).where(
                RefreshToken.token_hash == hash_opaque_token(tokens["refresh_token"])
            )
        )
        assert stored is not None
        stored.expires_at = datetime.datetime.now(datetime.UTC) - datetime.timedelta(minutes=1)
        await session.commit()

    response = await client.post(
        "/api/v1/auth/refresh", json={"refresh_token": tokens["refresh_token"]}
    )
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "TOKEN_EXPIRED"


async def test_refresh_token_is_stored_only_as_a_hash(
    client: AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    tokens = await register(client)
    async with session_factory() as session:
        stored = list(
            (await session.execute(select(RefreshToken.token_hash))).scalars().all()
        )
    assert tokens["refresh_token"] not in stored
    assert stored == [hash_opaque_token(tokens["refresh_token"])]


# --- Logout / revocation (Security.md §4) -------------------------------------------


async def test_logout_denylists_the_access_token(client: AsyncClient) -> None:
    """The jti denylist makes revocation immediate rather than waiting for expiry."""
    tokens = await register(client)
    auth = {"Authorization": f"Bearer {tokens['access_token']}"}

    assert (await client.get("/api/v1/auth/me", headers=auth)).status_code == 200

    logout = await client.post(
        "/api/v1/auth/logout", json={"refresh_token": tokens["refresh_token"]}, headers=auth
    )
    assert logout.status_code == 204

    after = await client.get("/api/v1/auth/me", headers=auth)
    assert after.status_code == 401
    assert after.json()["error"]["code"] == "TOKEN_REVOKED"


async def test_logout_revokes_the_refresh_family(client: AsyncClient) -> None:
    tokens = await register(client)
    await client.post(
        "/api/v1/auth/logout",
        json={"refresh_token": tokens["refresh_token"]},
        headers={"Authorization": f"Bearer {tokens['access_token']}"},
    )
    response = await client.post(
        "/api/v1/auth/refresh", json={"refresh_token": tokens["refresh_token"]}
    )
    assert response.status_code == 401


async def test_logout_cannot_revoke_another_users_family(
    client: AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    """Presenting someone else's refresh token must not log them out."""
    victim = await register(client)
    attacker = await register(
        client, email="attacker@example.com", organization_name="Attacker Co"
    )

    # Attacker authenticates as themselves but submits the victim's refresh token.
    logout = await client.post(
        "/api/v1/auth/logout",
        json={"refresh_token": victim["refresh_token"]},
        headers={"Authorization": f"Bearer {attacker['access_token']}"},
    )
    assert logout.status_code == 204

    # The victim's token still works.
    response = await client.post(
        "/api/v1/auth/refresh", json={"refresh_token": victim["refresh_token"]}
    )
    assert response.status_code == 200


# --- Token verification -------------------------------------------------------------


async def test_missing_credentials_returns_401(client: AsyncClient) -> None:
    response = await client.get("/api/v1/auth/me")
    assert response.status_code == 401
    assert response.headers.get("WWW-Authenticate") == "Bearer"


async def test_malformed_authorization_header_is_rejected(client: AsyncClient) -> None:
    tokens = await register(client)
    response = await client.get(
        "/api/v1/auth/me", headers={"Authorization": tokens["access_token"]}
    )
    assert response.status_code == 401


async def test_tampered_token_signature_is_rejected(client: AsyncClient) -> None:
    """RS256 verification — a token whose payload was edited must not validate."""
    tokens = await register(client)
    header, payload, signature = tokens["access_token"].split(".")
    forged = f"{header}.{payload}.{'A' * len(signature)}"
    response = await client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {forged}"})
    assert response.status_code == 401


async def test_role_revocation_takes_effect_before_token_expiry(
    client: AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    """The `role` claim is a client convenience; membership is re-read every request.

    Otherwise a revoked role would keep working until the access token expired.
    """
    tokens = await register(client)
    auth = {"Authorization": f"Bearer {tokens['access_token']}"}

    async with session_factory() as session:
        from app.models.organization import OrganizationMember

        member = await session.scalar(select(OrganizationMember))
        assert member is not None
        await session.delete(member)
        await session.commit()

    response = await client.get("/api/v1/auth/me", headers=auth)
    # Still authenticated, but now carries no org membership.
    assert response.status_code == 200
    assert response.json()["organizations"] == []
