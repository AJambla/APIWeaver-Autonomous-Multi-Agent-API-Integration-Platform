"""Sandbox execution boundary for running generated client code.

Provides a protocol and a Docker-backed executor that runs each generated-client call
in a short-lived, quota-enforced container.

Two modes, chosen per executor:

* **Hermetic** (default, `network_enabled=False`): the container has no network. The
  runner answers the client's HTTP requests from a mock built from the spec and fails the
  test if the request's method, path or required query parameters are wrong. This
  verifies the generated code without touching any real API.
* **Live** (`network_enabled=True`, opt-in via `SANDBOX_LIVE_NETWORK_ENABLED`): the call
  goes to the target API. Callers must vet the target first (`assert_public_target`), and
  production deployments should route egress through `SANDBOX_EGRESS_PROXY`.
"""

from __future__ import annotations

import asyncio
import io
import ipaddress
import json
import os
import re
import secrets
import shutil
import socket
import tarfile
import tempfile
import time
import traceback
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from app.core.config import Settings
from app.core.logging import get_logger

logger = get_logger(__name__)

# What a hermetic (mock-answered, no-network) run sees in place of the target credential.
HERMETIC_PLACEHOLDER_API_KEY = "apiweaver-hermetic-placeholder"


# Marker the sandbox runner prints before its nonce and single-line JSON result.
_RESULT_PREFIX = "APIWEAVER_RESULT:"

# Run as nobody inside the container: generated code is untrusted.
_DOCKER_USER = "65534:65534"

# Every container and volume the executor creates carries these labels so orphans left
# by a killed worker can be found and reaped (`reap_orphaned_sandboxes`).
SANDBOX_LABEL = "io.apiweaver.sandbox"
SANDBOX_CREATED_LABEL = "io.apiweaver.sandbox.created"
_REAP_INTERVAL_SECONDS = 300
_last_reap = 0.0

_RUNNER_DIR = Path(__file__).with_name("sandbox_runners")
RUNNER_SOURCE = (_RUNNER_DIR / "runner.py").read_text(encoding="utf-8")
NODE_RUNNER_SOURCE = (_RUNNER_DIR / "runner.mjs").read_text(encoding="utf-8")


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


class SandboxResultTampered(ValueError):
    """More than one result line carried the run's nonce."""


def _parse_runner_result(output: str, nonce: str | None = None) -> dict[str, Any] | None:
    """Extract the runner's JSON result from container output.

    With a `nonce`, only lines carrying it count, and exactly one must exist: the nonce
    is removed from the environment before generated code runs, so a second line means
    the output was forged. Without one (in-process tests), the last result line wins.
    """
    if nonce is not None:
        marker = f"{_RESULT_PREFIX}{nonce}:"
        matches = [line for line in output.splitlines() if line.startswith(marker)]
        if not matches:
            return None
        if len(matches) > 1:
            raise SandboxResultTampered("sandbox output contained more than one result line")
        return json.loads(matches[0][len(marker) :])

    for line in reversed(output.splitlines()):
        if line.startswith(_RESULT_PREFIX):
            rest = line[len(_RESULT_PREFIX) :]
            if not rest.startswith("{"):
                rest = rest.split(":", 1)[1] if ":" in rest else rest
            return json.loads(rest)
    return None


def _rewrite_ts_imports(content: str) -> str:
    """Point relative TS imports at `.ts` files: the sandbox runs Node's type stripping."""
    content = re.sub(r'''((?:from|import)\s+['"])(\.[^'"]*?)\.js(['"])''', r"\1\2.ts\3", content)
    content = re.sub(r'''(import\s*\(\s*['"])(\.[^'"]*?)\.js(['"])''', r"\1\2.ts\3", content)
    content = re.sub(
        r'''((?:from|import)\s+['"])(\.[^'"]*?)(?<!\.ts)(?<!\.js)(?<!\.json)(['"])''', r"\1\2.ts\3", content
    )
    return re.sub(
        r'''(import\s*\(\s*['"])(\.[^'"]*?)(?<!\.ts)(?<!\.js)(?<!\.json)(['"])''', r"\1\2.ts\3", content
    )


