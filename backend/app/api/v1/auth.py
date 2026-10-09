"""Auth routes — `API.md §1`."""

from __future__ import annotations

import redis.asyncio as aioredis
from fastapi import APIRouter, Cookie, Depends, Request, Response, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings, get_settings
from app.core.deps import (
    client_ip,
    get_current_principal,
    get_db,
    get_optional_principal,
    get_redis,
)
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


def _context(request: Request, settings: Settings) -> RequestContext:
    return RequestContext(
        ip_address=client_ip(request, settings),
        user_agent=request.headers.get("user-agent"),
    )


@router.post(
    "/register",
    response_model=TokenResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create an account and its organization",
)
async def register(
    response: Response,
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
        context=_context(request, settings),
    )
    response.set_cookie(
        "refresh_token",
        tokens.refresh_token,
        max_age=settings.jwt_refresh_token_expire_days * 86400,
        httponly=True,
        secure=settings.is_production,
        samesite="strict",
        path="/api/v1/auth",
    )
    return TokenResponse(
        access_token=tokens.access_token,
        refresh_token=tokens.refresh_token,
        expires_in=tokens.expires_in,
    )


@router.post("/login", response_model=TokenResponse, summary="Exchange credentials for a JWT")
async def login(
    response: Response,
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
        context=_context(request, settings),
    )
    response.set_cookie(
        "refresh_token",
        tokens.refresh_token,
        max_age=settings.jwt_refresh_token_expire_days * 86400,
        httponly=True,
        secure=settings.is_production,
        samesite="strict",
        path="/api/v1/auth",
    )
    return TokenResponse(
        access_token=tokens.access_token,
        refresh_token=tokens.refresh_token,
        expires_in=tokens.expires_in,
    )


@router.post("/refresh", response_model=TokenResponse, summary="Rotate a refresh token")
async def refresh(
    response: Response,
    request: Request,
    payload: RefreshRequest | None = None,
    cookie_refresh_token: str | None = Cookie(default=None, alias="refresh_token"),
    session: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> TokenResponse:
    token_to_use = (payload.refresh_token if payload and payload.refresh_token else None) or cookie_refresh_token
    if not token_to_use:
        raise UnauthenticatedError("No refresh token provided in request or cookie.")

    tokens = await auth_service.refresh(
        session,
        refresh_token=token_to_use,
        settings=settings,
        context=_context(request, settings),
    )
    response.set_cookie(
        "refresh_token",
        tokens.refresh_token,
        max_age=settings.jwt_refresh_token_expire_days * 86400,
        httponly=True,
        secure=settings.is_production,
        samesite="strict",
        path="/api/v1/auth",
    )
    return TokenResponse(
        access_token=tokens.access_token,
        refresh_token=tokens.refresh_token,
        expires_in=tokens.expires_in,
    )


@router.post(
    "/logout",
    status_code=status.HTTP_204_NO_CONTENT,
    response_model=None,
    summary="Revoke the current session",
)
async def logout(
    response: Response,
    request: Request,
    payload: LogoutRequest | None = None,
    cookie_refresh_token: str | None = Cookie(default=None, alias="refresh_token"),
    principal: Principal | None = Depends(get_optional_principal),
    session: AsyncSession = Depends(get_db),
    redis_client: aioredis.Redis = Depends(get_redis),
    settings: Settings = Depends(get_settings),
) -> None:
    token_to_use = (payload.refresh_token if payload and payload.refresh_token else None) or cookie_refresh_token
    if principal is not None and principal.user_id is None:
        # An API key has no session to end; it is revoked via the org API-key endpoints.
        raise UnauthenticatedError("Logout requires a user session, not an API key.")
    if principal is None and not token_to_use:
        raise UnauthenticatedError("Present the access token or the refresh token to log out.")

    await auth_service.logout(
        session,
        redis_client,
        user_id=principal.user_id if principal else None,
        organization_id=principal.organization_id if principal else None,
        jti=principal.jti if principal else None,
        refresh_token=token_to_use,
        settings=settings,
        context=_context(request, settings),
    )
    response.delete_cookie(
        "refresh_token",
        path="/api/v1/auth",
        httponly=True,
        secure=settings.is_production,
        samesite="strict",
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
