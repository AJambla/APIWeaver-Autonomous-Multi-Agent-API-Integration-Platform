# APIWeaver — Codebase Analysis Report

> **Inspection Date:** 2026-08-24
> **Scope:** Full repository re-read — reflects post-Phase 6 implementation with corrections.

---

## Executive Summary

The repository contains a **production-quality Phases 1 → 6 foundation**. The auth system, RBAC, database schema, spec ingestion, workflow orchestration, code generation, testing, export pipeline, agent-worker, frontend build, real-time events, additional API routes, and **Infrastructure & Observability (Helm, Terraform, Monitoring, OpenTelemetry, CI/CD, Self-hosted Compose)** are all complete and hardened.

**Key milestone reached:** Phase 6 — Infrastructure & Observability — is fully implemented. Phase 7 (final remaining items) is **also now complete**.

### Key Highlights:
- ✅ **Freeform LLM extraction IS implemented** — `doc_agent.py` lines 113–161 perform LLM-based freeform document extraction with fallback.
- ✅ **Qdrant service IS fully implemented** — `qdrant_service.py` has a complete `HttpQdrantClient` + `FakeQdrantClient` with cosine similarity.
- ✅ **Qdrant embedding pipeline NOW WIRED** — `doc_agent.py` calls `upsert_chunks()` for both deterministic and freeform docs; `LLMClient.generate_embedding()` added; `document_parser.py` (PDF/HTML/Markdown) and `chunker.py` created; `orchestrator.py` passes Qdrant client; Celery task creates client.
- ✅ **Freeform upload path FIXED** — `ingestion_service.ingest_document()` catches `UnprocessableEntityError`, stores Document only, returns `(doc, None, None)`; orchestrator runs `doc_agent`, persists LLM-extracted spec to DB. `.txt`/`.md`/`.pdf`/`.html` uploads now return 202.
- ✅ **Test count** — 20 test modules (plus `conftest.py`) covering all endpoints, agent logic, Celery tasks, and pipelines.
- ✅ **Frontend fully complete (Phase 5)** — Monitoring dashboard (`/projects/[id]/monitoring`) + org-level `/monitoring` implemented; all 9 missing UI components built; 404/500/auth-denied error screens added; Plan/Test/History/Settings pages enhanced per `UIUX.md §2`. New deps: `recharts`, `@monaco-editor/react`.

---

## 1. What Is Complete ✅

### 1.1 — Database Layer (Full Schema)
All 28+ tables from `Database.md §3` are defined as SQLAlchemy models, including all addendum tables:

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
| `retry.py` | `retry_configs` |

**Six Alembic migrations exist:**
- `0001_initial_schema.py` — Full schema DDL (all non-partitioned tables)
- `0002_partitioned_tables.py` — `agent_events` and `usage_metrics` with monthly/daily Postgres range partitioning
- `0003_add_github_oauth_and_connections.py` — GitHub OAuth state and connection tables
- `0004_artifact_version_active.py` — Adds `is_active` flag to `artifact_versions`
- `0005_rate_limit_override.py` — Adds `rate_limit_override` column to `organizations`
- `0006_retry_configs.py` — Creates `retry_configs` table for per-project retry policy configuration

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
- ✅ **Documentation Agent** (`doc_agent.py`) — deterministic OpenAPI/Swagger/Postman parsing + **LLM fallback for freeform docs** (Markdown/text via `generate_json`)
- ✅ **Planner Agent** — builds dependency graph + execution plan with risk assessment for destructive endpoints
- ✅ **Qdrant Embedding Pipeline** — `doc_agent.py` now extracts text (PDF/HTML/Markdown via `document_parser.py`), chunks (`chunker.py`), generates embeddings (`LLMClient.generate_embedding()`), and upserts to Qdrant
- ✅ **Freeform Document Ingestion** — `ingestion_service.py` catches `UnprocessableEntityError`, stores Document only, orchestrator runs `doc_agent`, persists LLM-extracted spec to DB
- ✅ `POST /api/v1/projects/{id}/workflows` — triggers pipeline, returns `workflow_run_id`
- ✅ `GET /api/v1/workflows/{run_id}` — get current status and progress
- ✅ `POST /api/v1/workflows/{run_id}/approve` — human-in-the-loop approval gate
- ✅ `POST /api/v1/workflows/{run_id}/cancel` — idempotent cancellation
- ✅ `GET /api/v1/workflows/{run_id}/tool-calls` — tool call trace

