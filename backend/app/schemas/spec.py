"""Spec-related schemas for patch operations."""

from __future__ import annotations

import decimal
import uuid
from typing import Any

from pydantic import Field

from app.schemas.common import ResponseModel, StrictModel


class ParameterUpdate(StrictModel):
    """Update for an endpoint parameter."""
    name: str | None = None
    location: str | None = None
    type: str | None = None
    required: bool | None = None


class EndpointPatchRequest(StrictModel):
    """Request body for patching an endpoint."""
    path: str | None = None
    method: str | None = None
    summary: str | None = None
    request_schema: dict[str, Any] | None = None
    response_schemas: dict[str, Any] | None = None
    parameters: list[ParameterUpdate] | None = None
    confidence_score: decimal.Decimal | None = Field(default=None, ge=0, le=1)


class EndpointPatchResponse(ResponseModel):
    """Response after patching an endpoint."""
    endpoint_id: uuid.UUID
    updated_fields: list[str]
    confidence_score: float
