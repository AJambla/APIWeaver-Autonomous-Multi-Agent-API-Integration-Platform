"""Phase 2 document-ingestion contracts."""

from __future__ import annotations

from typing import NoReturn

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.api.v1 import documents
from app.core.errors import UnprocessableEntityError
from app.models.audit import AuditLog
from app.models.workflow import WorkflowRun

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
    """Freeform text documents should be accepted (202) - was 422 before fix.

    The assertions below still demanded that old 422 after the fix landed, so this test has
    been failing on every run since; 202 is what the route returns, what its Markdown and
    HTML siblings assert, and what `API.md §6.2` documents (`freeform` is a valid
    `format_hint`, and 202 means the async workflow started).
    """
    project_id, headers = await _project_headers(client)
    response = await client.post(
        f"/api/v1/projects/{project_id}/upload",
        headers=headers,
        files={"file": ("notes.txt", b"API docs: GET /items lists items", "text/plain")},
    )
    assert response.status_code == 202, response.text
    assert response.json()["status"] == "processing"
    assert response.json()["workflow_run_id"] is not None
    assert response.json()["endpoints_discovered"] == 0
    assert response.json()["api_spec_id"] is None


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


async def test_a_refused_document_is_never_reported_as_processing(
    client: AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Audit finding L5: a refusal had to reach the client as a refusal.

    `documents.py` wrapped `ingest_document` in `except UnprocessableEntityError: pass`,
    which left `document` unset and then filled `document_id` with the *workflow run's* id
    -- so the response presented a `WorkflowRun` UUID as a document, the audit row recorded
    a `resource_id` of the wrong type, and an orchestrator was started in the background
    over bytes no parser accepted, with `status: "processing"` as the answer.
    """
    project_id, headers = await _project_headers(client)

    async def refuse(*args: object, **kwargs: object) -> NoReturn:
        raise UnprocessableEntityError("The uploaded document has no readable API.")

    monkeypatch.setattr(documents, "ingest_document", refuse)

    response = await client.post(
        f"/api/v1/projects/{project_id}/upload",
        headers=headers,
        files={"file": ("mystery.bin", b"not a spec at all", "application/octet-stream")},
    )

    assert response.status_code == 422, response.text
    error = response.json()["error"]
    assert error["code"] == "UNPROCESSABLE_ENTITY"
    assert error["message"] == "The uploaded document has no readable API."

    async with session_factory() as session:
        # A refused request persists nothing: no run to poll, no audit row to explain it.
        assert (
            await session.scalars(select(WorkflowRun).where(WorkflowRun.project_id == project_id))
        ).all() == []
        assert (
            await session.scalars(select(AuditLog).where(AuditLog.action == "document.uploaded"))
        ).all() == []


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


async def test_upload_normalizes_swagger_2_with_contradictory_format_hint(client: AsyncClient) -> None:
    project_id, headers = await _project_headers(client)
    response = await client.post(
        f"/api/v1/projects/{project_id}/upload",
        headers=headers,
        files={"file": ("petstore-openapi.json", SWAGGER, "application/json")},
        data={"format_hint": "openapi"},
    )
    assert response.status_code == 202, response.text
    spec = await client.get(f"/api/v1/projects/{project_id}/spec", headers=headers)
    assert spec.status_code == 200
    assert spec.json()["base_url"] == "https://legacy.example.test/api"
    assert response.json()["endpoints_discovered"] > 0


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


def _minimal_pdf(hex_text: str) -> bytes:
    """A one-page PDF that draws `hex_text`, given as PDF hex-string bytes.

    Hex encoding keeps the plaintext out of the raw bytes, so a decode that silently
    falls back to UTF-8 can never satisfy the caller's assertion.
    """
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 300 300] "
        b"/Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]
    stream = f"BT /F1 24 Tf 20 150 Td <{hex_text}> Tj ET".encode()
    objects.append(
        b"<< /Length " + str(len(stream)).encode() + b" >>\nstream\n" + stream + b"\nendstream"
    )

    out = bytearray(b"%PDF-1.4\n")
    offsets = []
    for number, body in enumerate(objects, start=1):
        offsets.append(len(out))
        out += f"{number} 0 obj ".encode() + body + b" endobj\n"

    xref_offset = len(out)
    out += f"xref\n0 {len(objects) + 1}\n".encode() + b"0000000000 65535 f \n"
    for offset in offsets:
        out += f"{offset:010d} 00000 n \n".encode()
    out += (
        f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\n"
        f"startxref\n{xref_offset}\n%%EOF\n"
    ).encode()
    return bytes(out)


def test_multipart_parser_floor_guard() -> None:
    """Audit finding H6: python-multipart before 0.0.27 is vulnerable to a
    multipart/form-data DoS, and this is the parser behind every upload route here."""
    from importlib.metadata import version

    parsed = tuple(int(part) for part in version("python-multipart").split(".")[:3])
    assert parsed >= (0, 0, 27)


def test_pdf_extraction_survives_pypdf_upgrade() -> None:
    """Audit finding H5: pypdf 4.x carried PDF-parsing DoS CVEs.

    The parser's PdfReader/pages/extract_text call path is exercised here so a future
    upgrade cannot pass while silently degrading every PDF upload to a raw byte dump.
    """
    import pypdf

    from app.services.document_parser import extract_text

    assert int(pypdf.__version__.split(".")[0]) >= 6

    # Hex for "H5 marker".
    extracted = extract_text(_minimal_pdf("4835206d61726b6572"), "spec.pdf")
    assert extracted.strip() == "H5 marker"