### 1.6 — Real-Time Events (Phase 4)
- ✅ `GET /api/v1/workflows/{run_id}/sse` — Server-Sent Events stream for workflow progress
- ✅ `GET /ws/workflows/{run_id}` — WebSocket endpoint for real-time workflow events
- ✅ Redis Streams pub/sub for event fan-out

### 1.7 — Logs API (Phase 4)
- ✅ `GET /api/v1/projects/{id}/logs` — paginated agent events with cursor-based pagination
- ✅ Frontend Logs page at `/projects/[id]/logs` with filtering and auto-refresh

### 1.8 — Phase 3: Downstream Agents & APIs

#### 1.8.1 — Code Generator Agent
- ✅ `backend/app/workflows/agents/code_agent.py` — Full agent implementation
- ✅ Phase-by-phase generation with checkpointing
- ✅ Cross-chunk consistency pass
- ✅ `patch()` method for self-healing repairs
- ✅ **Jinja2 templates** for Python and Node.js (9 templates)

#### 1.8.2 — Testing Agent
- ✅ `backend/app/workflows/agents/test_agent.py` — Full agent implementation
- ✅ `MockSandboxClient` — in-process Python module execution via `importlib`
- ✅ `FailureClassifier` — LLM-based classification (8 categories)
- ✅ Self-healing repair loop (max 3 attempts)

#### 1.8.3 — Export Agent
- ✅ `backend/app/workflows/agents/export_agent.py` (24 KB) — Full agent implementation
- ✅ `ExportAgent` class with `run(state, export_types)` method
- ✅ All 8 export types implemented:
  - **SDK**: Python wheel / npm package manifests
  - **Client**: Single-module flattened clients (client.py / client.ts)
  - **FastAPI**: Router with DI auth
  - **Docker**: Multi-stage Dockerfile + docker-compose.yml with health checks
  - **GitHub**: Repo creation manifest (Vault-stored GITHUB_TOKEN)
  - **MCP**: Tool definitions (JSON Schema) + stdio/SSE server
  - **Docs**: OpenAPI 3.1 spec + Markdown reference
  - **CI/CD**: GitHub Actions workflows (lint, test, build, publish)

#### 1.8.4 — Phase 3 API Routes
- ✅ `POST /api/v1/projects/{id}/generate` — Trigger code generation
- ✅ `GET /api/v1/projects/{id}/files` — Lists generated files (paginated)
- ✅ `GET /api/v1/projects/{id}/files/{file_id}/content` — Get file content
- ✅ `POST /api/v1/projects/{id}/test` — Trigger tests
- ✅ `GET /api/v1/projects/{id}/test-runs/{run_id}` — Get test run with results
- ✅ `GET /api/v1/projects/{id}/test-runs/{run_id}/repairs` — List repair attempts
- ✅ `POST /api/v1/projects/{id}/export` — Trigger exports
- ✅ `POST /api/v1/projects/{id}/export/mcp` — MCP-specific export
- ✅ RBAC permissions: `CODE_GENERATE`/`CODE_READ` (Editor+), `TEST_RUN`/`TEST_READ` (Editor+), `EXPORT_CREATE`/`EXPORT_READ` (Owner+)

#### 1.8.5 — Phase 3 Schemas
- ✅ `backend/app/schemas/generate.py` — `GenerateRequest`, `GenerateResponse`, `FileResponse`, `FileContentResponse`
- ✅ `backend/app/schemas/testing.py` — `TestRequest`, `TestRunResponse`, `TestResultResponse`, `RepairAttemptResponse`, `TestRunSummaryResponse`
- ✅ `backend/app/schemas/export.py` — `ExportRequest`, `ExportResponse`, `MCPExportResponse`, `ExportArtifactResponse`

#### 1.8.6 — LLM Client Extensions
- ✅ `LLMClient.generate_json()` — base JSON structured output (OpenAI + Anthropic + mock fallback)
- ✅ `LLMClient.generate_code_file_map()` — structured code generation
- ✅ `LLMClient.generate_repair()` — targeted repair with diagnosis
- ✅ `LLMClient.classify_failure()` — failure classification
- ✅ `LLMClient.generate_export_manifest()` — export manifest generation

