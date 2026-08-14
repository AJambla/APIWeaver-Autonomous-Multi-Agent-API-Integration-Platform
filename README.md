# APIWeaver

Agentic platform that generates API integrations from documentation.

## Current status

Phase 1 is implemented: the FastAPI platform foundation includes authentication, RBAC,
project management, audit logging, rate limiting, database migrations, and health probes.

Phase 2 ingestion is underway. The backend can now accept and normalize OpenAPI 3.x,
Swagger 2.0, and Postman Collection v2.1 documents:

1. Create a project.
2. Upload an API document with `POST /api/v1/projects/{id}/upload`.
3. Read the normalized specification with `GET /api/v1/projects/{id}/spec`.
4. Inspect discovered endpoints with `GET /api/v1/projects/{id}/endpoints`.

The agent worker, generated SDKs, self-healing tests, frontend dashboard, exports, and
production deployment remain planned work.

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

For document upload support, configure an S3-compatible endpoint (such as MinIO) through
the S3 variables in `.env.example`. The backend uses the configured uploads bucket for
the original document and stores only the object key in PostgreSQL.

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
