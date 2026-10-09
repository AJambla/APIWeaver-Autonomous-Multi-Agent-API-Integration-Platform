"""Unit tests for the Docker sandbox executor (Track B1)."""

from __future__ import annotations

import io
import json
import sys
import time
import types
from contextlib import redirect_stdout
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock

import pytest

from app.core.config import Settings
from app.services.sandbox_service import (
    _RESULT_PREFIX,
    HERMETIC_PLACEHOLDER_API_KEY,
    RUNNER_SOURCE,
    DockerSandboxExecutor,
    _cpu_to_nano_cpus,
    _memory_to_bytes,
    _parse_runner_result,
)
from app.workflows.agents import test_agent as test_agent_module


class FakeContainer:
    def __init__(self, exit_code: int = 0, output: str = "", wait_delay: float = 0.0) -> None:
        self.exit_code = exit_code
        self.output = output
        self.wait_delay = wait_delay
        self.killed = False
        self.removed = False
        self.archives: list[tuple[str, Any]] = []
        self.started = False
        # Set by FakeDockerClient: the environment the container was created with.
        self.environment: dict[str, str] = {}

    def wait(self) -> dict:
        if self.wait_delay:
            time.sleep(self.wait_delay)
        return {"StatusCode": self.exit_code}

    def kill(self) -> None:
        self.killed = True

    def logs(self, **kwargs: Any) -> bytes:
        # Sentinels are written with a `{NONCE}` placeholder; the real runner prints the
        # nonce the host passed in APIWEAVER_RESULT_NONCE.
        nonce = self.environment.get("APIWEAVER_RESULT_NONCE", "")
        return self.output.replace("{NONCE}", nonce).encode("utf-8")

    def remove(self, force: bool = False) -> None:
        self.removed = True

    def put_archive(self, path: str, data: Any) -> None:
        self.archives.append((path, data))

    def start(self) -> None:
        self.started = True


class FakeDockerClient:
    def __init__(self, container: FakeContainer) -> None:
        self.container = container
        self.run_kwargs: dict = {}
        self.create_kwargs: dict = {}

    @property
    def containers(self) -> SimpleNamespace:
        return SimpleNamespace(run=self._run, create=self._create)

    @property
    def volumes(self) -> SimpleNamespace:
        return SimpleNamespace(create=self._create_volume)

    def _run(self, image=None, command=None, **kwargs) -> FakeContainer:
        self.run_kwargs = {"image": image, "command": command, **kwargs}
        self.container.environment = kwargs.get("environment") or {}
        return self.container

    def _create(self, image=None, command=None, **kwargs) -> FakeContainer:
        self.create_kwargs = {"image": image, "command": command, **kwargs}
        self.container.environment = kwargs.get("environment") or {}
        return self.container

    def _create_volume(self, **kwargs) -> SimpleNamespace:
        return SimpleNamespace(name="fake-vol", remove=lambda force=False: None)


def _make_settings(**overrides) -> Settings:
    values = dict(
        database_url="sqlite+aiosqlite:///:memory:",
        redis_url="redis://localhost:6379/0",
        jwt_private_key_path="test-jwt-key.pem",
        jwt_public_key_path="test-jwt-key.pub",
        sandbox_backend="docker",
        sandbox_image="python:3.12-slim",
        sandbox_max_cpu="0.5",
        sandbox_max_memory="256Mi",
        sandbox_timeout_seconds=5,
        sandbox_pids_limit=64,
        sandbox_network_enabled=False,
    )
    values.update(overrides)
    return Settings(**values)


def test_cpu_quota_parsing():
    assert _cpu_to_nano_cpus("0.5") == 500_000_000
    assert _cpu_to_nano_cpus("500m") == 500_000_000
    assert _cpu_to_nano_cpus("1") == 1_000_000_000


def test_memory_quota_parsing():
    assert _memory_to_bytes("1Gi") == 1024**3
    assert _memory_to_bytes("256Mi") == 256 * 1024**2
    assert _memory_to_bytes("512Ki") == 512 * 1024
    assert _memory_to_bytes("1024") == 1024


