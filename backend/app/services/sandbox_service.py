"""Sandbox execution boundary for running generated client code.

Provides a protocol, an in-memory mock implementation for tests, and a
Docker-backed executor that enforces per-run resource quotas.
"""

from __future__ import annotations

import asyncio
import json
import shutil
import tempfile
import time
import traceback
import uuid
from dataclasses import dataclass, field
from pathlib import Path
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
        import io
        from contextlib import redirect_stderr, redirect_stdout

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


# Marker the sandbox runner prints before its single-line JSON result. The host
# scans stdout backwards for this prefix so client-side prints can't corrupt
# result parsing.
_RESULT_PREFIX = "APIWEAVER_RESULT:"

# Run as nobody inside the container: generated code is untrusted.
_DOCKER_USER = "65534:65534"

RUNNER_SOURCE = '''"""Sandbox runner: executes one generated-client call (stdlib only)."""
import asyncio
import importlib
import json
import os
import sys
import time
import traceback


async def _main() -> int:
    payload_path = os.environ.get("APIWEAVER_PAYLOAD_PATH", "/sandbox/payload.json")
    with open(payload_path, "r", encoding="utf-8") as handle:
        payload = json.load(handle)

    module = importlib.import_module(payload["module_name"])
    client_class = None
    for attr_name in dir(module):
        attr = getattr(module, attr_name)
        if isinstance(attr, type) and "Client" in attr_name:
            client_class = attr
            break
    if client_class is None:
        raise RuntimeError(f"no client class found in module {payload['module_name']}")

    # Credentials arrive via the APIWEAVER_API_KEY env var (never a file inside
    # the container — Security.md §7); payload["api_key"] stays as a secondary
    # source for hosts that pre-date the env-var channel.
    client = client_class(
        base_url=payload.get("base_url"),
        api_key=os.environ.get("APIWEAVER_API_KEY") or payload.get("api_key"),
    )

    operation = getattr(client, payload["op_id"], None)
    if operation is None:
        raise RuntimeError(f"method {payload['op_id']} not found on client")

    request = payload.get("request") or {}
    params = request.get("params") or {}
    body = request.get("body")

    started = time.perf_counter()
    response = await operation(**params, body=body)
    latency_ms = int((time.perf_counter() - started) * 1000)

    result = {
        "status": "passed",
        "status_code": None,
        "latency_ms": latency_ms,
        "response_snapshot": None,
        "error": None,
        "stack_trace": None,
    }
    try:
        result["status_code"] = response.status_code
    except AttributeError:
        pass
    try:
        snapshot = {"status_code": response.status_code, "headers": dict(response.headers)}
        if hasattr(response, "json"):
            try:
                snapshot["body"] = response.json()
            except Exception:
                snapshot["body"] = getattr(response, "text", None)
        result["response_snapshot"] = snapshot
    except Exception as snapshot_error:
        result["response_snapshot"] = {"snapshot_error": str(snapshot_error)}

    expected_status = payload.get("expected_status")
    if expected_status is not None and response.status_code != expected_status:
        result["status"] = "failed"
        result["error"] = f"Expected status {expected_status}, got {response.status_code}"

    close = getattr(client, "close", None)
    if close is not None:
        await close()

    print("APIWEAVER_RESULT:" + json.dumps(result))
    return 0


def _run() -> int:
    try:
        return asyncio.run(_main())
    except Exception:
        failure = traceback.format_exc()
        print("APIWEAVER_RESULT:" + json.dumps({
            "status": "failed",
            "status_code": None,
            "latency_ms": 0,
            "response_snapshot": None,
            "error": failure,
            "stack_trace": failure,
        }))
        return 1


if __name__ == "__main__":
    sys.exit(_run())
'''


def _cpu_to_nano_cpus(raw: str) -> int:
    """Convert a quota string ("0.5", "500m", "1") to Docker nano_cpus."""
    text = str(raw).strip()
    if text.endswith("m"):
        return int(float(text[:-1]) * 1_000_000)
    return int(float(text) * 1_000_000_000)


def _memory_to_bytes(raw: str) -> int:
    """Convert a quota string ("512Ki", "256Mi", "1Gi", bare bytes) to bytes."""
    text = str(raw).strip()
    for suffix, multiplier in (("Ki", 2**10), ("Mi", 2**20), ("Gi", 2**30)):
        if text.endswith(suffix):
            return int(float(text[: -len(suffix)]) * multiplier)
    return int(float(text))


def _parse_runner_result(output: str) -> dict[str, Any] | None:
    """Find the last sentinel-prefixed line in runner stdout."""
    for line in reversed(output.splitlines()):
        if line.startswith(_RESULT_PREFIX):
            return json.loads(line[len(_RESULT_PREFIX) :])
    return None


