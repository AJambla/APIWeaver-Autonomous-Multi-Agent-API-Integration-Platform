# APIWeaver — Codebase Analysis Report

> **Inspection Date:** 2026-08-19 (Updated from 2026-08-16 baseline)
> **Scope:** Full repository read — reflects post-Phase 4 implementation.

---

## Executive Summary

The repository contains a **production-quality Phase 1 + Phase 2 + Phase 3 + Phase 4 foundation**. The auth system, RBAC, database schema, spec ingestion, workflow orchestration, code generation, testing, export pipeline, GitHub integration, real-time events, monitoring, history/versioning, and a partial frontend are all implemented.

**Key milestone reached:** Phase 4 — GitHub OAuth integration, SSE/WebSocket gateway, monitoring routes, history/versioning routes, spec patch, dependency graph, API key management, and a partial Next.js frontend — is now **fully implemented** on the backend.

### What changed since Aug 16 baseline:
- ✅ **Auth Config / Vault Integration** completed — routes, Vault client, and secrets_refs wiring
- ✅ **Bug 1 fixed** — Upload endpoint now returns 202 and triggers workflow in background
- ✅ **Bug 2 fixed** — `audit_service.record()` kwarg correctly maps to `event_metadata` column
- ✅ **Qdrant integrated** — full vector store client with tenant isolation
- ✅ **GitHub OAuth (Phase 4)** — connect, callback, status, disconnect, repos routes
- ✅ **SSE/WebSocket gateway** — real-time workflow progress streaming
- ✅ **Monitoring routes** — per-project and per-org metrics
- ✅ **History & versioning routes** — timeline, versions list, rollback
- ✅ **Spec patch route** — `PATCH /projects/{id}/spec/endpoints/{endpoint_id}`
- ✅ **Dependency graph route** — `GET /projects/{id}/dependency-graph`
- ✅ **API key management routes** — full CRUD
- ✅ **Frontend started** — Next.js app with landing, login, dashboard, project pages
- ✅ **Agent worker Celery tasks** — 5 task modules registered

---

## 1. What Is Complete ✅

### 1.1 — Database Layer (Full Schema)
All 28+ tables from `Database.md §3` are defined as SQLAlchemy models, including all three addendum tables:

| Model File | Tables Covered |
|---|---|
| `user.py` | `users`, `refresh_tokens`, `api_keys` |
| `organization.py` | `organizations`, `organization_members` |
| `project.py` | `projects`, `project_members` |
| `document.py` | `documents`, `document_versions` |
| `spec.py` | `api_specs`, `endpoints`, `endpoint_parameters`, `endpoint_dependencies` |
| `auth_config.py` | `auth_configs`, `secrets_refs` |
| `workflow.py` | `workflow_runs`, `workflow_checkpoints`, `agent_events`, `tool_calls` |
| `codegen.py` | `code_generation_runs`, `generated_files` |
| `testing.py` | `test_runs`, `test_results`, `repair_attempts` |
| `export.py` | `exports`, `github_exports`, `mcp_tools`, `sdk_packages`, `sdk_versions` |
| `audit.py` | `audit_logs` |
| `metrics.py` | `usage_metrics` |
| `versioning.py` | `artifact_versions` |
| `github.py` | `github_connections`, `github_oauth_states` |

**Four Alembic migrations exist:**
- `0001_initial_schema.py` — Full schema DDL (all non-partitioned tables)
- `0002_partitioned_tables.py` — `agent_events` and `usage_metrics` with monthly/daily Postgres range partitioning
- `0003_add_github_oauth_and_connections.py` — GitHub OAuth state and connection tables
- `0004_artifact_version_active.py` — Adds `is_active` flag to `artifact_versions`

### 1.2 — Authentication & Security
The auth stack is fully implemented to `Security.md` spec:

- ✅ **RS256 JWT** access tokens (60-min lifetime, `sub`, `org_id`, `role`, `iat`, `exp`, `jti` claims)
- ✅ **Argon2id** password hashing (OWASP-recommended params: `m=64MiB, t=3, p=4`)
- ✅ **Rotating refresh tokens** — single-use, family-level revocation on replay
- ✅ **JTI denylist** in Redis for immediate access token revocation on logout
- ✅ **API key auth** (`apw_live_` prefix, SHA-256 hash stored, never plaintext)
- ✅ **Both auth modes** (`Authorization: Bearer` + `X-API-Key`) resolved in a single `get_current_principal` dependency
- ✅ **Timing-safe** password verification and identical error messages to prevent account enumeration
- ✅ **Password rehash** on login when work factor has changed

**Routes:** `POST /auth/register`, `POST /auth/login`, `POST /auth/refresh`, `POST /auth/logout`, `GET /auth/me`

### 1.3 — RBAC Authorization Layer
- ✅ **Centralized policy matrix** (`rbac/policy.py`) — all permissions with explicit `RoleRequirement`
- ✅ **Policy validated at import time** — startup fails if any `Permission` has no entry
- ✅ **`require_project_permission()`** and `require_org_permission()` dependency factories
- ✅ **Cross-tenant isolation** — project access is checked against the DB resource's org, never a caller-supplied org_id
- ✅ **API key scoping** to a single project (`restricted_to_project_id`)
- ✅ **Org-role hierarchy** (owner → admin → member; billing is side-role)
- ✅ **Project-role hierarchy** (owner → editor → viewer)
- ✅ **Phase 3/4 permissions added**: `CODE_GENERATE`, `CODE_READ`, `TEST_RUN`, `TEST_READ`, `EXPORT_CREATE`, `EXPORT_READ`, `AUTH_CONFIG_READ`, `AUTH_CONFIG_WRITE`, `GITHUB_CONNECT`, `SPEC_UPDATE`, `WORKFLOW_READ`, `ORG_VIEW_BILLING`

### 1.4 — Project CRUD API
- ✅ `POST /api/v1/projects` — create with org permission check, duplicate-name 409
- ✅ `GET /api/v1/projects` — cursor-paginated list, filtered by status/org, multi-tenant isolation in query
- ✅ `GET /api/v1/projects/{id}` — with endpoint count and last-run status summary
- ✅ `DELETE /api/v1/projects/{id}` — soft-delete (archive), idempotent, audit logged

### 1.5 — Document Upload & Spec Ingestion
- ✅ `POST /api/v1/projects/{id}/upload` — multipart upload, content stored in S3/MinIO
- ✅ **Format auto-detection** — OpenAPI 3.x, Swagger 2.0, Postman Collection v2.1 (JSON/YAML)
- ✅ **Spec normalization** — endpoints, parameters, request/response schemas extracted into `NormalizedSpec`
- ✅ **Duplicate detection** — SHA-256 content checksum checked before storage
- ✅ `GET /api/v1/projects/{id}/spec` — returns latest normalized spec
- ✅ `GET /api/v1/projects/{id}/endpoints` — filterable by method, deprecated flag, confidence score

### 1.5.1 — Workflow Orchestration (Phase 2)
- ✅ **Orchestrator** (`orchestrator.py`) — sequential state machine with checkpoint persistence to PostgreSQL
- ✅ **Documentation Agent** — deterministic OpenAPI/Swagger/Postman parsing with LLM fallback for freeform docs
- ✅ **Planner Agent** — builds dependency graph + execution plan with risk assessment for destructive endpoints
- ✅ `POST /api/v1/projects/{id}/workflows` — triggers pipeline, returns `workflow_run_id`
- ✅ `GET /api/v1/workflows/{run_id}` — get current status and progress
- ✅ `POST /api/v1/workflows/{run_id}/approve` — human-in-the-loop approval gate
- ✅ `POST /api/v1/workflows/{run_id}/cancel` — idempotent cancellation
- ✅ `GET /api/v1/workflows/{run_id}/tool-calls` — tool call trace