@pytest.mark.asyncio
async def test_execute_test_enforces_quotas_and_parses_result():
    sentinel = _RESULT_PREFIX + "{NONCE}:" + json.dumps(
        {
            "status": "passed",
            "status_code": 200,
            "latency_ms": 7,
            "response_snapshot": {"status_code": 200, "headers": {}, "body": {"ok": True}},
            "error": None,
            "stack_trace": None,
        }
    )
    container = FakeContainer(exit_code=0, output="client noise\n" + sentinel + "\n")
    client = FakeDockerClient(container)
    executor = DockerSandboxExecutor(_make_settings(), docker_client=client)
    await executor.load(
        project_id="proj-1",
        files={"demo_client.py": "class DemoClient:\n    pass\n"},
        base_url="http://api.test",
    )

    result = await executor.execute_test(
        {"id": "ep_1", "method": "GET", "path": "/users", "operationId": "listUsers"},
        {"request": {"params": {"limit": 5}, "body": None}, "expected_status": 200},
    )

    assert result["status"] == "passed"
    assert result["status_code"] == 200
    assert result["latency_ms"] == 7
    assert result["response_snapshot"]["body"] == {"ok": True}

    kwargs = client.run_kwargs
    assert kwargs["image"] == "python:3.12-slim"
    assert kwargs["command"] == ["python", "-P", "/sandbox/runner.py"]
    assert kwargs["nano_cpus"] == 500_000_000
    assert kwargs["mem_limit"] == 256 * 1024**2
    assert kwargs["pids_limit"] == 64
    assert kwargs["cap_drop"] == ["ALL"]
    assert kwargs["user"] == "65534:65534"
    assert kwargs["network_disabled"] is True
    bind = list((kwargs.get("volumes") or kwargs.get("binds", {})).values())[0]
    assert bind["mode"] == "ro"
    assert bind["bind"] == "/sandbox"
    assert container.removed is True

    payload = json.loads(
        (executor._workspace / "payload.json").read_text(encoding="utf-8")
    )
    assert payload["module_name"] == "demo_client"
    assert payload["op_id"] == "listUsers"
    assert payload["base_url"] == "http://api.test"
    assert payload["expected_status"] == 200
    assert "api_key" not in payload
    assert "APIWEAVER_API_KEY" not in kwargs["environment"]


@pytest.mark.asyncio
async def test_execute_test_injects_credential_via_env():
    container = FakeContainer(exit_code=0, output="")
    client = FakeDockerClient(container)
    executor = DockerSandboxExecutor(_make_settings(), docker_client=client, network_enabled=True)
    await executor.load(
        project_id="proj-1",
        files={"client.py": "x = 1\n"},
        base_url="https://api.target.example",
        api_key="sk-live-secret",
    )

    await executor.execute_test({"method": "GET", "path": "/users"}, {})

    kwargs = client.run_kwargs
    assert kwargs["environment"]["APIWEAVER_API_KEY"] == "sk-live-secret"
    payload = json.loads(
        (executor._workspace / "payload.json").read_text(encoding="utf-8")
    )
    assert "api_key" not in payload


@pytest.mark.asyncio
async def test_execute_test_reports_failed_sentinel():
    sentinel = _RESULT_PREFIX + "{NONCE}:" + json.dumps(
        {
            "status": "failed",
            "status_code": 500,
            "latency_ms": 3,
            "response_snapshot": None,
            "error": "Expected status 200, got 500",
            "stack_trace": None,
        }
    )
    executor = DockerSandboxExecutor(
        _make_settings(), docker_client=FakeDockerClient(FakeContainer(0, sentinel + "\n"))
    )
    await executor.load(project_id="proj-1", files={"client.py": "x = 1\n"})

    result = await executor.execute_test({"method": "GET", "path": "/users"}, {})

    assert result["status"] == "failed"
    assert result["status_code"] == 500
    assert "Expected status 200, got 500" in result["error"]


