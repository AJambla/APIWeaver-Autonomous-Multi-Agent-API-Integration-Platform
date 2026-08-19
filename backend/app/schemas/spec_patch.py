"""Spec Patch API contracts (`API.md §6.5`)."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import Field

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