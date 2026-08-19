"""History & Versioning API contracts (`API.md §6.9`)."""

from __future__ import annotations

import datetime
import uuid

from app.schemas.common import Page, ResponseModel, StrictModel


class HistoryItemResponse(ResponseModel):
    id: uuid.UUID
    workflow_run_id: uuid.UUID
    status: str
    stages: list[str]
    started_at: datetime.datetime
    completed_at: datetime.datetime | None
    total_tokens: int


class HistoryResponse(Page[HistoryItemResponse]):
    pass


class VersionResponse(ResponseModel):
    id: uuid.UUID
    artifact_type: str
    version_number: int
    created_at: datetime.datetime
    diff_ref: str | None
    is_active: bool = False


class VersionRollbackRequest(StrictModel):
    confirm: bool = True


class VersionRollbackResponse(ResponseModel):
    id: uuid.UUID
    artifact_type: str
    version_number: int
    is_active: bool
    message: str