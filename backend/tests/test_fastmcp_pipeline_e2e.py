"""End-to-End Integration Smoke Test for FastMCP Generation & Multi-Tier Verification.

Blueprint §10 (Phase 5):
Validates the complete FastMCP lifecycle through the public API:
1. User Registration & Org Provisioning
2. Project Creation & Spec Upload (OpenAPI 3.0 Petstore with GET, POST, DELETE)
3. Ingestion & Topological DAG Planning with Safety Classification (Destructive Gate)
4. Approval Gate Execution
5. FastMCP Code Generation (tools.py, server.py, test_mcp.py, manifest.json)
6. Pre-Sandbox Static Validation (AST Parse & Schema Validation)
7. Sandbox Execution & Multi-Tier Verification Report Generation:
   STATIC: PASS, SANDBOX: PASS, LIVE: NOT RUN, Overall: SANDBOX VERIFIED
8. FastMCP ZIP Bundle Export (apiweaver-mcp.zip) & Download
"""

from __future__ import annotations

import io
import json
import uuid
import zipfile
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest
from httpx import AsyncClient

import app.services.storage_service as storage_module
from app.services.safety_service import classify_safety
from app.services.validation_service import validate_mcp_code_statically
from app.services.verification_service import (
    OverallStatus,
    VerificationStatus,
    build_verification_report,
    render_report_json,
    render_report_markdown,
)
from app.workflows.agents.export_agent import ExportAgent
from app.workflows.llm import LLMClient
from tests.conftest import TEST_PASSWORD
from tests.fakes import InMemoryObjectStorage

PETSTORE_SPEC_YAML = """\
openapi: "3.0.3"
info:
  title: Petstore FastMCP API
  version: "1.0.0"
servers:
  - url: https://api.petstore.local/v1
paths:
  /pets:
    get:
      operationId: listPets
      summary: List all pets
      responses:
        "200":
          description: A list of pets
          content:
            application/json:
              schema:
                type: array
                items:
                  type: object
                  properties:
                    id:
                      type: integer
                    name:
                      type: string
    post:
      operationId: createPet
      summary: Create a pet
      requestBody:
        required: true
        content:
          application/json:
            schema:
              type: object
              required: [name]
              properties:
                name:
                  type: string
      responses:
        "201":
          description: Pet created
  /pets/{id}:
    delete:
      operationId: deletePet
      summary: Delete a pet by ID
      parameters:
        - name: id
          in: path
          required: true
          schema:
            type: integer
      responses:
        "204":
          description: Pet deleted
"""

FASTMCP_TOOLS_CODE = '''\
"""FastMCP Tool Definitions for Petstore API."""
import httpx
from pydantic import BaseModel, Field

# Base client configuration
BASE_URL = "https://api.petstore.local/v1"


class CreatePetInput(BaseModel):
    name: str = Field(..., description="The pet name")


async def list_pets() -> list[dict]:
    """[SAFE] List all pets in the catalog.
    
    Risk Level: LOW
    Requires Confirmation: False
    """
    async with httpx.AsyncClient(base_url=BASE_URL) as client:
        res = await client.get("/pets")
        return res.json() if res.status_code == 200 else []


async def create_pet(name: str) -> dict:
    """[STATE-CHANGING] Create a pet in the catalog.
    
    Risk Level: MEDIUM
    Requires Confirmation: False
    """
    async with httpx.AsyncClient(base_url=BASE_URL) as client:
        res = await client.post("/pets", json={"name": name})
        return res.json() if res.status_code == 201 else {"ok": True}


async def delete_pet(id: int) -> dict:
    """[DESTRUCTIVE ⚠] Delete a pet by ID.
    
    Risk Level: HIGH
    Requires Confirmation: True
    """
    async with httpx.AsyncClient(base_url=BASE_URL) as client:
        res = await client.delete(f"/pets/{id}")
        return {"deleted": True, "id": id}
'''

FASTMCP_SERVER_CODE = '''\
"""FastMCP Server Entrypoint for Petstore."""
from mcp.server.fastmcp import FastMCP
import tools

mcp = FastMCP("petstore-api")

@mcp.tool(name="list_pets", description="[SAFE] List all pets")
async def list_pets_tool() -> list[dict]:
    return await tools.list_pets()

@mcp.tool(name="create_pet", description="[STATE-CHANGING] Create a pet")
async def create_pet_tool(name: str) -> dict:
    return await tools.create_pet(name=name)

@mcp.tool(name="delete_pet", description="[DESTRUCTIVE ⚠] Delete a pet")
async def delete_pet_tool(id: int) -> dict:
    return await tools.delete_pet(id=id)

if __name__ == "__main__":
    mcp.run()
'''

FASTMCP_TEST_CODE = '''\
"""Pytest verification suite for FastMCP tools."""
import pytest
import tools

@pytest.mark.asyncio
async def test_list_pets():
    # Synthetic verification mock
    assert callable(tools.list_pets)

@pytest.mark.asyncio
async def test_create_pet():
    assert callable(tools.create_pet)

@pytest.mark.asyncio
async def test_delete_pet():
    assert callable(tools.delete_pet)
'''

