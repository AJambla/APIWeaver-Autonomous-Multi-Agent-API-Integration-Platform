"""Generated-source integrity: spec values must not change the code they land in (audit M6b).

The Jinja client templates and the FastAPI export paste spec fields into identifier,
string-literal, docstring and comment positions. These tests feed in values written to
close a literal and start a statement, then assert the produced source still parses and
carries no call the spec asked for.
"""

from __future__ import annotations

import ast
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest

from app.workflows.agents.code_agent import _render_templates
from app.workflows.agents.export_agent import ExportAgent
from app.workflows.source_safety import (
    derived_operation_id,
    safe_endpoint,
    to_base_url,
    to_display_name,
    to_http_method,
    to_identifier,
    to_literal,
    to_path,
    to_text,
    to_type_name,
)

# Written to break out of a double-quoted literal, a docstring, an identifier slot and a
# type annotation. Each is only dangerous if its quotes, brackets or newlines survive.
HOSTILE_PATH = '/users/list"; __import__("os"); popen("id"); #'
HOSTILE_SUMMARY = 'x */ __import__("os").popen("id") /* "'
HOSTILE_OP_ID = 'a():\n    __import__("os").popen("id")\nasync def b'
HOSTILE_TYPE = 'int = 1)\n    __import__("os").popen("id")\nasync def z('
HOSTILE_TITLE = 'Evil"; __import__("os").popen("id"); #'
HOSTILE_BASE_URL = 'https://x.test/"); __import__("os").popen("id"); #'
HOSTILE_METHOD = 'PUT"; __import__("os")'

DANGEROUS = {"__import__", "exec", "eval", "popen", "system", "execSync", "require"}


def dangerous_calls(source: str) -> list[str]:
    """Calls the parsed source really makes that generated code must never contain."""
    found: list[str] = []
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Call):
            printed = ast.unparse(node.func)
            if printed.split(".")[-1] in DANGEROUS:
                found.append(printed)
    return found


def hostile_spec() -> dict[str, Any]:
    return {
        "title": HOSTILE_TITLE,
        "base_url": HOSTILE_BASE_URL,
        "endpoints": [
            {
                "method": HOSTILE_METHOD,
                "path": HOSTILE_PATH,
                "summary": HOSTILE_SUMMARY,
                "operationId": HOSTILE_OP_ID,
                "parameters": [
                    {"name": 'q"); __import__("os")', "location": "query", "type": HOSTILE_TYPE},
                ],
                "request_schema": None,
            }
        ],
    }


def benign_spec() -> dict[str, Any]:
    return {
        "title": "Test API",
        "base_url": "https://api.example.com/v1",
        "endpoints": [
            {
                "method": "GET",
                "path": "/users/{id}",
                "summary": "Fetch a user",
                "operationId": "getUser",
                "parameters": [{"name": "id", "location": "path", "type": "string"}],
                "request_schema": None,
            }
        ],
    }


async def render(language: str, spec: dict[str, Any]) -> dict[str, str]:
    return await _render_templates(language, spec, None, {"endpoints": spec["endpoints"]})


@pytest.mark.parametrize("language", ["python", "node"])
async def test_hostile_spec_never_reaches_generated_source_verbatim(language: str):
    files = await render(language, hostile_spec())

    assert files, "every template failed to render"
    for name, content in files.items():
        assert HOSTILE_PATH not in content, name
        assert HOSTILE_OP_ID not in content, name
        assert HOSTILE_TYPE not in content, name
        assert HOSTILE_TITLE not in content, name
        assert HOSTILE_SUMMARY not in content, name
        assert 'require("' not in content, name


async def test_hostile_python_templates_still_parse_and_make_no_dangerous_call():
    files = await render("python", hostile_spec())

    py_files = {name: content for name, content in files.items() if name.endswith(".py")}
    assert py_files, "no python file was generated"
    for name, content in py_files.items():
        assert dangerous_calls(content) == [], name


async def test_benign_python_templates_still_generate_a_working_client():
    files = await render("python", benign_spec())

    client = files["client.py"]
    assert "class TestAPIClient:" in client
    assert "async def getUser(" in client
    assert 'url = "/users/{id}"' in client
    assert 'os.getenv("TEST_API_BASE_URL", "https://api.example.com/v1")' in client
    ast.parse(client)


