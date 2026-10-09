"""Request-scoped dependencies: database session, Redis, and the authenticated principal.

Resolves both auth modes documented in `API.md §1` — `Authorization: Bearer <jwt>` and
`X-API-Key` — into the single `Principal` the RBAC layer consumes, so no route needs to
know which mode was used.
"""

from __future__ import annotations

import datetime
import ipaddress
import uuid
from collections.abc import AsyncIterator
from typing import Annotated

import redis.asyncio as aioredis
from fastapi import Depends, Header, Request
from redis.exceptions import RedisError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings, get_settings
from app.core.errors import DependencyUnavailableError, ErrorCode, UnauthenticatedError
from app.core.logging import get_logger
from app.core.security import JWTError, decode_access_token, hash_opaque_token
from app.db.session import get_session
from app.models.organization import OrganizationMember
from app.models.user import APIKey
from app.rbac.policy import Principal
from app.services.storage_service import ObjectStorage

logger = get_logger(__name__)

# `denylist:jti:{jti}` — Security.md §4 immediate revocation ahead of natural expiry.
JTI_DENYLIST_PREFIX = "denylist:jti:"


async def get_db() -> AsyncIterator[AsyncSession]:
    async for session in get_session():
        yield session


def get_redis(request: Request) -> aioredis.Redis:
    """The connection pool created during app startup."""
    redis_client: aioredis.Redis = request.app.state.redis
    return redis_client


def get_stream_redis(request: Request) -> aioredis.Redis:
    """The Redis client for long blocking reads (SSE), with a socket timeout above the block."""
    stream_client: aioredis.Redis = getattr(request.app.state, "redis_stream", None) or get_redis(
        request
    )
    return stream_client


def get_object_storage(request: Request) -> ObjectStorage:
    """The S3/MinIO client created at application startup."""
    storage: ObjectStorage = request.app.state.object_storage
    return storage


SessionDep = Annotated[AsyncSession, Depends(get_db)]
RedisDep = Annotated[aioredis.Redis, Depends(get_redis)]


async def is_jti_denylisted(redis_client: aioredis.Redis, jti: str) -> bool:
    """Fails closed: if revocation cannot be checked, the token is not accepted (503)."""
    try:
        return await redis_client.exists(f"{JTI_DENYLIST_PREFIX}{jti}") == 1
    except (RedisError, OSError) as exc:
        logger.error("jti_denylist_unavailable", error=str(exc))
        raise DependencyUnavailableError(
            "Authentication is temporarily unavailable. Please retry shortly."
        ) from exc


async def denylist_jti(redis_client: aioredis.Redis, jti: str, ttl_seconds: int) -> None:
    """Revoke a token immediately. TTL matches the token's remaining lifetime so the
    denylist self-prunes rather than growing without bound."""
    if ttl_seconds > 0:
        await redis_client.setex(f"{JTI_DENYLIST_PREFIX}{jti}", ttl_seconds, "1")


async def _principal_from_jwt(
    token: str,
    session: AsyncSession,
    redis_client: aioredis.Redis,
    settings: Settings,
) -> Principal:
    try:
        claims = decode_access_token(token, settings)
    except JWTError as exc:
        raise UnauthenticatedError(
            "Access token is expired." if exc.expired else "Access token is invalid.",
            code=ErrorCode.TOKEN_EXPIRED if exc.expired else ErrorCode.UNAUTHENTICATED,
        ) from exc

    jti = str(claims["jti"])
    if await is_jti_denylisted(redis_client, jti):
        raise UnauthenticatedError("Access token has been revoked.", code=ErrorCode.TOKEN_REVOKED)

    user_id = uuid.UUID(str(claims["sub"]))
    org_claim = claims.get("org_id")
    org_id = uuid.UUID(str(org_claim)) if org_claim else None

    # The `role` claim is a convenience for the client, not the authorization source.
    # Re-read the membership so a role revoked mid-token-lifetime takes effect at once
    # instead of persisting until the token expires.
    org_role: str | None = None
    if org_id is not None:
        result = await session.execute(
            select(OrganizationMember.role).where(
                OrganizationMember.organization_id == org_id,
                OrganizationMember.user_id == user_id,
            )
        )
        org_role = result.scalar_one_or_none()

    return Principal(
        user_id=user_id,
        organization_id=org_id,
        org_role=org_role,
        auth_method="jwt",
        jti=jti,
    )