#### 1.8.7 — Phase 3 Tests
- ✅ `backend/tests/test_codegen.py` — Agent unit tests + API integration
- ✅ `backend/tests/test_testing.py` — Mock sandbox execution, failure classification, repair loop
- ✅ `backend/tests/test_export.py` — Each export type packaging
- ✅ `backend/tests/test_workflows_e2e.py` — Full pipeline tests

### 1.9 — GitHub Export & OAuth (Phase 4)

#### 1.9.1 — GitHub App Client
- ✅ `backend/app/services/github_service.py` — `GitHubAppClient` for JWT + installation token auth
- ✅ **Git Data API** — push commits, create/update repositories, manage branches
- ✅ **Repo creation manifest** — generates GitHub export artifacts with Vault-stored `GITHUB_TOKEN`

#### 1.9.2 — GitHub OAuth Client
- ✅ `GitHubOAuthClient` — OAuth code exchange with client secret fetched from Vault via `create_vault_client()`
- ✅ **OAuth flow** — `GET /api/v1/github/oauth/authorize` and `GET /api/v1/github/oauth/callback`
- ✅ `github_oauth_connections` DB table — stores installation state, access tokens, scopes

#### 1.9.3 — GitHub Export Routes
- ✅ `POST /api/v1/projects/{id}/export/github` — trigger GitHub export
- ✅ RBAC permission: `GITHUB_EXPORT` (Owner+)

### 1.10 — Agent-Worker (Phase 4)

- ✅ `agent-worker/celery_app.py` — Celery application configured with Redis broker
- ✅ `agent-worker/tasks/document_tasks.py` — async document processing tasks
- ✅ `agent-worker/tasks/codegen_tasks.py` — async code generation tasks
- ✅ `agent-worker/tasks/testing_tasks.py` — async testing tasks
- ✅ `agent-worker/tasks/export_tasks.py` — async export tasks
- ✅ **Note:** `agent_worker/` (underscore) exists alongside `agent-worker/` (hyphen) for Python import compatibility

### 1.11 — Real-Time Event Streaming (Phase 4)

- ✅ `backend/app/services/event_publisher.py` — Redis Streams publisher for workflow events
- ✅ `GET /api/v1/events/stream` — SSE endpoint for real-time progress updates
- ✅ **Event types**: workflow status changes, agent events, tool calls, test results, export progress
- ✅ `backend/tests/test_events.py` — Event publisher and SSE endpoint tests

### 1.12 — Next.js Frontend (Phase 4 — Core + Feature Pages)

- ✅ `frontend/` — Next.js 14 app with App Router
- ✅ **Implemented pages:**
  - `app/page.tsx` — Landing/redirect
  - `app/auth/login/` — Login page
  - `app/dashboard/` — Dashboard page
  - `app/projects/[id]/` — Project detail page (tabs: Overview, Spec, Workflows, Code, Tests, Exports)
  - `app/projects/[id]/upload/` — Upload page with file selection and format detection
  - `app/projects/[id]/plan/` — Plan page (review execution plan, approve workflow)
  - `app/projects/[id]/settings/` — Settings page (General, Auth & Secrets, Team, Danger Zone tabs)
  - `app/projects/[id]/history/` — History page (workflow run timeline)
  - `app/projects/[id]/logs/` — Logs page with filtering and auto-refresh
  - `app/projects/[id]/build/` — Build page
  - `app/projects/[id]/test/` — Test page
  - `app/projects/[id]/export/` — Export page
  - ✅ **Base component library**: `AppShell`, `Button`, `Card`, `Modal`, `StatusBadge`, `Table`, `Tabs`, `Toast`
  - ✅ **New UI components (Phase 5, per `UIUX.md §1.5`)**: `CodeBlock` (Monaco read-only + diff via `@monaco-editor/react`, lazy-loaded with `ssr:false`), `Timeline` (vertical/horizontal), `ProgressStepper` (Plan→Generate→Test→Export), `ToolCallLogViewer` (expandable JSON tree), `DependencyGraphView` (interactive SVG: pan/zoom, click-to-highlight, method colors, destructive flag), `SelfHealingTimeline` (expandable repair attempts), `TestCoverageChart` (recharts donut), `MetricsDashboard` (KPI cards + spend bar chart), `HistoryTimeline`, plus `AgentHealthPanel` (derived from real workflow runs), `RunComparisonView` (Monaco diff), and `charts.tsx` line/area/bar/donut wrappers (theme-aware via CSS variables)
  - ✅ **Implemented pages (full set)**:
    - `app/page.tsx` — Landing/redirect
    - `app/auth/login/` — Login page
    - `app/dashboard/` — Dashboard page
    - `app/monitoring/` — Org-level monitoring dashboard (`/org/{org_id}/metrics`)
    - `app/projects/[id]/` — Project detail page
    - `app/projects/[id]/upload/` — Upload page
    - `app/projects/[id]/plan/` — Plan page (`ProgressStepper`, `DependencyGraphView`, `PlanApprovalModal`)
    - `app/projects/[id]/settings/` — Settings (General, Auth & Secrets, **Retry Policy**, **Billing/Usage**, Team, Danger Zone)
    - `app/projects/[id]/history/` — History (`HistoryTimeline`, `RunComparisonView`, rollback dialog)
    - `app/projects/[id]/logs/` — Logs page
    - `app/projects/[id]/build/` — Build page
    - `app/projects/[id]/test/` — Test page (`TestRunPanel`, `SelfHealingTimeline`, `TestCoverageChart`, SSE live results)
    - `app/projects/[id]/export/` — Export page
    - `app/projects/[id]/monitoring/` — Monitoring dashboard (`/projects/{id}/metrics`)
    - `app/projects/[id]/auth-denied/` — Permission-denied screen
    - `app/not-found.tsx`, `app/error.tsx`, `app/global-error.tsx` — Error boundaries (404 / 500 platform-vs-target-API / global)
  - ✅ **Lib utilities**: `api.ts`, `auth-context.tsx`, `auth.ts`, `cn.ts`, `types.ts` (extended with monitoring/dependency-graph/test/workflow/version/retry types), `use-workflow-events.ts` (SSE)
  - ✅ **Libraries**: React 18, Tailwind CSS, `recharts` (charts), `@monaco-editor/react` (code/diff editor)
  - ✅ **Build artifacts** — `.next/` directory present (production build output; `npm run typecheck`, `npm run lint`, `npm run build` all pass)

