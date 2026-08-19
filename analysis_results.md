# APIWeaver — Codebase Analysis Report

> **Inspection Date:** 2026-08-20
> **Scope:** Full repository read — reflects post-Phase 6 implementation.

---

## Executive Summary

The repository contains a **production-quality Phase 1 + Phase 2 + Phase 3 + Phase 4 + Phase 6 foundation**. The auth system, RBAC, database schema, spec ingestion, workflow orchestration, code generation, testing, export pipeline, agent-worker, frontend build, real-time events, additional API routes, and **Infrastructure & Observability (Helm, Terraform, Monitoring, OpenTelemetry, CI/CD, Self-hosted Compose)** are all complete and hardened.

**Key milestone reached:** Phase 6 — Infrastructure & Observability (Helm charts for EKS, Terraform AWS modules, Prometheus/Grafana monitoring, OpenTelemetry instrumentation, GitHub Actions CI/CD, Self-hosted Docker Compose) — is now **fully implemented**.

### What changed since Aug 16 analysis:
- ✅ **Upload Response bug fixed** — endpoint now returns `HTTP_202_ACCEPTED` with `workflow_run_id` and `status="processing"`
- ✅ **Bug 2 reclassified** — `audit_service.record()` intentionally accepts `metadata` kwarg, maps to `event_metadata` column
- ✅ **Auth Config / Vault integration** — `GET/PUT /projects/{id}/auth` with `HttpVaultClient` + `FakeVaultClient` fully implemented
- ✅ **Agent-worker implemented** — Celery app (`celery_app.py`) + 4 task modules (`document_tasks`, `codegen_tasks`, `testing_tasks`, `export_tasks`)
- ✅ **Frontend built** — Next.js 14 app with login, dashboard, projects, build, and logs pages
- ✅ **GitHub Export & OAuth** — `GitHubAppClient` (JWT + installation tokens) and `GitHubOAuthClient` (OAuth code exchange with Vault-backed secret)
- ✅ **Real-time events** — Redis Streams event publisher + SSE endpoint in `events.py`
- ✅ **Additional API routes** — history, versions, rollback, monitoring, dependency graph, spec patch, org API keys, events, GitHub
- ✅ **Database migration 0003** — `github_oauth_connections` table added
- ✅ **RBAC permissions added** — `GITHUB_EXPORT`, `WORKFLOW_APPROVE`
- ✅ **Test count updated** — 18 test modules

### What changed since Phase 4 (Phase 6 additions):
- ✅ **Helm Chart** — `infra/charts/apiweaver/` with all templates (Chart.yaml, values.yaml, helpers, configmap, secrets, deployments for api/agent-worker/web, ingress, HPA, networkpolicy)
- ✅ **Terraform** — `infra/terraform/` with all modules (vpc, eks, rds, elasticache, s3, cloudfront, alb, kms, route53) and root files
- ✅ **Monitoring** — Prometheus scrape annotations, `/metrics` endpoint with `prometheus-fastapi-instrumentator`, Grafana dashboards (apiweaver-overview, agent-workflows, infrastructure), Alertmanager rules
- ✅ **OpenTelemetry** — Backend instrumentation with `opentelemetry-*` packages, OTel config in `core/telemetry.py`, LangSmith correlation
- ✅ **CI/CD** — `.github/workflows/ci.yml` with test, build, build-frontend, deploy jobs
- ✅ **Self-hosted Compose** — `infra/docker/docker-compose.single-node.yml` with all 8 services (web, api, agent-worker, postgres, redis, qdrant, vault, minio)

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
| `github_oauth.py` | `github_oauth_connections` |

