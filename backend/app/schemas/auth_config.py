"""Target-API auth config API contracts (`API.md §6.3`)."""

from __future__ import annotations

from typing import Any

from pydantic import Field

from app.models.enums import AuthScheme
from app.schemas.common import ResponseModel, StrictModel


class AuthConfigRequest(StrictModel):
    scheme: AuthScheme
    config_json: dict[str, Any] = Field(default_factory=dict)
    credentials: dict[str, Any] | None = Field(
        default=None,
        description=(
            "Written directly to Vault and never persisted in PostgreSQL "
            "or returned in API responses."
        ),
    )


class AuthConfigResponse(ResponseModel):
    scheme: str
    config_json: dict[str, Any]
    verified: bool = False