### 1.13 — Additional API Routes (Phase 4)

- ✅ `backend/app/api/v1/history.py` — version history, rollback endpoints
- ✅ `backend/app/api/v1/monitoring.py` — metrics per project and per org
- ✅ `backend/app/api/v1/dependency_graph.py` — `GET /projects/{id}/dependency-graph`
- ✅ `backend/app/api/v1/spec_patch.py` — `PATCH /projects/{id}/spec/endpoints/{endpoint_id}`
- ✅ `backend/app/api/v1/api_keys.py` — org API-key management (create, list, revoke)
- ✅ `backend/app/api/v1/events.py` — SSE stream for real-time events
- ✅ `backend/app/api/v1/github.py` — GitHub OAuth authorize/callback routes
- ✅ `backend/app/api/v1/settings.py` — project retry policy settings endpoints
- ✅ `backend/app/api/v1/organizations.py` — organization rate-limit override endpoints
- ✅ All 17 route modules wired in `router.py` (plus health route in `main.py`) with rate limiting

### 1.14 — Auth Config / Vault Integration (Phase 4)

- ✅ `backend/app/api/v1/auth_config.py` — `GET/PUT /projects/{id}/auth` with Vault write
- ✅ `backend/app/services/vault_service.py` — `HttpVaultClient` (KV v2), `FakeVaultClient`, `create_vault_client()` dependency
- ✅ **Secrets management** — auth configs stored in Vault with `secrets_refs` tracking in DB
- ✅ `backend/tests/test_auth_config.py` — Auth config and Vault client tests

### 1.15 — Qdrant Vector Store Client + Embedding Pipeline (Phase 2 — Complete)
- ✅ `backend/app/services/qdrant_service.py` — **Fully implemented** (not a skeleton)
  - `HttpQdrantClient` — async HTTP REST client with `ensure_collection`, `upsert_chunks`, `search`, `delete_by_document`
  - `FakeQdrantClient` — in-memory substitute with cosine similarity scoring for tests
  - `create_qdrant_client()` — FastAPI dependency factory
  - Tenant isolation via `project_id` filter on all search queries
  - `FakeQdrantClient` wired in `conftest.py` via dependency override
- ✅ **Embedding Pipeline** — `LLMClient.generate_embedding()` (OpenAI `text-embedding-3-small`, 1536 dims), `chunker.py` for text chunking, `document_parser.py` for PDF/HTML/Markdown extraction
- ✅ **Wired into ingestion** — `doc_agent.py` calls `qdrant_client.upsert_chunks()` for both deterministic and freeform documents; `orchestrator.py` passes Qdrant client; Celery task creates client in async mode

