"""Unit tests for the Docker sandbox executor (Track B1)."""

from __future__ import annotations

import asyncio
import io
import json
import sys
import time
import types
from contextlib import redirect_stdout
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.core.config import Settings
from app.services.sandbox_service import (
    _RESULT_PREFIX,
    RUNNER_SOURCE,
    DockerSandboxExecutor,
    _cpu_to_nano_cpus,
    _memory_to_bytes,
    _parse_runner_result,
)
from app.workflows.agents import test_agent as test_agent_module
from app.workflows.agents.test_agent import MockSandboxClient


class FakeContainer:
    def __init__(self, exit_code: int = 0, output: str = "", wait_delay: float = 0.0) -> None:
        self.exit_code = exit_code
        self.output = output
        self.wait_delay = wait_delay
        self.killed = False
        self.removed = False

    def wait(self) -> dict:
        if self.wait_delay:
            time.sleep(self.wait_delay)
        return {"StatusCode": self.exit_code}

    def kill(self) -> None:
        self.killed = True

    def logs(self) -> bytes:
        return self.output.encode("utf-8")

    def remove(self, force: bool = False) -> None:
        self.removed = True


class FakeDockerClient:
    def __init__(self, container: FakeContainer) -> None:
        self.container = container
        self.run_kwargs: dict = {}

    @property
    def containers(self) -> SimpleNamespace:
        return SimpleNamespace(run=self._run)

    def _run(self, image=None, command=None, **kwargs) -> FakeContainer:
        self.run_kwargs = {"image": image, "command": command, **kwargs}
        return self.container


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
    sentinel = _RESULT_PREFIX + json.dumps(
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
    assert kwargs["command"] == ["python", "/sandbox/runner.py"]
    assert kwargs["nano_cpus"] == 500_000_000
    assert kwargs["mem_limit"] == 256 * 1024**2
    assert kwargs["pids_limit"] == 64
    assert kwargs["cap_drop"] == ["ALL"]
    assert kwargs["user"] == "65534:65534"
    assert kwargs["network_disabled"] is True
    bind = list(kwargs["binds"].values())[0]
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


@pytest.mark.asyncio
async def test_execute_test_reports_failed_sentinel():
    sentinel = _RESULT_PREFIX + json.dumps(
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


@pytest.mark.asyncio
async def test_create_sandbox_selects_docker_executor(monkeypatch):
    captured: dict = {}

    class StubExecutor:
        def __init__(self, settings) -> None:
            captured["settings"] = settings

        async def load(self, *, project_id, files, base_url=None) -> None:
            captured["load"] = (project_id, files, base_url)

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
    )


@pytest.mark.asyncio
async def test_create_sandbox_defaults_to_mock(monkeypatch):
    monkeypatch.setattr(
        test_agent_module,
        "get_settings",
        lambda: SimpleNamespace(sandbox_backend="mock"),
    )

    sandbox = await test_agent_module._create_sandbox(
        {"project_id": "proj-1"}, [], {"title": "T"}
    )

    assert isinstance(sandbox, MockSandboxClient)
