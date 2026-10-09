"""Code generation API contracts (`API.md §6.6`)."""

from __future__ import annotations

import uuid
from typing import cast

from pydantic import Field

from app.core.constants import (
    DEFAULT_TARGET_LANGUAGES,
    DEFAULT_WORKFLOW_STAGES,
    TargetLanguage,
    WorkflowStage,
)
from app.models.enums import ExportType
from app.schemas.common import ResponseModel, StrictModel


class GenerateRequest(StrictModel):
    """Request to trigger code generation for a project."""

    stages: list[WorkflowStage] = Field(
        default_factory=lambda: cast(list[WorkflowStage], list(DEFAULT_WORKFLOW_STAGES)), min_length=1, max_length=5
    )
    target_languages: list[TargetLanguage] = Field(
        default_factory=lambda: cast(list[TargetLanguage], list(DEFAULT_TARGET_LANGUAGES)), min_length=1, max_length=2
    )
    export_types: list[ExportType] | None = Field(
        default=None, max_length=10, description="Subset of exports to run."
    )


class GenerateResponse(ResponseModel):
    """Response from triggering code generation."""

    workflow_run_id: uuid.UUID
    status: str


class FileResponse(ResponseModel):
    """Metadata for a single generated file."""

    id: uuid.UUID
    project_id: uuid.UUID
    file_path: str
    language: str | None = None
    file_type: str | None = None
    size_bytes: int = 0
    created_at: str | None = None
    code_generation_run_id: uuid.UUID | None = None


class FileContentResponse(ResponseModel):
    """Response containing the content of a generated file."""

    file_path: str
    content: str
    language: str | None = None
    file_type: str | None = None