@pytest.mark.asyncio
async def test_execute_test_timeout_kills_container():
    container = FakeContainer(exit_code=0, output="", wait_delay=2.0)
    executor = DockerSandboxExecutor(
        _make_settings(sandbox_timeout_seconds=1),
        docker_client=FakeDockerClient(container),
    )
    await executor.load(project_id="proj-1", files={"client.py": "x = 1\n"})

    result = await executor.execute_test({"method": "GET", "path": "/slow"}, {})

    assert result["status"] == "failed"
    assert "sandbox_timeout" in result["error"]
    assert container.killed is True
    assert container.removed is True


@pytest.mark.asyncio
async def test_execute_test_nonzero_exit_without_sentinel():
    executor = DockerSandboxExecutor(
        _make_settings(),
        docker_client=FakeDockerClient(FakeContainer(1, "Traceback ...\nboom\n")),
    )
    await executor.load(project_id="proj-1", files={"client.py": "x = 1\n"})

    result = await executor.execute_test({"method": "GET", "path": "/x"}, {})

    assert result["status"] == "failed"
    assert "sandbox exited with code 1" in result["error"]
    assert "boom" in result["error"]


@pytest.mark.asyncio
async def test_execute_test_without_load_fails_gracefully():
    executor = DockerSandboxExecutor(
        _make_settings(), docker_client=FakeDockerClient(FakeContainer())
    )

    result = await executor.execute_test({"method": "GET", "path": "/x"}, {})

    assert result["status"] == "failed"
    assert result["error"] == "Sandbox workspace not prepared"


def test_runner_source_executes_payload(tmp_path, monkeypatch):
    payload = {
        "module_name": "stub_sandbox_module",
        "op_id": "list_users",
        "request": {"params": {}, "body": None},
        "expected_status": 200,
        "base_url": "http://api.test",
        "api_key": "secret-do-not-log",
    }
    (tmp_path / "payload.json").write_text(json.dumps(payload), encoding="utf-8")
    monkeypatch.setenv("APIWEAVER_PAYLOAD_PATH", str(tmp_path / "payload.json"))

    class StubClient:
        def __init__(self, base_url=None, api_key=None, **kwargs) -> None:
            self.base_url = base_url
            self.api_key = api_key

        async def list_users(self, **kwargs):
            return SimpleNamespace(
                status_code=200,
                headers={"content-type": "application/json"},
                json=lambda: {"ok": True},
            )

        async def close(self) -> None:
            return None

    module = types.ModuleType("stub_sandbox_module")
    module.StubClient = StubClient
    monkeypatch.setitem(sys.modules, "stub_sandbox_module", module)

    runner_globals: dict = {"__name__": "apiweaver_runner_under_test"}
    exec(compile(RUNNER_SOURCE, "<runner>", "exec"), runner_globals)

    buffer = io.StringIO()
    with redirect_stdout(buffer):
        exit_code = runner_globals["_run"]()

    assert exit_code == 0
    parsed = _parse_runner_result(buffer.getvalue())
    assert parsed is not None
    assert parsed["status"] == "passed"
    assert parsed["status_code"] == 200
    assert parsed["response_snapshot"]["body"] == {"ok": True}
    assert parsed["error"] is None


def test_runner_source_prefers_env_credential(tmp_path, monkeypatch):
    payload = {
        "module_name": "stub_sandbox_module",
        "op_id": "list_users",
        "request": {"params": {}, "body": None},
        "expected_status": 200,
        "base_url": "http://api.test",
    }
    (tmp_path / "payload.json").write_text(json.dumps(payload), encoding="utf-8")
    monkeypatch.setenv("APIWEAVER_PAYLOAD_PATH", str(tmp_path / "payload.json"))
    monkeypatch.setenv("APIWEAVER_API_KEY", "env-injected-secret")

    seen: dict = {}

    class StubClient:
        def __init__(self, base_url=None, api_key=None, **kwargs) -> None:
            seen["base_url"] = base_url
            seen["api_key"] = api_key

        async def list_users(self, **kwargs):
            return SimpleNamespace(
                status_code=200,
                headers={},
                json=lambda: {"ok": True},
            )

        async def close(self) -> None:
            return None

    module = types.ModuleType("stub_sandbox_module")
    module.StubClient = StubClient
    monkeypatch.setitem(sys.modules, "stub_sandbox_module", module)

    runner_globals: dict = {"__name__": "apiweaver_runner_under_test"}
    exec(compile(RUNNER_SOURCE, "<runner>", "exec"), runner_globals)

    buffer = io.StringIO()
    with redirect_stdout(buffer):
        exit_code = runner_globals["_run"]()

    assert exit_code == 0
    assert seen == {"base_url": "http://api.test", "api_key": "env-injected-secret"}


