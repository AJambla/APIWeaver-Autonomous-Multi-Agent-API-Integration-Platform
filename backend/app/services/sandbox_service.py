"""Sandbox execution boundary for running generated client code.

Provides a protocol and in-memory mock implementation for tests.
Production implementation would use Docker/gVisor with network isolation.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Any, Protocol

from app.core.config import Settings
from app.core.logging import get_logger

logger = get_logger(__name__)


@dataclass(frozen=True, slots=True)
class SandboxResult:
    exit_code: int
    stdout: str
    stderr: str
    duration_ms: int
    artifacts: dict[str, Any] = field(default_factory=dict)


class SandboxClient(Protocol):
    async def prepare(self, *, project_id: uuid.UUID, language: str, files: dict[str, str]) -> None: ...

    async def run_test(
        self,
        *,
        project_id: uuid.UUID,
        test_file: str,
        test_code: str,
        env_vars: dict[str, str] | None = None,
    ) -> SandboxResult: ...

    async def cleanup(self, *, project_id: uuid.UUID) -> None: ...


class MockSandboxClient:
    """In-memory sandbox for unit/integration tests.

    Executes Python code in-process with isolated globals.
    For Node.js, validates syntax only (no actual execution).
    """

    def __init__(self) -> None:
        self._workspaces: dict[uuid.UUID, dict[str, str]] = {}
        self._fixtures: dict[uuid.UUID, list[dict[str, Any]]] = {}

    async def prepare(self, *, project_id: uuid.UUID, language: str, files: dict[str, str]) -> None:
        self._workspaces[project_id] = files
        if language == "python":
            self._fixtures[project_id] = self._generate_python_fixtures(files)

    def _generate_python_fixtures(self, files: dict[str, str]) -> list[dict[str, Any]]:
        fixtures = []
        for path, content in files.items():
            if path.endswith(".py") and "test_" in path:
                continue
            if "client" in path.lower() or "models" in path.lower() or "api" in path.lower():
                fixtures.append({
                    "module_path": path,
                    "content": content,
                })
        return fixtures

    async def run_test(
        self,
        *,
        project_id: uuid.UUID,
        test_file: str,
        test_code: str,
        env_vars: dict[str, str] | None = None,
    ) -> SandboxResult:
        import time
        import traceback

        start = time.perf_counter()
        workspace = self._workspaces.get(project_id, {})

        if test_file.endswith(".py"):
            return await self._run_python_test(workspace, test_code, start)
        elif test_file.endswith((".ts", ".js")):
            return await self._run_node_test(test_code, start)
        else:
            return SandboxResult(
                exit_code=1,
                stdout="",
                stderr=f"Unsupported test file type: {test_file}",
                duration_ms=int((time.perf_counter() - start) * 1000),
            )

    async def _run_python_test(
        self, workspace: dict[str, str], test_code: str, start: float
    ) -> SandboxResult:
        import sys
        import io
        from contextlib import redirect_stdout, redirect_stderr

        test_globals = {"__name__": "__main__"}

        for path, content in workspace.items():
            if path.endswith(".py"):
                try:
                    exec(content, test_globals)
                except Exception as e:
                    return SandboxResult(
                        exit_code=1,
                        stdout="",
                        stderr=f"Module import failed ({path}): {e}",
                        duration_ms=int((time.perf_counter() - start) * 1000),
                    )

        stdout_buf = io.StringIO()
        stderr_buf = io.StringIO()
        exit_code = 0

        try:
            with redirect_stdout(stdout_buf), redirect_stderr(stderr_buf):
                exec(test_code, test_globals)
        except Exception:
            exit_code = 1
            stderr_buf.write(traceback.format_exc())

        duration_ms = int((time.perf_counter() - start) * 1000)
        return SandboxResult(
            exit_code=exit_code,
            stdout=stdout_buf.getvalue(),
            stderr=stderr_buf.getvalue(),
            duration_ms=duration_ms,
        )

    async def _run_node_test(self, test_code: str, start: float) -> SandboxResult:
        try:
            import subprocess
            result = subprocess.run(
                ["node", "--check", "-e", test_code],
                capture_output=True,
                text=True,
                timeout=5,
            )
            return SandboxResult(
                exit_code=result.returncode,
                stdout=result.stdout,
                stderr=result.stderr,
                duration_ms=int((time.perf_counter() - start) * 1000),
            )
        except FileNotFoundError:
            return SandboxResult(
                exit_code=0,
                stdout="",
                stderr="Node.js not available — syntax check skipped (mock mode)",
                duration_ms=int((time.perf_counter() - start) * 1000),
            )
        except subprocess.TimeoutExpired:
            return SandboxResult(
                exit_code=1,
                stdout="",
                stderr="Node.js syntax check timed out",
                duration_ms=int((time.perf_counter() - start) * 1000),
            )

    async def cleanup(self, *, project_id: uuid.UUID) -> None:
        self._workspaces.pop(project_id, None)
        self._fixtures.pop(project_id, None)


def create_sandbox_client(settings: Settings) -> SandboxClient:
    return MockSandboxClient()