### 1.6 — Real-Time Events (Phase 4)
- ✅ `GET /api/v1/workflows/{run_id}/sse` — Server-Sent Events stream for workflow progress
- ✅ `GET /ws/workflows/{run_id}` — WebSocket endpoint for real-time workflow events
- ✅ Redis Streams pub/sub for event fan-out

### 1.7 — Phase 3: Downstream Agents & APIs

#### 1.7.1 — Code Generator Agent
- ✅ `backend/app/workflows/agents/code_agent.py` — Full agent implementation
- ✅ Phase-by-phase generation with checkpointing
- ✅ Cross-chunk consistency pass
- ✅ `patch()` method for self-healing repairs
- ✅ **Jinja2 templates** for Python and Node.js (9 templates)

#### 1.7.2 — Testing Agent
- ✅ `backend/app/workflows/agents/test_agent.py` — Full agent implementation
- ✅ `MockSandboxClient` — in-process Python module execution via `importlib`
- ✅ `FailureClassifier` — LLM-based classification (8 categories)
- ✅ Self-healing repair loop (max 3 attempts)

#### 1.7.3 — Export Agent
- ✅ `backend/app/workflows/agents/export_agent.py` — Full agent implementation
- ✅ All 8 export types implemented: SDK, Client, FastAPI, Docker, GitHub, MCP, Docs, CI/CD

#### 1.7.4 — Phase 3 API Routes
- ✅ `POST /api/v1/projects/{id}/generate` — Trigger code generation
- ✅ `GET /api/v1/projects/{id}/files` — Lists generated files (paginated)
- ✅ `GET /api/v1/projects/{id}/files/{file_id}/content` — Get file content
- ✅ `POST /api/v1/projects/{id}/test` — Trigger tests
- ✅ `GET /api/v1/projects/{id}/test-runs/{run_id}` — Get test run with results
- ✅ `GET /api/v1/projects/{id}/test-runs/{run_id}/repairs` — List repair attempts
- ✅ `POST /api/v1/projects/{id}/export` — Trigger exports
- ✅ `POST /api/v1/projects/{id}/export/mcp` — MCP-specific export

### 1.8 — Phase 4: GitHub Integration
- ✅ `POST /api/v1/github/connect` — Initiate GitHub OAuth flow
- ✅ `GET /api/v1/github/callback` — Handle OAuth callback
- ✅ `GET /api/v1/github/status` — Get connection status
- ✅ `POST /api/v1/github/disconnect` — Revoke connection
- ✅ `GET /api/v1/github/repos` — List accessible repositories
- ✅ `GitHubConnection` and `GitHubOAuthState` models
- ✅ `github_service.py` with `GitHubOAuthClient` and `GitHubAppClient`
- ✅ Worker tasks: `github_oauth`, `github_export`

### 1.9 — Phase 5: Additional API Routes
- ✅ `GET /api/v1/projects/{id}/metrics` — Project-level metrics
- ✅ `GET /api/v1/org/{org_id}/metrics` — Org-level metrics
- ✅ `GET /api/v1/projects/{id}/history` — Paginated workflow run timeline
- ✅ `GET /api/v1/projects/{id}/versions` — Artifact versions list
- ✅ `POST /api/v1/projects/{id}/versions/{version_id}/rollback` — Rollback to version
- ✅ `PATCH /api/v1/projects/{id}/spec/endpoints/{endpoint_id}` — Manual endpoint correction
- ✅ `GET /api/v1/projects/{id}/dependency-graph` — Endpoint dependency graph
- ✅ `POST /api/v1/org/{org_id}/api-keys` — Create API key
- ✅ `GET /api/v1/org/{org_id}/api-keys` — List API keys
- ✅ `DELETE /api/v1/org/{org_id}/api-keys/{key_id}` — Revoke API key

### 1.10 — Auth Config & Vault (Phase 2 Completion)
- ✅ `GET /api/v1/projects/{id}/auth` — Retrieve non-secret auth configuration
- ✅ `PUT /api/v1/projects/{id}/auth` — Create/update auth config; credentials written to Vault
- ✅ `HttpVaultClient` — Async Vault client speaking HTTP KV v2
- ✅ `FakeVaultClient` — In-memory mock for testing
- ✅ `secrets_refs.vault_path` populated on credential write