FASTMCP_MANIFEST_JSON = {
    "mcp_version": "1.0",
    "server_name": "petstore-api",
    "tools": [
        {
            "name": "list_pets",
            "description": "[SAFE] List all pets in the catalog.",
            "safety_badge": "[SAFE]",
            "requires_confirmation": False,
            "risk_level": "LOW",
        },
        {
            "name": "create_pet",
            "description": "[STATE-CHANGING] Create a pet in the catalog.",
            "safety_badge": "[STATE-CHANGING]",
            "requires_confirmation": False,
            "risk_level": "MEDIUM",
        },
        {
            "name": "delete_pet",
            "description": "[DESTRUCTIVE ⚠] Delete a pet by ID.",
            "safety_badge": "[DESTRUCTIVE ⚠]",
            "requires_confirmation": True,
            "risk_level": "HIGH",
        },
    ],
}


async def _fake_fastmcp_llm_generate(
    self: LLMClient,
    *,
    system_prompt: str,
    user_prompt: str,
    fallback_json: dict[str, Any] | None = None,
) -> tuple[dict[str, Any], int]:
    """Deterministic LLM test double generating FastMCP artifacts."""
    if "Planner Agent" in system_prompt or "topological" in system_prompt.lower():
        plan = {
            "dependency_graph": {
                "nodes": [
                    {"id": "ep_0", "method": "GET", "path": "/pets", "label": "listPets", "is_destructive": False},
                    {"id": "ep_1", "method": "POST", "path": "/pets", "label": "createPet", "is_destructive": False},
                    {"id": "ep_2", "method": "DELETE", "path": "/pets/{id}", "label": "deletePet", "is_destructive": True},
                ],
                "edges": [
                    {"from": "ep_2", "to": "ep_1", "relationship": "requires_created_resource"}
                ],
            },
            "phases": [
                {
                    "phase_number": 1,
                    "name": "Pet Operations",
                    "endpoints": ["ep_0", "ep_1", "ep_2"],
                }
            ],
        }
        return plan, 50

    if "Code Generator" in system_prompt or "fastmcp" in system_prompt.lower() or "client" in system_prompt.lower():
        return {
            "tools.py": FASTMCP_TOOLS_CODE,
            "server.py": FASTMCP_SERVER_CODE,
            "test_mcp.py": FASTMCP_TEST_CODE,
        }, 100

    return (fallback_json if fallback_json is not None else {}), 20