def _flatten_relative_python_imports(content: str) -> str:
    """`from .models import x` -> `from models import x`: the sandbox imports top-level."""
    content = re.sub(
        r"^(from\s+)\.([a-zA-Z_][a-zA-Z0-9_]*\s+import)", r"\1\2", content, flags=re.MULTILINE
    )
    return re.sub(
        r"^from\s+\.\s+import\s+([a-zA-Z_][a-zA-Z0-9_]*)", r"import \1", content, flags=re.MULTILINE
    )


def endpoint_path_regex(path: str) -> str:
    """Regex matching a request path for `path`, after any base-URL prefix (`/v2`)."""
    pieces = re.split(r"(\{[^}]*\})", path.rstrip("/") or "/")
    body = "".join("[^/]+" if piece.startswith("{") else re.escape(piece) for piece in pieces)
    return f"{body}/?$"


def _is_public_address(address: str) -> bool:
    """Globally routable unicast only.

    `is_global` also excludes ranges the old private/loopback/link-local list missed,
    such as 100.64.0.0/10 (carrier-grade NAT, home of some cloud metadata services). An
    IPv4-mapped IPv6 address (::ffff:10.0.0.1) is judged by the IPv4 address it carries.
    """
    ip = ipaddress.ip_address(address.split("%", 1)[0])
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped is not None:
        ip = ip.ipv4_mapped
    return ip.is_global and not ip.is_multicast


async def resolve_public_address(hostname: str, port: int) -> str:
    """Resolve `hostname` once and return an address to connect to, all of them vetted.

    Callers must connect to the returned address rather than the name: resolving the
    name again at connect time is exactly what a DNS-rebinding server exploits (public
    answer for the check, 169.254.169.254 for the connection).
    """
    loop = asyncio.get_running_loop()
    try:
        infos = await loop.getaddrinfo(hostname, port, type=socket.SOCK_STREAM)
    except socket.gaierror as exc:
        raise ValueError(f"cannot resolve {hostname!r}: {exc}") from exc
    addresses = [str(info[4][0]) for info in infos]
    blocked = sorted({a for a in addresses if not _is_public_address(a)})
    if blocked or not addresses:
        raise ValueError(
            f"{hostname!r} resolves to non-public address(es) {blocked}; "
            "set SANDBOX_ALLOW_PRIVATE_TARGETS=true only for trusted local development"
        )
    return addresses[0]


async def assert_public_target(url: str | None, *, allow_private: bool = False) -> None:
    """Refuse live tests whose target resolves to a private, loopback or metadata address.

    Live mode gives generated (LLM-written, spec-influenced) code network access; without
    this check a spec's `servers[0].url` could aim it at the host, the cluster, or the
    cloud metadata service (169.254.169.254).
    """
    parts = urlsplit(url or "")
    if parts.scheme not in ("http", "https") or not parts.hostname:
        raise ValueError(f"live testing needs an absolute http(s) base URL, got {url!r}")
    if allow_private:
        return
    default_port = 443 if parts.scheme == "https" else 80
    await resolve_public_address(parts.hostname, parts.port or default_port)


def reap_orphaned_sandboxes(docker_client: Any, *, max_age_seconds: int) -> int:
    """Remove labelled sandbox containers and volumes older than `max_age_seconds`.

    A worker killed mid-test (SIGKILL, Celery hard time limit) never reaches the
    `finally` that removes its container; this is the backstop. Returns how many
    objects were removed.
    """
    removed = 0
    now = time.time()
    containers = getattr(docker_client, "containers", None)
    if containers is not None and hasattr(containers, "list"):
        for container in containers.list(all=True, filters={"label": SANDBOX_LABEL}):
            created = float((getattr(container, "labels", {}) or {}).get(SANDBOX_CREATED_LABEL, now))
            if now - created > max_age_seconds:
                try:
                    container.remove(force=True)
                    removed += 1
                except Exception as exc:
                    logger.warning("sandbox_reap_container_failed", error=str(exc))
    volumes = getattr(docker_client, "volumes", None)
    if volumes is not None and hasattr(volumes, "list"):
        for volume in volumes.list(filters={"label": SANDBOX_LABEL}):
            labels = (getattr(volume, "attrs", {}) or {}).get("Labels") or {}
            created = float(labels.get(SANDBOX_CREATED_LABEL, now))
            if now - created > max_age_seconds:
                try:
                    volume.remove(force=True)
                    removed += 1
                except Exception as exc:
                    logger.warning("sandbox_reap_volume_failed", error=str(exc))
    if removed:
        logger.info("sandbox_orphans_reaped", count=removed)
    return removed