### 1.16 — Infrastructure & Observability (Phase 6)

#### 1.15.1 — Helm Chart (Kubernetes / EKS)
- ✅ `infra/charts/apiweaver/Chart.yaml` — chart metadata, apiweaver/1.0.0
- ✅ `infra/charts/apiweaver/values.yaml` — all tunables: replicaCounts, image tags, resource limits, env vars, secrets refs, autoscaling, ingress, HPA thresholds
- ✅ `infra/charts/apiweaver/templates/_helpers.tpl` — common name/label templates
- ✅ `infra/charts/apiweaver/templates/configmap.yaml` — non-secret env (CORS origins, log level, rate limit tiers)
- ✅ `infra/charts/apiweaver/templates/secrets.yaml` — placeholder Kubernetes Secrets; production values sourced from Vault Agent Injector
- ✅ `infra/charts/apiweaver/templates/api-deployment.yaml` — FastAPI deployment, HPA (2–20 replicas), service, Prometheus annotations
- ✅ `infra/charts/apiweaver/templates/agent-worker-deployment.yaml` — Celery worker deployment, dedicated node selector/taint for `agents` node group
- ✅ `infra/charts/apiweaver/templates/web-deployment.yaml` — Next.js deployment, HPA (2–10), service
- ✅ `infra/charts/apiweaver/templates/ingress.yaml` — ALB Ingress rules: `/api/*` → api, `/*` → web, `/ws/*` → SSE gateway
- ✅ `infra/charts/apiweaver/templates/hpa.yaml` — HPA resources for api, agent-worker, web
- ✅ `infra/charts/apiweaver/templates/networkpolicy.yaml` — deny-by-default egress for agent-worker sandbox pods

#### 1.15.2 — Terraform (AWS Infrastructure)
- ✅ All 9 modules: `vpc`, `eks`, `rds`, `elasticache`, `s3`, `cloudfront`, `alb`, `kms`, `route53`
- ✅ `infra/terraform/main.tf` — module instantiations with production/staging workspaces
- ✅ `infra/terraform/backend.tf` — S3 remote state + DynamoDB lock table
- ✅ `infra/terraform/variables.tf` — region, environment, domain, allowed IPs
- ✅ `infra/terraform/outputs.tf` — ALB DNS, CloudFront domain, RDS endpoint, Redis endpoint, EKS kubeconfig

#### 1.15.3 — Monitoring Dashboards & Scrape Config
- ✅ Prometheus annotations added to FastAPI, Celery worker, and Next.js pods in Helm templates
- ✅ `prometheus-fastapi-instrumentator` added to `pyproject.toml` dependencies
- ✅ `/metrics` endpoint exposed in `main.py`
- ✅ `monitoring/dashboards/apiweaver-overview.json` — RED metrics per API route
- ✅ `monitoring/dashboards/agent-workflows.json` — workflow run duration, token spend
- ✅ `monitoring/dashboards/infrastructure.json` — EKS node CPU/mem, RDS connections, Redis hit rate
- ✅ `monitoring/alert_rules.yaml` — Alertmanager rules (error rate, crash-loop, queue depth, RDS storage, failed workflows)

#### 1.15.4 — OpenTelemetry Instrumentation
- ✅ `opentelemetry-*` packages added to `pyproject.toml`
- ✅ `backend/app/core/telemetry.py` — OTel configuration with service name `apiweaver-api`
- ✅ Spans exported to `OTEL_EXPORTER_OTLP_ENDPOINT`
- ✅ `request_id` and `workflow_run_id` propagated as span attributes
- ✅ LangSmith correlation via `LANGSMITH_API_KEY`

#### 1.15.5 — GitHub Actions CI/CD
- ✅ `.github/workflows/ci.yml` — Triggers: push to `main`, pull requests
- ✅ Jobs: `test` (pytest, ruff, mypy), `build` (backend image to ECR), `build-frontend` (Next.js to ECR), `deploy` (helm upgrade on main branch)

#### 1.15.6 — Self-Hosted Single-Node Docker Compose
- ✅ `infra/docker/docker-compose.single-node.yml` — Services: `web`, `api`, `agent-worker`, `postgres`, `redis`, `qdrant`, `vault`, `minio`
- ✅ `infra/docker/docker-compose.dev.yml` — API-only dev compose (Phase 1/2/3/4)
- ✅ Health checks for all services; shared `apiweaver` network

