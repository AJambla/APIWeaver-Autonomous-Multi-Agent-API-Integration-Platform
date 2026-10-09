"""Spec Patch API contracts (`API.md §6.5`)."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import Field, field_validator

from app.schemas.common import ResponseModel, StrictModel


class EndpointParameterRequest(StrictModel):
    name: str
    location: Literal["path", "query", "header", "body"]
    type: str
    required: bool = False


class EndpointPatchRequest(StrictModel):
    method: str | None = None
    path: str | None = None
    summary: str | None = None
    request_schema: dict[str, Any] | None = None
    response_schemas: dict[str, Any] | None = None
    deprecated: bool | None = None
    is_destructive: bool | None = None
    confidence_score: float | None = Field(default=None, ge=0, le=1)
    parameters: list[EndpointParameterRequest] | None = None

    @field_validator("method")
    @classmethod
    def _known_method(cls, value: str | None) -> str | None:
        if value is None:
            return None
        upper = value.upper()
        if upper not in {"GET", "POST", "PUT", "PATCH", "DELETE"}:
            raise ValueError("method must be one of GET, POST, PUT, PATCH, DELETE")
        return upper

    @field_validator("path")
    @classmethod
    def _absolute_path(cls, value: str | None) -> str | None:
        if value is not None and not value.startswith("/"):
            raise ValueError("path must start with '/'")
        return value


class EndpointResponse(ResponseModel):
    id: str
    method: str
    path: str
    summary: str | None
    request_schema: dict[str, Any] | None
    response_schemas: dict[str, Any]
    deprecated: bool
    is_destructive: bool
    confidence_score: float | None