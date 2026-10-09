"""Workflow execution API contracts (`API.md §6.4`)."""

from __future__ import annotations

import datetime
import uuid
from typing import Any, Literal

from pydantic import Field

from app.core.constants import (
    DEFAULT_TARGET_LANGUAGES,
    DEFAULT_WORKFLOW_STAGES,
    TargetLanguage,
    WorkflowStage,
)
from app.schemas.common import ResponseModel, StrictModel


class TriggerWorkflowRequest(StrictModel):
    stages: list[WorkflowStage] = Field(
        default_factory=lambda: list(DEFAULT_WORKFLOW_STAGES), min_length=1, max_length=5
    )
    target_languages: list[TargetLanguage] = Field(
        default_factory=lambda: list(DEFAULT_TARGET_LANGUAGES), min_length=1, max_length=2
    )
    execution_mode: Literal["sync", "async"] = "sync"


class TriggerWorkflowResponse(ResponseModel):
    workflow_run_id: uuid.UUID
    status: str


class WorkflowRunResponse(ResponseModel):
    id: uuid.UUID
    status: str
    current_node: str | None = None
    progress_percent: int = 0
    started_at: datetime.datetime | None = None
    completed_at: datetime.datetime | None = None
    total_tokens_used: int = 0


class ApproveWorkflowRequest(StrictModel):
    approved: bool = True
    notes: str | None = Field(default=None, max_length=5000)
    target_languages: list[TargetLanguage] | None = Field(default=None, min_length=1, max_length=2)


class ApproveWorkflowResponse(ResponseModel):
    workflow_run_id: uuid.UUID
    status: str
    approved: bool


class ToolCallResponse(ResponseModel):
    id: int
    agent_event_id: int
    tool_name: str
    arguments: dict[str, Any] | None = None
    result: dict[str, Any] | None = None
    duration_ms: int | None = None