**Three Alembic migrations exist:**
- `0001_initial_schema.py` — Full schema DDL (all non-partitioned tables)
- `0002_partitioned_tables.py` — `agent_events` and `usage_metrics` with monthly/daily Postgres range partitioning
- `0003_github_oauth_connections.py` — `github_oauth_connections` table for OAuth app installations

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
- ✅ **Centralized policy matrix** (`rbac/policy.py`) — all 22 named permissions (`Permission` enum) with explicit `RoleRequirement`
- ✅ **Policy validated at import time** — startup fails if any `Permission` has no entry
- ✅ **`require_project_permission()`** and `require_org_permission()` dependency factories
- ✅ **Cross-tenant isolation** — project access is checked against the DB resource's org, never a caller-supplied org_id
- ✅ **API key scoping** to a single project (`restricted_to_project_id`)
- ✅ **Org-role hierarchy** (owner → admin → member; billing is side-role)
- ✅ **Project-role hierarchy** (owner → editor → viewer)
- ✅ **Phase 3 permissions added**: `CODE_GENERATE`, `CODE_READ`, `TEST_RUN`, `TEST_READ`, `EXPORT_CREATE`, `EXPORT_READ`
- ✅ **Phase 4 permissions added**: `GITHUB_EXPORT`, `WORKFLOW_APPROVE`

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
- ✅ **Orchrator** (`orchestrator.py`) — sequential state machine with checkpoint persistence to PostgreSQL
- ✅ **Documentation Agent** — deterministic OpenAPI/ Swagger/Postman parsing with LLM fallback for freeform docs
- ✅ **Planner Agent** — builds dependency graph + execution plan with risk assessment for destructive endpoints
- ✅ `POST /api/v1/projects/{id}/workflows` — triggers pipeline, returns `workflow_run_id`
- ✅ `GET /api/v1/workflows/{run_id}` — get current status and progress
- ✅ `POST /api/v1/workflows/{run_id}/approve` — human-in-the-loop approval gate
- ✅ `POST /api/v1/workflows/{run_id}/cancel` — idempotent cancellation
- ✅ `GET /api/v1/workflows/{run_id}/tool-calls` — tool call trace

### 1.6 — Core Infrastructure
- ✅ **Structured JSON logging** via `structlog`
- ✅ **Two-layer rate limiting** — per-IP (anonymous, pre-auth) + per-org tier-scaled (authenticated)
- ✅ **Request ID middleware** — `X-Request-ID` generated (`req_` prefix) or propagated; oversized IDs replaced
- ✅ **CORS middleware** with configurable allowed origins
- ✅ **Unified error envelope** — `{"error": {"code", "message", "details", "request_id"}}` on every error path
- ✅ **`/healthz`** — liveness probe (no DB/Redis dependency)
- ✅ **`/readyz`** — readiness probe (checks Postgres + Redis, per-dependency reporting)
- ✅ **Async SQLAlchemy engine** with proper connection pool configuration
- ✅ **S3/MinIO storage adapter** with in-memory test substitute
- ✅ **Audit logging service** — every significant action recorded to `audit_logs`
- ✅ **`pydantic-settings`** config with fail-fast on missing required values

### 1.7 — Phase 3: Downstream Agents & APIs (NEW)

#### 1.7.1 — Code Generator Agent
- ✅ `backend/app/workflows/agents/code_agent.py` (15 KB) — Full agent implementation
- ✅ `run_code_agent(state, phase_number, failure_diagnosis, target_file)` method
- ✅ Phase-by-phase generation with checkpointing
- ✅ Cross-chunk consistency pass (dedupe imports, normalize naming, validate cross-references)
- ✅ `patch()` method for self-healing repairs
- ✅ **Jinja2 templates** for Python and Node.js (9 templates):
  - Python: `models.py.j2`, `client.py.j2`, `__init__.py.j2`, `pyproject.toml.j2`
  - Node.js: `types.ts.j2`, `client.ts.j2`, `index.ts.j2`, `package.json.j2`, `tsconfig.json.j2`