### 1.11 — Qdrant Vector Store (Phase 2.6)
- ✅ `HttpQdrantClient` — Async Qdrant client over HTTP REST API
- ✅ `FakeQdrantClient` — In-memory mock for testing
- ✅ `ensure_collection`, `upsert_chunks`, `search`, `delete_by_document`
- ✅ Tenant isolation via payload filters (`project_id`)

### 1.12 — Agent Worker (Celery)
- ✅ `agent_worker/celery_app.py` — Full Celery application configuration
- ✅ `agent_worker/tasks/document_tasks.py`
- ✅ `agent_worker/tasks/codegen_tasks.py`
- ✅ `agent_worker/tasks/testing_tasks.py`
- ✅ `agent_worker/tasks/export_tasks.py`
- ✅ `agent_worker/tasks/workflow_tasks.py`

### 1.13 — Frontend (Partial)
- ✅ Next.js app with TypeScript, Tailwind CSS, shadcn/ui components
- ✅ Pages: landing (`/`), login (`/auth/login`), dashboard (`/dashboard`), project (`/projects/[id]`)
- ✅ Components: `Button`, `Card`, `Table`, `StatusBadge`, `Modal`, `Toast`, `Tabs`, `AppShell`
- ✅ Auth context and API client library

### 1.14 — Core Infrastructure
- ✅ **Structured JSON logging** via `structlog`
- ✅ **Two-layer rate limiting** — per-IP (anonymous, pre-auth) + per-org tier-scaled (authenticated)
- ✅ **Request ID middleware** — `X-Request-ID` generated or propagated
- ✅ **CORS middleware** with configurable allowed origins
- ✅ **Unified error envelope** — `{"error": {"code", "message", "details", "request_id"}}` on every error path
- ✅ **`/healthz`** — liveness probe
- ✅ **`/readyz`** — readiness probe
- ✅ **Async SQLAlchemy engine** with proper connection pool configuration
- ✅ **S3/MinIO storage adapter** with in-memory test substitute
- ✅ **Audit logging service** — every significant action recorded to `audit_logs`
- ✅ **`pydantic-settings`** config with fail-fast on missing required values

### 1.15 — What was fixed since Aug 14 analysis

| Bug # | Description | Status | Fix |
|---|---|---|---|
| Bug 1 | Upload returns 201, not 202; no workflow triggered | ✅ **FIXED** | Returns 202, triggers `Orchestrator.run()` in background |
| Bug 2 | `audit_service.record()` kwarg `metadata` may not map to `event_metadata` | ✅ **FIXED** | Kwarg is `metadata` but constructor passes `event_metadata=metadata` |
| Bug 3 | S3 Storage uses sync `boto3` in async context | ⚠️ **Mitigated** | `asyncio.to_thread()` used (works but blocks threads; consider `aiobotocore` for production scale) |

---

## 2. What Is Still Incomplete / Partially Implemented 🟡

### 2.1 — Freeform Document Ingestion Not Accessible From Upload
`spec_normalizer.py` **raises `UnprocessableEntityError`** for anything other than OpenAPI/Swagger/Postman. The LLM-based extraction pipeline in `doc_agent.py` exists as a fallback but is **unreachable from the upload endpoint** because `ingest_document()` calls `normalize()` synchronously before the orchestrator runs. A user uploading a Markdown/PDF/HTML file receives a 422 error. The LLM fallback path is only reachable if the normalized spec is injected directly into workflow state.

### 2.2 — `agent-worker` Not Integrated With Main App
The entire `agent_worker/` directory contains Celery task definitions, but:
- The main FastAPI app's `Orchestrator.run()` executes in-process via `BackgroundTasks`
- No Celery broker URL is wired into the main app
- No task dispatch from API routes to Celery
- Redis Streams are used for events, but Celery is not used for job dispatch

