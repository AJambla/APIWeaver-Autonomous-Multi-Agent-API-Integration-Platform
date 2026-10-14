from app.services.validation_service import validate_mcp_code_statically


VALID_FASTMCP_CODE = '''"""Sample FastMCP Tools."""
from mcp.server.fastmcp import FastMCP
import httpx

mcp = FastMCP("petstore")

@mcp.tool()
async def get_pet(pet_id: int) -> dict:
    """Retrieve pet details by ID.
    
    Safety Tier: [SAFE] (LOW)
    """
    async with httpx.AsyncClient() as client:
        res = await client.get(f"https://api.example.com/pets/{pet_id}")
        return res.json()

@mcp.tool
def delete_pet(pet_id: int) -> dict:
    """Delete pet permanently.
    
    Safety Tier: [DESTRUCTIVE ⚠] (HIGH)
    Requires Confirmation: True
    """
    return {"deleted": pet_id}
'''

SYNTAX_ERROR_CODE = '''"""Broken Python Code."""
from mcp.server.fastmcp import FastMCP

mcp = FastMCP("petstore")

@mcp.tool()
def broken_syntax(foo: str)
    return foo
'''

MISSING_ANNOTATION_CODE = '''"""Missing Type Annotation."""
from mcp.server.fastmcp import FastMCP

mcp = FastMCP("petstore")

@mcp.tool()
def unannotated_tool(pet_id) -> dict:
    """A tool with no type annotations."""
    return {"id": pet_id}
'''


def test_validate_valid_fastmcp_code():
    res = validate_mcp_code_statically(VALID_FASTMCP_CODE, "tools.py")
    assert res.is_valid is True
    assert res.ast_syntax_valid is True
    assert res.mcp_contract_valid is True
    assert res.tool_count == 2
    assert "get_pet" in res.tool_names
    assert "delete_pet" in res.tool_names
    assert len(res.errors) == 0


def test_validate_syntax_error():
    res = validate_mcp_code_statically(SYNTAX_ERROR_CODE, "tools.py")
    assert res.is_valid is False
    assert res.ast_syntax_valid is False
    assert len(res.errors) == 1
    assert "SyntaxError" in res.errors[0]
    assert "line 7" in res.errors[0]


def test_validate_missing_type_annotation():
    res = validate_mcp_code_statically(MISSING_ANNOTATION_CODE, "tools.py")
    assert res.is_valid is False
    assert res.ast_syntax_valid is True
    assert res.mcp_contract_valid is False
    assert any("missing a type annotation" in err for err in res.errors)


def test_validate_empty_code():
    res = validate_mcp_code_statically("", "tools.py")
    assert res.is_valid is False
    assert "Code content is empty" in res.errors[0]
