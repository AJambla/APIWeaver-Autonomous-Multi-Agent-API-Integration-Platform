"""Sandbox execution boundary for running generated client code.

Provides a protocol, an in-memory mock implementation for tests, and a
Docker-backed executor that enforces per-run resource quotas.
"""

from __future__ import annotations

import asyncio
import io
import json
import os
import re
import shutil
import tarfile
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
    if "/sandbox" not in sys.path:
        sys.path.insert(0, "/sandbox")
    for root, dirs, _ in os.walk("/sandbox"):
        if root not in sys.path:
            sys.path.insert(0, root)
    payload_dir = os.path.dirname(payload_path)
    if payload_dir and payload_dir not in sys.path:
        sys.path.insert(0, payload_dir)

    with open(payload_path, "r", encoding="utf-8") as handle:
        payload = json.load(handle)

    module_name = payload["module_name"]
    try:
        module = importlib.import_module(module_name)
    except ModuleNotFoundError:
        base_name = module_name.split(".")[-1]
        module = importlib.import_module(base_name)

    client_classes = [
        getattr(module, a)
        for a in dir(module)
        if isinstance(getattr(module, a), type) and "Client" in a
    ]
    if not client_classes:
        client_classes = [
            getattr(module, a)
            for a in dir(module)
            if isinstance(getattr(module, a), type)
            and a not in ("BaseModel", "Exception", "APIWeaverError")
            and not a.startswith("_")
        ]

    # Select the client class that implements the requested operation (or its variants)
    op_id = payload.get("op_id", "")
    op_norm = op_id.lower().replace("_", "").replace("-", "")
    client_class = None
    for cls in client_classes:
        methods = {m.lower().replace("_", "").replace("-", "") for m in dir(cls) if not m.startswith("_")}
        if op_norm in methods or hasattr(cls, op_id):
            client_class = cls
            break

    # If no specific match, choose the client class with the most public methods
    if client_class is None and client_classes:
        client_class = max(
            client_classes,
            key=lambda c: len([m for m in dir(c) if not m.startswith("_") and callable(getattr(c, m, None))]),
        )
    if client_class is None:
        raise RuntimeError(f"no client class found in module {payload['module_name']}")

    # Credentials arrive via the APIWEAVER_API_KEY env var (never a file inside
    # the container — Security.md §7); payload["api_key"] stays as a secondary
    # source for hosts that pre-date the env-var channel.
    import inspect
    init_kwargs = {}
    resolved_auth = os.environ.get("APIWEAVER_API_KEY") or payload.get("api_key")
    try:
        init_sig = inspect.signature(client_class.__init__)
        params = init_sig.parameters
        has_varkw = any(p.kind == inspect.Parameter.VAR_KEYWORD for p in params.values())
        if "base_url" in params or has_varkw:
            init_kwargs["base_url"] = payload.get("base_url")
        if "api_key" in params or has_varkw:
            init_kwargs["api_key"] = resolved_auth
        elif "token" in params:
            init_kwargs["token"] = resolved_auth
        elif "auth_token" in params:
            init_kwargs["auth_token"] = resolved_auth
        client = client_class(**init_kwargs)
    except TypeError:
        try:
            client = client_class(base_url=payload.get("base_url"))
        except TypeError:
            client = client_class()

    op_id = payload["op_id"]
    operation = None
    if hasattr(client, op_id):
        operation = getattr(client, op_id)
    else:
        import re
        snake = re.sub(r'(?<!^)(?=[A-Z])', '_', op_id).lower().replace('__', '_')
        if hasattr(client, snake):
            operation = getattr(client, snake)
        else:
            parts = op_id.split('_')
            camel = parts[0] + ''.join(p.title() for p in parts[1:])
            if hasattr(client, camel):
                operation = getattr(client, camel)
            else:
                target_norm = op_id.lower().replace('_', '').replace('-', '')
                for attr_name in dir(client):
                    if attr_name.startswith('_'):
                        continue
                    if attr_name.lower().replace('_', '').replace('-', '') == target_norm:
                        operation = getattr(client, attr_name)
                        break

    if operation is None:
        available_ops = [m for m in dir(client) if not m.startswith('_') and callable(getattr(client, m, None))]
        raise RuntimeError(f"method '{op_id}' not found on client. Available methods: {available_ops}")

    request = payload.get("request") or {}
    params = request.get("params") or {}
    body = request.get("body")

    params_normalized = {}
    for k, v in params.items():
        params_normalized[k] = v
        params_normalized[k.lower().replace("_", "").replace("-", "")] = v
        k_snake = re.sub(r'(?<!^)(?=[A-Z])', '_', k).lower()
        params_normalized[k_snake] = v

    started = time.perf_counter()
    sig = inspect.signature(operation)
    call_kwargs = {}
    for p_name, p in sig.parameters.items():
        if p.kind == inspect.Parameter.VAR_KEYWORD:
            call_kwargs.update(params)
            break
        if p_name in params:
            call_kwargs[p_name] = params[p_name]
        else:
            p_norm = p_name.lower().replace("_", "").replace("-", "")
            if p_norm in params_normalized:
                call_kwargs[p_name] = params_normalized[p_norm]
            elif p_name in params_normalized:
                call_kwargs[p_name] = params_normalized[p_name]

    if "body" in sig.parameters or any(p.kind == inspect.Parameter.VAR_KEYWORD for p in sig.parameters.values()):
        if body is not None:
            call_kwargs["body"] = body
    else:
        for body_param in ("payload", "data", "request"):
            if body_param in sig.parameters and body is not None:
                call_kwargs[body_param] = body
                break

    if asyncio.iscoroutinefunction(operation):
        response = await operation(**call_kwargs)
    else:
        response = operation(**call_kwargs)
        if asyncio.iscoroutine(response):
            response = await response
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
        if isinstance(response, dict):
            result["status_code"] = response.get("status_code") or response.get("status")
    try:
        snapshot = {"status_code": result.get("status_code"), "headers": dict(getattr(response, "headers", {}))}
        if hasattr(response, "json"):
            try:
                snapshot["body"] = response.json()
            except Exception:
                snapshot["body"] = getattr(response, "text", None)
        elif isinstance(response, dict):
            snapshot["body"] = response
        result["response_snapshot"] = snapshot
    except Exception as snapshot_error:
        result["response_snapshot"] = {"snapshot_error": str(snapshot_error)}

    expected_status = payload.get("expected_status")
    status_code = result.get("status_code")
    is_success_code = status_code is not None and 200 <= status_code < 300
    expected_is_2xx = expected_status is None or (isinstance(expected_status, int) and 200 <= expected_status < 300)

    if expected_status is not None:
        if expected_is_2xx:
            if not is_success_code:
                result["status"] = "failed"
                result["error"] = f"Expected 2xx status, got {status_code}"
        elif status_code != expected_status:
            result["status"] = "failed"
            result["error"] = f"Expected status {expected_status}, got {status_code}"
    elif not is_success_code and status_code is not None:
        result["status"] = "failed"
        result["error"] = f"HTTP error status {status_code}"

    close = getattr(client, "close", None)
    if close is not None:
        await close()

    print("APIWEAVER_RESULT:" + json.dumps(result))
    return 0