---

## 2. What Is Incomplete / Partially Implemented 🟡

### 2.1 — Enterprise Rate Limit Overrides
✅ **Implemented** — `organizations.rate_limit_override` column added (migration `0005`), `enforce_org_rate_limit` in `ratelimit.py:178` uses per-org override when set, new `PUT/DELETE /api/v1/organizations/{org_id}/rate-limit` endpoint (owner-only via `ORG_EDIT_BILLING`) with `RateLimitUpdate`/`RateLimitResponse` schemas. Enterprise orgs can now be given a custom ceiling.

### 2.2 — Frontend Feature Gaps
The Next.js frontend is now feature-complete per `UIUX.md §2`. All screens are implemented and linked in the `AppShell` `PROJECT_NAV`, and the 9 missing UI components are built and reusable. All originally-planned backend gaps are now implemented (Phase 7 complete).

| Screen | UIUX.md Ref | Status |
|---|---|---|
| Landing Page | §2.1 | ✅ Implemented (`app/page.tsx`) |
| Upload Screen | §2.4 | ✅ Implemented (`app/projects/[id]/upload/page.tsx`) — file selection, format detection, progress |
| Integration Builder / Plan | §2.5 | ✅ Complete — `DependencyGraphView` (interactive SVG), `PlanApprovalModal` (Monaco plan + approve), `ProgressStepper` synced to workflow status |
| Testing Screen | §2.6 | ✅ Complete — `TestRunPanel` (env/endpoint selectors), `SelfHealingTimeline`, `TestCoverageChart`, SSE live results via `useWorkflowEvents` |
| Settings | §2.8 | ✅ Complete — General, Auth & Secrets, **Retry Policy** (backend API live, was localStorage stub), **Billing/Usage** (org metrics), Team, Danger Zone tabs |
| Monitoring Dashboard | §2.9 | ✅ Complete — `MetricsDashboard` + `AgentHealthPanel` at `/projects/[id]/monitoring` and org-level `/monitoring` |
| History Screen | §2.10 | ✅ Complete — `HistoryTimeline`, `RunComparisonView` (Monaco diff), rollback dialog |
| Error Screens (404, 500, auth-denied) | §2.11 | ✅ Complete — `not-found.tsx`, `error.tsx` (platform vs target-API), `global-error.tsx`, `auth-denied` page |

**Missing UI components** (per `UIUX.md §1.5`) — ✅ **All 9 built**:
- `CodeBlock` (Monaco read-only + diff), `Timeline`, `ProgressStepper`, `ToolCallLogViewer`, `DependencyGraphView`, `SelfHealingTimeline`, `TestCoverageChart`, `MetricsDashboard`, `HistoryTimeline` (plus `AgentHealthPanel`, `RunComparisonView`, and chart wrappers).

### 2.3 — Retry Policy Config API (Backend)
✅ **Implemented** — `retry_configs` table (migration `0006`) with `max_attempts`, `backoff_base_seconds`, `retryable_status_codes`; `RetryConfig` model, `RetryPolicyRequest`/`RetryPolicyResponse` schemas, `GET/PUT /api/v1/projects/{id}/settings/retry-policy` routes (gated by `PROJECT_SETTINGS_WRITE`), wired in `router.py`. Frontend localStorage fallback removed (`settings/page.tsx`).

### 2.4 — DB Permission Enforcement for `audit_logs`
✅ **Implemented** — `infra/terraform/modules/rds/variables.tf` adds `db_app_role` (default `"apiweaver"`); `infra/terraform/modules/rds/main.tf` includes an idempotent `null_resource` (with `DO $$ ... EXCEPTION ... END $$` block) that GRANTs `INSERT, SELECT` on `audit_logs` and REVOKEs `UPDATE, DELETE` from the app role after RDS creation.

---

## 3. What Is Broken / Mismatched 🔴

| # | Bug | Description | Impact |
|---|---|---|---|
| Bug 1 | ~~Sync S3 in async context~~ | **FIXED** — `storage_service.py` now uses `aiobotocore` (`AsyncS3ObjectStorage`) instead of `boto3` + `asyncio.to_thread()` | No more thread pool exhaustion under concurrency |
| Bug 2 | ~~Freeform upload path broken~~ | **FIXED** — `ingestion_service.py` now catches `UnprocessableEntityError` and returns Document only; orchestrator runs doc_agent for freeform docs | Freeform doc uploads now work (202) |
| Bug 3 | ~~`ingestion_service` does not populate Qdrant~~ | **FIXED** — `doc_agent.py` calls `qdrant_client.upsert_chunks()` for both deterministic and freeform paths | RAG now functional; vector store populated on every upload |

