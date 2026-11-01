import ast
from pathlib import Path
import pytest
from jinja2 import Environment, FileSystemLoader
from app.services.validation_service import validate_mcp_code_statically
from app.workflows.source_safety import to_literal, to_py_type


def test_fastmcp_tools_template_renders_valid_mcp_contract():
    template_dir = Path(__file__).resolve().parent.parent / "app" / "workflows" / "templates" / "python"
    env = Environment(loader=FileSystemLoader(template_dir))
    env.filters["py_type"] = to_py_type
    env.filters["lit"] = to_literal

    template = env.get_template("tools.py.j2")
    sample_context = {
        "title": "Petstore",
        "base_url": "https://petstore.example.com/v2",
        "auth_schemes": ["api_key"],
        "endpoints": [
            {
                "method": "GET",
                "path": "/pet/{petId}",
                "summary": "Find pet by ID",
                "operationId": "getPetById",
                "requires_confirmation": False,
                "parameters": [{"name": "petId", "type": "integer", "required": True, "location": "path"}],
                "request_schema": None,
            },
            {
                "method": "DELETE",
                "path": "/pet/{petId}",
                "summary": "Delete pet by ID",
                "operationId": "deletePet",
                "requires_confirmation": True,
                "parameters": [{"name": "petId", "type": "integer", "required": True, "location": "path"}],
                "request_schema": None,
            },
        ],
    }
    rendered = template.render(**sample_context)
    result = validate_mcp_code_statically(rendered, "tools.py")
    assert result.is_valid, f"Rendered tools.py invalid: {result.errors}"
    assert result.tool_count == 2
    assert "getPetById" in result.tool_names or "get_pet_by_id" in [t.lower() for t in result.tool_names]
    assert "deletePet" in result.tool_names or "delete_pet" in [t.lower() for t in result.tool_names]


def test_fastmcp_server_template_renders_valid_syntax():
    template_dir = Path(__file__).resolve().parent.parent / "app" / "workflows" / "templates" / "python"
    env = Environment(loader=FileSystemLoader(template_dir))
    env.filters["py_type"] = to_py_type
    env.filters["lit"] = to_literal

    template = env.get_template("server.py.j2")
    sample_context = {
        "title": "Petstore API",
        "base_url": "https://petstore.example.com/v2",
    }
    rendered = template.render(**sample_context)
    tree = ast.parse(rendered)
    assert tree is not None
    assert "FastMCP" in rendered
