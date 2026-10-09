"""Tests for Export Agent and API (`Feature.md §15-24`)."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import AsyncClient

from app.workflows.agents.export_agent import ExportAgent
from app.workflows.state import WorkflowState


class TestExportAgent:
    """Unit tests for the Export Agent."""

    @pytest.fixture
    def mock_state(self) -> WorkflowState:
        return WorkflowState(
            project_id="test-project",
            organization_id="test-org",
            workflow_run_id="test-run",
            stages=["export"],
            target_languages=["python", "node"],
            normalized_spec={
                "title": "Test API",
                "base_url": "https://api.example.com/v1",
                "endpoints": [
                    {
                        "method": "GET",
                        "path": "/users",
                        "summary": "List users",
                        "operationId": "listUsers",
                        "parameters": [
                            {"name": "limit", "location": "query", "type": "integer", "required": False}
                        ],
                        "request_schema": None,
                        "response_schemas": {
                            "200": {"type": "array", "items": {"type": "object"}}
                        },
                    },
                    {
                        "method": "POST",
                        "path": "/users",
                        "summary": "Create user",
                        "operationId": "createUser",
                        "parameters": [],
                        "request_schema": {"type": "object", "properties": {"name": {"type": "string"}}},
                        "response_schemas": {"201": {"type": "object"}},
                    }
                ],
            },
            execution_plan={
                "phases": [
                    {
                        "phase_number": 1,
                        "name": "Users",
                        "endpoints": ["GET /users", "POST /users"],
                    }
                ]
            },
            plan_approved=True,
            generated_files=[
                {
                    "file_path": "client.py",
                    "content_s3_key": "generated/test-project/client.py",
                    "language": "python",
                    "file_type": "sdk",
                },
                {
                    "file_path": "client.ts",
                    "content_s3_key": "generated/test-project/client.ts",
                    "language": "node",
                    "file_type": "sdk",
                }
            ],
            test_suite=[
                {"endpoint_id": "1", "method": "GET", "path": "/users", "status": "passed", "status_code": 200},
                {"endpoint_id": "2", "method": "POST", "path": "/users", "status": "passed", "status_code": 201},
            ],
            test_run_summary={"total": 2, "passed": 2, "failed": 0, "skipped": 0, "pass_rate": 1.0},
            errors=[],
            total_tokens_used=0,
            status="running",
            progress_percent=0,
            current_node="",
        )

    @pytest.mark.asyncio
    async def test_package_sdk(self, mock_state):
        """Test SDK packaging."""
        with patch("app.workflows.agents.export_agent.storage_service") as mock_storage:
            mock_storage.download = AsyncMock(return_value=b"# test content")
            mock_storage.upload = AsyncMock()

            agent = ExportAgent()
            result = await agent._package_sdk(
                project_id="test-project",
                generated_files=mock_state["generated_files"],
                test_run_summary=mock_state["test_run_summary"],
                target_languages=mock_state["target_languages"],
                normalized_spec=mock_state["normalized_spec"],
            )

            assert result["type"] == "sdk"
            assert len(result["artifacts"]) == 2  # python + node

    @pytest.mark.asyncio
    async def test_package_client(self, mock_state):
        """Test client packaging."""
        with patch("app.workflows.agents.export_agent.storage_service") as mock_storage:
            mock_storage.download = AsyncMock(return_value=b"# test content")
            mock_storage.upload = AsyncMock()

            agent = ExportAgent()
            result = await agent._package_client(
                project_id="test-project",
                generated_files=mock_state["generated_files"],
                normalized_spec=mock_state["normalized_spec"],
            )

            assert result["type"] == "client"
            assert len(result["artifacts"]) == 2  # python + node

    @pytest.mark.asyncio
    async def test_package_docker(self, mock_state):
        """Test Docker packaging."""
        with patch("app.workflows.agents.export_agent.storage_service") as mock_storage:
            mock_storage.upload = AsyncMock()

            agent = ExportAgent()
            result = await agent._package_docker(
                project_id="test-project",
                target_languages=mock_state["target_languages"],
                normalized_spec=mock_state["normalized_spec"],
            )

            assert result["type"] == "docker"
            assert len(result["artifacts"]) == 2  # Dockerfile + docker-compose.yml

    @pytest.mark.asyncio
    async def test_package_mcp(self, mock_state):
        """Test MCP packaging and generated server script."""
        uploaded_files = {}

        async def capture_upload(key: str, data: bytes):
            uploaded_files[key] = data

        with patch("app.workflows.agents.export_agent.storage_service") as mock_storage:
            mock_storage.upload = AsyncMock(side_effect=capture_upload)

            agent = ExportAgent()
            result = await agent._package_mcp(
                project_id="test-project",
                normalized_spec=mock_state["normalized_spec"],
            )

            assert result["type"] == "mcp"
            assert result["status"] == "completed"
            assert result["tools_generated"] == 2
            assert result["flagged_destructive"] == 0
            assert len(result["artifacts"]) == 2

            # Validate manifest artifact
            manifest_key = "exports/test-project/mcp/manifest.json"
            assert manifest_key in uploaded_files
            manifest_data = json.loads(uploaded_files[manifest_key].decode("utf-8"))
            assert manifest_data["tools_count"] == 2
            assert len(manifest_data["tools"]) == 2
            tool_names = [t["name"] for t in manifest_data["tools"]]
            assert "listUsers" in tool_names
            assert "createUser" in tool_names

            # Validate server artifact
            server_key = "exports/test-project/mcp/server.py"
            assert server_key in uploaded_files
            server_code = uploaded_files[server_key].decode("utf-8")
            assert "execute_http_call" in server_code
            assert "handle_message" in server_code

            # Test JSON-RPC execution by running server's handle_message
            namespace = {}
            exec(server_code, namespace)
            handle_message = namespace["handle_message"]
            tools_list = manifest_data["tools"]
            tools_map = {t["name"]: t for t in tools_list}

            # 1. initialize handshake
            init_res = handle_message({"jsonrpc": "2.0", "id": 1, "method": "initialize"}, tools_list, tools_map)
            assert init_res["result"]["protocolVersion"] == "2024-11-05"
            assert "tools" in init_res["result"]["capabilities"]

            # 2. tools/list
            list_res = handle_message({"jsonrpc": "2.0", "id": 2, "method": "tools/list"}, tools_list, tools_map)
            assert len(list_res["result"]["tools"]) == 2

            # 3. tools/call unknown tool
            call_err = handle_message({"jsonrpc": "2.0", "id": 3, "method": "tools/call", "params": {"name": "unknown"}}, tools_list, tools_map)
            assert "error" in call_err
            assert call_err["error"]["code"] == -32601

            # 4. tools/call known tool (mocking urllib)
            with patch("urllib.request.urlopen") as mock_urlopen:
                mock_resp = MagicMock()
                mock_resp.read.return_value = b'{"status": "ok"}'
                mock_urlopen.return_value.__enter__.return_value = mock_resp
                call_ok = handle_message(
                    {"jsonrpc": "2.0", "id": 4, "method": "tools/call", "params": {"name": "listUsers", "arguments": {"limit": 10}}},
                    tools_list,
                    tools_map,
                )
                assert call_ok["result"]["isError"] is False
                assert call_ok["result"]["content"][0]["text"] == '{"status": "ok"}'

    @pytest.mark.asyncio
    async def test_package_docs(self, mock_state):
        """Test docs packaging."""
        with patch("app.workflows.agents.export_agent.storage_service") as mock_storage:
            mock_storage.upload = AsyncMock()

            agent = ExportAgent()
            result = await agent._package_docs(
                project_id="test-project",
                normalized_spec=mock_state["normalized_spec"],
            )

            assert result["type"] == "docs"
            assert len(result["artifacts"]) == 2  # openapi.json + reference.md

    @pytest.mark.asyncio
    async def test_package_cicd(self, mock_state):
        """Test CI/CD packaging."""
        with patch("app.workflows.agents.export_agent.storage_service") as mock_storage:
            mock_storage.upload = AsyncMock()

            agent = ExportAgent()
            result = await agent._package_cicd(
                project_id="test-project",
                target_languages=mock_state["target_languages"],
            )

            assert result["type"] == "cicd"
            assert len(result["artifacts"]) == 2  # python + node workflows

    @pytest.mark.asyncio
    async def test_run_full_export(self, mock_state):
        """Test full export pipeline."""
        with patch("app.workflows.agents.export_agent.storage_service") as mock_storage:
            mock_storage.download = AsyncMock(return_value=b"# test content")
            mock_storage.upload = AsyncMock()

            agent = ExportAgent()
            result = await agent.run(mock_state, export_types=["sdk", "client", "docker", "mcp", "docs", "cicd"])

            assert result["status"] in ("completed", "completed_with_errors")
            assert "exports" in result
            assert len(result["exports"]) == 6


OPENAPI_SPEC = b'''openapi: 3.0.3
info:
  title: Test Export API
  version: 1.0.0
servers:
  - url: https://api.example.test/v1
paths:
  /items:
    get:
      summary: List items
      operationId: listItems
      parameters:
        - name: limit
          in: query
          schema: {type: integer}
      responses:
        "200":
          description: OK
          content:
            application/json:
              schema: {type: array}
'''


class TestExportAPI:
    """Integration tests for the Export API."""

    async def _setup_project(self, client: AsyncClient, auth_headers: dict[str, str]) -> str:
        me = await client.get("/api/v1/auth/me", headers=auth_headers)
        assert me.status_code == 200, me.text
        org_id = me.json()["organizations"][0]["organization_id"]
        res = await client.post(
            "/api/v1/projects",
            json={"name": "Export Test Project", "organization_id": org_id},
            headers=auth_headers,
        )
        assert res.status_code == 201, res.text
        return res.json()["id"]

    @pytest.mark.asyncio
    async def test_trigger_export_endpoint(self, client: AsyncClient, auth_headers: dict[str, str]):
        """Test POST /projects/{id}/export endpoint."""
        project_id = await self._setup_project(client, auth_headers)
        res = await client.post(
            f"/api/v1/projects/{project_id}/export",
            headers=auth_headers,
            json={"export_types": ["mcp", "docker"]},
        )
        assert res.status_code == 202, res.text
        data = res.json()
        assert "export_id" in data
        assert len(data["artifacts"]) == 2
        types = [a["type"] for a in data["artifacts"]]
        assert "mcp" in types
        assert "docker" in types
        assert all(a["status"] == "queued" for a in data["artifacts"])

    @pytest.mark.asyncio
    async def test_trigger_export_rejects_unknown_or_empty_types(
        self, client: AsyncClient, auth_headers: dict[str, str]
    ):
        """Unknown types used to reach the `exports` CHECK and answer 500 on Postgres."""
        project_id = await self._setup_project(client, auth_headers)
        for body in ({"export_types": ["zip-bomb"]}, {"export_types": []}):
            res = await client.post(
                f"/api/v1/projects/{project_id}/export", headers=auth_headers, json=body
            )
            assert res.status_code == 400, res.text

    @pytest.mark.asyncio
    async def test_trigger_export_accepts_fastapi_and_defaults_exclude_github(
        self, client: AsyncClient, auth_headers: dict[str, str]
    ):
        project_id = await self._setup_project(client, auth_headers)
        res = await client.post(
            f"/api/v1/projects/{project_id}/export",
            headers=auth_headers,
            json={"export_types": ["fastapi", "fastapi"]},
        )
        assert res.status_code == 202, res.text
        assert [a["type"] for a in res.json()["artifacts"]] == ["fastapi"]

        res = await client.post(f"/api/v1/projects/{project_id}/export", headers=auth_headers, json={})
        assert res.status_code == 202, res.text
        types = {a["type"] for a in res.json()["artifacts"]}
        assert "github" not in types
        assert {"sdk", "client", "fastapi", "mcp"} <= types

    @pytest.mark.asyncio
    async def test_export_mcp_endpoint_no_spec(self, client: AsyncClient, auth_headers: dict[str, str]):
        """Test POST /projects/{id}/export/mcp without normalized spec returns 404."""
        project_id = await self._setup_project(client, auth_headers)
        res = await client.post(
            f"/api/v1/projects/{project_id}/export/mcp",
            headers=auth_headers,
        )
        assert res.status_code == 404, res.text
        assert res.json()["error"]["code"] == "NOT_FOUND"

    @pytest.mark.asyncio
    async def test_export_mcp_endpoint_success(self, client: AsyncClient, auth_headers: dict[str, str]):
        """Test POST /projects/{id}/export/mcp with valid spec returns 200."""
        project_id = await self._setup_project(client, auth_headers)

        # Upload spec
        upload_res = await client.post(
            f"/api/v1/projects/{project_id}/upload",
            headers=auth_headers,
            files={"file": ("openapi.yaml", OPENAPI_SPEC, "application/yaml")},
        )
        assert upload_res.status_code == 202, upload_res.text

        # Call export/mcp
        res = await client.post(
            f"/api/v1/projects/{project_id}/export/mcp",
            headers=auth_headers,
        )
        assert res.status_code == 200, res.text
        data = res.json()
        assert data["tools_generated"] >= 1
        assert data["mcp_manifest_url"].endswith("/exports/mcp/manifest.json")

        # Verify export record in list_exports
        list_res = await client.get(
            f"/api/v1/projects/{project_id}/exports",
            headers=auth_headers,
        )
        assert list_res.status_code == 200, list_res.text
        records = list_res.json()
        mcp_rec = next((r for r in records if r["export_type"] == "mcp"), None)
        assert mcp_rec is not None
        assert mcp_rec["status"] == "completed"