---

## 4. What Should Be Implemented Next 🔵

### Phase 2 Remaining (High Priority) — **COMPLETED**

| # | Task | Spec Refs | Effort | Status |
|---|---|---|---|---|
| 2.1 | **Qdrant embedding pipeline** — add `create_embedding()` (OpenAI `text-embedding-3-small`), chunking step, wire `upsert_chunks()` in `ingestion_service` or `document_tasks.py` | Architecture.md §2, Database.md §8 | Medium | ✅ **DONE** |
| 2.2 | **Freeform document pre-processing** — add PDF→text (pypdf) and HTML→text (BeautifulSoup) preprocessing before `normalize()` or LLM extraction; fix the sync-before-async path | Feature.md §2, AI_Instruction.md §2.1 | Medium | ✅ **DONE** |

### Phase 5 — Frontend Feature Completion (High Priority) — ✅ COMPLETE

| # | Task | UIUX.md Ref | Effort | Status |
|---|---|---|---|---|
| 5.1 | **Integration Builder** — `ProgressStepper`, `DependencyGraphView`, `PlanApprovalModal` (Monaco plan via `CodeBlock`), live workflow progress | §2.5 | Large | ✅ **DONE** |
| 5.2 | **Testing screen** — `TestRunPanel` (env + endpoint targeting), `SelfHealingTimeline`, `TestCoverageChart`, SSE live results | §2.6 | Medium | ✅ **DONE** |
| 5.3 | **Monitoring dashboard** — `MetricsDashboard`, `CostUsageChart`/`AgentHealthPanel` (project + org `/monitoring`) | §2.9 | Medium | ✅ **DONE** |
| 5.4 | **History screen** — `HistoryTimeline`, `RunComparisonView` (Monaco diff), rollback dialog | §2.10 | Medium | ✅ **DONE** |
| 5.5 | **Error screens** — 404, 500/Agent Failure, Auth/Permission Denied | §2.11 | Small | ✅ **DONE** |

### Phase 7 — Remaining Items (Nice-to-Have) — ✅ COMPLETED

| # | Task | Spec Refs | Effort | Status |
|---|---|---|---|---|
| 7.1 | **DB permission enforcement** — GRANT INSERT/SELECT only on `audit_logs` at Terraform/RDS level (idempotent `null_resource`) | ADDENDUM §A.3 | Small | ✅ **DONE** |
| 7.2 | **Enterprise rate limit overrides** — per-org `rate_limit_override` column instead of Pro hardcode | API.md §3 | Medium | ✅ **DONE** |
| 7.3 | **Retry Policy API** — `GET/PUT /api/v1/projects/{id}/settings/retry-policy` + `retry_configs` table | Feature.md §15 | Medium | ✅ **DONE** |
| 7.4 | **Async S3 client** — Replace `boto3` + `asyncio.to_thread()` with `aiobotocore` | Performance | Medium | ✅ **DONE** |
| 7.5 | **Parallel agent execution** — `asyncio.gather` for independent endpoint groups in code generation (feature-flagged) | Feature.md §6 | Medium | ✅ **DONE** |

---

## 5. Bug Log

| Bug # | Description | Status | Fix |
|---|---|---|---|
| Bug 1 | Upload Response: 201 vs 202, wrong body shape | ✅ **FIXED** | Endpoint returns `HTTP_202_ACCEPTED` with `workflow_run_id` and `status="processing"` |
| Bug 2 | `audit_service.record()` kwarg naming | ℹ️ **NOT A BUG** | Intentionally accepts `metadata` kwarg and maps it to `event_metadata` column |
| Bug 3 | Sync S3 in async context | ✅ **Fixed** — replaced `boto3` + `asyncio.to_thread()` with `aiobotocore` in `storage_service.py` (Task 7.4) |
| Bug 4 | Freeform upload path broken | ✅ **FIXED** | `ingestion_service.py` catches `UnprocessableEntityError`, returns Document only; orchestrator runs doc_agent; LLM extraction works for PDF/HTML/Markdown/Text |
| Bug 5 | Qdrant never populated | ✅ **FIXED** | `doc_agent.py` calls `upsert_chunks()` for both structured and freeform docs; chunking + embedding pipeline complete |

