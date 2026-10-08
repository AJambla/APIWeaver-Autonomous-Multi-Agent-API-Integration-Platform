"""Global application constants."""

from __future__ import annotations

DEFAULT_TARGET_LANGUAGES: list[str] = ["python", "node"]
SUPPORTED_LANGUAGES: list[str] = DEFAULT_TARGET_LANGUAGES
DEFAULT_WORKFLOW_STAGES: list[str] = ["plan", "generate", "test", "export"]
DEFAULT_BASE_URL: str = "http://localhost:8000"
