# Phase 3 Implementation Plan: Downstream Agents & APIs

## Goal
Implement the three downstream agents (Code Generator, Testing, Export) with their API endpoints, completing the full multi-agent pipeline from document upload to export-ready artifacts.

## Scope
- **Code Generator Agent**: Python + Node.js/TypeScript targets
- **Testing Agent**: Mock sandbox execution + self-healing repair loop (max 3 retries)
- **Export Agent**: SDK, Client, Docker, GitHub, MCP, Docs, CI/CD
- **API Endpoints**: `/generate`, `/files`, `/test`, `/test-runs`, `/export` per `API.md §6.6-6.8`

## Current State (Done in Phase 1-2)
- ✅ Orchestrator with LangGraph state machine + checkpointing
- ✅ Documentation Agent (deterministic + LLM fallback)
- ✅ Planner Agent (dependency graph + execution plan)
- ✅ Auth/RBAC, Vault, Qdrant, Storage services
- ✅ Document upload + spec normalization + workflow trigger
- ✅ Database models for codegen, testing, export tables

## Implementation Tasks

### 1. Code Generator Agent (`backend/app/workflows/agents/code_agent.py`)
**Input**: `WorkflowState` with `execution_plan`, `normalized_spec`, `target_languages`
**Output**: `generated_files` list with `{file_path, content_s3_key, language, file_type}`

**Components**:
- `CodeGeneratorAgent` class with `run(state, phase_number: int | None = None)` method
- `patch(state, failure_diagnosis: dict, file_path: str)` method for self-healing repairs
- Per-language template engines (Jinja2 for Python, Handlebars/JS for Node)
- Shared utilities: naming normalization, import management, auth injection
- LLM prompts per `AI_Instruction.md §2.3` + repair prompt `§2.4`

**Language-specific**:
- **Python**: Pydantic v2 models, httpx client, custom exceptions, Google docstrings, ruff + mypy
- **Node.js**: Zod schemas, native fetch/axios, ESM, TypeScript strict mode, eslint + tsc

**Chunking strategy** (per `AI_Instruction.md §12`):
- Orchestrator iterates `execution_plan.phases` sequentially
- Per phase: call `run_code_agent(state, phase_number=phase["phase_number"])` → checkpoint
- After all phases: cross-chunk consistency pass (dedupe imports, normalize naming, validate cross-references)
- `run_code_agent` signature: `run_code_agent(state, phase_number: int | None = None, failure_diagnosis: dict | None = None, target_file: str | None = None)`
  - `phase_number=None, failure_diagnosis=None` → process all (backward compat / small APIs)
  - `phase_number=N` → process single phase only
  - `failure_diagnosis` + `target_file` → targeted repair for self-healing loop

### 2. Testing Agent (`backend/app/workflows/agents/test_agent.py`)
**Input**: `WorkflowState` with `generated_files`, `normalized_spec`, `execution_plan`
**Output**: `test_suite` results, `test_run_summary`

**Components**:
- `TestingAgent` class with `run(state)` method
- `MockSandboxClient` (in-process, like `FakeQdrantClient`) — executes generated code against recorded fixtures
- Test fixture generator from endpoint schemas/examples
- `FailureClassifier` (LLM prompt per `AI_Instruction.md §2.5`)
- Repair loop orchestrator (max 3 attempts per `AI_Instruction.md §8`)

**Sandbox behavior**:
- In-process import/execution of generated Python modules (via `importlib`)
- For Node: skip execution, validate syntax + types only (mock via `tsc --noEmit`)
- Captures: status_code, latency_ms, response_snapshot, stack_trace on error

**Self-healing loop**:
```python
for attempt in 1..3:
  run tests → collect failures
  if no failures: break
  for each failure:
    classify → build repair prompt → call run_code_agent(state, failure_diagnosis=classification, target_file=failed_file)
    re-run failed test
  if all resolved: break
escalate remaining failures
```

**Integration with Code Generator**: The Testing Agent imports and calls `run_code_agent` directly with `failure_diagnosis` and `target_file` parameters to trigger targeted repairs.

### 3. Export Agent (`backend/app/workflows/agents/export_agent.py`)
**Input**: `WorkflowState` with `generated_files`, `test_run_summary`, `target_languages`
**Output**: Export artifacts metadata + S3 keys