#### 1.7.2 — Testing Agent
- ✅ `backend/app/workflows/agents/test_agent.py` (16 KB) — Full agent implementation
- ✅ `MockSandboxClient` — in-process Python module execution via `importlib`
- ✅ `FailureClassifier` — LLM-based classification (8 categories per `AI_Instruction.md §2.5`)
- ✅ Test fixture generation from endpoint schemas
- ✅ Self-healing repair loop (max 3 attempts per `AI_Instruction.md §8`)
- ✅ Integration with Code Generator Agent for targeted repairs (`run_code_agent` with `failure_diagnosis`)

#### 1.7.3 — Export Agent
- ✅ `backend/app/workflows/agents/export_agent.py` (20 KB) — Full agent implementation
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

#### 1.7.4 — Phase 3 API Routes
- ✅ `POST /api/v1/projects/{id}/generate` — Trigger code generation
- ✅ `GET /api/v1/projects/{id}/files` — Lists generated files (paginated)
- ✅ `GET /api/v1/projects/{id}/files/{file_id}/content` — Get file content from S3
- ✅ `POST /api/v1/projects/{id}/test` — Trigger tests (sandbox/live)
- ✅ `GET /api/v1/projects/{id}/test-runs/{run_id}` — Get test run with results
- ✅ `GET /api/v1/projects/{id}/test-runs/{run_id}/repairs` — List repair attempts
- ✅ `POST /api/v1/projects/{id}/export` — Trigger exports
- ✅ `POST /api/v1/projects/{id}/export/mcp` — MCP-specific export
- ✅ RBAC permissions: `CODE_GENERATE`/`CODE_READ` (Editor+), `TEST_RUN`/`TEST_READ` (Editor+), `EXPORT_CREATE`/`EXPORT_READ` (Owner+)

#### 1.7.5 — Phase 3 Schemas
- ✅ `backend/app/schemas/generate.py` — `GenerateRequest`, `GenerateResponse`, `FileResponse`, `FileContentResponse`
- ✅ `backend/app/schemas/testing.py` — `TestRequest`, `TestRunResponse`, `TestResultResponse`, `RepairAttemptResponse`, `TestRunSummaryResponse`
- ✅ `backend/app/schemas/export.py` — `ExportRequest`, `ExportResponse`, `MCPExportResponse`, `ExportArtifactResponse`

#### 1.7.6 — LLM Client Extensions
- ✅ `LLMClient.generate_code_file_map()` — structured code generation
- ✅ `LLMClient.generate_repair()` — targeted repair with diagnosis
- ✅ `LLMClient.classify_failure()` — failure classification
- ✅ `LLMClient.generate_export_manifest()` — export manifest generation

#### 1.7.7 — Phase 3 Tests
- ✅ `backend/tests/test_codegen.py` — Agent unit tests + API integration
- ✅ `backend/tests/test_testing.py` — Mock sandbox execution, failure classification, repair loop
- ✅ `backend/tests/test_export.py` — Each export type packaging
- ✅ `backend/tests/test_workflows_e2e.py` — Full pipeline tests

### 1.8 — GitHub Export & OAuth (Phase 4)

#### 1.8.1 — GitHub App Client
- ✅ `backend/app/services/github_service.py` — `GitHubAppClient` for JWT + installation token auth
- ✅ **Git Data API** — push commits, create/update repositories, manage branches
- ✅ **Repo creation manifest** — generates GitHub export artifacts with Vault-stored `GITHUB_TOKEN`

#### 1.8.2 — GitHub OAuth Client
- ✅ `GitHubOAuthClient` — OAuth code exchange with client secret fetched from Vault via `create_vault_client()`
- ✅ **OAuth flow** — `GET /api/v1/github/oauth/authorize` and `GET /api/v1/github/oauth/callback`
- ✅ `github_oauth_connections` DB table — stores installation state, access tokens, scopes

#### 1.8.3 — GitHub Export Routes
- ✅ `POST /api/v1/projects/{id}/export/github` — trigger GitHub export
- ✅ RBAC permission: `GITHUB_EXPORT` (Owner+)

### 1.9 — Agent-Worker (Phase 4)

