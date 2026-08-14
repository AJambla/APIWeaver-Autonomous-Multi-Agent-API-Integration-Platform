"""Document-ingestion API contracts."""

from __future__ import annotations

import uuid
from typing import Any

from pydantic import Field

from app.schemas.common import ResponseModel


class UploadResponse(ResponseModel):
    document_id: uuid.UUID
    status: str = "processing"
    workflow_run_id: uuid.UUID | None = None
    api_spec_id: uuid.UUID | None = None
    endpoints_discovered: int | None = None


class EndpointResponse(ResponseModel):
    id: uuid.UUID
    method: str
    path: str
    summary: str | None
    deprecated: bool
    confidence_score: float | None = None


class SpecResponse(ResponseModel):
    id: uuid.UUID
    title: str | None
    base_url: str | None
    raw_normalized: dict[str, Any]
    confidence_score: float | None = None


class EndpointFilters(ResponseModel):
    method: str | None = None
    deprecated: bool | None = None
    confidence_min: float | None = Field(default=None, ge=0, le=1)
