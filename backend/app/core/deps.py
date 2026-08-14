"""Request-scoped dependencies: database session, Redis, and the authenticated principal.

Resolves both auth modes documented in `API.md §1` — `Authorization: Bearer <jwt>` and
`X-API-Key` — into the single `Principal` the RBAC layer consumes, so no route needs to
know which mode was used.
"""

from __future__ import annotations

import datetime
import uuid
from collections.abc import AsyncIterator
from typing import Annotated

import redis.asyncio as aioredis
from fastapi import Depends, Header, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings, get_settings
from app.core.errors import ErrorCode, UnauthenticatedError
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


def get_object_storage(request: Request) -> ObjectStorage:
    """The S3/MinIO client created at application startup."""
    storage: ObjectStorage = request.app.state.object_storage
    return storage


SessionDep = Annotated[AsyncSession, Depends(get_db)]
RedisDep = Annotated[aioredis.Redis, Depends(get_redis)]


async def is_jti_denylisted(redis_client: aioredis.Redis, jti: str) -> bool:
    return await redis_client.exists(f"{JTI_DENYLIST_PREFIX}{jti}") == 1


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


def client_ip(request: Request) -> str | None:
    """Best-effort client IP for audit logging (`Security.md §17`).

    Reads `X-Forwarded-For` because the ALB terminates TLS and proxies
    (`Architecture.md §11`), so `request.client.host` would be the load balancer. Only
    the left-most entry is used, and it is treated as advisory — a client can forge it,
    so it is recorded for investigation, never used for an authorization decision.
    """
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip() or None
    return request.client.host if request.client else None


def utc_now() -> datetime.datetime:
    return datetime.datetime.now(datetime.UTC)