**Components**:
- `ExportAgent` class with `run(state, export_types: list[str] | None = None)` method
- `export_types` parameter: subset of `["sdk", "client", "fastapi", "docker", "github", "mcp", "docs", "cicd"]` (defaults to all)
- Per-export-type packagers (each returns `{artifact_name, s3_key, metadata}`):
  - **SDK**: `pyproject.toml`/`package.json`, README, version, tarball (wheel/npm package)
  - **Client**: flatten generated files to single-module client (e.g., `client.py` / `client.ts`)
  - **FastAPI wrapper**: generate FastAPI router with DI auth, mountable in user's app
  - **Docker**: multi-stage `Dockerfile` + `docker-compose.yml` with health checks
  - **GitHub**: create repo via GitHub API (requires `GITHUB_TOKEN` in Vault), push files + CI/CD workflows
  - **MCP**: convert endpoints → tool definitions (JSON Schema), generate stdio/SSE server entrypoint
  - **Docs**: OpenAPI 3.1 spec (from normalized_spec) + markdown reference (endpoints, models, auth)
  - **CI/CD**: GitHub Actions workflows (lint, test, build, publish) — parameterized by language

**Vault integration**: GitHub export reads `GITHUB_TOKEN` from Vault (`app/services/vault_service.py`).

### 4. API Routes (add to `backend/app/api/v1/`)

| File | Endpoints |
|------|-----------|
| `generate.py` | `POST /projects/{id}/generate`, `GET /projects/{id}/files`, `GET /projects/{id}/files/{file_id}/content` |
| `testing.py` | `POST /projects/{id}/test`, `GET /projects/{id}/test-runs/{run_id}`, `GET /projects/{id}/test-runs/{run_id}/repairs` |
| `export.py` | `POST /projects/{id}/export`, `POST /projects/{id}/export/mcp` |

**Permissions** (per `rbac/policy.py`):
- `CODE_GENERATE`/`CODE_READ` → Editor+
- `TEST_RUN`/`TEST_READ` → Editor+
- `EXPORT_CREATE`/`EXPORT_READ` → Owner only

### 5. Orchestrator Integration (`backend/app/workflows/orchestrator.py`)
Add stages to pipeline with phase-by-phase code generation:
```python
stages = current_dict.get("stages", ["plan"])
# After planner:
if "generate" in stages and current_dict.get("plan_approved"):
    plan = current_dict.get("execution_plan", {})
    phases = plan.get("phases", [])
    for phase in phases:
        code_updates = await run_code_agent(
            cast(WorkflowState, current_dict),
            phase_number=phase["phase_number"],
        )
        current_dict.update(code_updates)
        await record_checkpoint(
            session, ..., node_name=f"code_agent_phase_{phase['phase_number']}", state=current_dict
        )
    # Cross-chunk consistency pass
    consistency_updates = await run_code_agent(
        cast(WorkflowState, current_dict),
        phase_number=None,  # consistency pass
    )
    current_dict.update(consistency_updates)
    await record_checkpoint(session, ..., node_name="code_agent_consistency", state=current_dict)

if "test" in stages and current_dict.get("generated_files"):
    test_updates = await run_test_agent(cast(WorkflowState, current_dict))
    current_dict.update(test_updates)
    await record_checkpoint(session, ..., node_name="test_agent", state=current_dict)

if "export" in stages and current_dict.get("test_suite"):
    export_updates = await run_export_agent(cast(WorkflowState, current_dict))
    current_dict.update(export_updates)
    await record_checkpoint(session, ..., node_name="export_agent", state=current_dict)
```

### 6. Schemas (`backend/app/schemas/`)
- `generate.py`:
  - `GenerateRequest` — `stages`, `target_languages`, `export_types?`
  - `GenerateResponse` — `workflow_run_id`, `status`
  - `FileResponse` — `id`, `file_path`, `language`, `file_type`, `created_at`
  - `FileContentResponse` — `content` (streamed from S3)
- `testing.py`:
  - `TestRequest` — `environment` (sandbox/live), `filter_endpoints?`
  - `TestRunResponse` — `run_id`, `status`, `summary`
  - `TestResultResponse` — `endpoint_id`, `status`, `status_code`, `latency_ms`, `error?`
  - `RepairAttemptResponse` — `attempt_number`, `classification`, `diff_summary`, `outcome`
- `export.py`:
  - `ExportRequest` — `export_types` (list), `github_repo_name?`, `docker_image_name?`
  - `ExportResponse` — `export_id`, `artifacts` (`[{type, s3_key, metadata}]`)
  - `MCPExportResponse` — `tools` (`[{name, input_schema, requires_confirmation}]`), `server_s3_key`

### 7. Tests (`backend/tests/`)
- `test_codegen.py`: Agent unit tests + API integration (Python + Node targets)
- `test_testing.py`: Mock sandbox execution, failure classification, repair loop
- `test_export.py`: Each export type packaging
- `test_workflows_e2e.py`: Full pipeline upload → plan → generate → test → export

