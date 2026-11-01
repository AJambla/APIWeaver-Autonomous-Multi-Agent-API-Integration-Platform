from pathlib import Path


def test_pipeline_thoughts_contain_mcp():
    pipeline_path = Path("backend/app/workflows/langgraph_pipeline.py")
    if not pipeline_path.exists():
        pipeline_path = Path(__file__).resolve().parent.parent / "app" / "workflows" / "langgraph_pipeline.py"
    src = pipeline_path.read_text(encoding="utf-8")

    assert "Starting FastMCP tool and client synthesis" in src
    assert "Starting SDK code synthesis" not in src
    assert "FastMCP code generation complete" in src
    assert "SDK generation complete" not in src
    assert "Packaging verified FastMCP server bundle" in src