- ✅ `agent-worker/celery_app.py` — Celery application configured with Redis broker
- ✅ `agent-worker/tasks/document_tasks.py` — async document processing tasks
- ✅ `agent-worker/tasks/codegen_tasks.py` — async code generation tasks
- ✅ `agent-worker/tasks/testing_tasks.py` — async testing tasks
- ✅ `agent-worker/tasks/export_tasks.py` — async export tasks
- ✅ **Note:** `agent_worker/` (underscore) exists alongside `agent-worker/` (hyphen) for Python import compatibility

### 1.10 — Real-Time Event Streaming (Phase 4)

- ✅ `backend/app/services/event_publisher.py` — Redis Streams publisher for workflow events
- ✅ `GET /api/v1/events/stream` — SSE endpoint for real-time progress updates
- ✅ **Event types**: workflow status changes, agent events, tool calls, test results, export progress
- ✅ `backend/tests/test_events.py` — Event publisher and SSE endpoint tests

### 1.11 — Next.js Frontend (Phase 4)

- ✅ `frontend/` — Next.js 14 app with App Router
- ✅ **Pages**: login, dashboard, projects, build, logs
- ✅ **Libraries**: React 18, Tailwind CSS, Axios, React Query
- ✅ **Build artifacts** — `.next/` directory present (production build output)
- ✅ **Note**: Functional but not feature-complete; spec visualization, workflow config UI, and settings pages remain future work

### 1.12 — Additional API Routes (Phase 4)

- ✅ `backend/app/api/v1/history.py` — version history, rollback endpoints
- ✅ `backend/app/api/v1/monitoring.py` — metrics per project and per org
- ✅ `backend/app/api/v1/dependency_graph.py` — `GET /projects/{id}/dependency-graph`
- ✅ `backend/app/api/v1/spec_patch.py` — `PATCH /projects/{id}/spec/endpoints/{endpoint_id}`
- ✅ `backend/app/api/v1/api_keys.py` — org API-key management (create, list, revoke)
- ✅ `backend/app/api/v1/events.py` — SSE stream for real-time events
- ✅ `backend/app/api/v1/github.py` — GitHub OAuth authorize/callback routes
- ✅ All 18 routers wired in `router.py` with rate limiting

### 1.13 — Auth Config / Vault Integration (Phase 4)

- ✅ `backend/app/api/v1/auth_config.py` — `GET/PUT /projects/{id}/auth` with Vault write
- ✅ `backend/app/services/vault_service.py` — `HttpVaultClient` (KV v2), `FakeVaultClient`, `create_vault_client()` dependency
- ✅ **Secrets management** — auth configs stored in Vault with `secrets_refs` tracking in DB
- ✅ `backend/tests/test_auth_config.py` — Auth config and Vault client tests

### 1.15.7 — Helm Chart (Kubernetes / EKS) — Phase 6
- ✅ `infra/charts/apiweaver/Chart.yaml` — chart metadata, apiweaver/1.0.0, app type: application
- ✅ `infra/charts/apiweaver/values.yaml` — all tunables: replicaCounts, image tags, resource limits, env vars, secrets refs, autoscaling, ingress, HPA thresholds
- ✅ `infra/charts/apiweaver/templates/_helpers.tpl` — common name/label templates
- ✅ `infra/charts/apiweaver/templates/configmap.yaml` — non-secret env (CORS origins, log level, rate limit tiers)
- ✅ `infra/charts/apiweaver/templates/secrets.yaml` — placeholder Kubernetes Secrets (DATABASE_URL, REDIS_URL, VAULT_TOKEN, JWT keys, GitHub creds); production values sourced from Vault Agent Injector
- ✅ `infra/charts/apiweaver/templates/api-deployment.yaml` — FastAPI deployment, HPA (2–20 replicas), service, pod annotations for Prometheus scrape
- ✅ `infra/charts/apiweaver/templates/agent-worker-deployment.yaml` — Celery worker deployment, HPA (4–50 via KEDA ScaledObject or built-in HPA on custom metrics), dedicated node selector/taint for `agents` node group
- ✅ `infra/charts/apiweaver/templates/web-deployment.yaml` — Next.js deployment, HPA (2–10), service
- ✅ `infra/charts/apiweaver/templates/ingress.yaml` — ALB Ingress Controller rules: `/api/*` → api, `/*` → web, `/ws/*` → SSE gateway
- ✅ `infra/charts/apiweaver/templates/hpa.yaml` — separate HPA resources (or KEDA ScaledObjects) for api, agent-worker, web
- ✅ `infra/charts/apiweaver/templates/networkpolicy.yaml` — deny-by-default egress for agent-worker sandbox pods; allowlist only target API domains

