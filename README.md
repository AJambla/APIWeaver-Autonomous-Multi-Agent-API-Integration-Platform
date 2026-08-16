# APIWeaver

Agentic platform that generates API integrations from documentation.

## Current status

**Phase 1** ✅ — FastAPI platform foundation: authentication, RBAC, project management, audit logging, rate limiting, database migrations, and health probes.

**Phase 2** ✅ — Document ingestion & normalization: accepts OpenAPI 3.x, Swagger 2.0, Postman Collection v2.1; extracts normalized spec with confidence scores; deterministic parsing with LLM fallback; planner agent builds dependency graph and execution plan with human approval gate.

**Phase 3** ✅ — Downstream agents & APIs: code generation (Python + Node.js), self-healing testing, and multi-format export.

### Phase 3 — Downstream Agents (COMPLETED)

1. **Code Generator Agent** — Generates idiomatic client code from execution plan phases:
   - Python: Pydantic v2, httpx, custom exceptions, Google docstrings, ruff + mypy
   - Node.js: TypeScript strict, Zod schemas, native fetch, ESM modules
   - Phase-by-phase generation with checkpointing, cross-chunk consistency pass
   - Targeted self-healing repairs via Testing Agent integration

2. **Testing Agent** — Mock sandbox execution + self-healing:
   - In-process Python module execution via `importlib`
   - LLM-based failure classification (8 categories per `AI_Instruction.md §2.5`)
   - Test fixture generation from endpoint schemas
   - Repair loop (max 3 attempts) calling Code Generator Agent with failure diagnosis
   - Node.js: syntax + type validation only (`tsc --noEmit`)

3. **Export Agent** — Packages artifacts (8 types):
   - SDK: Python wheel / npm package manifests
   - Client: Single-module flattened clients
   - FastAPI: Router with DI auth
   - Docker: Multi-stage Dockerfile + docker-compose.yml with health checks
   - GitHub: Repo creation via API (Vault-stored token)
   - MCP: Tool definitions (JSON Schema) + stdio/SSE server
   - Docs: OpenAPI 3.1 spec + Markdown reference
   - CI/CD: GitHub Actions workflows (lint, test, build, publish)

### API Endpoints Added (Phase 3)

| Endpoint | Description |
|---|---|
| `POST /projects/{id}/generate` | Trigger code generation |
| `GET /projects/{id}/files` | List generated files |
| `GET /projects/{id}/files/{id}/content` | Get file content (S3) |
| `POST /projects/{id}/test` | Trigger tests (sandbox/live) |
| `GET /projects/{id}/test-runs/{id}` | Get test run with results |
| `GET /projects/{id}/test-runs/{id}/repairs` | List repair attempts |
| `POST /projects/{id}/export` | Trigger exports |
| `POST /projects/{id}/export/mcp` | MCP-specific export |

## Repository layout

| Path | Purpose |
|---|---|
| `frontend/` | Next.js web application (web-bff) |
| `backend/` | FastAPI REST API (api-service) |
| `agent-worker/` | LangGraph/Celery orchestrator worker |
| `infra/` | Docker Compose, Terraform, Helm charts |
| `monitoring/` | Grafana dashboards |
| `scripts/` | Dev utilities (seed data, etc.) |
| `Project-docs/` | Product and architecture specifications |

## Phase 1 — Local backend setup

### Prerequisites

- Python 3.12+
- Poetry
- PostgreSQL 16
- Redis 7

### Generate JWT keys

```bash
mkdir -p secrets
openssl genrsa -out secrets/jwt_private.pem 2048
openssl rsa -in secrets/jwt_private.pem -pubout -out secrets/jwt_public.pem
```

### Install and run

```bash
cp .env.example .env
cd backend
poetry install
poetry run alembic upgrade head
poetry run uvicorn app.main:app --reload --port 8000
```

For document upload support, configure an S3-compatible endpoint (such as MinIO) through the S3 variables in `.env.example`. The backend uses the configured uploads bucket for the original document and stores only the object key in PostgreSQL.

### Health check

```bash
curl http://localhost:8000/healthz
```

## Verification

From `backend/`:

```bash
poetry run pytest -q
poetry run ruff check app tests
```

## Documentation

Full specifications live in [`Project-docs/`](Project-docs/).