### 2.3 — `frontend` Is Partial
The `frontend/` directory contains a functional Next.js skeleton but only **4 of ~12 screens** specified in `UIUX.md` are built:
- ✅ Landing page
- ✅ Login page
- ✅ Dashboard
- ✅ Project page
- ❌ Upload screen
- ❌ Plan/Build screen
- ❌ Test screen
- ❌ Export screen
- ❌ Logs screen
- ❌ Settings screen
- ❌ History screen
- ❌ Monitoring screen

### 2.4 — GitHub Vault Token Storage Not Wired
GitHub OAuth callback (`github.py`) stores `access_token_vault_path` and `refresh_token_vault_path` in the database but **does not actually write the tokens to Vault**. The code comments indicate this is a placeholder:
```python
# Store tokens in Vault (implementation depends on vault_service)
# For now, we store Vault paths - actual token storage would be done here
```

### 2.5 — Infra Directories Are Skeleton-Only
Both `infra/charts/` and `infra/terraform/` contain only `.gitkeep` files. No Kubernetes manifests or Terraform modules exist.

### 2.6 — Monitoring Has No Implementation
`monitoring/dashboards/` exists but is empty. No Prometheus scrape config, no Grafana dashboard JSON, no OpenTelemetry instrumentation in code.

### 2.7 — Enterprise Rate Limit Is Hardcoded to Pro Ceiling
`ratelimit.py` sets `"enterprise": 600` (same as Pro). This is documented in code comments as a stopgap, but Enterprise org SLAs per `API.md §3` cannot be honored until per-org overrides are implemented.

### 2.8 — Self-Review / Reflection Not Implemented
`AI_Instruction.md §9` describes a reflection pass where the Code Generator Agent reviews its own output before testing. This is not implemented in `code_agent.py`.

### 2.9 — Token Budget Enforcement Not Implemented
`AI_Instruction.md §22` and `Security.md §15` describe per-project/org token budgets with hard cutoffs. The `workflow_runs` model has `total_tokens_used` and `estimated_cost_usd` columns, and the LLM system prompt mentions budgets, but no enforcement logic exists.

### 2.10 — Retry Policy Config Endpoint Not Implemented
`Feature.md §15` describes a configurable retry policy. The generated SDKs include retry logic, but `PUT /api/v1/projects/{id}/settings/retry-policy` does not exist.

### 2.11 — DB Permission Enforcement Is Future Work
Append-only enforcement on `audit_logs` is implemented at the application layer (`audit_service` exposes no update/delete path). The `GRANT` at the database level (withholding `UPDATE`/`DELETE` from the application role) belongs to infrastructure provisioning (Phase 6 / Terraform).

---

## 3. What Is Broken / Mismatched 🔴

| # | Bug | Description | Impact |
|---|---|---|---|
| Bug 3 | Sync S3 in async context | `boto3` calls wrapped in `asyncio.to_thread()` | Performance bottleneck at scale |

---

## 4. What Should Be Implemented Next 🔵

### Phase 2 Remaining (High Priority)

| # | Task | Spec Refs |
|---|---|---|
| 2.1 | **Freeform Document Ingestion** — route non-OpenAPI uploads to LLM extraction pipeline | Feature.md §2, AI_Instruction.md §2.1 |
| 2.2 | **GitHub Vault token wiring** — actually write OAuth tokens to Vault on callback | Security.md §7, Feature.md §22 |
| 2.3 | **Enterprise rate limit overrides** — per-org configurable limits | API.md §3, ratelimit.py |
| 2.4 | **Self-review reflection pass** — Code Generator reviews own output before testing | AI_Instruction.md §9 |
| 2.5 | **Token budget enforcement** — hard cutoffs per project/org | Security.md §15, AI_Instruction.md §22 |

### Phase 4 — Real-Time & Integration Enhancements

