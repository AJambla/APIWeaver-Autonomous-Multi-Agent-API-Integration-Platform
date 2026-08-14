"""Project schemas — `API.md §6.1`."""

from __future__ import annotations

import datetime
import uuid

from pydantic import Field

from app.models.enums import ProjectStatus
from app.schemas.common import ResponseModel, StrictModel


class CreateProjectRequest(StrictModel):
    name: str = Field(min_length=1, max_length=255)
    organization_id: uuid.UUID


class ProjectResponse(ResponseModel):
    id: uuid.UUID
    name: str
    status: str
    organization_id: uuid.UUID
    created_at: datetime.datetime
    updated_at: datetime.datetime
    archived_at: datetime.datetime | None = None


class ProjectSummaryResponse(ProjectResponse):
    """`GET /projects/{id}` — adds the summary counts named in `API.md §6.1`."""

    endpoint_count: int = 0
    last_run_status: str | None = None


class ProjectListFilters(StrictModel):
    status: ProjectStatus | None = None
    organization_id: uuid.UUID | None = None
