"""Auth request/response schemas — `API.md §1`."""

from __future__ import annotations

import uuid

from pydantic import EmailStr, Field, field_validator

from app.core.security import MIN_PASSWORD_LENGTH
from app.schemas.common import ResponseModel, StrictModel


class RegisterRequest(StrictModel):
    email: EmailStr
    password: str = Field(min_length=MIN_PASSWORD_LENGTH, max_length=256)
    full_name: str = Field(min_length=1, max_length=255)
    # Creating an org on signup keeps the first user from landing with no tenant. An
    # invite-based join flow arrives with the org-management endpoints.
    organization_name: str = Field(min_length=1, max_length=255)

    @field_validator("password")
    @classmethod
    def _reject_trivial(cls, value: str) -> str:
        """Cheap local checks only.

        The breached-password corpus check required by `Security.md §8 (A07)` needs an
        external service (k-anonymity range query against a breach API) and lands with
        the signup-hardening pass; this is not a substitute for it.
        """
        if value.strip() != value:
            raise ValueError("password must not begin or end with whitespace")
        if len(set(value)) < 5:
            raise ValueError("password is too repetitive")
        return value


class LoginRequest(StrictModel):
    email: EmailStr
    password: str = Field(max_length=256)


class RefreshRequest(StrictModel):
    refresh_token: str = Field(min_length=1, max_length=512)


class LogoutRequest(StrictModel):
    # Optional: logout denylists the access token's jti regardless, but passing the
    # refresh token also revokes its whole family so no descendant survives.
    refresh_token: str | None = Field(default=None, max_length=512)


class TokenResponse(ResponseModel):
    """Exactly the shape in `API.md §1`."""

    access_token: str
    refresh_token: str
    expires_in: int
    token_type: str = "bearer"


class UserResponse(ResponseModel):
    id: uuid.UUID
    email: EmailStr
    full_name: str
    mfa_enabled: bool


class MembershipResponse(ResponseModel):
    organization_id: uuid.UUID
    organization_name: str
    role: str


class MeResponse(ResponseModel):
    user: UserResponse
    organizations: list[MembershipResponse]
