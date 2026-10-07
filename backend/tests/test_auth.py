"""Auth flows — `API.md §1`, `Security.md §1` and `§4`."""

from __future__ import annotations

import base64
import datetime
import hashlib
import hmac
import json
import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config import Settings
from app.core.security import JWTError, decode_access_token, hash_opaque_token, load_keys
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


def _b64url(data: bytes) -> str:
    """base64url without padding, as JWS requires."""
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


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


async def test_second_signup_same_org_disambiguates_slug(client: AsyncClient) -> None:
    tokens1 = await register(client)
    tokens2 = await register(
        client,
        email="second@example.com",
        organization_name="Acme Payments",
    )
    assert tokens2["access_token"]
    assert tokens1["access_token"] != tokens2["access_token"]


async def test_access_token_carries_the_specified_claims(
    client: AsyncClient, test_settings: object
) -> None:
    """`Security.md §4` names the claim set exactly: sub, org_id, role, exp, iat, jti."""
    tokens = await register(client)
    claims = decode_access_token(tokens["access_token"], test_settings)  # type: ignore[arg-type]
    for claim in ("sub", "org_id", "role", "exp", "iat", "jti"):
        assert claim in claims, f"missing claim: {claim}"
    assert claims["role"] == "owner"


def test_decode_refuses_an_hs256_token_signed_with_the_public_key(
    test_settings: Settings,
) -> None:
    """Audit finding L7 (pyjwt 2.14.0 -> 2.15.x): the algorithm pin must keep its teeth.

    The forge below is the classic RS256 -> HS256 confusion: the public key is public, so the
    attacker tries it as an HMAC secret and hopes the verifier trusts the token's own `alg`
    header. It is assembled by hand rather than with `jwt.encode`, because pyjwt refuses to
    *sign* an HMAC token with an asymmetric key -- an attacker is not using our library and
    gets no such guard.

    With `algorithms` pinned to the configured RS256, pyjwt rejects the header's `alg` before
    the key is prepared and the wrapper raises a clean JWTError. Measured against a mutated
    pin (["RS256", "HS256"]) the token is still refused, but by pyjwt's HMAC key-shape guard
    as `InvalidKeyError` -- which is a PyJWTError, not an InvalidTokenError, so it escapes
    this wrapper uncaught. The pin is therefore what keeps the refusal well-shaped.
    """
    now = datetime.datetime.now(datetime.UTC)
    claims = {
        "sub": str(uuid.uuid4()),
        "org_id": None,
        "role": "owner",
        "iat": int(now.timestamp()),
        "exp": int((now + datetime.timedelta(hours=1)).timestamp()),
        "jti": str(uuid.uuid4()),
        "iss": test_settings.jwt_issuer,
    }
    segments = [
        _b64url(json.dumps({"alg": "HS256", "typ": "JWT"}).encode()),
        _b64url(json.dumps(claims).encode()),
    ]
    signing_input = ".".join(segments).encode()
    signature = hmac.new(
        load_keys(test_settings).public_key.encode(), signing_input, hashlib.sha256
    ).digest()
    segments.append(_b64url(signature))

    with pytest.raises(JWTError) as excinfo:
        decode_access_token(".".join(segments), test_settings)
    assert excinfo.value.expired is False


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


# --- Per-account lockout (audit M2) -------------------------------------------------


async def _wrong_password_attempts(client: AsyncClient, email: str, count: int) -> list[int]:
    """Hammer the login endpoint with bad passwords for one account; returns the codes."""
    codes = []
    for _ in range(count):
        response = await client.post(
            "/api/v1/auth/login", json={"email": email, "password": "wrong-password-x"}
        )
        codes.append(response.status_code)
    return codes


async def _load_user(
    session_factory: async_sessionmaker[AsyncSession], email: str
) -> User:
    async with session_factory() as session:
        return (
            await session.execute(select(User).where(User.email == email))
        ).scalar_one()


async def test_repeated_bad_passwords_lock_the_account(
    client: AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    """The per-IP Redis limiter fails open and is IP-keyed, so credential stuffing from
    many addresses never tripped it; the account itself now has a ceiling."""
    await register(client)
    assert await _wrong_password_attempts(client, "maya@example.com", 4) == [401] * 4
    assert await _wrong_password_attempts(client, "maya@example.com", 1) == [401]

    correct = await client.post(
        "/api/v1/auth/login", json={"email": "maya@example.com", "password": TEST_PASSWORD}
    )
    assert correct.status_code == 401, "the right password must not work while locked"

    locked_user = await _load_user(session_factory, "maya@example.com")
    assert locked_user.locked_until is not None
    assert locked_user.failed_login_count == 0

    # Attempts in flight must not extend the lock, or lockout becomes a permanent DoS.
    await _wrong_password_attempts(client, "maya@example.com", 3)
    after = await _load_user(session_factory, "maya@example.com")
    assert after.locked_until == locked_user.locked_until
    assert after.failed_login_count == 0


async def test_a_locked_account_is_indistinguishable_from_an_unknown_email(
    client: AsyncClient,
) -> None:
    await register(client)
    await _wrong_password_attempts(client, "maya@example.com", 5)

    locked = await client.post(
        "/api/v1/auth/login", json={"email": "maya@example.com", "password": TEST_PASSWORD}
    )
    unknown = await client.post(
        "/api/v1/auth/login", json={"email": "nobody@example.com", "password": TEST_PASSWORD}
    )
    assert locked.status_code == unknown.status_code == 401
    locked_body = locked.json()["error"]
    unknown_body = unknown.json()["error"]
    assert {k: v for k, v in locked_body.items() if k != "request_id"} == {
        k: v for k, v in unknown_body.items() if k != "request_id"
    }


async def test_lockout_expiry_restores_access(
    client: AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    await register(client)
    await _wrong_password_attempts(client, "maya@example.com", 5)

    async with session_factory() as session:
        user = (
            await session.execute(select(User).where(User.email == "maya@example.com"))
        ).scalar_one()
        user.locked_until = datetime.datetime.now(datetime.UTC) - datetime.timedelta(minutes=1)
        await session.commit()

    recovered = await client.post(
        "/api/v1/auth/login", json={"email": "maya@example.com", "password": TEST_PASSWORD}
    )
    assert recovered.status_code == 200, recovered.text


async def test_a_successful_login_clears_the_failure_ledger(
    client: AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    """Failures before a good login must not be counted against the next streak."""
    await register(client)
    await _wrong_password_attempts(client, "maya@example.com", 4)

    first = await client.post(
        "/api/v1/auth/login", json={"email": "maya@example.com", "password": TEST_PASSWORD}
    )
    assert first.status_code == 200
    assert (await _load_user(session_factory, "maya@example.com")).failed_login_count == 0

    assert await _wrong_password_attempts(client, "maya@example.com", 4) == [401] * 4
    second = await client.post(
        "/api/v1/auth/login", json={"email": "maya@example.com", "password": TEST_PASSWORD}
    )
    assert second.status_code == 200


async def test_lockout_is_written_to_the_audit_log(
    client: AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    await register(client)
    await _wrong_password_attempts(client, "maya@example.com", 5)

    async with session_factory() as session:
        stmt = select(AuditLog).where(AuditLog.action == AuditAction.USER_LOGIN_FAILED)
        rows = (await session.execute(stmt)).scalars().all()
    reasons = [(row.event_metadata or {}).get("reason") for row in rows]
    assert reasons.count("bad_password") == 4
    assert reasons.count("account_locked") == 1


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
