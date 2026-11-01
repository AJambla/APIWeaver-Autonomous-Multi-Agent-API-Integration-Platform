import pytest
from unittest.mock import AsyncMock, MagicMock
from app.workflows.agents.code_agent import run_code_agent
from app.workflows.llm import LLMClient


@pytest.mark.asyncio
async def test_code_agent_generates_tools_and_server():
    state = {
        "project_id": "00000000-0000-0000-0000-000000000001",
        "normalized_spec": {
            "title": "Petstore",
            "version": "1.0.0",
            "base_url": "https://api.petstore.com/v1",
            "endpoints": [
                {"method": "GET", "path": "/pets", "summary": "List pets", "parameters": []}
            ],
        },
        "target_languages": ["python"],
        "generated_files": [],
        "total_tokens_used": 0,
    }
    mock_llm = MagicMock(spec=LLMClient)
    mock_llm.generate_json = AsyncMock(return_value=({}, 0))

    result = await run_code_agent(state, llm_client=mock_llm)
    files = {f["file_path"]: f for f in result["generated_files"]}
    assert "tools.py" in files, f"Expected tools.py in generated files: {list(files.keys())}"
    assert "server.py" in files, f"Expected server.py in generated files: {list(files.keys())}"
    assert files["tools.py"]["file_type"] == "mcp"
    assert files["server.py"]["file_type"] == "mcp"

