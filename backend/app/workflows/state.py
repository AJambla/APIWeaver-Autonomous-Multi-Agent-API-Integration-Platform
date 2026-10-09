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


def merge_generated_files(
    left: list[dict[str, Any]] | None,
    right: list[dict[str, Any]] | None,
) -> list[dict[str, Any]]:
    """Reducer that merges generated files by path so updates replace existing files."""
    if not right:
        return list(left or [])
    if not left:
        return list(right)
    by_path: dict[str, dict[str, Any]] = {}
    for f in left:
        path = str(f.get("path") or f.get("filename") or id(f))
        by_path[path] = f
    for f in right:
        path = str(f.get("path") or f.get("filename") or id(f))
        by_path[path] = f
    return list(by_path.values())


def merge_repair_attempts(
    left: list[dict[str, Any]] | None,
    right: list[dict[str, Any]] | None,
) -> list[dict[str, Any]]:
    """Reducer that merges repair attempts without duplicating existing ones."""
    if not right:
        return list(left or [])
    if not left:
        return list(right)
    if len(right) >= len(left) and right[: len(left)] == left:
        return list(right)
    res = list(left)
    for att in right:
        if att not in res:
            res.append(att)
    return res


def merge_test_suite(
    left: list[dict[str, Any]] | None,
    right: list[dict[str, Any]] | None,
) -> list[dict[str, Any]]:
    """Reducer that updates test suite results by test name or appends new tests."""
    if not right:
        return list(left or [])
    if not left:
        return list(right)
    by_name: dict[str, dict[str, Any]] = {}
    for t in left:
        key = str(t.get("name") or t.get("test_name") or id(t))
        by_name[key] = t
    for t in right:
        key = str(t.get("name") or t.get("test_name") or id(t))
        by_name[key] = t
    return list(by_name.values())


def merge_exports(
    left: list[dict[str, Any]] | None,
    right: list[dict[str, Any]] | None,
) -> list[dict[str, Any]]:
    """Reducer that merges export artifacts by type so reruns/updates do not duplicate."""
    if not right:
        return list(left or [])
    if not left:
        return list(right)
    by_type: dict[str, dict[str, Any]] = {}
    for exp in left:
        key = str(exp.get("type") or id(exp))
        by_type[key] = exp
    for exp in right:
        key = str(exp.get("type") or id(exp))
        by_type[key] = exp
    return list(by_type.values())


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
    # Object-storage key of the uploaded document; the worker reloads bytes from here.
    document_s3_key: str | None
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
    generated_files: Annotated[list[dict[str, Any]], merge_generated_files]
    test_suite: Annotated[list[dict[str, Any]], merge_test_suite]
    test_run_summary: dict[str, Any] | None
    repair_attempts: Annotated[list[dict[str, Any]], merge_repair_attempts]

    # Export stage
    export_types: list[str] | None
    exports: Annotated[list[dict[str, Any]], merge_exports]
    github_repo_name: str | None
    github_org: str | None
    github_private: bool | None
    github_branch: str | None
    github_commit_message: str | None
    docker_image_name: str | None
    # Set by `/approve` when an owner exports despite exhausted repairs.
    export_override_approved: bool | None
    # Set by `POST /export`, which creates one Export row per type up front and finalizes
    # them after the run (dispatch.apply_post_run); the export node must not add its own.
    export_rows_managed: bool | None

    # Pipeline tracking
    current_node: str
    progress_percent: int
    status: str
    errors: Annotated[list[str], add_errors]
    total_tokens_used: int
    token_budget: int | None
