"""Shared workflow state definitions across the multi-agent pipeline (`AI_Instruction.md §4`).

Represents working memory passed between agent nodes and checkpointed to PostgreSQL.
"""

from __future__ import annotations

from typing import Annotated, Any, TypedDict


def add_errors(left: list[str] | None, right: list[str] | None) -> list[str]:
    """Reducer that appends new errors while preserving previously accumulated errors."""
    res = list(left or [])
    if right:
        for err in right:
            if err and err not in res:
                res.append(err)
    return res


class WorkflowState(TypedDict, total=False):
    # Identifiers & routing
    project_id: str
    organization_id: str
    workflow_run_id: str
    stages: list[str]
    target_languages: list[str]
    environment: str | None

    # Input artifacts
    document_id: str | None
    raw_document_bytes: bytes | None
    document_filename: str | None
    format_hint: str | None
    spec_persisted: bool | None
    endpoints_discovered: int | None

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
    repair_attempts: list[dict[str, Any]]

    # Export stage
    export_types: list[str] | None
    exports: list[dict[str, Any]]
    github_repo_name: str | None
    github_org: str | None
    github_private: bool | None
    github_branch: str | None
    github_commit_message: str | None
    docker_image_name: str | None

    # Pipeline tracking
    current_node: str
    progress_percent: int
    status: str
    errors: Annotated[list[str], add_errors]
    total_tokens_used: int
    token_budget: int | None
    execution_mode: str | None