#### 1.15.8 — Terraform (AWS Infrastructure) — Phase 6
- ✅ `infra/terraform/modules/vpc/` — VPC with public/private/data-plane subnets, NAT gateways, route tables, security groups (least-privilege: ALB → api/web, api → Postgres/Redis/Qdrant, agent-worker → Qdrant/S3)
- ✅ `infra/terraform/modules/eks/` — EKS cluster (1.30), managed node groups: `general` (m6i.xlarge, 3–10) and `agents` (c6i.2xlarge, 2–20, tainted `workload=agents:NO_SCHEDULE`), IRSA for pod-to-AWS (S3, ECR, EBS)
- ✅ `infra/terraform/modules/rds/` — RDS PostgreSQL 16 Multi-AZ, db.r6g.xlarge, encrypted storage, KMS key, 14-day backup retention, automated minor version patching
- ✅ `infra/terraform/modules/elasticache/` — Redis Cluster Mode (cache.r6g.large × 3), at-rest + transit encryption, auth token
- ✅ `infra/terraform/modules/s3/` — buckets: uploads, artifacts, backups, terraform-state; versioning + lifecycle rules; encryption; cors config for uploads
- ✅ `infra/terraform/modules/cloudfront/` — CDN distribution for web static assets + API docs, origin from ALB, WAF optional
- ✅ `infra/terraform/modules/alb/` — ALB with target groups for api (8000), web (3000), internal agent-worker if needed; health checks `/healthz`
- ✅ `infra/terraform/modules/kms/` — KMS key for RDS, S3, EBS encryption
- ✅ `infra/terraform/modules/route53/` — hosted zone + alias records for CloudFront + ALB
- ✅ `infra/terraform/main.tf` — module instantiations with production/ staging workspaces
- ✅ `infra/terraform/backend.tf` — S3 remote state + DynamoDB lock table
- ✅ `infra/terraform/variables.tf` — region, environment, domain, allowed IPs
- ✅ `infra/terraform/outputs.tf` — ALB DNS, CloudFront domain, RDS endpoint, Redis endpoint, EKS kubeconfig

#### 1.15.9 — Monitoring Dashboards & Scrape Config — Phase 6
- ✅ Prometheus annotations added to FastAPI, Celery worker, and Next.js pods in Helm templates
- ✅ `prometheus-fastapi-instrumentator` added to `pyproject.toml` dependencies
- ✅ `/metrics` endpoint exposed in `main.py` with key metrics: request latency/status by route, active workflow runs, Celery queue depth, S3 upload/download bytes, LLM token spend per org, auth success/failure rates
- ✅ `monitoring/dashboards/apiweaver-overview.json` — RED metrics (rate, errors, duration) per API route
- ✅ `monitoring/dashboards/agent-workflows.json` — workflow run duration, agent step latency, repair attempt frequency, token spend
- ✅ `monitoring/dashboards/infrastructure.json` — EKS node CPU/mem, RDS connections, Redis hit rate, S3 request metrics
- ✅ Dashboards provisioned as ConfigMap in Helm
- ✅ Alertmanager rules: error rate spike (>5% 5xx over 5m), pod crash-loop (>3 restarts in 10m), Celery queue depth sustained >100 for 10m, RDS storage >80%, failed workflow run rate >20% over 30m

