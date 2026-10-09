"""Real-path E2E pipeline test (Track A5).

Drives the whole pipeline through the public API with zero injected workflow
state: register -> create project -> upload OpenAPI YAML (multipart) -> plan ->
PAUSED_FOR_APPROVAL -> dependency-graph edges persisted -> approve ->
generate / test / export -> COMPLETED.

Only two things are faked: `LLMClient.generate_json` (returns a deterministic
plan and a sandbox-friendly client) and the storage backend (in-memory).
Normalization, persistence, the orchestrator, sandbox execution, and export
all run the real code paths.
"""

from __future__ import annotations

import copy
import uuid
from typing import Any
from unittest.mock import patch

import pytest
from httpx import AsyncClient

import app.services.storage_service as storage_module
from app.workflows.llm import LLMClient
from tests.conftest import TEST_PASSWORD
from tests.fakes import InMemoryObjectStorage

# Generated code runs in real Docker sandboxes (the SANDBOX_IMAGE must exist locally).
pytestmark = pytest.mark.integration

SPEC_YAML = """\
openapi: "3.0.3"
info:
  title: Users API
  version: "1.0"
servers:
  - url: https://api.example.com/v1
paths:
  /users:
    get:
      operationId: listUsers
      summary: List users
      responses:
        "200":
          description: A list of users
    post:
      operationId: createUser
      summary: Create a user
      requestBody:
        content:
          application/json:
            schema:
              type: object
      responses:
        "201":
          description: Created
"""

SANDBOX_CLIENT_CODE = '''\
"""Sandbox-friendly generated client (deterministic test double)."""
import httpx


def _mock_handler(request: httpx.Request) -> httpx.Response:
    status = 201 if request.method == "POST" else 200
    return httpx.Response(status, json={"ok": True})


class SandboxEchoClient:
    def __init__(self, base_url=None, api_key=None, **kwargs):
        self._client = httpx.AsyncClient(
            base_url=base_url or "http://mock.local",
            transport=httpx.MockTransport(_mock_handler),
        )

    async def close(self):
        await self._client.aclose()

    # The hermetic sandbox checks the request each operation makes, so the double
    # behaves like a real client: the spec's method and path, relative to base_url.
    async def listUsers(self, **kwargs):
        return await self._client.get("users")

    async def createUser(self, body=None, **kwargs):
        return await self._client.post("users", json=body)
'''

SANDBOX_NODE_CLIENT_CODE = '''\
export class SandboxEchoClient {
    constructor(config = {}) {
        this.baseUrl = (config.baseUrl || "http://mock.local").replace(/\/+$/, "");
    }
    async listUsers() {
        const response = await fetch(`${this.baseUrl}/users`);
        return { status_code: response.status, data: await response.json() };
    }
    async createUser(body) {
        const response = await fetch(`${this.baseUrl}/users`, {
            method: "POST",
            headers: { "content-type": "application/json" },
            body: JSON.stringify(body ?? {}),
        });
        return { status_code: response.status, data: await response.json() };
    }
}
'''


async def _fake_generate_json(
    self: LLMClient,
    *,
    system_prompt: str,
    user_prompt: str,
    fallback_json: dict[str, Any] | None = None,
) -> tuple[dict[str, Any], int]:
    if system_prompt.startswith("You are the Planner Agent"):
        plan = copy.deepcopy(fallback_json) if fallback_json is not None else {}
        graph = plan.setdefault("dependency_graph", {"nodes": [], "edges": []})
        graph["edges"] = [
            {"from": "ep_1", "to": "ep_0", "relationship": "requires_created_resource"}
        ]
        return plan, 42
    if system_prompt.startswith("You are the Code Generator Agent"):
        if "generate node" in system_prompt.lower():
            return {"sandbox_e2e_client.ts": SANDBOX_NODE_CLIENT_CODE}, 42
        return {"sandbox_e2e_client.py": SANDBOX_CLIENT_CODE}, 42
    return (fallback_json if fallback_json is not None else {}), 42


