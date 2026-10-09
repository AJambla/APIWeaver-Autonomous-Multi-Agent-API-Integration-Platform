"""Document-ingestion API contracts."""

from __future__ import annotations

import uuid
from typing import Any

from pydantic import Field

from app.schemas.common import ResponseModel, StrictModel


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
    operation_id: str | None = None
    summary: str | None
    deprecated: bool
    confidence_score: float | None = None


class SpecResponse(ResponseModel):
    id: uuid.UUID
    title: str | None
    base_url: str | None
    raw_normalized: dict[str, Any]
    confidence_score: float | None = None


class FetchSpecRequest(StrictModel):
    """`POST /projects/{id}/fetch-spec`: import a specification from a URL."""

    url: str = Field(min_length=8, max_length=2048, pattern=r"^https?://")


class FetchSpecResponse(ResponseModel):
    content: str
    content_type: str | None = None
    size_bytes: int
