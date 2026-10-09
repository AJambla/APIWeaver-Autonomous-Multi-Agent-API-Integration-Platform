"""Global application constants."""

from __future__ import annotations

from typing import Literal

DEFAULT_TARGET_LANGUAGES: list[str] = ["python", "node"]

# Everything except `github`: pushing to a repository is outward-facing and must be an
# explicit choice, never the side effect of a run that named no export types.
DEFAULT_EXPORT_TYPES: list[str] = ["sdk", "client", "fastapi", "docker", "mcp", "docs", "cicd"]
DEFAULT_WORKFLOW_STAGES: list[str] = ["plan", "generate", "test", "export"]
DEFAULT_BASE_URL: str = "http://localhost:8000"

DEFAULT_WORKFLOW_NODE_PROGRESS: dict[str, int] = {
    "doc_node": 15,
    "doc_agent": 15,
    "planner_node": 30,
    "planner_agent": 30,
    "approval_gate": 30,
    "approval_gate_node": 30,
    "codegen_node": 60,
    "code_agent": 60,
    "test_node": 75,
    "test_agent": 75,
    "repair_node": 80,
    "repair_agent": 80,
    "export_node": 95,
    "export_agent": 95,
    "completed": 100,
    "finalize": 100,
    "finalize_node": 100,
}

# The values the pipeline router understands (langgraph_pipeline.route_from_start) and the
# languages there are templates and sandboxes for. Request schemas use these so a typo like
# "tests" is a 422 instead of a run that routes straight to finalize and reports COMPLETED
# having done nothing.
WorkflowStage = Literal["doc", "plan", "generate", "test", "export"]
TargetLanguage = Literal["python", "node"]