@pytest.mark.asyncio
async def test_create_sandbox_selects_docker_executor(monkeypatch):
    captured: dict = {}

    class StubExecutor:
        def __init__(self, settings, *, network_enabled=False) -> None:
            captured["settings"] = settings

        async def load(self, *, project_id, files, base_url=None, api_key=None) -> None:
            captured["load"] = (project_id, files, base_url, api_key)

    monkeypatch.setattr(test_agent_module, "DockerSandboxExecutor", StubExecutor)
    monkeypatch.setattr(
        test_agent_module,
        "get_settings",
        lambda: SimpleNamespace(sandbox_backend="docker"),
    )
    monkeypatch.setattr(
        test_agent_module,
        "storage_service",
        SimpleNamespace(download=AsyncMock(return_value=b"class X:\n    pass\n")),
    )

    sandbox = await test_agent_module._create_sandbox(
        {"project_id": "proj-1"},
        [{"file_path": "client.py", "content_s3_key": "k", "language": "python"}],
        {"base_url": "http://api.test"},
    )

    assert isinstance(sandbox, StubExecutor)
    assert captured["load"] == (
        "proj-1",
        {"client.py": "class X:\n    pass\n"},
        "http://api.test",
        None,
    )


@pytest.mark.asyncio
async def test_create_sandbox_passes_resolved_credential(monkeypatch):
    captured: dict = {}

    class StubExecutor:
        def __init__(self, settings, *, network_enabled=False) -> None:
            pass

        async def load(self, *, project_id, files, base_url=None, api_key=None) -> None:
            captured["api_key"] = api_key

    monkeypatch.setattr(test_agent_module, "DockerSandboxExecutor", StubExecutor)
    monkeypatch.setattr(
        test_agent_module,
        "get_settings",
        lambda: SimpleNamespace(sandbox_backend="docker"),
    )
    monkeypatch.setattr(
        test_agent_module,
        "storage_service",
        SimpleNamespace(download=AsyncMock(return_value=b"class X:\n    pass\n")),
    )

    await test_agent_module._create_sandbox(
        {"project_id": "proj-1"},
        [{"file_path": "client.py", "content_s3_key": "k", "language": "python"}],
        {"base_url": "http://api.test"},
        auth={
            "scheme": "api_key",
            "config": {},
            "credentials": {"api_key": "sk-vault-secret"},
        },
    )

    assert captured["api_key"] == "sk-vault-secret"


@pytest.mark.asyncio
async def test_create_sandbox_selects_docker_by_default(monkeypatch):
    monkeypatch.setattr(
        test_agent_module,
        "get_settings",
        lambda: SimpleNamespace(sandbox_backend="docker"),
    )

    sandbox = await test_agent_module._create_sandbox(
        {"project_id": "proj-1"}, [], {"title": "T"}
    )

    assert isinstance(sandbox, DockerSandboxExecutor)


# --- C2 regression tests: path traversal + sandbox backend default -----------


def test_sandbox_backend_defaults_to_docker(monkeypatch):
    monkeypatch.delenv("SANDBOX_BACKEND", raising=False)
    settings = Settings(
        database_url="sqlite+aiosqlite:///:memory:",
        redis_url="redis://localhost:6379/0",
        jwt_private_key_path="test-jwt-key.pem",
        jwt_public_key_path="test-jwt-key.pub",
    )
    assert settings.sandbox_backend == "docker"