async def _principal_from_api_key(api_key: str, session: AsyncSession) -> Principal:
    """Resolve an `X-API-Key` header (`Security.md §5`).

    Lookup is by hash, so the plaintext key is never compared against stored data and
    never needs to exist in the database.
    """
    result = await session.execute(
        select(APIKey).where(APIKey.key_hash == hash_opaque_token(api_key))
    )
    key = result.scalar_one_or_none()
    if key is None or not key.is_active:
        # Same message whether the key is unknown, revoked, or expired — distinguishing
        # them would tell a prober which of their guesses was once valid.
        raise UnauthenticatedError("API key is invalid or has been revoked.")

    role_result = await session.execute(
        select(OrganizationMember.role)
        .where(OrganizationMember.organization_id == key.organization_id)
        .where(OrganizationMember.user_id == key.created_by)
    )
    creator_role: str | None = role_result.scalar_one_or_none()

    return Principal(
        user_id=None,
        organization_id=key.organization_id,
        # A key never outranks the person who created it; if they have since been
        # removed from the org, the key resolves to no role and authorizes nothing.
        org_role=creator_role,
        restricted_to_project_id=key.project_id,
        auth_method="api_key",
        api_key_id=key.id,
    )


async def get_current_principal(
    session: SessionDep,
    redis_client: RedisDep,
    authorization: Annotated[str | None, Header()] = None,
    x_api_key: Annotated[str | None, Header()] = None,
    settings: Settings = Depends(get_settings),
) -> Principal:
    """Authenticate the request. Raises 401 when no valid credential is present."""
    if x_api_key:
        return await _principal_from_api_key(x_api_key, session)

    if authorization:
        scheme, _, token = authorization.partition(" ")
        if scheme.lower() != "bearer" or not token:
            raise UnauthenticatedError("Authorization header must be 'Bearer <token>'.")
        return await _principal_from_jwt(token, session, redis_client, settings)

    raise UnauthenticatedError()


PrincipalDep = Annotated[Principal, Depends(get_current_principal)]


def _as_ip(value: str | None) -> str | None:
    """`value` canonicalised, or None unless it really is an IP address.

    `audit_logs.ip_address` is a Postgres `INET` column, so anything else aborts the whole
    transaction with `invalid input syntax for type inet` — measured on the dev database —
    and the audited action fails while leaving no audit row behind.
    """
    if not value:
        return None
    try:
        address = ipaddress.ip_address(value.strip())
    except ValueError:
        return None
    # A link-local IPv6 can carry a scope id (`fe80::1%eth0`). `ipaddress` parses it and
    # hands it back verbatim; Postgres `INET` rejects it (`invalid input syntax for type
    # inet` — measured), which is the abort this function exists to prevent. The scope
    # names an interface on whatever appended it, not a routable client, so recording
    # nothing is the honest answer.
    if getattr(address, "scope_id", None):
        return None
    return str(address)


def select_client_ip(
    forwarded_for: str | None, peer: str | None, trusted_proxy_hops: int
) -> str | None:
    """The address the client connected from, given a chain of `trusted_proxy_hops` proxies.

    Each proxy appends the peer it saw, so the entries our own proxies appended are the
    right-most `trusted_proxy_hops` ones — and everything a caller typed sits to their left.
    The left-most entry, which is what this function used to return, is free text: it made
    the pre-auth per-IP limiter trivially bypassable (one fresh bucket per forged value) and
    let a forged string reach the `INET` column.

    Two honest limitations, both stated rather than papered over: if the real chain is
    shorter than `trusted_proxy_hops`, the index clamps to the left-most entry, so an
    over-counted setting is again the client's text; and a hop whose append is not an IP
    falls through to the transport peer rather than being reported.
    """
    entries = [entry.strip() for entry in forwarded_for.split(",")] if forwarded_for else []
    if entries and trusted_proxy_hops > 0:
        candidate = _as_ip(entries[max(len(entries) - trusted_proxy_hops, 0)])
        if candidate is not None:
            return candidate
    return _as_ip(peer)


def client_ip(request: Request, settings: Settings) -> str | None:
    """Best-effort client IP for audit logging (`Security.md §17`).

    `X-Forwarded-For` is read at the depth named by `settings.trusted_proxy_hops` because
    the ALB terminates TLS and proxies (`Architecture.md §11`), so `request.client.host`
    alone would be the load balancer. The result is still advisory — it is recorded for
    investigation and is never an authorization input.
    """
    return select_client_ip(
        request.headers.get("x-forwarded-for"),
        request.client.host if request.client else None,
        settings.trusted_proxy_hops,
    )


def utc_now() -> datetime.datetime:
    return datetime.datetime.now(datetime.UTC)
