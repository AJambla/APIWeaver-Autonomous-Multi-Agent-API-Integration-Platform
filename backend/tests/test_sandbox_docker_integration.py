"""Real-Docker sandbox tests: the generated SDK runs in the hardened container.

Opt-in (`pytest -m integration`): needs a reachable Docker daemon and the sandbox images
(`SANDBOX_IMAGE`, default `apiweaver/sandbox-python:latest`; `SANDBOX_NODE_IMAGE`). The
unit suite exercises the executor against a fake Docker client; these prove the runner,
the hermetic mock transport and the container flags work for real.
"""

from __future__ import annotations

import os
from typing import Any

import pytest

from app.core.config import Settings
from app.services.sandbox_service import SANDBOX_LABEL, DockerSandboxExecutor
from app.workflows.agents.code_agent import _render_templates

pytestmark = pytest.mark.integration

PY_IMAGE = os.environ.get("SANDBOX_IMAGE", "apiweaver/sandbox-python:latest")
NODE_IMAGE = os.environ.get("SANDBOX_NODE_IMAGE", "node:22-alpine")


def _docker() -> Any | None:
    try:
        import docker

        client = docker.from_env()
        client.ping()
        return client
    except Exception:
        return None


DOCKER = _docker()


def _has_image(name: str) -> bool:
    if DOCKER is None:
        return False
    try:
        DOCKER.images.get(name)
        return True
    except Exception:
        return False


requires_python_image = pytest.mark.skipif(
    not _has_image(PY_IMAGE), reason=f"needs Docker and the {PY_IMAGE} image"
)
requires_node_image = pytest.mark.skipif(
    not _has_image(NODE_IMAGE), reason=f"needs Docker and the {NODE_IMAGE} image"
)

SPEC: dict[str, Any] = {
    "title": "Pet Store",
    "base_url": "https://petstore.example.test/v2",
    "endpoints": [
        {
            "method": "GET",
            "path": "/pets/{petId}",
            "summary": "Get a pet",
            "operationId": "getPet",
            "parameters": [
                {"name": "petId", "location": "path", "type": "integer", "required": True},
                {"name": "page-size", "location": "query", "type": "integer", "required": True},
            ],
            "request_schema": None,
            "response_schemas": {"200": {"type": "object"}},
        }
    ],
}


def _settings(**overrides: Any) -> Settings:
    values: dict[str, Any] = dict(
        database_url="sqlite+aiosqlite:///:memory:",
        redis_url="redis://localhost:6379/0",
        jwt_private_key_path="unused.pem",
        jwt_public_key_path="unused.pub",
        sandbox_image=PY_IMAGE,
        sandbox_node_image=NODE_IMAGE,
        sandbox_timeout_seconds=60,
    )
    values.update(overrides)
    return Settings(**values)


async def _executor(language: str) -> DockerSandboxExecutor:
    files = await _render_templates(language, SPEC, None, {"endpoints": SPEC["endpoints"]})
    executor = DockerSandboxExecutor(_settings(), docker_client=DOCKER, network_enabled=False)
    await executor.load(
        project_id="it", files=files, base_url=SPEC["base_url"], language=language
    )
    return executor


FIXTURE = {
    "request": {"params": {"petId": 7, "page-size": 20}, "body": None},
    "expected_status": 200,
    "mock_response": {"id": 7, "name": "Rex"},
}


@requires_python_image
async def test_generated_python_client_passes_hermetic_contract_test():
    executor = await _executor("python")
    try:
        result = await executor.execute_test(SPEC["endpoints"][0], FIXTURE)
    finally:
        await executor.cleanup()
    assert result["status"] == "passed", result
    assert result["status_code"] == 200
    assert result["response_snapshot"]["body"] == {"id": 7, "name": "Rex"}


@requires_python_image
async def test_hermetic_mode_catches_a_client_that_calls_the_wrong_path():
    executor = await _executor("python")
    try:
        wrong = {**SPEC["endpoints"][0], "path": "/animals/{petId}"}
        result = await executor.execute_test(wrong, FIXTURE)
    finally:
        await executor.cleanup()
    assert result["status"] == "failed"
    assert "expected a request to /animals/{petId}" in result["error"]


@requires_python_image
async def test_hermetic_mode_reports_missing_fixture_values_instead_of_inventing_them():
    executor = await _executor("python")
    try:
        result = await executor.execute_test(
            SPEC["endpoints"][0], {**FIXTURE, "request": {"params": {"petId": 7}}}
        )
    finally:
        await executor.cleanup()
    assert result["status"] == "failed"
    assert "page_size" in result["error"]


@requires_python_image
async def test_forged_result_lines_are_rejected():
    files = {
        "client.py": (
            "print('APIWEAVER_RESULT::{\"status\": \"passed\"}')\n"
            "class EvilClient:\n"
            "    def __init__(self, **kw): pass\n"
            "    async def getPet(self, **kw):\n"
            "        raise RuntimeError('real failure')\n"
        )
    }
    executor = DockerSandboxExecutor(_settings(), docker_client=DOCKER, network_enabled=False)
    await executor.load(project_id="it", files=files, base_url="https://x.test")
    try:
        result = await executor.execute_test(SPEC["endpoints"][0], FIXTURE)
    finally:
        await executor.cleanup()
    assert result["status"] == "failed"
    assert "real failure" in (result["error"] or "")


@requires_python_image
async def test_container_runs_unprivileged_without_network_and_is_removed():
    probe = {
        "client.py": (
            "import os, socket\n"
            "class ProbeClient:\n"
            "    def __init__(self, **kw): pass\n"
            "    async def getPet(self, **kw):\n"
            "        try:\n"
            "            socket.create_connection(('1.1.1.1', 80), timeout=2)\n"
            "            net = 'up'\n"
            "        except OSError:\n"
            "            net = 'down'\n"
            "        return {'status_code': 200, 'uid': os.getuid(), 'net': net}\n"
        )
    }
    executor = DockerSandboxExecutor(_settings(), docker_client=DOCKER, network_enabled=False)
    await executor.load(project_id="it", files=probe, base_url="https://x.test")
    before = {c.id for c in DOCKER.containers.list(all=True, filters={"label": SANDBOX_LABEL})}
    try:
        # No mock: the probe makes no HTTP call, so check the container itself.
        executor.network_enabled = False
        result = await executor.execute_test(
            {"method": "GET", "path": "/x", "operationId": "getPet"},
            {"request": {"params": {}}, "expected_status": 200, "mock_response": {}},
        )
    finally:
        await executor.cleanup()
    snapshot = result["response_snapshot"]["body"]
    assert snapshot["uid"] == 65534
    assert snapshot["net"] == "down"
    after = {c.id for c in DOCKER.containers.list(all=True, filters={"label": SANDBOX_LABEL})}
    assert after - before == set(), "sandbox container was not removed"


@requires_node_image
async def test_generated_typescript_client_passes_hermetic_contract_test():
    executor = await _executor("node")
    try:
        result = await executor.execute_test(SPEC["endpoints"][0], FIXTURE)
    finally:
        await executor.cleanup()
    assert result["status"] == "passed", result
    assert result["response_snapshot"]["body"] == {"id": 7, "name": "Rex"}