@dataclass(slots=True)
class _ContainerOutcome:
    exit_code: int
    output: str
    timed_out: bool = False


class DockerSandboxExecutor:
    """Runs generated clients in a quota-enforced Docker container.

    One short-lived container per call: capabilities are dropped, the root filesystem is
    read-only, the process runs as nobody with memory/CPU/PID limits, the network is off
    unless live mode was requested, and a hard wall-clock timeout kills hung containers
    (a hung sandbox is recorded as a failed test, never an outage — Architecture.md §277).
    """

    def __init__(
        self,
        settings: Settings,
        *,
        docker_client: Any | None = None,
        network_enabled: bool = False,
    ) -> None:
        self._settings = settings
        self._docker_client = docker_client
        # Hermetic unless the caller is running a vetted live test.
        self._network_enabled = network_enabled
        self._workspace: Path | None = None
        self._client_module: str | None = None
        self._client_file: str | None = None
        self._language: str = "python"
        self._base_url: str | None = None
        self._api_key: str | None = None
        self._images_checked: set[str] = set()

    @property
    def network_enabled(self) -> bool:
        return self._network_enabled

    @network_enabled.setter
    def network_enabled(self, value: bool) -> None:
        self._network_enabled = value

    # --- Docker plumbing ------------------------------------------------------

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

    def _ensure_image(self, docker_client: Any, image: str) -> None:
        """Pull a missing image once: `containers.create` (DooD mode) never auto-pulls."""
        if image in self._images_checked or not hasattr(docker_client, "images"):
            return
        from docker.errors import ImageNotFound

        try:
            docker_client.images.get(image)
        except ImageNotFound:
            logger.info("sandbox_image_pull", image=image)
            docker_client.images.pull(image)
        self._images_checked.add(image)

    def _maybe_reap(self, docker_client: Any) -> None:
        global _last_reap
        now = time.time()
        if now - _last_reap < _REAP_INTERVAL_SECONDS:
            return
        _last_reap = now
        try:
            reap_orphaned_sandboxes(
                docker_client, max_age_seconds=max(self._settings.sandbox_timeout_seconds * 2, 600)
            )
        except Exception as exc:
            logger.warning("sandbox_reap_failed", error=str(exc))

    def _labels(self) -> dict[str, str]:
        return {SANDBOX_LABEL: "true", SANDBOX_CREATED_LABEL: str(int(time.time()))}

    def _network_options(self, environment: dict[str, str]) -> dict[str, Any]:
        if not self._network_enabled:
            return {"network_disabled": True}
        options: dict[str, Any] = {"network_disabled": False}
        if self._settings.sandbox_network:
            options["network"] = self._settings.sandbox_network
        proxy = self._settings.sandbox_egress_proxy
        if proxy:
            for key in ("HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy"):
                environment[key] = proxy
            environment["NODE_USE_ENV_PROXY"] = "1"
        return options

    def _create_tar_archive(self, workspace: Path) -> io.BytesIO:
        """Create an in-memory tar archive of workspace files for container injection."""
        buf = io.BytesIO()
        with tarfile.open(fileobj=buf, mode="w") as tar:
            for root, _dirs, files in os.walk(workspace):
                rel_dir = os.path.relpath(root, workspace)
                if rel_dir != ".":
                    d_info = tarfile.TarInfo(name=rel_dir.replace("\\", "/"))
                    d_info.type = tarfile.DIRTYPE
                    d_info.mode = 0o755
                    tar.addfile(d_info)
                for f in files:
                    file_path = Path(root) / f
                    content = file_path.read_bytes()
                    f_info = tarfile.TarInfo(
                        name=os.path.relpath(file_path, workspace).replace("\\", "/")
                    )
                    f_info.size = len(content)
                    f_info.mode = 0o644
                    tar.addfile(f_info, io.BytesIO(content))
        buf.seek(0)
        return buf

    async def _run_container(
        self, *, image: str, command: list[str], environment: dict[str, str]
    ) -> _ContainerOutcome:
        """Run one container to completion; always removes the container and volume."""
        if self._workspace is None:
            raise RuntimeError("sandbox workspace not prepared")
        docker_client = await asyncio.to_thread(self._get_docker_client)
        await asyncio.to_thread(self._maybe_reap, docker_client)
        await asyncio.to_thread(self._ensure_image, docker_client, image)

        memory = _memory_to_bytes(self._settings.sandbox_max_memory)
        common: dict[str, Any] = dict(
            image=image,
            command=command,
            environment=environment,
            tmpfs={"/tmp": "size=64m"},
            nano_cpus=_cpu_to_nano_cpus(self._settings.sandbox_max_cpu),
            mem_limit=memory,
            # Equal to mem_limit: no swap on top of the memory quota.
            memswap_limit=memory,
            pids_limit=self._settings.sandbox_pids_limit,
            cap_drop=["ALL"],
            user=_DOCKER_USER,
            read_only=self._settings.sandbox_read_only_rootfs,
            security_opt=["no-new-privileges:true"],
            labels=self._labels(),
            **self._network_options(environment),
        )

        container = None
        volume = None
        try:
            if self._is_containerized() and hasattr(docker_client, "volumes") and hasattr(
                docker_client.containers, "create"
            ):
                # Docker-out-of-Docker: the daemon cannot see this container's filesystem,
                # so the workspace travels as a tar archive into a fresh labelled volume.
                volume = await asyncio.to_thread(docker_client.volumes.create, labels=self._labels())
                container = await asyncio.to_thread(
                    docker_client.containers.create,
                    volumes={volume.name: {"bind": "/sandbox", "mode": "rw"}},
                    **common,
                )
                archive = await asyncio.to_thread(self._create_tar_archive, self._workspace)
                await asyncio.to_thread(container.put_archive, "/sandbox", archive)
                await asyncio.to_thread(container.start)
            else:
                container = await asyncio.to_thread(
                    docker_client.containers.run,
                    volumes={str(self._workspace): {"bind": "/sandbox", "mode": "ro"}},
                    detach=True,
                    **common,
                )
            assert container is not None  # both branches above create it

            try:
                wait_result = await asyncio.wait_for(
                    asyncio.to_thread(container.wait),
                    timeout=self._settings.sandbox_timeout_seconds,
                )
            except TimeoutError:
                await asyncio.to_thread(container.kill)
                return _ContainerOutcome(exit_code=1, output="", timed_out=True)

            exit_code = wait_result.get("StatusCode", 0) if isinstance(wait_result, dict) else 0
            logs = await asyncio.to_thread(
                container.logs, stdout=True, stderr=True, tail=self._settings.sandbox_log_tail_lines
            )
            text = logs.decode("utf-8", errors="replace") if isinstance(logs, bytes) else str(logs)
            # Keep the tail: the runner's result line is printed last.
            limit = self._settings.sandbox_log_max_bytes
            if len(text) > limit:
                text = text[-limit:]
            return _ContainerOutcome(exit_code=exit_code, output=text)
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

    # --- Workspace ------------------------------------------------------------

    @staticmethod
    def _new_workspace(project_id: Any) -> Path:
        workspace = Path(tempfile.mkdtemp(prefix=f"apiweaver-sandbox-{project_id or 'run'}-"))
        # mkdtemp is 0700 and owned by the worker; the container runs as uid 65534 and
        # must be able to read the bind-mounted files (host mode).
        workspace.chmod(0o755)
        return workspace

    @staticmethod
    def _write_file(target: Path, content: str) -> None:
        target.parent.mkdir(parents=True, exist_ok=True)
        for parent in target.parents:
            try:
                parent.chmod(0o755)
            except OSError:
                break
            if parent.name.startswith("apiweaver-sandbox-"):
                break
        target.write_text(content, encoding="utf-8")
        target.chmod(0o644)

    def _stage(self, project_id: Any, files: dict[str, str]) -> Path:
        workspace = self._new_workspace(project_id)
        for rel_path, content in files.items():
            target = _safe_workspace_target(workspace, rel_path)
            if target is None:
                logger.warning("sandbox_path_rejected", path=rel_path)
                continue
            if rel_path.endswith(".py"):
                content = _flatten_relative_python_imports(content)
            elif rel_path.endswith((".ts", ".tsx")):
                content = _rewrite_ts_imports(content)
            self._write_file(target, content)
        self._write_file(workspace / "runner.py", RUNNER_SOURCE)
        self._write_file(workspace / "runner.mjs", NODE_RUNNER_SOURCE)
        return workspace

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
        # A second load must not leak the first workspace.
        await self.cleanup()
        self._base_url = base_url
        self._api_key = api_key
        self._workspace = await asyncio.to_thread(self._stage, project_id, files)

        has_node_files = any(rel_path.endswith((".ts", ".js", ".mjs")) for rel_path in files)
        if language == "node" or (
            language is None and has_node_files and not any(r.endswith(".py") for r in files)
        ):
            self._language = "node"
        else:
            self._language = "python"

        client_module = None
        client_file = None
        # First priority: dedicated sandbox/mock client if provided
        for rel_path in files:
            normalized = rel_path.replace("\\", "/").lower()
            if (
                self._language == "python"
                and normalized.endswith(".py")
                and ("sandbox" in normalized or "mock" in normalized)
                and "client" in normalized
            ):
                client_module = rel_path.replace("\\", "/").removesuffix(".py").replace("/", ".")
                break
            if (
                self._language == "node"
                and normalized.endswith((".ts", ".js", ".mjs"))
                and ("sandbox" in normalized or "mock" in normalized)
                and "client" in normalized
            ):
                client_file = rel_path.replace("\\", "/")
                break

        # Second priority: standard client module
        if not client_module and not client_file:
            for rel_path in files:
                normalized = rel_path.replace("\\", "/").lower()
                if self._language == "python" and normalized.endswith(".py") and "client" in normalized:
                    client_module = rel_path.replace("\\", "/").removesuffix(".py").replace("/", ".")
                    break
                if (
                    self._language == "node"
                    and normalized.endswith((".ts", ".js", ".mjs"))
                    and "client" in normalized
                ):
                    client_file = rel_path.replace("\\", "/")
                    break

        if self._language == "node" and not client_file:
            for rel_path in files:
                if rel_path.endswith((".ts", ".js", ".mjs")):
                    client_file = rel_path.replace("\\", "/")
                    break

        self._client_module = client_module
        self._client_file = client_file

    # --- One endpoint call ----------------------------------------------------

    @staticmethod
    def _declared_names(endpoint: dict[str, Any]) -> set[str]:
        names: set[str] = set()
        for param in endpoint.get("parameters") or []:
            if isinstance(param, dict) and param.get("name"):
                names.add(re.sub(r"[^a-z0-9]", "", str(param["name"]).lower()))
        return names

    def _mock_for(
        self, endpoint: dict[str, Any], fixture: dict[str, Any], method: str, path: str, expected: int
    ) -> dict[str, Any]:
        required_query = [
            str(p["name"])
            for p in endpoint.get("parameters") or []
            if isinstance(p, dict) and p.get("name") and p.get("location", p.get("in")) == "query"
            and p.get("required")
        ]
        return {
            "method": method,
            "path": path,
            "path_regex": endpoint_path_regex(path),
            "required_query": required_query,
            "status": expected,
            "body": fixture.get("mock_response", {}),
        }

    async def execute_test(self, endpoint: dict[str, Any], fixture: dict[str, Any]) -> dict[str, Any]:
        """Run one endpoint test in a fresh container; returns the per-test result shape."""
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

        result: dict[str, Any] = {
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

        started = time.perf_counter()
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

            params_data: dict[str, Any] = {}
            for source in (request_data, fixture):
                for sub_key in ("params", "path_params", "query_params", "path", "query"):
                    val = source.get(sub_key)
                    if isinstance(val, dict):
                        params_data.update(val)

            # Flat fixture keys only count when they name a declared parameter: fixture
            # metadata (`method`, `summary`, `status`, ...) must not become call arguments.
            declared = self._declared_names(endpoint) | {
                re.sub(r"[^a-z0-9]", "", name.lower()) for name in re.findall(r"\{([^}]+)\}", path)
            }
            for source in (request_data, fixture):
                for key, value in source.items():
                    if (
                        not isinstance(value, dict | list)
                        and re.sub(r"[^a-z0-9]", "", str(key).lower()) in declared
                    ):
                        params_data.setdefault(key, value)

            body_data = request_data.get("body")
            if body_data is None:
                for b_key in ("data", "json", "formData"):
                    if isinstance(request_data.get(b_key), dict | list):
                        body_data = request_data[b_key]
                        break

            exp_status = fixture.get("expected_status")
            if not isinstance(exp_status, int):
                exp_status = None
                resp_sc = endpoint.get("response_schemas") or endpoint.get("responses")
                if isinstance(resp_sc, dict):
                    for code in resp_sc:
                        try:
                            if 200 <= int(code) < 300:
                                exp_status = int(code)
                                break
                        except (ValueError, TypeError):
                            continue
                if exp_status is None:
                    exp_status = 201 if method == "POST" else (204 if method == "DELETE" else 200)

            payload = {
                "module_name": self._client_module,
                "client_file": self._client_file,
                "language": self._language,
                "op_id": op_id,
                "request": {"params": params_data, "body": body_data},
                "expected_status": exp_status,
                "base_url": self._base_url,
                "mock": None
                if self._network_enabled
                else self._mock_for(endpoint, fixture, method, path, exp_status),
            }
            await asyncio.to_thread(
                self._write_file, self._workspace / "payload.json", json.dumps(payload)
            )
            nonce = secrets.token_hex(16)
            environment = {
                "PYTHONDONTWRITEBYTECODE": "1",
                "APIWEAVER_PAYLOAD_PATH": "/sandbox/payload.json",
                "APIWEAVER_RESULT_NONCE": nonce,
            }
            if self._api_key:
                # Runtime secret injection (Security.md §7): the credential travels
                # in the container environment, never inside a file. Only a live run
                # can use it; a hermetic run gets a placeholder so clients that require
                # a key still construct, without handing the real secret to generated
                # code whose output (stack traces) is stored and fed back to the LLM.
                environment["APIWEAVER_API_KEY"] = (
                    self._api_key if self._network_enabled else HERMETIC_PLACEHOLDER_API_KEY
                )

            if self._language == "node":
                image = self._settings.sandbox_node_image
                command = ["node", "--experimental-strip-types", "/sandbox/runner.mjs"]
            else:
                image = self._settings.sandbox_image
                command = ["python", "-P", "/sandbox/runner.py"]

            outcome = await self._run_container(image=image, command=command, environment=environment)
            if outcome.timed_out:
                result["error"] = f"sandbox_timeout: exceeded {self._settings.sandbox_timeout_seconds}s"
                return result

            try:
                parsed = _parse_runner_result(outcome.output, nonce)
            except SandboxResultTampered as exc:
                result["error"] = f"sandbox result rejected: {exc}"
                return result
            if parsed is not None:
                for key in ("status", "status_code", "latency_ms", "response_snapshot", "error", "stack_trace"):
                    if key in parsed:
                        result[key] = parsed[key]
                if not result["latency_ms"] or result["latency_ms"] <= 0:
                    result["latency_ms"] = int((time.perf_counter() - started) * 1000)
            elif outcome.exit_code != 0:
                result["error"] = f"sandbox exited with code {outcome.exit_code}: {outcome.output[-2000:]}"
            else:
                result["error"] = "sandbox produced no result"
            return result
        except Exception as exc:
            result["error"] = str(exc)
            result["stack_trace"] = traceback.format_exc()
            return result

    async def cleanup(self, *, project_id: Any = None) -> None:
        if self._workspace is not None:
            workspace, self._workspace = self._workspace, None
            await asyncio.to_thread(shutil.rmtree, workspace, True)
