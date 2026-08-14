"""Registration, login, and refresh-token rotation.

Implements `Security.md §1`: Argon2id password verification and single-use refresh tokens
with family-level revocation on replay.
"""

from __future__ import annotations

import datetime
import re
import unicodedata
import uuid
from dataclasses import dataclass

import redis.asyncio as aioredis
from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.deps import denylist_jti
from app.core.errors import ConflictError, ErrorCode, UnauthenticatedError
from app.core.logging import get_logger
from app.core.security import (
    create_access_token,
    generate_opaque_token,
    hash_opaque_token,
    hash_password,
    password_needs_rehash,
    verify_password,
)
from app.models.audit import AuditAction
from app.models.enums import ActorType, OrgRole
from app.models.organization import Organization, OrganizationMember
from app.models.user import RefreshToken, User
from app.services import audit_service

logger = get_logger(__name__)


@dataclass(frozen=True, slots=True)
class IssuedTokens:
    access_token: str
    refresh_token: str
    expires_in: int


@dataclass(frozen=True, slots=True)
class RequestContext:
    """Caller metadata recorded on audit entries (`Security.md §17`)."""

    ip_address: str | None = None
    user_agent: str | None = None


def _utc_now() -> datetime.datetime:
    return datetime.datetime.now(datetime.UTC)


async def _commit_before_raising(session: AsyncSession) -> None:
    """Persist security-relevant writes that must survive the rejection that follows.

    The request-scoped session rolls back on any exception (`db/session.py`), which is
    right for ordinary handlers but wrong for two cases here:

    * a failed-login audit entry — an attack that leaves no trace defeats the intrusion
      detection `Security.md §17` exists for;
    * refresh-token family revocation on reuse — if the revocation rolled back, the
      "compromise detected" response would be a lie and the stolen family would stay live.

    Both write only rows that describe the failure, so committing them and then raising
    leaves no half-finished business operation behind.
    """
    await session.commit()


def slugify(value: str) -> str:
    """URL-safe organization slug.

    NFKD-normalizes first so accented input produces a stable ASCII slug rather than
    collapsing to an empty string.
    """
    normalized = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode()
    slug = re.sub(r"[^a-z0-9]+", "-", normalized.lower()).strip("-")
    return slug[:90] or "org"


async def _issue_token_pair(
    session: AsyncSession,
    *,
    user: User,
    organization_id: uuid.UUID | None,
    org_role: str | None,
    settings: Settings,
    family_id: uuid.UUID | None = None,
) -> IssuedTokens:
    """Mint an access token plus a refresh token in `family_id` (a new family if None)."""
    access = create_access_token(
        user_id=user.id, org_id=organization_id, role=org_role, settings=settings
    )

    refresh_plaintext = generate_opaque_token()
    session.add(
        RefreshToken(
            user_id=user.id,
            family_id=family_id or uuid.uuid4(),
            token_hash=hash_opaque_token(refresh_plaintext),
            expires_at=_utc_now() + datetime.timedelta(days=settings.jwt_refresh_token_expire_days),
        )
    )

    return IssuedTokens(
        access_token=access.token,
        refresh_token=refresh_plaintext,
        expires_in=access.expires_in,
    )


async def _primary_membership(
    session: AsyncSession, user_id: uuid.UUID
) -> tuple[uuid.UUID, str] | None:
    """The organization a token is scoped to.

    Multi-org users get their earliest-joined org; an explicit org switcher endpoint
    arrives with the org-management routes.
    """
    result = await session.execute(
        select(OrganizationMember.organization_id, OrganizationMember.role)
        .where(OrganizationMember.user_id == user_id)
        .order_by(OrganizationMember.joined_at)
        .limit(1)
    )
    row = result.first()
    return (row[0], row[1]) if row else None