### 8. LLM Client Extension (`backend/app/workflows/llm.py`)
Add structured output schemas and helper methods for:
- **Code generation** (file map JSON): `generate_code_file_map(spec, plan, phase_number, target_languages)`
- **Repair** (diagnosis + corrected file): `generate_repair(diagnosis, original_file, spec_context)`
- **Failure classification**: `classify_failure(test_error, endpoint_spec, generated_code)`
- **Export manifests**: `generate_export_manifest(export_type, generated_files, test_summary)`

Each method returns `(parsed_json, token_count)` with fallback JSON for offline/dev mode.

---

## Data Flow

```
Upload (doc_agent) → Plan (planner_agent) → [Approval Gate]
       ↓
Generate (code_agent) → writes files to S3, metadata to generated_files
       ↓
Test (test_agent) → MockSandboxClient runs fixtures → test_results + repair_attempts
       ↓ (self-healing loop max 3×)
Export (export_agent) → assembles artifacts → S3 keys in exports/sdk_packages/mcp_tools
```

## Failure Modes & Handling

| Failure Point | Handling |
|---------------|----------|
| LLM JSON parse error | Fallback to algorithmic template (like planner/doc agents) |
| Code generation timeout | Checkpointed — resume from last phase |
| Test sandbox error | Record as `TestResultStatus.FAILED` with error snapshot |
| Repair loop exhausted | `RepairOutcome.ESCALATED` → workflow `PAUSED_FOR_APPROVAL` |
| Export partial failure | Other exports continue; failed export marked `status=failed` |

## Rollout / Migration

- No DB migrations needed (models already in `0001_initial_schema.py`)
- Feature-flag new stages in `stages` param default: `["plan", "generate", "test", "export"]`
- Existing workflows with `stages=["plan"]` unchanged

## Validation Plan

1. **Unit**: Each agent in isolation with mocked LLM + mocked dependencies
2. **Integration**: Full pipeline via `POST /projects/{id}/workflows` with `stages=["plan","generate","test","export"]`
3. **E2E**: Upload OpenAPI spec → verify generated Python client compiles + passes mock tests → SDK tarball created
4. **Load**: 10 concurrent workflow runs, verify checkpointing + no cross-contamination

---

## Open Questions (Resolved)

1. **Both Python + Node.js** → Yes, implement both in Phase 3
2. **Mock sandbox first** → Yes, `FakeSandboxClient` for Python; Node type-check only
3. **Self-healing in Phase 3** → Yes, max 3 repair attempts per failing test

---

## File Tree (New/Modified)

```
backend/
├── app/
│   ├── workflows/
│   │   ├── agents/
│   │   │   ├── code_agent.py          # NEW
│   │   │   ├── test_agent.py          # NEW
│   │   │   └── export_agent.py        # NEW
│   │   └── orchestrator.py            # MODIFY (add stages)
│   ├── schemas/
│   │   ├── generate.py                # NEW
│   │   ├── testing.py                 # NEW
│   │   └── export.py                  # NEW
│   ├── api/v1/
│   │   ├── generate.py                # NEW
│   │   ├── testing.py                 # NEW
│   │   ├── export.py                  # NEW
│   │   └── router.py                  # MODIFY (include new routers)
│   └── services/
│       └── sandbox_service.py         # NEW (MockSandboxClient + protocol)
└── tests/
    ├── test_codegen.py                # NEW
    ├── test_testing.py                # NEW
    ├── test_export.py                 # NEW
    └── test_workflows_e2e.py          # NEW
```

---

## Dependencies

- `jinja2` for Python templates
- `httpx` already in deps
- `pydantic` v2 already in deps
- `ruff`/`mypy`/`typescript`/`eslint` — dev deps only (lint in CI, not runtime)

---

## Template Files (New)

The Code Generator Agent uses Jinja2 templates for both Python and Node.js targets:

```
backend/app/workflows/templates/
├── python/
│   ├── models.py.j2          # Pydantic v2 models for all endpoints
│   ├── client.py.j2          # httpx AsyncClient with auth, retry, error handling
│   ├── __init__.py.j2        # Package exports
│   └── pyproject.toml.j2     # Modern Python packaging (build, ruff, mypy)
└── node/
    ├── types.ts.j2           # Zod schemas + TypeScript types
    ├── client.ts.j2          # Fetch-based client with retry, auth
    ├── index.ts.j2           # Main entrypoint + resource namespace exports
    ├── package.json.j2       # ESM, TypeScript strict, vitest
    └── tsconfig.json.j2      # Strict TS config
```

Template context includes: `title`, `base_url`, `endpoints`, `resources` (grouped by resource), `auth_schemes`, helper filters (`normalize_name`, `python_type`, `ts_type`).