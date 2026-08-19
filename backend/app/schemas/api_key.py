"""Organization API Key management API contracts (`API.md §1`, `Security.md §5`)."""

from __future__ import annotations

import datetime
import uuid

from pydantic import Field

from app.schemas.common import Page, ResponseModel, StrictModel


class APIKeyCreateRequest(StrictModel):
    name: str = Field(min_length=1, max_length=255)
    project_id: uuid.UUID | None = None
    expires_in_days: int | None = Field(default=None, ge=1, le=3650)


class APIKeyCreateResponse(ResponseModel):
    id: uuid.UUID
    key: str
    prefix: str
    name: str
    project_id: uuid.UUID | None
    expires_at: datetime.datetime | None


class APIKeyListResponse(ResponseModel):
    id: uuid.UUID
    prefix: str
    name: str
    project_id: uuid.UUID | None
    created_at: datetime.datetime
    expires_at: datetime.datetime | None
    revoked_at: datetime.datetime | None


class APIKeyListPage(Page[APIKeyListResponse]):
    pass