async def register(
    session: AsyncSession,
    *,
    email: str,
    password: str,
    full_name: str,
    organization_name: str,
    settings: Settings,
    context: RequestContext,
) -> tuple[User, IssuedTokens]:
    """Create a user, their organization, and an `owner` membership."""
    normalized_email = email.strip().lower()

    organization = Organization(name=organization_name, slug=slugify(organization_name))
    user = User(
        email=normalized_email,
        password_hash=hash_password(password),
        full_name=full_name,
    )
    session.add_all([organization, user])

    try:
        # Flush rather than commit: we need the generated ids to build the membership and
        # token rows, but the whole registration must still succeed or fail as one unit.
        await session.flush()
    except IntegrityError as exc:
        await session.rollback()
        # Both the email and slug unique constraints land here. Reported as a generic
        # conflict without echoing which one — confirming an email is registered is an
        # account-enumeration oracle.
        raise ConflictError(
            "An account or organization with these details already exists."
        ) from exc

    session.add(
        OrganizationMember(organization_id=organization.id, user_id=user.id, role=OrgRole.OWNER)
    )

    tokens = await _issue_token_pair(
        session,
        user=user,
        organization_id=organization.id,
        org_role=OrgRole.OWNER,
        settings=settings,
    )

    await audit_service.record(
        session,
        action=AuditAction.USER_REGISTERED,
        actor_type=ActorType.USER,
        organization_id=organization.id,
        actor_user_id=user.id,
        resource_type="user",
        resource_id=str(user.id),
        ip_address=context.ip_address,
        user_agent=context.user_agent,
    )
    logger.info("user_registered", user_id=str(user.id), organization_id=str(organization.id))
    return user, tokens


async def login(
    session: AsyncSession,
    *,
    email: str,
    password: str,
    settings: Settings,
    context: RequestContext,
) -> tuple[User, IssuedTokens]:
    """Authenticate by password and issue a fresh token family."""
    normalized_email = email.strip().lower()
    result = await session.execute(select(User).where(User.email == normalized_email))
    user = result.scalar_one_or_none()

    if user is None:
        # Hash anyway so a nonexistent account takes the same time as a wrong password;
        # otherwise response timing enumerates valid emails.
        hash_password(password)
        await audit_service.record(
            session,
            action=AuditAction.USER_LOGIN_FAILED,
            actor_type=ActorType.SYSTEM,
            resource_type="email",
            ip_address=context.ip_address,
            user_agent=context.user_agent,
            metadata={"reason": "unknown_email"},
        )
        await _commit_before_raising(session)
        raise UnauthenticatedError(
            "Email or password is incorrect.", code=ErrorCode.INVALID_CREDENTIALS
        )

    if not verify_password(password, user.password_hash):
        await audit_service.record(
            session,
            action=AuditAction.USER_LOGIN_FAILED,
            actor_type=ActorType.USER,
            actor_user_id=user.id,
            resource_type="user",
            resource_id=str(user.id),
            ip_address=context.ip_address,
            user_agent=context.user_agent,
            metadata={"reason": "bad_password"},
        )
        await _commit_before_raising(session)
        raise UnauthenticatedError(
            "Email or password is incorrect.", code=ErrorCode.INVALID_CREDENTIALS
        )

    # Transparently upgrade the stored hash when the work factor has been raised.
    if user.password_hash and password_needs_rehash(user.password_hash):
        user.password_hash = hash_password(password)

    membership = await _primary_membership(session, user.id)
    org_id, org_role = membership if membership else (None, None)

    tokens = await _issue_token_pair(
        session,
        user=user,
        organization_id=org_id,
        org_role=org_role,
        settings=settings,
    )

    await audit_service.record(
        session,
        action=AuditAction.USER_LOGIN_SUCCEEDED,
        actor_type=ActorType.USER,
        organization_id=org_id,
        actor_user_id=user.id,
        resource_type="user",
        resource_id=str(user.id),
        ip_address=context.ip_address,
        user_agent=context.user_agent,
    )
    logger.info("login_succeeded", user_id=str(user.id))
    return user, tokens


async def _revoke_family(session: AsyncSession, family_id: uuid.UUID) -> None:
    """Revoke every unrevoked token in a family."""
    await session.execute(
        update(RefreshToken)
        .where(RefreshToken.family_id == family_id, RefreshToken.revoked_at.is_(None))
        .values(revoked_at=_utc_now())
    )


