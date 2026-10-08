"""Target-API auth config API contracts (`API.md §6.3`)."""

from __future__ import annotations

from typing import Any, Self

from pydantic import Field, model_validator

from app.models.enums import AuthScheme
from app.schemas.common import ResponseModel, StrictModel


class ApiKeyCredentials(StrictModel):
    """API key authentication secret."""

    api_key: str = Field(..., min_length=1, description="API key or token secret")

    @model_validator(mode="before")
    @classmethod
    def _normalize_key(cls, data: Any) -> Any:
        if isinstance(data, dict):
            if "api_key" not in data and "key" in data:
                data = dict(data)
                data["api_key"] = data.pop("key")
        return data


class BearerJwtCredentials(StrictModel):
    """Bearer JWT authentication secret."""

    token: str = Field(..., min_length=1, description="Bearer token or JWT")

    @model_validator(mode="before")
    @classmethod
    def _normalize_token(cls, data: Any) -> Any:
        if isinstance(data, dict):
            if "token" not in data:
                data = dict(data)
                if "bearer_token" in data:
                    data["token"] = data.pop("bearer_token")
                elif "jwt" in data:
                    data["token"] = data.pop("jwt")
                elif "access_token" in data:
                    data["token"] = data.pop("access_token")
        return data


class OAuth2ClientCredentials(StrictModel):
    """OAuth2 client credentials flow secrets."""

    client_id: str = Field(..., min_length=1, description="OAuth2 client ID")
    client_secret: str = Field(..., min_length=1, description="OAuth2 client secret")


class OAuth2AuthCodeCredentials(StrictModel):
    """OAuth2 authorization code flow secrets."""

    client_id: str = Field(..., min_length=1, description="OAuth2 client ID")
    client_secret: str = Field(..., min_length=1, description="OAuth2 client secret")
    access_token: str | None = Field(default=None, min_length=1, description="Current access token")
    refresh_token: str | None = Field(default=None, min_length=1, description="Refresh token")


class BasicAuthCredentials(StrictModel):
    """HTTP Basic authentication credentials."""

    username: str = Field(..., min_length=1, description="Basic authentication username")
    password: str = Field(..., min_length=1, description="Basic authentication password")


class HmacCredentials(StrictModel):
    """HMAC authentication signing secret."""

    secret: str = Field(..., min_length=1, description="HMAC shared secret key")
    key_id: str | None = Field(default=None, min_length=1, description="HMAC key ID")

    @model_validator(mode="before")
    @classmethod
    def _normalize_secret(cls, data: Any) -> Any:
        if isinstance(data, dict):
            if "secret" not in data:
                data = dict(data)
                if "secret_key" in data:
                    data["secret"] = data.pop("secret_key")
                elif "api_secret" in data:
                    data["secret"] = data.pop("api_secret")
        return data


type TargetCredentials = (
    ApiKeyCredentials
    | BearerJwtCredentials
    | OAuth2ClientCredentials
    | OAuth2AuthCodeCredentials
    | BasicAuthCredentials
    | HmacCredentials
)


class AuthConfigRequest(StrictModel):
    scheme: AuthScheme
    config_json: dict[str, Any] = Field(default_factory=dict)
    credentials: (
        TargetCredentials
        | dict[str, Any]
        | None
    ) = Field(
        default=None,
        description=(
            "Written directly to Vault and never persisted in PostgreSQL "
            "or returned in API responses. Validated strictly against the chosen auth scheme."
        ),
    )

    @model_validator(mode="after")
    def validate_credentials_for_scheme(self) -> Self:
        if self.credentials is None:
            return self

        if self.scheme == AuthScheme.NONE:
            if isinstance(self.credentials, dict) and not self.credentials:
                self.credentials = None
                return self
            raise ValueError("Credentials cannot be provided when auth scheme is 'none'.")

        raw_cred = (
            self.credentials.model_dump(exclude_none=True)
            if isinstance(self.credentials, StrictModel)
            else self.credentials
        )
        if not isinstance(raw_cred, dict):
            raise ValueError("Credentials must be a dictionary or structured credential object.")

        scheme_models: dict[AuthScheme, type[StrictModel]] = {
            AuthScheme.API_KEY: ApiKeyCredentials,
            AuthScheme.BEARER_JWT: BearerJwtCredentials,
            AuthScheme.OAUTH2_CLIENT_CREDENTIALS: OAuth2ClientCredentials,
            AuthScheme.OAUTH2_AUTH_CODE: OAuth2AuthCodeCredentials,
            AuthScheme.BASIC: BasicAuthCredentials,
            AuthScheme.HMAC: HmacCredentials,
        }

        target_model = scheme_models.get(self.scheme)
        if target_model:
            validated = target_model.model_validate(raw_cred)
            self.credentials = validated.model_dump(exclude_none=True)

        return self


class AuthConfigResponse(ResponseModel):
    scheme: str
    config_json: dict[str, Any]
    verified: bool = False