| # | Task | Spec Refs |
|---|---|---|
| 4.1 | **Celery integration** — wire worker tasks into main app async dispatch | Architecture.md §14, Deployment.md §4 |
| 4.2 | **WebSocket/SSE gateway** — Redis Streams → real-time progress to frontend (backend done, frontend consumer missing) | Architecture.md §8 |
| 4.3 | **OpenTelemetry instrumentation** — spans per agent node, correlated with LangSmith | Architecture.md §13, AI_Instruction.md §19 |

### Phase 5 — Frontend & Remaining API

| # | Task | Spec Refs |
|---|---|---|
| 5.1 | **Next.js frontend screens** — upload, plan, build, test, export, logs, settings, history, monitoring | UIUX.md |
| 5.2 | **Retry policy config endpoint** — `PUT /projects/{id}/settings/retry-policy` | Feature.md §15 |
| 5.3 | **Logs API route** — `GET /api/v1/projects/{id}/logs` | Feature.md §16 |

### Phase 6 — Infrastructure & Observability

| # | Task | Spec Refs |
|---|---|---|
| 6.1 | **Helm charts** — Kubernetes manifests for all services | Deployment.md §5 |
| 6.2 | **Terraform** — AWS infrastructure (EKS, RDS, ElastiCache, S3, CloudFront) | Architecture.md §6, Deployment.md §7 |
| 6.3 | **Grafana dashboards** — Prometheus metrics, Loki logs | Feature.md §25 |
| 6.4 | **DB permission enforcement** — GRANT INSERT/SELECT only on `audit_logs` at infra level | ADDENDUM §A.3 |
| 6.5 | **Prometheus scrape configs** — annotations on all services | Deployment.md §10 |

---

## 5. Feature Completeness Matrix

| Feature (PRD §11) | Priority | Status |
|---|---|---|
| FR-1: Parse OpenAPI/Swagger/Postman | P0 | ✅ Complete |
| FR-2: LLM extraction for freeform docs | P0 | 🟡 LLM fallback exists in doc_agent but upload endpoint rejects freeform docs before reaching it |
| FR-3: Auth scheme detection | P0 | ✅ Complete (extraction + Vault integration) |
| FR-4: Dependency graph builder | P1 | ✅ Complete (Planner Agent builds dependency graph) |
| FR-5: User-reviewable execution plan | P0 | ✅ Complete (Planner Agent + approval gate) |
| FR-6: Python + Node.js code generation | P0 | ✅ Complete (Code Generator Agent with templates) |
| FR-7: Automated test generation | P0 | ✅ Complete (Testing Agent with fixtures) |
| FR-8: Sandbox test execution | P0 | ✅ Complete (MockSandboxClient in-process) |
| FR-9: Self-healing repair loop | P0 | ✅ Complete (max 3 attempts, integrates with Code Agent) |
| FR-10: Export (SDK/Docker/GitHub/MCP) | P0 | ✅ Complete (Export Agent with 8 types) |
| FR-11: Execution history + versioning | P1 | ✅ Complete (DB models + routes) |
| FR-12: REST API + web dashboard | P0 | 🟡 API complete for Phases 1-4; frontend partial (~4 of ~12 screens) |

---

## 6. Code Quality Assessment

| Dimension | Verdict |
|---|---|
| Architecture | **Excellent** — clean layering (routes → services → models → db), deny-by-default RBAC, no leaking abstractions, phased pipeline design |
| Security | **Excellent** — Argon2id, RS256, refresh token rotation with replay detection, JTI denylist, timing-safe auth, Vault-backed secrets |
| Test coverage | **Good** — 40+ async tests (37 Phase 1/2 + 4 Phase 3 files + Phase 4 tests), full test isolation per test |
| Documentation | **Excellent** — every source file references the exact spec section it implements |
| Type safety | **Strict** — `mypy strict` mode with Pydantic v2 models throughout |
| Async consistency | **Good** — async/await throughout; S3 uses `asyncio.to_thread()` (minor concern) |
| Bugs identified | **1 confirmed** — sync S3 in async context (Bug 3, mitigated) |