def _run() -> int:
    try:
        return asyncio.run(_main())
    except Exception as exc:
        failure = traceback.format_exc()
        error_msg = str(exc) if str(exc) else (failure.strip().splitlines()[-1] if failure else "Unknown error")
        print("APIWEAVER_RESULT:" + json.dumps({
            "status": "failed",
            "status_code": None,
            "latency_ms": 0,
            "response_snapshot": None,
            "error": error_msg,
            "stack_trace": failure,
        }))
        return 1


if __name__ == "__main__":
    sys.exit(_run())
'''

NODE_RUNNER_SOURCE = '''// Sandbox runner: executes one generated Node.js/TS client call.
import fs from "node:fs";
import path from "node:path";
import { pathToFileURL } from "node:url";

const RESULT_PREFIX = "APIWEAVER_RESULT:";

async function main() {
    const payloadPath = process.env.APIWEAVER_PAYLOAD_PATH || "/sandbox/payload.json";
    const payload = JSON.parse(fs.readFileSync(payloadPath, "utf-8"));

    const relPath = payload.client_file || "client.ts";
    const fullPath = path.resolve("/sandbox", relPath);
    const fileUrl = pathToFileURL(fullPath).href;

    const module = await import(fileUrl);

    let ClientClass = null;
    const clientClasses = [];
    for (const [key, val] of Object.entries(module)) {
        if (typeof val === "function" && (key.endsWith("Client") || key.toLowerCase().includes("client"))) {
            clientClasses.push(val);
        }
    }
    if (clientClasses.length === 0 && module.default && typeof module.default === "function") {
        clientClasses.push(module.default);
    }

    const targetOpId = payload.op_id || "";
    const opNorm = targetOpId.toLowerCase().replace(/[^a-z0-9]/g, "");
    for (const cls of clientClasses) {
        const protoMethods = Object.getOwnPropertyNames(cls.prototype || {}).map(m => m.toLowerCase().replace(/[^a-z0-9]/g, ""));
        if (protoMethods.includes(opNorm)) {
            ClientClass = cls;
            break;
        }
    }
    if (!ClientClass && clientClasses.length > 0) {
        ClientClass = clientClasses.sort((a, b) =>
            Object.getOwnPropertyNames(b.prototype || {}).length - Object.getOwnPropertyNames(a.prototype || {}).length
        )[0];
    }
    if (!ClientClass) {
        throw new Error(`no client class found in module ${relPath}`);
    }

    const apiKey = process.env.APIWEAVER_API_KEY || payload.api_key;
    const client = new ClientClass({
        baseUrl: payload.base_url,
        apiKey: apiKey,
    });

    const opId = payload.op_id;
    let operation = client[opId];
    if (typeof operation !== "function") {
        const camel = opId.replace(/_([a-z0-9])/gi, (_, c) => c.toUpperCase());
        if (typeof client[camel] === "function") {
            operation = client[camel];
        }
    }
    if (typeof operation !== "function") {
        const snake = opId.replace(/([A-Z])/g, "_$1").toLowerCase().replace(/^_/, "");
        if (typeof client[snake] === "function") {
            operation = client[snake];
        }
    }
    if (typeof operation !== "function") {
        const norm = opId.toLowerCase().replace(/[^a-z0-9]/g, "");
        for (const [key, val] of Object.entries(client)) {
            if (typeof val === "function" && key.toLowerCase().replace(/[^a-z0-9]/g, "") === norm) {
                operation = val;
                break;
            }
        }
    }
    if (typeof operation !== "function") {
        const avail = Object.keys(client).filter(k => typeof client[k] === "function");
        throw new Error(`method '${opId}' not found on client. Available methods: ${avail.join(", ")}`);
    }

    const request = payload.request || {};
    const params = request.params || {};
    const body = request.body;

    const started = performance.now();
    let response;
    try {
        response = await operation.call(client, { ...params, body });
    } catch {
        response = await operation.call(client, params, body);
    }
    const latencyMs = Math.round(performance.now() - started);

    const extractStatusCode = (res) => {
        if (res == null) return null;
        if (typeof res.status === "number") return res.status;
        if (typeof res.statusCode === "number") return res.statusCode;
        if (typeof res.status_code === "number") return res.status_code;
        return null;
    };

    const result = {
        status: "passed",
        status_code: extractStatusCode(response),
        latency_ms: latencyMs,
        response_snapshot: null,
        error: null,
        stack_trace: null,
    };

    if (response) {
        if (typeof response.json === "function") {
            try { result.response_snapshot = await response.json(); } catch {}
        } else if (response.data !== undefined) {
            result.response_snapshot = response.data;
        } else {
            result.response_snapshot = response;
        }
    }

    const expectedStatus = payload.expected_status;
    const isSuccess = result.status_code !== null && result.status_code >= 200 && result.status_code < 300;
    const expectedIs2xx = !expectedStatus || (expectedStatus >= 200 && expectedStatus < 300);
    if (result.status_code === null && !response) {
        result.status = "failed";
        result.error = "No response returned from client method";
    } else if (expectedStatus) {
        if (expectedIs2xx) {
            if (!isSuccess) {
                result.status = "failed";
                result.error = `Expected 2xx status, got ${result.status_code}`;
            }
        } else if (result.status_code !== expectedStatus) {
            result.status = "failed";
            result.error = `Expected status ${expectedStatus}, got ${result.status_code}`;
        }
    } else if (!isSuccess && result.status_code !== null) {
        result.status = "failed";
        result.error = `HTTP error status ${result.status_code}`;
    }

    if (typeof client.close === "function") {
        await client.close();
    }

    console.log(RESULT_PREFIX + JSON.stringify(result));
    return 0;
}