@pytest.mark.asyncio
async def test_load_skips_path_traversal(tmp_path, monkeypatch):
    import tempfile

    workspace = tmp_path / "ws"
    workspace.mkdir()
    monkeypatch.setattr(tempfile, "mkdtemp", lambda prefix="": str(workspace))

    executor = DockerSandboxExecutor(
        _make_settings(), docker_client=FakeDockerClient(FakeContainer())
    )
    await executor.load(
        project_id="proj-1",
        files={
            "pkg/client.py": "class DemoClient:\n    pass\n",
            "nested/./ok.py": "ok",
            "../escape.py": "bad",
            "/abs/escape.py": "bad",
            r"..\\win_escape.py": "bad",
            r"C:\\drive_escape.py": "bad",
            "a/../../up.py": "bad",
        },
    )

    assert (workspace / "pkg" / "client.py").exists()
    assert (workspace / "nested" / "ok.py").exists()
    assert not (tmp_path / "escape.py").exists()
    assert not (tmp_path / "win_escape.py").exists()
    assert not (tmp_path / "up.py").exists()
    await executor.cleanup()


@pytest.mark.asyncio
async def test_docker_executor_prepare_and_run_test():
    container = FakeContainer(exit_code=0, output="test passed")
    client = FakeDockerClient(container)
    settings = _make_settings()
    executor = DockerSandboxExecutor(settings, docker_client=client)

    await executor.prepare(
        project_id="proj-1",
        language="python",
        files={"client.py": "class Client: pass"},
    )
    assert (executor._workspace / "client.py").exists()

    res = await executor.run_test(
        project_id="proj-1",
        test_file="test_client.py",
        test_code="def test_ok(): pass",
    )
    assert res.exit_code == 0
    assert res.stdout == "test passed"
    await executor.cleanup()


@pytest.mark.asyncio
async def test_execute_node_test_selects_node_image_and_runner():
    """Verify that staged Node.js/TS files select node:22-alpine and runner.mjs."""
    sentinel = _RESULT_PREFIX + "{NONCE}:" + json.dumps(
        {
            "status": "passed",
            "status_code": 200,
            "latency_ms": 12,
            "response_snapshot": {"users": []},
            "error": None,
            "stack_trace": None,
        }
    )
    container = FakeContainer(exit_code=0, output=sentinel)
    client = FakeDockerClient(container)
    settings = _make_settings(sandbox_node_image="node:22-alpine")
    executor = DockerSandboxExecutor(settings, docker_client=client)

    await executor.load(
        project_id="node-proj",
        files={
            "client.ts": "export class PetClient { async getPets() { return { status: 200, data: [] }; } }",
            "types.ts": "export interface Pet { id: string; }",
        },
        base_url="http://api.node.test",
    )

    assert executor._language == "node"
    assert executor._client_file == "client.ts"
    assert (executor._workspace / "runner.mjs").exists()

    result = await executor.execute_test(
        {"id": "ep_1", "method": "GET", "path": "/pets", "operationId": "getPets"},
        {"request": {}, "expected_status": 200},
    )

    assert result["status"] == "passed"
    assert result["status_code"] == 200
    assert result["latency_ms"] == 12

    kwargs = client.run_kwargs
    assert kwargs["image"] == "node:22-alpine"
    assert kwargs["command"] == ["node", "--experimental-strip-types", "/sandbox/runner.mjs"]
    assert kwargs["mem_limit"] == 256 * 1024**2
    assert kwargs["user"] == "65534:65534"
    assert kwargs["read_only"] is True
    assert kwargs["security_opt"] == ["no-new-privileges:true"]

    payload = json.loads((executor._workspace / "payload.json").read_text(encoding="utf-8"))
    assert payload["client_file"] == "client.ts"
    assert payload["language"] == "node"
    assert payload["op_id"] == "getPets"


def test_docker_sandbox_custom_docker_host(monkeypatch):
    """Verify DockerSandboxExecutor connects to custom docker_host when configured."""
    captured_hosts = []

    class _MockDockerModule:
        @staticmethod
        def DockerClient(base_url):
            captured_hosts.append(base_url)
            return "custom_client_instance"

    import sys
    monkeypatch.setitem(sys.modules, "docker", _MockDockerModule)

    settings = _make_settings(docker_host="tcp://docker-dind:2375")
    executor = DockerSandboxExecutor(settings)
    client = executor._get_docker_client()

    assert client == "custom_client_instance"
    assert captured_hosts == ["tcp://docker-dind:2375"]