async def refresh(
    session: AsyncSession,
    *,
    refresh_token: str,
    settings: Settings,
    context: RequestContext,
) -> IssuedTokens:
    """Rotate a refresh token (`Security.md §1`).

    Single-use: redeeming a token marks it spent and issues a successor in the same
    family. Redeeming an already-spent token means either the client replayed it or an
    attacker stole it — indistinguishable from here, so the safe reading is compromise:
    the entire family is revoked, forcing a fresh login.
    """
    token_hash = hash_opaque_token(refresh_token)
    result = await session.execute(
        select(RefreshToken).where(RefreshToken.token_hash == token_hash)
    )
    stored = result.scalar_one_or_none()

    if stored is None:
        raise UnauthenticatedError("Refresh token is invalid.", code=ErrorCode.INVALID_CREDENTIALS)

    if stored.used_at is not None:
        await _revoke_family(session, stored.family_id)
        await audit_service.record(
            session,
            action=AuditAction.TOKEN_REUSE_DETECTED,
            actor_type=ActorType.SYSTEM,
            actor_user_id=stored.user_id,
            resource_type="refresh_token_family",
            resource_id=str(stored.family_id),
            ip_address=context.ip_address,
            user_agent=context.user_agent,
            metadata={"revoked_family": True},
        )
        logger.warning(
            "refresh_token_reuse_detected",
            user_id=str(stored.user_id),
            family_id=str(stored.family_id),
        )
        # The revocation must outlive this rejection, or the response claims a family was
        # revoked while the stolen tokens keep working.
        await _commit_before_raising(session)
        raise UnauthenticatedError(
            "Refresh token has already been used; the token family has been revoked. "
            "Please sign in again.",
            code=ErrorCode.TOKEN_REUSE_DETECTED,
        )

    if stored.revoked_at is not None:
        raise UnauthenticatedError("Refresh token has been revoked.", code=ErrorCode.TOKEN_REVOKED)

    if stored.expires_at <= _utc_now():
        raise UnauthenticatedError("Refresh token has expired.", code=ErrorCode.TOKEN_EXPIRED)

    user = await session.get(User, stored.user_id)
    if user is None:
        # The user was deleted while the token was live.
        await _revoke_family(session, stored.family_id)
        raise UnauthenticatedError("Refresh token is invalid.", code=ErrorCode.INVALID_CREDENTIALS)

    stored.used_at = _utc_now()

    membership = await _primary_membership(session, user.id)
    org_id, org_role = membership if membership else (None, None)

    tokens = await _issue_token_pair(
        session,
        user=user,
        organization_id=org_id,
        org_role=org_role,
        settings=settings,
        family_id=stored.family_id,
    )

    await audit_service.record(
        session,
        action=AuditAction.TOKEN_REFRESHED,
        actor_type=ActorType.USER,
        organization_id=org_id,
        actor_user_id=user.id,
        resource_type="refresh_token_family",
        resource_id=str(stored.family_id),
        ip_address=context.ip_address,
        user_agent=context.user_agent,
    )
    return tokens


async def logout(
    session: AsyncSession,
    redis_client: aioredis.Redis,
    *,
    user_id: uuid.UUID,
    organization_id: uuid.UUID | None,
    jti: str | None,
    refresh_token: str | None,
    settings: Settings,
    context: RequestContext,
) -> None:
    """Revoke the current session.

    Denylists the access token's `jti` (`Security.md §4`) so it stops working before its
    natural expiry, and revokes the presented refresh token's family so no descendant
    survives.
    """
    if jti:
        await denylist_jti(redis_client, jti, settings.jwt_access_token_expire_minutes * 60)

    if refresh_token:
        result = await session.execute(
            select(RefreshToken).where(RefreshToken.token_hash == hash_opaque_token(refresh_token))
        )
        stored = result.scalar_one_or_none()
        # Only revoke a family belonging to the caller — otherwise presenting someone
        # else's refresh token would let an attacker log them out.
        if stored is not None and stored.user_id == user_id:
            await _revoke_family(session, stored.family_id)

    await audit_service.record(
        session,
        action=AuditAction.USER_LOGGED_OUT,
        actor_type=ActorType.USER,
        organization_id=organization_id,
        actor_user_id=user_id,
        resource_type="user",
        resource_id=str(user_id),
        ip_address=context.ip_address,
        user_agent=context.user_agent,
    )
