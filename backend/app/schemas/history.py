"""History and versioning API contracts (`API.md §6.9`)."""

from __future__ import annotations

import datetime
import uuid
from typing import Any

from app.schemas.common import ResponseModel, StrictModel


class WorkflowRunSummary(ResponseModel):
    """Lightweight workflow run for history listing."""
    id: uuid.UUID
    status: str
    started_at: datetime.datetime | None
    completed_at: datetime.datetime | None
    total_tokens_used: int
    estimated_cost_usd: float


class HistoryResponse(ResponseModel):
    data: list[WorkflowRunSummary]
    pagination: dict[str, Any]


class ArtifactVersionResponse(ResponseModel):
    id: uuid.UUID
    artifact_type: str
    version_number: int
    diff_ref: str | None
    created_at: datetime.datetime


class ArtifactVersionsResponse(ResponseModel):
    data: list[ArtifactVersionResponse]
    pagination: dict[str, Any]


class RollbackRequest(StrictModel):
    """Empty request body for rollback - all info is in path params."""


class RollbackResponse(ResponseModel):
    version_id: uuid.UUID
    rolled_back_from: uuid.UUID
    status: str
    created_at: datetime.datetime


class HistoryFilters(StrictModel):
    status: str | None = None
    start_date: datetime.datetime | None = None
    end_date: datetime.datetime | None = None