main().catch((err) => {
    console.log(RESULT_PREFIX + JSON.stringify({
        status: "failed",
        status_code: null,
        latency_ms: 0,
        response_snapshot: null,
        error: String(err?.message || err),
        stack_trace: String(err?.stack || ""),
    }));
    process.exit(1);
});
'''


def _safe_workspace_target(workspace: Path, rel_path: str) -> Path | None:
    """Join rel_path under workspace, or None if it would escape.

    Generated file names come from LLM output, so POSIX/Windows absolute
    paths and any ".." segment are rejected before touching the filesystem.
    """
    text = rel_path.replace("\\", "/")
    if not text or "\x00" in text:
        return None
    if text.startswith("/") or text[1:2] == ":":
        return None
    parts = [part for part in text.split("/") if part not in ("", ".")]
    if not parts or any(part == ".." for part in parts):
        return None
    target = workspace.joinpath(*parts)
    try:
        if not target.resolve().is_relative_to(workspace.resolve()):
            return None
    except OSError:
        return None
    return target


def _cpu_to_nano_cpus(raw: str) -> int:
    """Convert a quota string ("0.5", "500m", "1") to Docker nano_cpus."""
    text = str(raw).strip()
    if text.endswith("m"):
        return int(float(text[:-1]) * 1_000_000)
    return int(float(text) * 1_000_000_000)


def _memory_to_bytes(raw: str) -> int:
    """Convert a quota string ("512Ki", "256Mi", "1Gi", "1g", "512m", bare bytes) to bytes."""
    text = str(raw).strip()
    for suffix, multiplier in (
        ("Gi", 2**30), ("gi", 2**30), ("GB", 2**30), ("gb", 2**30), ("G", 2**30), ("g", 2**30),
        ("Mi", 2**20), ("mi", 2**20), ("MB", 2**20), ("mb", 2**20), ("M", 2**20), ("m", 2**20),
        ("Ki", 2**10), ("ki", 2**10), ("KB", 2**10), ("kb", 2**10), ("K", 2**10), ("k", 2**10),
    ):
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

    def __init__(
        self,
        settings: Settings,
        *,
        docker_client: Any | None = None,
        network_enabled: bool | None = None,
    ) -> None:
        self._settings = settings
        self._docker_client = docker_client
        self._network_enabled = (
            network_enabled
            if network_enabled is not None
            else getattr(settings, "sandbox_network_enabled", False)
        )
        self._workspace: Path | None = None
        self._client_module: str | None = None
        self._client_file: str | None = None
        self._language: str = "python"
        self._base_url: str | None = None
        self._api_key: str | None = None

    def _get_docker_client(self) -> Any:
        if self._docker_client is None:
            import docker

            if self._settings.docker_host:
                self._docker_client = docker.DockerClient(base_url=self._settings.docker_host)
            else:
                self._docker_client = docker.from_env()
        return self._docker_client

    def _is_containerized(self) -> bool:
        """Check if backend is running inside a Docker container (DooD environment)."""
        return (
            os.path.exists("/.dockerenv")
            or bool(os.environ.get("APIWEAVER_IN_DOCKER"))
            or bool(os.environ.get("DOCKER_CONTAINER"))
        )

    def _create_tar_archive(self, workspace: Path) -> io.BytesIO:
        """Create an in-memory tar archive of workspace files for container injection."""
        buf = io.BytesIO()
        with tarfile.open(fileobj=buf, mode="w") as tar:
            for root, dirs, files in os.walk(workspace):
                rel_dir = os.path.relpath(root, workspace)
                if rel_dir != ".":
                    norm_dir = rel_dir.replace("\\", "/")
                    d_info = tarfile.TarInfo(name=norm_dir)
                    d_info.type = tarfile.DIRTYPE
                    d_info.mode = 0o777
                    tar.addfile(d_info)
                for f in files:
                    file_path = Path(root) / f
                    rel_file = os.path.relpath(file_path, workspace).replace("\\", "/")
                    content = file_path.read_bytes()
                    f_info = tarfile.TarInfo(name=rel_file)
                    f_info.size = len(content)
                    f_info.mode = 0o666
                    tar.addfile(f_info, io.BytesIO(content))
        buf.seek(0)
        return buf

    async def prepare(
        self,
        *,
        project_id: Any,
        language: str,
        files: dict[str, str],
    ) -> None:
        """Satisfies the SandboxClient protocol."""
        await self.load(project_id=project_id, files=files, language=language)

    async def run_test(
        self,
        *,
        project_id: Any,
        test_file: str,
        test_code: str,
        env_vars: dict[str, str] | None = None,
    ) -> SandboxResult:
        """Execute a standalone test file inside a quota-enforced Docker container."""
        started = time.perf_counter()
        if self._workspace is None:
            self._workspace = Path(tempfile.mkdtemp(prefix=f"apiweaver-sandbox-{project_id or 'run'}-"))

        target = _safe_workspace_target(self._workspace, test_file)
        if target is None:
            return SandboxResult(
                exit_code=1,
                stdout="",
                stderr=f"Unsafe test file path rejected: {test_file}",
                duration_ms=int((time.perf_counter() - started) * 1000),
            )
        target.parent.mkdir(parents=True, exist_ok=True)
        if test_file.endswith((".ts", ".tsx")):
            test_code = re.sub(r'''((?:from|import)\s+['"])(\.[^'"]*?)\.js(['"])''', r'\1\2.ts\3', test_code)
            test_code = re.sub(r'''(import\s*\(\s*['"])(\.[^'"]*?)\.js(['"])''', r'\1\2.ts\3', test_code)
            test_code = re.sub(r'''((?:from|import)\s+['"])(\.[^'"]*?)(?<!\.ts)(?<!\.js)(?<!\.json)(['"])''', r'\1\2.ts\3', test_code)
            test_code = re.sub(r'''(import\s*\(\s*['"])(\.[^'"]*?)(?<!\.ts)(?<!\.js)(?<!\.json)(['"])''', r'\1\2.ts\3', test_code)
        target.write_text(test_code, encoding="utf-8")

        is_node = test_file.endswith((".ts", ".js", ".mjs"))
        if is_node:
            sandbox_img = self._settings.sandbox_node_image
            sandbox_cmd = ["node", "--experimental-strip-types", f"/sandbox/{test_file}"]
        else:
            sandbox_img = self._settings.sandbox_image
            sandbox_cmd = ["python", f"/sandbox/{test_file}"]

        environment = {
            "PYTHONDONTWRITEBYTECODE": "1",
        }
        if env_vars:
            environment.update(env_vars)

        docker_client = self._get_docker_client()
        container = None
        volume = None
        try:
            if self._is_containerized() and hasattr(docker_client, "volumes") and hasattr(docker_client.containers, "create"):
                volume = await asyncio.to_thread(docker_client.volumes.create)
                run_volumes = {volume.name: {"bind": "/sandbox", "mode": "rw"}}
                container = await asyncio.to_thread(
                    docker_client.containers.create,
                    image=sandbox_img,
                    command=sandbox_cmd,
                    environment=environment,
                    volumes=run_volumes,
                    tmpfs={"/tmp": "size=64m"},
                    nano_cpus=_cpu_to_nano_cpus(self._settings.sandbox_max_cpu),
                    mem_limit=_memory_to_bytes(self._settings.sandbox_max_memory),
                    pids_limit=self._settings.sandbox_pids_limit,
                    cap_drop=["ALL"],
                    user=_DOCKER_USER,
                    network_disabled=not self._network_enabled,
                    read_only=self._settings.sandbox_read_only_rootfs,
                    security_opt=["no-new-privileges:true"],
                )
                archive_buf = self._create_tar_archive(self._workspace)
                await asyncio.to_thread(container.put_archive, "/sandbox", archive_buf)
                await asyncio.to_thread(container.start)
            else:
                run_kwargs = dict(
                    image=sandbox_img,
                    command=sandbox_cmd,
                    environment=environment,
                    volumes={str(self._workspace): {"bind": "/sandbox", "mode": "ro"}},
                    tmpfs={"/tmp": "size=64m"},
                    nano_cpus=_cpu_to_nano_cpus(self._settings.sandbox_max_cpu),
                    mem_limit=_memory_to_bytes(self._settings.sandbox_max_memory),
                    pids_limit=self._settings.sandbox_pids_limit,
                    cap_drop=["ALL"],
                    user=_DOCKER_USER,
                    network_disabled=not self._network_enabled,
                    read_only=self._settings.sandbox_read_only_rootfs,
                    security_opt=["no-new-privileges:true"],
                    detach=True,
                )
                container = await asyncio.to_thread(docker_client.containers.run, **run_kwargs)

            try:
                wait_result = await asyncio.wait_for(
                    asyncio.to_thread(container.wait),
                    timeout=self._settings.sandbox_timeout_seconds,
                )
            except TimeoutError:
                await asyncio.to_thread(container.kill)
                return SandboxResult(
                    exit_code=1,
                    stdout="",
                    stderr=f"sandbox_timeout: exceeded {self._settings.sandbox_timeout_seconds}s",
                    duration_ms=int((time.perf_counter() - started) * 1000),
                )

            exit_code = wait_result.get("StatusCode", 0) if isinstance(wait_result, dict) else 0
            logs = await asyncio.to_thread(container.logs)
            text = logs.decode("utf-8", errors="replace") if isinstance(logs, bytes) else str(logs)
            return SandboxResult(
                exit_code=exit_code,
                stdout=text if exit_code == 0 else "",
                stderr=text if exit_code != 0 else "",
                duration_ms=int((time.perf_counter() - started) * 1000),
            )
        except Exception as exc:
            return SandboxResult(
                exit_code=1,
                stdout="",
                stderr=str(exc),
                duration_ms=int((time.perf_counter() - started) * 1000),
            )
        finally:
            if container is not None:
                try:
                    await asyncio.to_thread(container.remove, force=True)
                except Exception as rem_err:
                    logger.warning("sandbox_container_remove_failed", error=str(rem_err))
            if volume is not None:
                try:
                    await asyncio.to_thread(volume.remove, force=True)
                except Exception as vol_err:
                    logger.warning("sandbox_volume_remove_failed", error=str(vol_err))

    async def load(
        self,
        *,
        project_id: Any,
        files: dict[str, str],
        base_url: str | None = None,
        api_key: str | None = None,
        language: str | None = None,
    ) -> None:
        """Stage generated files into a host workspace the container will bind."""
        self._base_url = base_url
        self._api_key = api_key
        workspace = Path(tempfile.mkdtemp(prefix=f"apiweaver-sandbox-{project_id or 'run'}-"))
        for rel_path, content in files.items():
            target = _safe_workspace_target(workspace, rel_path)
            if target is None:
                logger.warning("sandbox_path_rejected", path=rel_path)
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            if rel_path.endswith(".py"):
                content = re.sub(r'^(from\s+)\.([a-zA-Z_][a-zA-Z0-9_]*\s+import)', r'\1\2', content, flags=re.MULTILINE)
                content = re.sub(r'^from\s+\.\s+import\s+([a-zA-Z_][a-zA-Z0-9_]*)', r'import \1', content, flags=re.MULTILINE)
            elif rel_path.endswith((".ts", ".tsx")):
                content = re.sub(r'''((?:from|import)\s+['"])(\.[^'"]*?)\.js(['"])''', r'\1\2.ts\3', content)
                content = re.sub(r'''(import\s*\(\s*['"])(\.[^'"]*?)\.js(['"])''', r'\1\2.ts\3', content)
                content = re.sub(r'''((?:from|import)\s+['"])(\.[^'"]*?)(?<!\.ts)(?<!\.js)(?<!\.json)(['"])''', r'\1\2.ts\3', content)
                content = re.sub(r'''(import\s*\(\s*['"])(\.[^'"]*?)(?<!\.ts)(?<!\.js)(?<!\.json)(['"])''', r'\1\2.ts\3', content)
            target.write_text(content, encoding="utf-8")

        # Determine target language: explicit parameter or inferred from extensions
        has_node_files = any(
            rel_path.endswith((".ts", ".js", ".mjs")) for rel_path in files
        )
        if language == "node" or (language is None and has_node_files and not any(r.endswith(".py") for r in files)):
            self._language = "node"
        else:
            self._language = "python"

        client_module = None
        client_file = None
        # First priority: dedicated sandbox/mock client if provided
        for rel_path in files:
            normalized = rel_path.replace("\\", "/").lower()
            if self._language == "python" and normalized.endswith(".py") and ("sandbox" in normalized or "mock" in normalized) and "client" in normalized:
                client_module = (
                    rel_path.replace("\\", "/").removesuffix(".py").replace("/", ".")
                )
                break
            elif self._language == "node" and normalized.endswith((".ts", ".js", ".mjs")) and ("sandbox" in normalized or "mock" in normalized) and "client" in normalized:
                client_file = rel_path.replace("\\", "/")
                break

        # Second priority: standard client module
        if not client_module and not client_file:
            for rel_path in files:
                normalized = rel_path.replace("\\", "/").lower()
                if self._language == "python" and normalized.endswith(".py") and "client" in normalized:
                    client_module = (
                        rel_path.replace("\\", "/").removesuffix(".py").replace("/", ".")
                    )
                    break
                elif self._language == "node" and normalized.endswith((".ts", ".js", ".mjs")) and "client" in normalized:
                    client_file = rel_path.replace("\\", "/")
                    break

        if self._language == "node" and not client_file:
            for rel_path in files:
                if rel_path.endswith((".ts", ".js", ".mjs")):
                    client_file = rel_path.replace("\\", "/")
                    break

        (workspace / "runner.py").write_text(RUNNER_SOURCE, encoding="utf-8")
        (workspace / "runner.mjs").write_text(NODE_RUNNER_SOURCE, encoding="utf-8")
        self._workspace = workspace
        self._client_module = client_module
        self._client_file = client_file

    async def execute_test(self, endpoint: dict[str, Any], fixture: dict[str, Any]) -> dict[str, Any]:
        """Run one endpoint test in a fresh container; returns the mock result shape."""
        if isinstance(endpoint, list):
            endpoint = endpoint[0] if endpoint and isinstance(endpoint[0], dict) else {}
        elif not isinstance(endpoint, dict):
            endpoint = {}

        if isinstance(fixture, list):
            fixture = fixture[0] if fixture and isinstance(fixture[0], dict) else {}
        elif not isinstance(fixture, dict):
            fixture = {}

        method = str(endpoint.get("method") or "GET").upper()
        path = str(endpoint.get("path") or "/")

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

        if self._workspace is None or (self._client_module is None and self._client_file is None):
            result["error"] = "Sandbox workspace not prepared"
            return result

        docker_client = self._get_docker_client()
        started = time.perf_counter()
        container = None
        volume = None
        try:
            op_id = (
                endpoint.get("operationId")
                or endpoint.get("operation_id")
                or path.replace("/", "_").replace("{", "").replace("}", "").replace("-", "_")
            )
            request_data = fixture.get("request", {}) or {}
            if isinstance(request_data, list):
                request_data = request_data[0] if request_data and isinstance(request_data[0], dict) else {}
            elif not isinstance(request_data, dict):
                request_data = {}

            params_data = request_data.get("params", {}) or {}
            if not isinstance(params_data, dict):
                params_data = {}

            exp_status = fixture.get("expected_status") if isinstance(fixture, dict) else None
            if exp_status is None:
                resp_sc = endpoint.get("response_schemas") or endpoint.get("responses")
                if isinstance(resp_sc, dict):
                    for cs in resp_sc.keys():
                        try:
                            ci = int(cs)
                            if 200 <= ci < 300:
                                exp_status = ci
                                break
                        except (ValueError, TypeError):
                            pass
                if exp_status is None:
                    exp_status = 201 if method == "POST" else (204 if method == "DELETE" else 200)

            payload = {
                "module_name": self._client_module,
                "client_file": self._client_file,
                "language": self._language,
                "op_id": op_id,
                "request": {
                    "params": params_data,
                    "body": request_data.get("body"),
                },
                "expected_status": exp_status,
                "base_url": self._base_url,
            }
            (self._workspace / "payload.json").write_text(json.dumps(payload), encoding="utf-8")
            environment = {
                "PYTHONDONTWRITEBYTECODE": "1",
                "APIWEAVER_PAYLOAD_PATH": "/sandbox/payload.json",
            }
            if self._api_key:
                # Runtime secret injection (Security.md §7): the credential travels
                # in the container environment, never inside a file.
                environment["APIWEAVER_API_KEY"] = self._api_key

            if self._language == "node":
                sandbox_img = self._settings.sandbox_node_image
                sandbox_cmd = ["node", "--experimental-strip-types", "/sandbox/runner.mjs"]
            else:
                sandbox_img = self._settings.sandbox_image
                sandbox_cmd = ["python", "/sandbox/runner.py"]

            if self._is_containerized() and hasattr(docker_client, "volumes") and hasattr(docker_client.containers, "create"):
                volume = await asyncio.to_thread(docker_client.volumes.create)
                run_volumes = {volume.name: {"bind": "/sandbox", "mode": "rw"}}
                container = await asyncio.to_thread(
                    docker_client.containers.create,
                    image=sandbox_img,
                    command=sandbox_cmd,
                    environment=environment,
                    volumes=run_volumes,
                    tmpfs={"/tmp": "size=64m"},
                    nano_cpus=_cpu_to_nano_cpus(self._settings.sandbox_max_cpu),
                    mem_limit=_memory_to_bytes(self._settings.sandbox_max_memory),
                    pids_limit=self._settings.sandbox_pids_limit,
                    cap_drop=["ALL"],
                    user=_DOCKER_USER,
                    network_disabled=not self._network_enabled,
                    read_only=self._settings.sandbox_read_only_rootfs,
                    security_opt=["no-new-privileges:true"],
                )
                archive_buf = self._create_tar_archive(self._workspace)
                await asyncio.to_thread(container.put_archive, "/sandbox", archive_buf)
                await asyncio.to_thread(container.start)
            else:
                run_kwargs = dict(
                    image=sandbox_img,
                    command=sandbox_cmd,
                    environment=environment,
                    volumes={str(self._workspace): {"bind": "/sandbox", "mode": "ro"}},
                    tmpfs={"/tmp": "size=64m"},
                    nano_cpus=_cpu_to_nano_cpus(self._settings.sandbox_max_cpu),
                    mem_limit=_memory_to_bytes(self._settings.sandbox_max_memory),
                    pids_limit=self._settings.sandbox_pids_limit,
                    cap_drop=["ALL"],
                    user=_DOCKER_USER,
                    network_disabled=not self._network_enabled,
                    read_only=self._settings.sandbox_read_only_rootfs,
                    security_opt=["no-new-privileges:true"],
                    detach=True,
                )
                container = await asyncio.to_thread(docker_client.containers.run, **run_kwargs)
            try:
                wait_result = await asyncio.wait_for(
                    asyncio.to_thread(container.wait),
                    timeout=self._settings.sandbox_timeout_seconds,
                )
            except TimeoutError:
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
            if volume is not None:
                try:
                    await asyncio.to_thread(volume.remove, force=True)
                except Exception as vol_error:
                    logger.warning("sandbox_volume_remove_failed", error=str(vol_error))

    async def cleanup(self, *, project_id: Any = None) -> None:
        if self._workspace is not None:
            shutil.rmtree(self._workspace, ignore_errors=True)
            self._workspace = None


def create_sandbox_client(settings: Settings) -> SandboxClient:
    """Instantiate a production-level Docker sandbox executor."""
    if settings.sandbox_backend != "docker":
        raise RuntimeError(
            f"SANDBOX_BACKEND={settings.sandbox_backend} cannot be used in {settings.app_env} mode. "
            "Docker sandbox executor is strictly required."
        )
    return DockerSandboxExecutor(settings)