"""Shared workflow state definitions across the multi-agent pipeline (`AI_Instruction.md §4`).

Represents working memory passed between agent nodes and checkpointed to PostgreSQL.
"""

from __future__ import annotations

from typing import Any, TypedDict


class WorkflowState(TypedDict, total=False):
    # Identifiers & routing
    project_id: str
    organization_id: str
    workflow_run_id: str
    stages: list[str]
    target_languages: list[str]

    # Input artifacts
    document_id: str | None
    raw_document_bytes: bytes | None
    document_filename: str | None
    format_hint: str | None

    # Agent intermediate outputs
    normalized_spec: dict[str, Any] | None
    spec_confidence_score: float | None
    execution_plan: dict[str, Any] | None
    plan_approved: bool | None
    approval_notes: str | None

    # Code generation & testing outputs
    generated_files: list[dict[str, Any]]
    test_suite: list[dict[str, Any]]
    test_run_summary: dict[str, Any] | None

    # Pipeline tracking
    current_node: str
    progress_percent: int
    status: str
    errors: list[str]
    total_tokens_used: int
