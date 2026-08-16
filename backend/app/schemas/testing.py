"""Testing API contracts (`API.md §6.7`)."""

from __future__ import annotations

import uuid
from typing import Any

from pydantic import Field

from app.schemas.common import ResponseModel, StrictModel


class TestRequest(StrictModel):
    """Request to trigger tests for a project."""

    environment: str = Field(default="sandbox", description="sandbox or live")
    endpoint_ids: list[uuid.UUID] | None = Field(default=None, description="Optional subset of endpoints to test.")


class TestRunResponse(ResponseModel):
    """Response from triggering a test run."""

    test_run_id: uuid.UUID
    status: str


class TestResultResponse(ResponseModel):
    """Response for a single test result."""

    id: uuid.UUID
    test_run_id: uuid.UUID
    endpoint_id: uuid.UUID | None = None
    status: str
    status_code: int | None = None
    latency_ms: int | None = None
    error: str | None = None
    response_snapshot: dict[str, Any] | None = None
    stack_trace: str | None = None


class RepairAttemptResponse(ResponseModel):
    """Response for a single repair attempt."""

    id: uuid.UUID
    test_result_id: uuid.UUID
    attempt_number: int
    failure_classification: str | None = None
    diff_summary: dict[str, Any] | None = None
    outcome: str | None = None


class TestRunSummaryResponse(ResponseModel):
    """Summary of a test run."""

    test_run_id: uuid.UUID
    status: str
    summary: dict[str, Any]
    results: list[TestResultResponse]
    repairs: list[RepairAttemptResponse] | None = None