async def test_full_pipeline_end_to_end(client: AsyncClient) -> None:
    register = await client.post(
        "/api/v1/auth/register",
        json={
            "email": f"e2e-{uuid.uuid4().hex[:8]}@example.com",
            "password": TEST_PASSWORD,
            "full_name": "E2E Tester",
            "organization_name": f"E2E Org {uuid.uuid4().hex[:6]}",
        },
    )
    assert register.status_code == 201, register.text
    headers = {"Authorization": f"Bearer {register.json()['access_token']}"}

    me = await client.get("/api/v1/auth/me", headers=headers)
    assert me.status_code == 200, me.text
    org_id = me.json()["organizations"][0]["organization_id"]

    project = await client.post(
        "/api/v1/projects",
        json={"name": "E2E Pipeline", "organization_id": org_id},
        headers=headers,
    )
    assert project.status_code == 201, project.text
    project_id = project.json()["id"]

    with (
        patch.object(storage_module, "_storage_instance", InMemoryObjectStorage()),
        patch.object(LLMClient, "generate_json", new=_fake_generate_json),
    ):
        upload = await client.post(
            f"/api/v1/projects/{project_id}/upload",
            files={"file": ("users-api.yaml", SPEC_YAML, "application/x-yaml")},
            headers=headers,
        )
        assert upload.status_code == 202, upload.text
        upload_body = upload.json()
        assert upload_body["endpoints_discovered"] == 2
        assert upload_body["api_spec_id"] is not None
        run_id = upload_body["workflow_run_id"]
        assert run_id

        run = await client.get(f"/api/v1/workflows/{run_id}", headers=headers)
        assert run.status_code == 200, run.text
        assert run.json()["status"] == "paused_for_approval"

        graph = await client.get(
            f"/api/v1/projects/{project_id}/dependency-graph", headers=headers
        )
        assert graph.status_code == 200, graph.text
        graph_body = graph.json()
        assert len(graph_body["nodes"]) == 2
        assert len(graph_body["edges"]) == 1
        edge = graph_body["edges"][0]
        assert edge["relationship"] == "requires_created_resource"
        node_ids = {node["id"] for node in graph_body["nodes"]}
        assert {edge["from_id"], edge["to_id"]} <= node_ids
        assert edge["from_id"] != edge["to_id"]

        approve = await client.post(
            f"/api/v1/workflows/{run_id}/approve",
            json={"approved": True, "notes": "Plan looks good"},
            headers=headers,
        )
        assert approve.status_code == 200, approve.text
        assert approve.json()["approved"] is True

        run = await client.get(f"/api/v1/workflows/{run_id}", headers=headers)
        assert run.status_code == 200, run.text
        final_run = run.json()
        assert final_run["status"] == "completed"
        assert final_run["progress_percent"] == 100
        assert final_run["completed_at"] is not None

    logs = await client.get(
        f"/api/v1/projects/{project_id}/logs?limit=100", headers=headers
    )
    assert logs.status_code == 200, logs.text
    events = logs.json()["data"]
    types = [event["event_type"] for event in events]
    assert "workflow_started" in types
    assert "workflow_finished" in types

    finished = next(e for e in events if e["event_type"] == "workflow_finished")
    assert finished["payload"]["status"] == "completed"

    planner_events = [e for e in events if e["agent_name"] == "planner_agent"]
    assert planner_events, "expected a planner_agent event"
    assert planner_events[0]["event_type"] == "stage_completed"
    assert planner_events[0]["payload"]["edges_written"] == 1

    test_events = [e for e in events if e["agent_name"] == "test_agent"]
    assert test_events, "expected a test_agent event"
    test_summary = test_events[0]["payload"]["test_summary"]
    assert test_summary["total"] == 4
    assert test_summary["passed"] == 4
    assert test_summary["failed"] == 0

    export_events = [e for e in events if e["agent_name"] == "export_agent"]
    assert export_events, "expected an export_agent event"

    tool_calls = await client.get(f"/api/v1/workflows/{run_id}/tool-calls", headers=headers)
    assert tool_calls.status_code == 200, tool_calls.text
    calls = tool_calls.json()
    uploads = [c for c in calls if c["tool_name"] == "storage.upload"]
    assert uploads, "expected storage.upload tool calls"
    sandbox_calls = [c for c in calls if c["tool_name"] == "sandbox.execute_test"]
    assert len(sandbox_calls) == 4
    assert all(c["result"]["status"] == "passed" for c in sandbox_calls)
