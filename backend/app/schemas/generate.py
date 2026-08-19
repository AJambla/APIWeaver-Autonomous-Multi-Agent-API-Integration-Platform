"""Code generation API contracts (`API.md §6.6`)."""

from __future__ import annotations

import uuid

from pydantic import Field

from app.schemas.common import ResponseModel, StrictModel


class GenerateRequest(StrictModel):
    """Request to trigger code generation for a project."""

    stages: list[str] = Field(default_factory=lambda: ["plan", "generate", "test", "export"])
    target_languages: list[str] = Field(default_factory=lambda: ["python", "node"])
    export_types: list[str] | None = Field(default=None, description="Subset of exports to run.")


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


class FileContentResponse(ResponseModel):
    """Response containing the content of a generated file."""

    file_path: str
    content: str
    language: str | None = None
    file_type: str | None = None