async def test_python_client_template_ordering_and_types_hazards():
    spec = {
        "title": "Hazard API",
        "base_url": "https://api.example.com/v1",
        "endpoints": [
            {
                "method": "GET",
                "path": "/items/{item_id}",
                "summary": "Get item",
                "operationId": "getItem",
                "parameters": [
                    {"name": "filter", "location": "query", "type": "string", "required": False},
                    {"name": "limit", "location": "query", "type": "integer", "required": False},
                    {"name": "active", "location": "query", "type": "boolean", "required": False},
                    {"name": "tags", "location": "query", "type": "array", "required": False},
                    {"name": "item_id", "location": "path", "type": "string", "required": True},
                ],
                "request_schema": None,
            },
            {
                "method": "POST",
                "path": "/items",
                "summary": "Create item",
                "operationId": "createItem",
                "parameters": [],
                "request_schema": {"type": "object", "properties": {"name": {"type": "string"}}},
            },
        ],
    }
    files = await render("python", spec)
    client_code = files["client.py"]
    models_code = files["models.py"]
    ast.parse(client_code)
    ast.parse(models_code)
    assert "ItemsPOSTItemsRequest" in models_code
    assert "limit: Optional[int] = None" in client_code
    assert "active: Optional[bool] = None" in client_code
    assert "tags: Optional[list[Any]] = None" in client_code

    ts_files = await render("node", spec)
    ts_client = ts_files["client.ts"]
    assert "item_id: string" in ts_client
    assert "filter?: string" in ts_client


async def export_router(spec: dict[str, Any]) -> str:
    captured: dict[str, bytes] = {}

    async def capture(key: str, payload: bytes) -> None:
        captured[key] = payload

    with patch("app.workflows.agents.export_agent.storage_service") as storage:
        storage.upload = AsyncMock(side_effect=capture)
        result = await ExportAgent()._package_fastapi(project_id="p1", normalized_spec=spec)

    return captured[result["s3_key"]].decode()


async def test_fastapi_export_cannot_add_a_statement():
    router_code = await export_router(hostile_spec())

    assert dangerous_calls(router_code) == []
    assert HOSTILE_PATH not in router_code
    assert HOSTILE_OP_ID not in router_code
    assert HOSTILE_METHOD not in router_code


async def test_fastapi_export_still_declares_the_spec_endpoints():
    router_code = await export_router(benign_spec())

    ast.parse(router_code)
    assert "FastAPI router for Test_API." in router_code
    assert 'router = APIRouter(prefix="/test-api")' in router_code
    assert '@router.get("/users/{id}", summary="Fetch a user")' in router_code
    assert "async def getUser():" in router_code
    assert 'return {"message": "Not implemented"}' in router_code


def test_path_slots_keep_url_shape_and_drop_literals():
    assert to_path("/users/{id}") == "/users/{id}"
    assert to_path("users/{id}") == "/users/{id}"
    assert to_path(HOSTILE_PATH) == "/users/list__import__ospopenid"
    assert to_path("") == "/"
    for char in '"();#\\\n':
        assert char not in to_path(HOSTILE_PATH)


def test_identifier_slots_are_always_usable_names():
    assert to_identifier("getUser", fallback="endpoint") == "getUser"
    assert to_identifier(HOSTILE_OP_ID, fallback="endpoint").isidentifier()
    assert to_identifier(None, fallback="param") == "param"
    assert to_identifier("", fallback="param") == "param"
    assert to_identifier("class", fallback="param") == "param_class"
    assert to_identifier("9 lives", fallback="param") == "param_9_lives"
    assert to_type_name("integer") == "integer"
    assert to_type_name(HOSTILE_TYPE).isidentifier()


def test_prose_slots_cannot_close_a_docstring_or_a_block_comment():
    summary = to_text(HOSTILE_SUMMARY)
    for char in '"*`\\':
        assert char not in summary
    assert "\n" not in summary
    assert to_text("List   users\nand pets") == "List users and pets"
    assert to_text(None, fallback="/x") == "/x"


def test_display_names_and_urls_keep_benign_shapes():
    assert to_display_name("Pet Shop API") == "Pet Shop API"
    for char in '"();#\\\n':
        assert char not in to_display_name(HOSTILE_TITLE)
    assert to_base_url("https://api.example.com/v1?q=1#x") == "https://api.example.com/v1?q=1#x"
    hostile_url = to_base_url(HOSTILE_BASE_URL)
    assert hostile_url.startswith("https://")
    for char in '"();\\\n':
        assert char not in hostile_url
    assert to_base_url("ftp://host") == "https://api.example.com"


def test_methods_are_restricted_to_real_verbs():
    assert to_http_method("DELETE") == "delete"
    assert to_http_method(HOSTILE_METHOD) == "get"


def test_literals_survive_a_round_trip():
    assert ast.literal_eval(to_literal(HOSTILE_PATH)) == HOSTILE_PATH
    assert ast.literal_eval(to_literal(HOSTILE_SUMMARY)) == HOSTILE_SUMMARY
    assert to_literal("/users/{id}").startswith('"') and to_literal("/users/{id}").endswith('"')


def test_endpoints_and_operation_ids_are_shaped_before_templates_see_them():
    clean = safe_endpoint(hostile_spec()["endpoints"][0])
    assert clean["method"] == "get"
    assert clean["operationId"].isidentifier()
    assert all(p["name"].isidentifier() for p in clean["parameters"])

    derived = safe_endpoint({"method": "post", "path": "/pets/{petId}"})
    assert derived["operationId"] == derived_operation_id("post", "/pets/{petId}")
    assert derived["operationId"].isidentifier()
    assert derived["summary"] == "/pets/{petId}"