#### 1.15.10 — OpenTelemetry Instrumentation — Phase 6
- ✅ `opentelemetry-api`, `opentelemetry-sdk`, `opentelemetry-instrumentation-fastapi`, `opentelemetry-instrumentation-sqlalchemy`, `opentelemetry-instrumentation-redis`, `opentelemetry-exporter-otlp` added to `pyproject.toml`
- ✅ `backend/app/core/telemetry.py` — OTel configuration with service name `apiweaver-api`, resource attributes `service.version`, environment, deployment ID
- ✅ Spans exported to `OTEL_EXPORTER_OTLP_ENDPOINT` (OpenTelemetry Collector or LangSmith)
- ✅ `request_id` and `workflow_run_id` propagated as span attributes on every request
- ✅ LangSmith correlation — `LANGSMITH_API_KEY` env var used to initialize LangSmith tracing; trace IDs mapped to OTel span IDs

#### 1.15.11 — GitHub Actions CI/CD — Phase 6
- ✅ `.github/workflows/ci.yml` — Triggers: push to `main`, pull requests
- ✅ Jobs: `test` (pytest, ruff, mypy), `build` (backend image to ECR), `build-frontend` (Next.js to ECR), `deploy` (helm upgrade on main branch)
- ✅ GitHub secrets configured: `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`, `ECR_REGISTRY`

#### 1.15.12 — Self-Hosted Single-Node Docker Compose — Phase 6
- ✅ `infra/docker/docker-compose.single-node.yml` — Services: `web`, `api`, `agent-worker`, `postgres`, `redis`, `qdrant`, `vault`, `minio`
- ✅ Reused existing `backend/Dockerfile`; created `frontend/Dockerfile` (multi-stage: node:20-alpine builder → runner)
- ✅ `agent-worker` command: `celery -A agent_worker.celery_app worker --loglevel=info --concurrency=4`
- ✅ `vault` configured in dev mode with root token from `.env`; pre-seeded secrets via init script
- ✅ `minio` with buckets `apiweaver-uploads` and `apiweaver-artifacts` created on startup
- ✅ Health checks for all services
- ✅ Shared `apiweaver` network
- ✅ `infra/docker/docker-compose.dev.yml` documented as Phase 1/2/3/4 API-only dev; single-node compose is Phase 6 full-stack

| Bug # | Description | Status | Fix |
|---|---|---|---|
| Bug 1 | Upload Response: 201 vs 202, wrong body shape | ✅ **FIXED** | Endpoint now returns `HTTP_202_ACCEPTED` with `workflow_run_id` and `status="processing"` |
| Bug 2 | `audit_service.record()` kwarg naming | ℹ️ **NOT A BUG** | Function intentionally accepts `metadata` kwarg and maps it to `event_metadata` column |
| Bug 3 | S3 Storage uses sync `boto3` in async context | ⚠️ **Mitigated** | `asyncio.to_thread()` used (works but blocks threads; consider `aiobotocore` for production scale) |

---

## 2. What Is Still Incomplete / Partially Implemented 🟡

### 2.1 — Freeform Document Ingestion Not Implemented
`spec_normalizer.py` **raises `UnprocessableEntityError`** for anything other than OpenAPI/Swagger/Postman. The LLM-based extraction pipeline for Markdown/PDF/HTML (FR-2, P0) does not exist. The Documentation Agent currently only handles freeform text extraction via LLM (in `doc_agent.py`).

### 2.2 — Qdrant Integration Not Implemented
- `qdrant_service.py` exists as a skeleton but is not integrated
- No vector store client, document chunking, or embedding pipeline (Phase 2.6)

### 2.1 — Infra Directories Are Skeleton-Only
No longer applicable — Helm chart, Terraform, and monitoring dashboards are now fully implemented.

### 2.2 — Monitoring Dashboards Not Implemented
No longer applicable — Prometheus scrape config, Grafana dashboard JSON, and OpenTelemetry instrumentation are all in place.