@pytest.mark.asyncio
async def test_docker_executor_run_test_reports_failure_on_exception():
    """Verify run_test returns non-zero exit code when docker execution encounters an exception."""
    container = FakeContainer(exit_code=1, output="Traceback: SyntaxError")
    client = FakeDockerClient(container)
    settings = _make_settings()
    executor = DockerSandboxExecutor(settings, docker_client=client)

    res = await executor.run_test(
        project_id="proj-1",
        test_file="test_invalid.py",
        test_code="def invalid syntax :::: ",
    )
    assert res.exit_code == 1
    await executor.cleanup()


def test_deterministic_fixtures_use_spec_examples_and_enums():
    """Verify _generate_deterministic_fixture uses spec example/default/enum instead of petstore literals."""
    from app.workflows.agents.test_agent import _generate_deterministic_fixture

    ep = {
        "method": "POST",
        "path": "/widgets/{widget_id}",
        "parameters": [
            {"name": "widget_id", "location": "path", "type": "string", "example": "wdg_123"},
            {"name": "mode", "location": "query", "type": "string", "default": "fast"},
            {"name": "status", "location": "query", "type": "string", "enum": ["active", "paused"]},
        ],
        "request_schema": {
            "type": "object",
            "properties": {
                "sku": {"type": "string", "example": "SKU-999"},
                "count": {"type": "integer", "default": 42},
            },
        },
        "response_schemas": {"201": {"type": "object"}},
    }
    fixture = _generate_deterministic_fixture(ep)
    assert fixture["request"]["params"]["widget_id"] == "wdg_123"
    assert fixture["request"]["params"]["mode"] == "fast"
    assert fixture["request"]["params"]["status"] == "active"
    assert fixture["request"]["body"]["sku"] == "SKU-999"
    assert fixture["request"]["body"]["count"] == 42
    assert fixture["expected_status"] == 201



# --- Hardening: result nonce, target vetting, path matching, reaping ----------------

from app.services.sandbox_service import (  # noqa: E402
    SANDBOX_CREATED_LABEL,
    SANDBOX_LABEL,
    SandboxResultTampered,
    assert_public_target,
    endpoint_path_regex,
    reap_orphaned_sandboxes,
)


def test_result_lines_must_carry_the_nonce_exactly_once():
    good = _RESULT_PREFIX + "abc:" + json.dumps({"status": "passed"})
    forged = _RESULT_PREFIX + "zzz:" + json.dumps({"status": "passed"})
    assert _parse_runner_result(f"noise\n{forged}\n", "abc") is None
    assert _parse_runner_result(f"{forged}\n{good}\n", "abc") == {"status": "passed"}
    with pytest.raises(SandboxResultTampered):
        _parse_runner_result(f"{good}\n{good}\n", "abc")


@pytest.mark.parametrize(
    ("path", "request_path", "matches"),
    [
        ("/pets/{petId}", "/v2/pets/7", True),
        ("/pets/{petId}", "/pets/7/", True),
        ("/pets/{petId}", "/pets", False),
        ("/pets/{petId}", "/animals/7", False),
        ("/a.b/{x}", "/aXb/1", False),
    ],
)
def test_endpoint_path_regex(path, request_path, matches):
    import re

    assert bool(re.search(endpoint_path_regex(path), request_path)) is matches


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "url",
    [
        "http://127.0.0.1:8000",
        "http://169.254.169.254/latest/meta-data",
        "http://10.0.0.5",
        "http://[::1]/",
        "ftp://example.com",
        "/relative/only",
    ],
)
async def test_live_targets_on_private_addresses_are_refused(url):
    with pytest.raises(ValueError):
        await assert_public_target(url)


@pytest.mark.asyncio
async def test_private_targets_allowed_only_when_opted_in():
    await assert_public_target("http://127.0.0.1:8000", allow_private=True)