class DockerSandboxExecutor:
    """Runs generated clients in a quota-enforced Docker container.

    One short-lived container per execute_test call: the staged workspace is
    bound read-only, capabilities are dropped, the network is disabled unless
    explicitly enabled, and a hard wall-clock timeout kills hung containers
    (a hung sandbox is recorded as a failed test, never an outage —
    Architecture.md §277/§314).
    """

    def __init__(self, settings: Settings, *, docker_client: Any | None = None) -> None:
        self._settings = settings
        self._docker_client = docker_client
        self._workspace: Path | None = None
        self._client_module: str | None = None
        self._base_url: str | None = None
        self._api_key: str | None = None

    def _get_docker_client(self) -> Any:
        if self._docker_client is None:
            import docker

            self._docker_client = docker.from_env()
        return self._docker_client

    async def load(
        self,
        *,
        project_id: Any,
        files: dict[str, str],
        base_url: str | None = None,
        api_key: str | None = None,
    ) -> None:
        """Stage generated files into a host workspace the container will bind."""
        self._base_url = base_url
        self._api_key = api_key
        workspace = Path(tempfile.mkdtemp(prefix=f"apiweaver-sandbox-{project_id or 'run'}-"))
        for rel_path, content in files.items():
            target = workspace / rel_path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content, encoding="utf-8")

        client_module = None
        for rel_path in files:
            normalized = rel_path.replace("\\", "/").lower()
            if normalized.endswith(".py") and "client" in normalized:
                client_module = (
                    rel_path.replace("\\", "/").removesuffix(".py").replace("/", ".")
                )
                break

        (workspace / "runner.py").write_text(RUNNER_SOURCE, encoding="utf-8")
        self._workspace = workspace
        self._client_module = client_module

    async def execute_test(self, endpoint: dict[str, Any], fixture: dict[str, Any]) -> dict[str, Any]:
        """Run one endpoint test in a fresh container; returns the mock result shape."""
        method = endpoint.get("method", "GET").upper()
        path = endpoint.get("path", "/")

        result = {
            "endpoint_id": endpoint.get("id"),
            "method": method,
            "path": path,
            "status": "failed",
            "status_code": None,
            "latency_ms": 0,
            "response_snapshot": None,
            "error": None,
            "stack_trace": None,
        }

        if self._workspace is None or self._client_module is None:
            result["error"] = "Sandbox workspace not prepared"
            return result

        op_id = endpoint.get(
            "operationId",
            path.replace("/", "_").replace("{", "").replace("}", "").replace("-", "_"),
        )
        request_data = fixture.get("request", {}) or {}
        payload = {
            "module_name": self._client_module,
            "op_id": op_id,
            "request": {
                "params": request_data.get("params", {}) or {},
                "body": request_data.get("body"),
            },
            "expected_status": fixture.get("expected_status", 200),
            "base_url": self._base_url,
        }
        (self._workspace / "payload.json").write_text(json.dumps(payload), encoding="utf-8")

        docker_client = self._get_docker_client()
        started = time.perf_counter()
        container = None
        try:
            environment = {
                "PYTHONDONTWRITEBYTECODE": "1",
                "APIWEAVER_PAYLOAD_PATH": "/sandbox/payload.json",
            }
            if self._api_key:
                # Runtime secret injection (Security.md §7): the credential travels
                # in the container environment, never inside a file.
                environment["APIWEAVER_API_KEY"] = self._api_key
            run_kwargs = dict(
                image=self._settings.sandbox_image,
                command=["python", "/sandbox/runner.py"],
                environment=environment,
                binds={str(self._workspace): {"bind": "/sandbox", "mode": "ro"}},
                tmpfs={"/tmp": "size=64m"},
                nano_cpus=_cpu_to_nano_cpus(self._settings.sandbox_max_cpu),
                mem_limit=_memory_to_bytes(self._settings.sandbox_max_memory),
                pids_limit=self._settings.sandbox_pids_limit,
                cap_drop=["ALL"],
                user=_DOCKER_USER,
                network_disabled=not self._settings.sandbox_network_enabled,
                detach=True,
            )
            container = await asyncio.to_thread(docker_client.containers.run, **run_kwargs)
            try:
                wait_result = await asyncio.wait_for(
                    asyncio.to_thread(container.wait),
                    timeout=self._settings.sandbox_timeout_seconds,
                )
            except asyncio.TimeoutError:
                await asyncio.to_thread(container.kill)
                result["error"] = (
                    f"sandbox_timeout: exceeded {self._settings.sandbox_timeout_seconds}s"
                )
                return result

            exit_code = wait_result.get("StatusCode", 0) if isinstance(wait_result, dict) else 0
            logs = await asyncio.to_thread(container.logs)
            text = logs.decode("utf-8", errors="replace") if isinstance(logs, bytes) else str(logs)

            parsed = _parse_runner_result(text)
            if parsed is not None:
                for key in ("status", "status_code", "latency_ms", "response_snapshot", "error", "stack_trace"):
                    if key in parsed:
                        result[key] = parsed[key]
                if result["latency_ms"] <= 0:
                    result["latency_ms"] = int((time.perf_counter() - started) * 1000)
            elif exit_code != 0:
                result["error"] = f"sandbox exited with code {exit_code}: {text[-2000:]}"
            else:
                result["error"] = "sandbox produced no result"
            return result
        except Exception as exc:
            result["error"] = str(exc)
            result["stack_trace"] = traceback.format_exc()
            return result
        finally:
            if container is not None:
                try:
                    await asyncio.to_thread(container.remove, force=True)
                except Exception as remove_error:
                    logger.warning("sandbox_container_remove_failed", error=str(remove_error))

    async def cleanup(self, *, project_id: Any = None) -> None:
        if self._workspace is not None:
            shutil.rmtree(self._workspace, ignore_errors=True)
            self._workspace = None