@pytest.mark.asyncio
async def test_fastmcp_pipeline_end_to_end(client: AsyncClient) -> None:
    """Validate full end-to-end FastMCP pipeline execution and artifacts."""
    # 1. User Registration & Org Setup
    register = await client.post(
        "/api/v1/auth/register",
        json={
            "email": f"fastmcp-{uuid.uuid4().hex[:8]}@example.com",
            "password": TEST_PASSWORD,
            "full_name": "FastMCP Engineer",
            "organization_name": f"FastMCP Org {uuid.uuid4().hex[:6]}",
        },
    )
    assert register.status_code == 201, register.text
    tokens = register.json()
    headers = {"Authorization": f"Bearer {tokens['access_token']}"}

    me = await client.get("/api/v1/auth/me", headers=headers)
    assert me.status_code == 200, me.text
    org_id = me.json()["organizations"][0]["organization_id"]

    # 2. Project Creation
    project = await client.post(
        "/api/v1/projects",
        json={"name": "Petstore-MCP", "organization_id": org_id},
        headers=headers,
    )
    assert project.status_code == 201, project.text
    project_id = project.json()["id"]

    # Storage test double
    storage_fake = InMemoryObjectStorage()

    with (
        patch.object(storage_module, "_storage_instance", storage_fake),
        patch.object(LLMClient, "generate_json", new=_fake_fastmcp_llm_generate),
    ):
        # 3. Spec Upload & Normalization
        upload = await client.post(
            f"/api/v1/projects/{project_id}/upload",
            files={"file": ("petstore.yaml", PETSTORE_SPEC_YAML, "application/x-yaml")},
            headers=headers,
        )
        assert upload.status_code == 202, upload.text
        upload_body = upload.json()
        assert upload_body["endpoints_discovered"] == 3
        assert upload_body["api_spec_id"] is not None
        run_id = upload_body["workflow_run_id"]
        assert run_id

        # 4. Verification of Approval Gate
        run = await client.get(f"/api/v1/workflows/{run_id}", headers=headers)
        assert run.status_code == 200, run.text
        assert run.json()["status"] == "paused_for_approval"

        # 5. Dependency Graph & Safety Tier Checks
        graph = await client.get(
            f"/api/v1/projects/{project_id}/dependency-graph", headers=headers
        )
        assert graph.status_code == 200, graph.text
        graph_body = graph.json()
        assert len(graph_body["nodes"]) == 3
        delete_node = next(n for n in graph_body["nodes"] if n["method"] == "DELETE")
        assert delete_node["is_destructive"] is True

        # 6. Static Safety Engine Checks on Tools Code
        get_safety = classify_safety("GET", "/pets")
        assert get_safety.badge == "[SAFE]"
        assert get_safety.requires_confirmation is False

        post_safety = classify_safety("POST", "/pets")
        assert post_safety.badge == "[STATE-CHANGING]"
        assert post_safety.requires_confirmation is False

        delete_safety = classify_safety("DELETE", "/pets/{id}")
        assert delete_safety.badge == "[DESTRUCTIVE ⚠]"
        assert delete_safety.requires_confirmation is True

        # 7. Pre-Sandbox Static Validation Gate (AST Syntax & Schema)
        tools_validation = validate_mcp_code_statically(FASTMCP_TOOLS_CODE, "tools.py")
        assert tools_validation.is_valid is True
        assert tools_validation.ast_syntax_valid is True

        server_validation = validate_mcp_code_statically(FASTMCP_SERVER_CODE, "server.py")
        assert server_validation.is_valid is True
        assert server_validation.ast_syntax_valid is True

        # 8. Multi-Level Verification Report Generation
        endpoints_data = [
            {"method": "GET", "path": "/pets", "summary": "List all pets", "operation_id": "listPets"},
            {"method": "POST", "path": "/pets", "summary": "Create a pet", "operation_id": "createPets"},
            {"method": "DELETE", "path": "/pets/{petId}", "summary": "Delete pet", "operation_id": "deletePet"},
        ]
        test_suite_results = [
            {"method": "GET", "path": "/pets", "status": "passed"},
            {"method": "POST", "path": "/pets", "status": "passed"},
            {"method": "DELETE", "path": "/pets/{petId}", "status": "passed"},
        ]
        report = build_verification_report(
            project_id=project_id,
            static_result=tools_validation,
            test_suite_results=test_suite_results,
            endpoints=endpoints_data,
            repair_cycles=0,
            live_tested=False,
            live_passed=False,
        )
        assert report.static_status == VerificationStatus.PASS
        assert report.sandbox_status == VerificationStatus.PASS
        assert report.live_status == VerificationStatus.NOT_RUN
        assert report.overall_status == OverallStatus.SANDBOX_VERIFIED

        report_md = render_report_markdown(report)
        assert "Overall: SANDBOX VERIFIED" in report_md
        assert "**Level 1 (Static Verification):** `PASS`" in report_md
        assert "**Level 2 (Sandbox Verification):** `PASS`" in report_md
        assert "**Level 3 (Live API Verification):** `NOT RUN`" in report_md

        report_json = render_report_json(report)
        assert report_json["overall_status"] == "SANDBOX VERIFIED"
        assert report_json["static_status"] == "PASS"
        assert report_json["sandbox_status"] == "PASS"
        assert report_json["live_status"] == "NOT RUN"

        # 9. FastMCP Export Bundle Verification
        export_agent = ExportAgent()
        export_run_id = str(uuid.uuid4())
        state = {
            "project_id": str(project_id),
            "organization_id": str(org_id),
            "workflow_run_id": export_run_id,
            "stages": ["export"],
            "target_languages": ["python"],
            "normalized_spec": {
                "title": "Petstore API",
                "endpoints": [
                    {"method": "GET", "path": "/pets", "summary": "List pets"},
                    {"method": "POST", "path": "/pets", "summary": "Create pet"},
                    {"method": "DELETE", "path": "/pets/{id}", "summary": "Delete pet"},
                ],
            },
            "generated_files": [
                {"file_path": "tools.py", "language": "python", "content": FASTMCP_TOOLS_CODE},
                {"file_path": "server.py", "language": "python", "content": FASTMCP_SERVER_CODE},
                {"file_path": "test_mcp.py", "language": "python", "content": FASTMCP_TEST_CODE},
            ],
            "test_suite": [],
            "errors": [],
        }

        export_result = await export_agent.run(state)
        assert export_result["status"] == "completed"
        assert export_result["overall_status"] == OverallStatus.SANDBOX_VERIFIED

        # 10. Inspect ZIP archive contents
        mcp_bundle_key = f"exports/{project_id}/mcp/apiweaver-mcp.zip"
        zip_bytes = await storage_fake.download(mcp_bundle_key)
        assert zip_bytes is not None

        with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
            namelist = zf.namelist()
            assert "server.py" in namelist
            assert "tools.py" in namelist
            assert "test_mcp.py" in namelist
            assert "manifest.json" in namelist
            assert "VERIFICATION_REPORT.md" in namelist
            assert "VERIFICATION_REPORT.json" in namelist
            assert "requirements.txt" in namelist

            # Verify manifest content inside archive
            manifest_content = json.loads(zf.read("manifest.json").decode("utf-8"))
            assert len(manifest_content.get("tools", [])) == 3

            # Verify report markdown inside archive
            bundle_report_md = zf.read("VERIFICATION_REPORT.md").decode("utf-8")
            assert "Overall: SANDBOX VERIFIED" in bundle_report_md
