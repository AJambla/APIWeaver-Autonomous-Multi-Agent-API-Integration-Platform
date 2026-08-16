"""Export API contracts (`API.md §6.8`)."""

from __future__ import annotations

import uuid
from typing import Any

from pydantic import Field

from app.schemas.common import ResponseModel, StrictModel


class ExportRequest(StrictModel):
    """Request to trigger exports for a project."""

    export_types: list[str] = Field(default_factory=lambda: ["sdk", "client", "docker", "github", "mcp", "docs", "cicd"])
    github_repo_name: str | None = Field(default=None, description="Full repo name for GitHub export, e.g. myorg/stripe-integration")
    docker_image_name: str | None = Field(default=None, description="Docker image name for Docker export")


class ExportResponse(ResponseModel):
    """Response from triggering exports."""

    export_id: uuid.UUID
    artifacts: list[dict[str, Any]]


class MCPExportResponse(ResponseModel):
    """Response for MCP export."""

    mcp_manifest_url: str
    tools_generated: int
    flagged_destructive: int


class ExportArtifactResponse(ResponseModel):
    """Metadata for a single export artifact."""

    id: uuid.UUID
    export_id: uuid.UUID
    export_type: str
    artifact_name: str
    s3_key: str
    metadata: dict[str, Any] | None = None
    created_at: str | None = None