@pytest.mark.asyncio
async def test_public_targets_pass(monkeypatch):
    import asyncio as _asyncio

    async def fake_getaddrinfo(host, port, **kwargs):
        return [(None, None, None, "", ("93.184.216.34", port))]

    loop = _asyncio.get_running_loop()
    monkeypatch.setattr(loop, "getaddrinfo", fake_getaddrinfo)
    await assert_public_target("https://api.example.com/v1")


def test_reaper_removes_only_old_labelled_sandboxes():
    now = time.time()

    class Item:
        def __init__(self, age: float) -> None:
            self.labels = {SANDBOX_LABEL: "true", SANDBOX_CREATED_LABEL: str(now - age)}
            self.attrs = {"Labels": self.labels}
            self.removed = False

        def remove(self, force: bool = False) -> None:
            self.removed = True

    old, fresh, old_volume = Item(4000), Item(10), Item(4000)
    seen_filters: list = []

    def list_containers(all: bool = False, filters=None):
        seen_filters.append(filters)
        return [old, fresh]

    client = SimpleNamespace(
        containers=SimpleNamespace(list=list_containers),
        volumes=SimpleNamespace(list=lambda filters=None: [old_volume]),
    )

    assert reap_orphaned_sandboxes(client, max_age_seconds=600) == 2
    assert old.removed and old_volume.removed and not fresh.removed
    assert seen_filters == [{"label": SANDBOX_LABEL}]


@pytest.mark.asyncio
async def test_containers_are_labelled_and_swap_capped():
    container = FakeContainer(exit_code=0, output="")
    client = FakeDockerClient(container)
    executor = DockerSandboxExecutor(_make_settings(), docker_client=client)
    await executor.load(project_id="p", files={"client.py": "x = 1\n"})

    await executor.execute_test({"method": "GET", "path": "/users"}, {})

    kwargs = client.run_kwargs
    assert kwargs["labels"][SANDBOX_LABEL] == "true"
    assert kwargs["memswap_limit"] == kwargs["mem_limit"]
    assert kwargs["environment"]["APIWEAVER_RESULT_NONCE"]
    payload = json.loads((executor._workspace / "payload.json").read_text(encoding="utf-8"))
    assert payload["mock"]["method"] == "GET"
    assert payload["mock"]["path"] == "/users"


@pytest.mark.asyncio
async def test_live_executor_sends_no_mock_and_uses_configured_egress():
    container = FakeContainer(exit_code=0, output="")
    client = FakeDockerClient(container)
    settings = _make_settings(sandbox_network="sandbox-egress", sandbox_egress_proxy="http://proxy:3128")
    executor = DockerSandboxExecutor(settings, docker_client=client, network_enabled=True)
    await executor.load(project_id="p", files={"client.py": "x = 1\n"})

    await executor.execute_test({"method": "GET", "path": "/users"}, {})

    kwargs = client.run_kwargs
    assert kwargs["network_disabled"] is False
    assert kwargs["network"] == "sandbox-egress"
    assert kwargs["environment"]["HTTPS_PROXY"] == "http://proxy:3128"
    payload = json.loads((executor._workspace / "payload.json").read_text(encoding="utf-8"))
    assert payload["mock"] is None


@pytest.mark.asyncio
async def test_hermetic_run_never_receives_the_real_credential():
    """A mock-answered run cannot use the key; generated code must not see it either."""
    container = FakeContainer(exit_code=0, output="")
    client = FakeDockerClient(container)
    executor = DockerSandboxExecutor(_make_settings(), docker_client=client)
    await executor.load(
        project_id="proj-1",
        files={"client.py": "x = 1\n"},
        base_url="https://api.target.example",
        api_key="sk-live-secret",
    )

    await executor.execute_test({"method": "GET", "path": "/users"}, {})

    kwargs = client.run_kwargs
    assert kwargs["network_disabled"] is True
    assert kwargs["environment"]["APIWEAVER_API_KEY"] == HERMETIC_PLACEHOLDER_API_KEY
    assert "sk-live-secret" not in json.dumps(kwargs["environment"])


def test_the_deprecated_network_flag_does_not_network_an_executor():
    settings = _make_settings(sandbox_network_enabled=True)
    assert DockerSandboxExecutor(settings).network_enabled is False