---

## 6. Feature Completeness Matrix

| Feature (PRD §11 / Feature.md) | Priority | Status |
|---|---|---|
| FR-1: Parse OpenAPI/Swagger/Postman | P0 | ✅ Complete |
| FR-2: LLM extraction for freeform docs | P0 | ✅ **Complete** — LLM logic in `doc_agent.py`; sync upload path fixed; PDF/HTML/Markdown pre-processing via `document_parser.py` |
| FR-3: Auth scheme detection | P0 | ✅ Complete |
| FR-4: Dependency graph builder | P1 | ✅ Complete (Planner Agent builds dependency graph) |
| FR-5: User-reviewable execution plan | P0 | ✅ Complete (Planner Agent + approval gate) |
| FR-6: Python + Node.js code generation | P0 | ✅ Complete (Code Generator Agent with templates) |
| FR-7: Automated test generation | P0 | ✅ Complete (Testing Agent with fixtures) |
| FR-8: Sandbox test execution | P0 | ✅ Complete (MockSandboxClient in-process) |
| FR-9: Self-healing repair loop | P0 | ✅ Complete (max 3 attempts, integrates with Code Agent) |
| FR-10: Export (SDK/Docker/GitHub/MCP) | P0 | ✅ Complete (Export Agent with 8 types) |
| FR-11: Execution history + versioning | P1 | ✅ Complete (history routes, rollback, versioning API) |
| FR-12: REST API complete | P0 | ✅ Complete — 18 route modules for Phases 1–6 |
| FR-13: Web dashboard | P0 | ✅ Complete — all screens incl. Monitoring (`/projects/[id]/monitoring` + org `/monitoring`), error screens, and enhanced Plan/Test/History/Settings per `UIUX.md §2` |
| FR-14: Vector search / RAG | P1 | ✅ **Complete** — Client + embedding pipeline wired; chunking, PDF/HTML extraction, upsert on every upload |
| FR-15: Retry policy config | P1 | ✅ **Complete** — `retry_configs` table, `GET/PUT /api/v1/projects/{id}/settings/retry-policy` routes, `RetryPolicyRequest/Response` schemas (frontend localStorage fallback removed)
| FR-16: Logs retrieval API | P0 | ✅ Complete — `GET /api/v1/projects/{id}/logs` with cursor-based pagination wired in `logs.py` |

---

## 7. Code Quality Assessment

| Dimension | Verdict |
|---|---|
| Architecture | **Excellent** — clean layering (routes → services → models → db), deny-by-default RBAC, no leaking abstractions, phased pipeline design |
| Security | **Excellent** — Argon2id, RS256, refresh token rotation with replay detection, JTI denylist, timing-safe auth |
| Test coverage | **Good** — 20 test modules (plus `conftest.py`), full isolation per test; Qdrant tested via `FakeQdrantClient` |
| Documentation | **Excellent** — every source file references the exact spec section it implements |
| Type safety | **Strict** — `mypy strict` mode with Pydantic v2 models throughout |
| Async consistency | **Excellent** — async/await throughout; S3 client fully async via `aiobotocore` |
| Confirmed open bugs | **0 confirmed** — Bug 4 (freeform upload path) and Bug 5 (Qdrant not wired) **both fixed** |

---

## 8. Phase Completion Summary

| Phase | Description | Status |
|---|---|---|
| Phase 1 | DB schema, Auth, RBAC, Project CRUD, Upload, Spec Ingestion, Core Infra | ✅ Complete |
| Phase 2 | Workflow Orchestration, Doc/Planner Agents, Qdrant client + embedding pipeline | ✅ **Complete** |
| Phase 3 | Code Gen, Testing, Export agents + APIs | ✅ Complete |
| Phase 4 | GitHub OAuth, Agent-Worker, Real-time SSE, Frontend core, Additional routes | ✅ Complete |
| Phase 5 | Frontend feature completion (Monitoring, Plan/Test/History/Settings enhancements, 9 UI components, error screens) | ✅ Complete |
| Phase 6 | Helm, Terraform, Monitoring, OTel, CI/CD, Self-hosted Compose | ✅ Complete |
| Phase 7 | DB audit_logs permission enforcement, Enterprise rate limit overrides, Retry Policy API, Async S3 client, Parallel agent execution | ✅ **Complete** |
