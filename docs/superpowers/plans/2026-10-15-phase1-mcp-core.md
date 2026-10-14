# Phase 1: Code Purge & Core MCP Retargeting Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Transform APIWeaver's generation and export core into an MCP-first compiler by introducing local artifact storage, pruning 1,000+ lines of dead SDK/proxy/docker exporters, streamlining export schemas, and retargeting code generation to Python FastMCP tools.

**Architecture:** 
1. Storage abstraction supports both local filesystem (dev) and S3 (prod) through `storage_service.py`.
2. `export_agent.py` focuses exclusively on bundling verified FastMCP servers (`server.py`, `tools.py`, `README.md`, `requirements.txt`).
3. `code_agent.py` generates idiomatic Python FastMCP tool definitions with type annotations, docstrings, parameter conversions, and safety flags (`requires_confirmation=True`).
4. Dead exporters (`_package_sdk`, `_package_client`, `_package_fastapi`, `_package_docker`, `_package_github`, `_package_cicd`) and unused schemas are purged.

**Tech Stack:** Python 3.12, FastAPI, LangGraph, Pydantic, aiobotocore / local aiofiles, Pytest.

**Spec:** `C:\Users\WELCOME\.gemini\antigravity\brain\21068cce-9a93-4d38-93de-f85001610bf5\API_WEAVER_REFACTORING_BLUEPRINT.md`

## Global Constraints
- Target language for generated MCP servers is **Python FastMCP**.
- MCP is the sole first-class product output.
- No new heavy dependencies; use existing installed packages.
- Commit atomically after completing each task.
- Follow the Ponytail principle: write the minimum complete code that solves the task.

## Review Focus
1. `LocalFileSystemObjectStorage` path sanitization prevents directory traversal attacks.
2. `export_agent.py` cleanly packages the MCP bundle with manifest, server, and tool files into a valid ZIP archive without missing dependencies.
3. `/projects/{id}/export` gracefully handles requests with default MCP export without crashing on removed export types.
4. `code_agent.py` produces syntactically parseable Python code (`ast.parse`) for `@mcp.tool` functions.
5. All existing non-deprecated backend tests remain green.

---

### Task 1: Artifact Storage Abstraction (`storage_service.py`)

**Files:**
- Modify: `backend/app/services/storage_service.py`
- Modify: `backend/app/core/config.py`
- Create/Modify: `backend/tests/test_storage_service.py`

**Steps:**
- [x] Add `storage_backend` ("s3" or "local") and `storage_local_dir` (default: `./storage`) to `Settings` in `backend/app/core/config.py`.
- [x] Implement `LocalFileSystemObjectStorage` in `backend/app/services/storage_service.py` conforming to `ObjectStorage` protocol (`get`, `put`, `delete`, `upload`, `download`).
- [x] Update `create_object_storage()` factory to return `LocalFileSystemObjectStorage` if `storage_backend == "local"` or if `aiobotocore` is unavailable.
- [x] Write unit tests in `backend/tests/test_storage_service.py` verifying put, get, delete, and directory traversal rejection for `LocalFileSystemObjectStorage`.
- [x] Run pytest on `test_storage_service.py`.
- [x] Commit: `feat(storage): add local filesystem object storage for development`

---

### Task 2: Prune Dead Exporters in `export_agent.py` & Elevate MCP Generation

**Files:**
- Modify: `backend/app/workflows/agents/export_agent.py`
- Modify: `backend/tests/test_export.py`

**Steps:**
- [x] In `backend/app/workflows/agents/export_agent.py`, delete methods: `_package_sdk`, `_package_client`, `_package_fastapi`, `_package_docker`, `_package_github`, `_package_cicd`.
- [x] Update `_export_type` and `run` to default to `mcp` export.
- [x] Refine `_package_mcp` to ensure it generates:
  - `server.py`: FastMCP stdio/SSE server
  - `tools.py`: Tool definitions with `@mcp.tool` and `requires_confirmation` tags
  - `requirements.txt`: Minimal dependencies (`fastmcp>=0.1.0`, `httpx>=0.28.0`, `pydantic>=2.0.0`)
  - `README.md`: Clear setup and configuration guide for Claude Desktop & Cursor
  - `manifest.json`: Machine-readable tool list and safety flags
  - Standalone downloadable zip bundle `apiweaver-mcp.zip`
- [x] Update `backend/tests/test_export.py` to remove deleted export tests and assert that `_package_mcp` produces the complete FastMCP bundle.
- [x] Run pytest on `backend/tests/test_export.py`.
- [x] Commit: `refactor(export): prune non-MCP exporters and elevate FastMCP bundle generator`

---

### Task 3: Streamline Export Schemas & API Endpoints

**Files:**
- Modify: `backend/app/schemas/export.py`
- Modify: `backend/app/api/v1/export.py`
- Modify: `backend/app/models/export.py`

**Steps:**
- [x] In `backend/app/schemas/export.py`:
  - Deprecate/remove `SDK`, `CLIENT`, `FASTAPI`, `DOCKER`, `GITHUB` from `ExportFormat`.
  - Set default export format to `MCP`.
- [x] In `backend/app/api/v1/export.py`:
  - Update `trigger_export` to handle MCP as default.
  - Retain `/projects/{id}/export/mcp` as dedicated fast-path.
  - Ensure `/projects/{id}/exports/{export_id}/download` serves the MCP zip bundle cleanly via `storage_service`.
- [x] Run pytest on export API tests.
- [x] Commit: `refactor(api): streamline export schemas and endpoints for MCP-first delivery`

---

### Task 4: Retarget `code_agent.py` to FastMCP Tool & Server Generation

**Files:**
- Modify: `backend/app/workflows/agents/code_agent.py`
- Modify: `backend/tests/test_codegen.py`

**Steps:**
- [x] In `backend/app/workflows/agents/code_agent.py`:
  - Update prompt templates and AST builders to synthesize FastMCP `tools.py` and `server.py` instead of multi-file SDK clients (`client.py`, `models.py`, `auth.py`).
  - Add deterministic safety rule tagging in tool decorators:
    - `DELETE` / dangerous keywords → `requires_confirmation=True, risk_level="HIGH"`
    - State-changing `POST`/`PUT`/`PATCH` → `requires_confirmation=False, risk_level="STATE_CHANGING"`
    - Read-only `GET` → `requires_confirmation=False, risk_level="SAFE"`
  - Generate corresponding `test_mcp.py` using `pytest` and `respx` / mock fixtures for sandbox verification.
- [x] Update `backend/tests/test_codegen.py` to verify FastMCP code generation.
- [x] Run pytest on `backend/tests/test_codegen.py`.
- [x] Commit: `feat(codegen): retarget code_agent to synthesize FastMCP tools and test fixtures`

---

### Task 5: End-to-End Pipeline Verification for Phase 1

**Files:**
- Modify: `backend/tests/test_langgraph_pipeline.py`
- Modify: `backend/tests/test_workflows_e2e.py`

**Steps:**
- [x] Run `test_langgraph_pipeline.py` and `test_workflows_e2e.py` with mock LLM to ensure the LangGraph pipeline smoothly runs:
  `doc_agent → planner_agent → code_agent (FastMCP) → test_agent → export_agent (MCP Bundle)`.
- [x] Fix any contract mismatches or residual SDK assumptions in pipeline reducers.
- [x] Run full test suite for Phase 1 components: `pytest backend/tests/test_export.py backend/tests/test_codegen.py backend/tests/test_storage_service.py`.
- [x] Commit: `test(e2e): verify end-to-end FastMCP generation and export in workflow pipeline`
