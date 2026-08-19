"""API key management API contracts (`API.md §1`)."""

from __future__ import annotations

import datetime
import uuid

from pydantic import Field

from app.schemas.common import ResponseModel, StrictModel


class CreateAPIKeyRequest(StrictModel):
    """Request body for creating an API key."""
    name: str = Field(max_length=255)
    project_id: uuid.UUID | None = None
    expires_at: datetime.datetime | None = None
    live: bool = Field(default=True, description="True for apw_live_, False for apw_test_")


class APIKeyResponse(ResponseModel):
    """API key returned on creation (includes the full key)."""
    id: uuid.UUID
    name: str
    key: str = Field(description="Full API key - shown only once")
    key_prefix: str
    project_id: uuid.UUID | None
    created_at: datetime.datetime
    expires_at: datetime.datetime | None


class APIKeyListItem(ResponseModel):
    """API key in list (does not include full key)."""
    id: uuid.UUID
    name: str
    key_prefix: str
    project_id: uuid.UUID | None
    created_at: datetime.datetime
    expires_at: datetime.datetime | None
    is_active: bool


class APIKeyListResponse(ResponseModel):
    data: list[APIKeyListItem]