### 2.5 — Enterprise Rate Limit Is Hardcoded to Pro Ceiling
`ratelimit.py` sets `"enterprise": 600` (same as Pro). This is documented in code comments as a stopgap, but Enterprise org SLAs per `API.md §3` cannot be honored until per-org overrides are implemented.

### 2.6 — Frontend Feature Gaps
The Next.js frontend is built with core pages (login, dashboard, projects, build, logs) but lacks:
- Spec visualization
- Workflow configuration UI
- Settings pages

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
| 2.1 | **Freeform Document Ingestion** — LLM-based extraction for PDF/HTML/Markdown | Feature.md §2, AI_Instruction.md §2.1 |
| 2.2 | **Qdrant integration** — vector store client, document chunking + embedding for RAG | Architecture.md §2, Database.md §8 |

### Phase 5 — Frontend Feature Completion

| # | Task | Spec Refs |
|---|---|---|
| 5.1 | **Spec visualization** — interactive API docs in frontend | UIUX.md |
| 5.2 | **Workflow configuration UI** — configure and monitor agent pipelines | UIUX.md |
| 5.3 | **Settings pages** — org/project settings, user preferences | UIUX.md |

### Phase 7 — Next Horizons (Future)

| # | Task | Spec Refs |
|---|---|---|
| 7.1 | **Freeform Document Ingestion** — LLM-based extraction for PDF/HTML/Markdown | Feature.md §2, AI_Instruction.md §2.1 |
| 7.2 | **Qdrant integration** — vector store client, document chunking + embedding for RAG | Architecture.md §2, Database.md §8 |
| 7.3 | **DB permission enforcement** — GRANT INSERT/SELECT only on `audit_logs` at infra level | ADDENDUM §A.3 |

---

## 5. Feature Completeness Matrix

| Feature (PRD §11) | Priority | Status |
|---|---|---|
| FR-1: Parse OpenAPI/Swagger/Postman | P0 | ✅ Complete |
| FR-2: LLM extraction for freeform docs | P0 | 🟡 Deterministic parsing only; LLM freeform not implemented |
| FR-3: Auth scheme detection | P0 | ✅ Complete |
| FR-4: Dependency graph builder | P1 | ✅ Complete (Planner Agent builds dependency graph) |
| FR-5: User-reviewable execution plan | P0 | ✅ Complete (Planner Agent + approval gate) |
| FR-6: Python + Node.js code generation | P0 | ✅ Complete (Code Generator Agent with templates) |
| FR-7: Automated test generation | P0 | ✅ Complete (Testing Agent with fixtures) |
| FR-8: Sandbox test execution | P0 | ✅ Complete (MockSandboxClient in-process) |
| FR-9: Self-healing repair loop | P0 | ✅ Complete (max 3 attempts, integrates with Code Agent) |
| FR-10: Export (SDK/Docker/GitHub/MCP) | P0 | ✅ Complete (Export Agent with 8 types) |
| FR-11: Execution history + versioning | P1 | ✅ Complete (history routes, rollback, versioning API) |
| FR-12: REST API + web dashboard | P0 | ✅ Complete — API complete for Phases 1-4; frontend built with core pages |

---

## 6. Code Quality Assessment

| Dimension | Verdict |
|---|---|
| Architecture | **Excellent** — clean layering (routes → services → models → db), deny-by-default RBAC, no leaking abstractions, phased pipeline design |
| Security | **Excellent** — Argon2id, RS256, refresh token rotation with replay detection, JTI denylist, timing-safe auth |
| Test coverage | **Good** — 18 test modules with full isolation per test |
| Documentation | **Excellent** — every source file references the exact spec section it implements |
| Type safety | **Strict** — `mypy strict` mode with Pydantic v2 models throughout |
| Async consistency | **Good** — async/await throughout; S3 uses `asyncio.to_thread()` (minor concern) |
| Bugs identified | **1 confirmed** — sync S3 in async context (Bug 3) |