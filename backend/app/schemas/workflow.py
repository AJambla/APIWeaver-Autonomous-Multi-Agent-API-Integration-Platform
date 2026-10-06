"""Workflow execution API contracts (`API.md §6.4`)."""

from __future__ import annotations

import datetime
import uuid
from typing import Any, Literal

from pydantic import Field

from app.schemas.common import ResponseModel, StrictModel


class TriggerWorkflowRequest(StrictModel):
    stages: list[str] = Field(default_factory=lambda: ["plan", "generate", "test", "export"])
    target_languages: list[str] = Field(default_factory=lambda: ["python", "node"])
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
    notes: str | None = None


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
