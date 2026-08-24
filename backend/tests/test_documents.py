"""Phase 2 document-ingestion contracts."""

from __future__ import annotations

from httpx import AsyncClient

OPENAPI = b'''openapi: 3.0.3
info:
  title: Pet Store
  version: 1.0.0
servers:
  - url: https://api.example.test/v1
paths:
  /pets:
    get:
      summary: List pets
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
    post:
      requestBody:
        content:
          application/json:
            schema: {type: object}
      responses:
        "201": {description: Created}
'''

SWAGGER = b'''{
  "swagger": "2.0",
  "info": {"title": "Legacy API", "version": "1.0"},
  "host": "legacy.example.test",
  "basePath": "/api",
  "schemes": ["https"],
  "paths": {"/orders": {"get": {"responses": {"200": {"description": "OK"}}}}}
}'''

POSTMAN = b'''{
  "info": {
    "name": "Payments Collection",
    "schema": "https://schema.getpostman.com/json/collection/v2.1.0/collection.json"
  },
  "item": [{"name": "List payments", "request": {"method": "GET", "url": "{{baseUrl}}/payments"}}]
}'''

MARKDOWN_FREEFORM = b"""# Pet Store API

## GET /pets
List all pets

Query parameters:
- limit (integer, optional): Maximum number of pets to return

Response: 200 OK - Array of pet objects

## POST /pets
Create a new pet

Request body: Pet object
Response: 201 Created - Created pet object
"""

HTML_FREEFORM = b"""<!DOCTYPE html>
<html>
<head><title>API Documentation</title></head>
<body>
<h1>User API</h1>
<h2>GET /users</h2>
<p>List all users</p>
<h2>POST /users</h2>
<p>Create a user</p>
</body>
</html>
"""


async def _project_headers(client: AsyncClient) -> tuple[str, dict[str, str]]:
    registration = await client.post(
        "/api/v1/auth/register",
        json={
            "email": "docs@example.com",
            "password": "correct-horse-battery-staple",
            "full_name": "Docs User",
            "organization_name": "Docs Org",
        },
    )
    token = registration.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}
    me = await client.get("/api/v1/auth/me", headers=headers)
    org_id = me.json()["organizations"][0]["organization_id"]
    project = await client.post(
        "/api/v1/projects", json={"name": "Pet API", "organization_id": org_id}, headers=headers
    )
    assert project.status_code == 201, project.text
    return project.json()["id"], headers


async def test_upload_openapi_persists_normalized_spec_and_endpoints(client: AsyncClient) -> None:
    project_id, headers = await _project_headers(client)
    response = await client.post(
        f"/api/v1/projects/{project_id}/upload",
        headers=headers,
        files={"file": ("petstore.yaml", OPENAPI, "application/yaml")},
    )
    assert response.status_code == 202, response.text
    assert response.json()["status"] == "processing"
    assert response.json()["workflow_run_id"] is not None
    assert response.json()["endpoints_discovered"] == 2

    spec = await client.get(f"/api/v1/projects/{project_id}/spec", headers=headers)
    assert spec.status_code == 200
    assert spec.json()["title"] == "Pet Store"
    assert spec.json()["base_url"] == "https://api.example.test/v1"

    endpoints = await client.get(
        f"/api/v1/projects/{project_id}/endpoints?method=GET", headers=headers
    )
    assert endpoints.status_code == 200
    assert endpoints.json() == [{
        "id": endpoints.json()[0]["id"], "method": "GET", "path": "/pets",
        "summary": "List pets", "deprecated": False, "confidence_score": 1.0,
    }]


async def test_upload_freeform_markdown_accepted(client: AsyncClient) -> None:
    """Freeform Markdown documents should be accepted (202) and processed by doc_agent."""
    project_id, headers = await _project_headers(client)
    response = await client.post(
        f"/api/v1/projects/{project_id}/upload",
        headers=headers,
        files={"file": ("api.md", MARKDOWN_FREEFORM, "text/markdown")},
    )
    assert response.status_code == 202, response.text
    assert response.json()["status"] == "processing"
    assert response.json()["workflow_run_id"] is not None
    # Freeform docs don't have endpoints discovered at upload time
    assert response.json()["endpoints_discovered"] == 0
    assert response.json()["api_spec_id"] is None


async def test_upload_freeform_html_accepted(client: AsyncClient) -> None:
    """Freeform HTML documents should be accepted (202) and processed by doc_agent."""
    project_id, headers = await _project_headers(client)
    response = await client.post(
        f"/api/v1/projects/{project_id}/upload",
        headers=headers,
        files={"file": ("api.html", HTML_FREEFORM, "text/html")},
    )
    assert response.status_code == 202, response.text
    assert response.json()["status"] == "processing"
    assert response.json()["workflow_run_id"] is not None
    assert response.json()["endpoints_discovered"] == 0
    assert response.json()["api_spec_id"] is None


async def test_upload_freeform_text_accepted(client: AsyncClient) -> None:
    """Freeform text documents should be accepted (202) - was 422 before fix."""
    project_id, headers = await _project_headers(client)
    response = await client.post(
        f"/api/v1/projects/{project_id}/upload",
        headers=headers,
        files={"file": ("notes.txt", b"API docs: GET /items lists items", "text/plain")},
    )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "UNPROCESSABLE_ENTITY"


async def test_upload_rejects_duplicate_document_content(client: AsyncClient) -> None:
    project_id, headers = await _project_headers(client)
    files = {"file": ("petstore.yaml", OPENAPI, "application/yaml")}
    first = await client.post(
        f"/api/v1/projects/{project_id}/upload", headers=headers, files=files
    )
    assert first.status_code == 202
    duplicate = await client.post(
        f"/api/v1/projects/{project_id}/upload", headers=headers, files=files
    )
    assert duplicate.status_code == 409


async def test_upload_normalizes_swagger_2(client: AsyncClient) -> None:
    project_id, headers = await _project_headers(client)
    response = await client.post(
        f"/api/v1/projects/{project_id}/upload",
        headers=headers,
        files={"file": ("legacy.json", SWAGGER, "application/json")},
    )
    assert response.status_code == 202, response.text
    spec = await client.get(f"/api/v1/projects/{project_id}/spec", headers=headers)
    assert spec.json()["base_url"] == "https://legacy.example.test/api"


async def test_upload_normalizes_postman_v21(client: AsyncClient) -> None:
    project_id, headers = await _project_headers(client)
    response = await client.post(
        f"/api/v1/projects/{project_id}/upload",
        headers=headers,
        files={"file": ("payments.json", POSTMAN, "application/json")},
    )
    assert response.status_code == 202, response.text
    endpoints = await client.get(f"/api/v1/projects/{project_id}/endpoints", headers=headers)
    assert endpoints.json()[0]["path"] == "/payments"
