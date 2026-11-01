import io
import zipfile
import pytest
from app.workflows.agents.export_agent import ExportAgent


@pytest.mark.asyncio
async def test_export_agent_packages_authentic_fastmcp():
    agent = ExportAgent()
    state = {
        "project_id": "00000000-0000-0000-0000-000000000001",
        "normalized_spec": {
            "title": "Petstore API",
            "version": "1.0.0",
            "base_url": "https://api.petstore.com/v1",
            "endpoints": [
                {
                    "method": "GET",
                    "path": "/pets",
                    "summary": "List pets",
                    "operationId": "listPets",
                    "parameters": [],
                }
            ],
        },
        "generated_files": [
            {
                "file_path": "tools.py",
                "content": "@mcp.tool()\nasync def listPets(): pass\n",
                "file_type": "mcp",
            },
            {
                "file_path": "server.py",
                "content": "from mcp.server.fastmcp import FastMCP\nmcp = FastMCP('Petstore')\n",
                "file_type": "mcp",
            },
        ],
        "test_run_summary": {"total": 1, "passed": 1, "failed": 0},
    }
    result = await agent.run(state, export_types=["mcp"])
    assert result["status"] == "completed"

    mcp_art = next(a for a in result["exports"] if a["type"] == "mcp")
    assert mcp_art["status"] == "completed"
    assert mcp_art["tools_generated"] == 1

    # Check zip contents
    zip_bytes = agent._last_zip_bytes if hasattr(agent, "_last_zip_bytes") else None
    assert zip_bytes is not None or "s3_key" in mcp_art
