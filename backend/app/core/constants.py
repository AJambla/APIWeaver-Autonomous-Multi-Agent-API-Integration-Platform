"""Global application constants."""

from __future__ import annotations

DEFAULT_TARGET_LANGUAGES: list[str] = ["python", "node"]
SUPPORTED_LANGUAGES: list[str] = DEFAULT_TARGET_LANGUAGES
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
