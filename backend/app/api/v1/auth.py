"""Auth routes — `API.md §1`."""

from __future__ import annotations

import redis.asyncio as aioredis
from fastapi import APIRouter, Depends, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings, get_settings
from app.core.deps import client_ip, get_current_principal, get_db, get_redis
from app.core.errors import UnauthenticatedError
from app.models.organization import Organization, OrganizationMember
from app.models.user import User
from app.rbac.policy import Principal
from app.schemas.auth import (
    LoginRequest,
    LogoutRequest,
    MembershipResponse,
    MeResponse,
    RefreshRequest,
    RegisterRequest,
    TokenResponse,
    UserResponse,
)
from app.services import auth_service
from app.services.auth_service import RequestContext

router = APIRouter(prefix="/auth", tags=["auth"])


def _context(request: Request) -> RequestContext:
    return RequestContext(
        ip_address=client_ip(request),
        user_agent=request.headers.get("user-agent"),
    )


@router.post(
    "/register",
    response_model=TokenResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create an account and its organization",
)
async def register(
    payload: RegisterRequest,
    request: Request,
    session: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> TokenResponse:
    _, tokens = await auth_service.register(
        session,
        email=payload.email,
        password=payload.password,
        full_name=payload.full_name,
        organization_name=payload.organization_name,
        settings=settings,
        context=_context(request),
    )
    return TokenResponse(
        access_token=tokens.access_token,
        refresh_token=tokens.refresh_token,
        expires_in=tokens.expires_in,
    )


@router.post("/login", response_model=TokenResponse, summary="Exchange credentials for a JWT")
async def login(
    payload: LoginRequest,
    request: Request,
    session: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> TokenResponse:
    _, tokens = await auth_service.login(
        session,
        email=payload.email,
        password=payload.password,
        settings=settings,
        context=_context(request),
    )
    return TokenResponse(
        access_token=tokens.access_token,
        refresh_token=tokens.refresh_token,
        expires_in=tokens.expires_in,
    )


@router.post("/refresh", response_model=TokenResponse, summary="Rotate a refresh token")
async def refresh(
    payload: RefreshRequest,
    request: Request,
    session: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> TokenResponse:
    tokens = await auth_service.refresh(
        session,
        refresh_token=payload.refresh_token,
        settings=settings,
        context=_context(request),
    )
    return TokenResponse(
        access_token=tokens.access_token,
        refresh_token=tokens.refresh_token,
        expires_in=tokens.expires_in,
    )


@router.post(
    "/logout",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Revoke the current session",
)
async def logout(
    payload: LogoutRequest,
    request: Request,
    principal: Principal = Depends(get_current_principal),
    session: AsyncSession = Depends(get_db),
    redis_client: aioredis.Redis = Depends(get_redis),
    settings: Settings = Depends(get_settings),
) -> None:
    if principal.user_id is None:
        # An API key has no session to end; it is revoked via the org API-key endpoints.
        raise UnauthenticatedError("Logout requires a user session, not an API key.")

    await auth_service.logout(
        session,
        redis_client,
        user_id=principal.user_id,
        organization_id=principal.organization_id,
        jti=principal.jti,
        refresh_token=payload.refresh_token,
        settings=settings,
        context=_context(request),
    )


@router.get("/me", response_model=MeResponse, summary="The authenticated user")
async def me(
    principal: Principal = Depends(get_current_principal),
    session: AsyncSession = Depends(get_db),
) -> MeResponse:
    if principal.user_id is None:
        raise UnauthenticatedError("This endpoint requires a user session, not an API key.")

    user = await session.get(User, principal.user_id)
    if user is None:
        raise UnauthenticatedError()

    result = await session.execute(
        select(Organization.id, Organization.name, OrganizationMember.role)
        .join(OrganizationMember, OrganizationMember.organization_id == Organization.id)
        .where(OrganizationMember.user_id == principal.user_id)
        .order_by(OrganizationMember.joined_at)
    )
    memberships = [
        MembershipResponse(organization_id=row[0], organization_name=row[1], role=row[2])
        for row in result.all()
    ]

    return MeResponse(user=UserResponse.model_validate(user), organizations=memberships)
