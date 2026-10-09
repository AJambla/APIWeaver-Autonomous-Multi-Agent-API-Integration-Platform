"""Spec Patch API contracts (`API.md §6.5`)."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import Field, field_validator

from app.schemas.common import ResponseModel, StrictModel


# Bounds mirror the columns (models/spec.py): over-length values used to reach the
# database and come back as a 500.
class EndpointParameterRequest(StrictModel):
    name: str = Field(min_length=1, max_length=255)
    location: Literal["path", "query", "header", "body"]
    type: str = Field(min_length=1, max_length=50)
    required: bool = False


class EndpointPatchRequest(StrictModel):
    method: str | None = None
    path: str | None = Field(default=None, min_length=1, max_length=1000)
    summary: str | None = Field(default=None, max_length=10_000)
    request_schema: dict[str, Any] | None = None
    response_schemas: dict[str, Any] | None = None
    deprecated: bool | None = None
    is_destructive: bool | None = None
    confidence_score: float | None = Field(default=None, ge=0, le=1)
    parameters: list[EndpointParameterRequest] | None = Field(default=None, max_length=200)

    @field_validator("parameters")
    @classmethod
    def _unique_parameters(
        cls, value: list[EndpointParameterRequest] | None
    ) -> list[EndpointParameterRequest] | None:
        if value is not None:
            keys = [(p.name, p.location) for p in value]
            if len(keys) != len(set(keys)):
                raise ValueError("parameters must be unique by (name, location)")
        return value

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