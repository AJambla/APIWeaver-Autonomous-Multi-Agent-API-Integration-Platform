# APIWeaver

> **Autonomous Multi-Agent API Integration Platform**  
> Ingests raw API specifications and unstructured documentation, computes topological dependency graphs, generates typed client code, executes sandboxed validation with iterative self-healing repairs, and exports production-ready SDKs, servers, Docker containers, and MCP tool servers.

---

## Current Status (Phases 1 → 7 Complete & Production Hardened ✅)

- **Phase 1: Platform Foundation** ✅ — FastAPI architecture, Argon2id & RS256 JWT auth, RBAC matrix, project CRUD, PostgreSQL schema & Alembic migrations (10 versions), Redis JTI denylist & rate limiting.
- **Phase 2: Document Ingestion & Vector RAG** ✅ — OpenAPI 3.x, Swagger 2.0, Postman v2.1 deterministic normalization + PDF/HTML/Markdown LLM fallback; Qdrant vector store with semantic chunking & 1536-dim embeddings; Planner agent with topological DAG execution plans.
- **Phase 3: Autonomous Code Generation, Sandbox Testing & Export** ✅ — Code Generator Agent (Python/TypeScript Jinja2 templates), Testing Agent (Docker executor + in-process mock for hermetic testing, 8-category failure classification, 3-attempt self-healing patch loop), Export Agent (8 packaging targets: SDK, Standalone Client, FastAPI, Docker, MCP, GitHub, Docs, CI/CD).
- **Phase 4: Async Workers, Streaming & Frontend Core** ✅ — Celery workers with Redis broker, Redis Streams SSE real-time event streaming, Vite + React 18 SPA, GitHub App & OAuth integration.
- **Phase 5: Frontend Feature Polish & Rich Visualizations** ✅ — Monaco Editor (read-only + diff views), interactive SVG Dependency Graph (pan/zoom/risk indicators), Recharts monitoring metrics, self-healing timeline, dedicated error boundaries.
- **Phase 6: Infrastructure & Observability** ✅ — AWS Terraform (9 modules), OpenTelemetry distributed tracing, Prometheus metrics, and single-node production Docker Compose stack.
- **Phase 7: Hardening & Enterprise Controls** ✅ — Audit log DB-level immutability, enterprise per-organization rate-limit overrides, project Retry Policy API, non-blocking `aiobotocore` async S3 storage, storage key/Vault path traversal prevention, and production sandbox isolation.

---

## Repository Layout

```
API_Weaver/
├── frontend/                  # Vite + React 18 SPA (React Router v6, Tailwind CSS, Monaco, Lucide, Recharts)
│   ├── src/                   # Components, pages, hooks, state, and test suites
│   └── package.json           # Vitest, Testing Library, ESLint, Vite configuration
├── backend/                   # FastAPI REST API & Core Services (SQLAlchemy, Alembic, Pydantic v2)
│   ├── alembic/               # 10 Database migrations (initial schema -> test runs summary)
│   ├── app/                   # API routes, core auth/RBAC, models, and background services
│   │   ├── api/v1/            # 17 modular REST routers + SSE & WebSocket endpoints
│   │   ├── workflows/agents/  # DocAgent, PlannerAgent, CodeAgent, TestAgent, ExportAgent
│   │   └── services/          # Qdrant, Vault, GitHub, S3 Storage, Redis Event services
│   └── tests/                 # 32 pytest test suites (316 hermetic tests) + conftest fixtures
├── agent_worker/              # Celery background task worker definitions & DLQ tasks
├── infra/                     # Infrastructure & Deployment configurations
│   ├── terraform/             # AWS Terraform modules (VPC, RDS, ElastiCache, S3, KMS, ALB, Route53)
│   └── docker/                # Production single-node & dev Docker Compose files + Sandbox Dockerfile
├── monitoring/                # Grafana dashboards & Prometheus Alertmanager rules
├── secrets/                   # Local development RSA JWT key pairs
├── .github/workflows/         # Production CI/CD pipeline (backend, frontend, terraform, trivy, GHCR matrix)
└── Project-docs/              # Complete PRD, architecture, security, and UI/UX specifications
```

---

## How to Run Locally

You can run APIWeaver either using **Option 1 (Docker Compose)** or **Option 2 (Bare-Metal Local Dev Mode)**.

---

### Option 1: Docker Compose (Full Stack Single-Node Production)

Best if you have Docker Desktop installed and want to start the full stack (PostgreSQL, Redis, Qdrant, MinIO, Vault, FastAPI API, Celery Worker, and React Web App) with a single command.

```powershell
# 1. Copy environment variables
cp .env.example .env

# 2. Start all containers in the background (including containerized UI)
docker compose -f infra/docker/docker-compose.single-node.yml --profile docker-ui up -d --build
```

- **Web Dashboard:** [http://localhost:3000](http://localhost:3000)
- **API Swagger Docs:** [http://localhost:8000/api/v1/docs](http://localhost:8000/api/v1/docs)
- **MinIO Console:** [http://localhost:9001](http://localhost:9001) (`minioadmin` / `minioadmin`)
- **Qdrant Dashboard:** [http://localhost:6333/dashboard](http://localhost:6333/dashboard)
- **Vault Server:** [http://localhost:8200](http://localhost:8200)

To view logs or stop the stack:
```powershell
# View streaming logs
docker compose -f infra/docker/docker-compose.single-node.yml logs -f

# Stop all services
docker compose -f infra/docker/docker-compose.single-node.yml down
```

---

### Option 2: Bare-Metal Local Dev Mode

Best for active local code editing with instant hot-reloading.

#### Prerequisites

1. **Python 3.12+**: Download & install from [python.org](https://www.python.org/downloads/).
2. **Node.js 20+ & npm**: Download & install LTS from [nodejs.org](https://nodejs.org/).
3. **Docker** (to run supporting data stores via `infra/docker/docker-compose.dev.yml`):
   ```powershell
   docker compose -f infra/docker/docker-compose.dev.yml up -d
   ```
   *(Starts Postgres 16 on `:5432` and Redis 7 on `:6379`)*

---

#### Step 1: First-Time Setup & Installation

Open PowerShell in the project root (`API_Weaver`):

```powershell
# 1. Copy the environment configuration
cp .env.example .env

# 2. Backend dependency installation
cd backend
poetry install --with dev

# 3. Apply all 10 Database Migrations
poetry run alembic upgrade head

# 4. Frontend Dependency Installation
cd ..\frontend
npm ci --legacy-peer-deps
```

---

#### Step 2: Running the Services (Start in 3 Separate Terminals)

##### 🖥️ Terminal 1: React + Vite Frontend
```powershell
cd frontend
npm run dev
```
- **UI Address:** [http://localhost:3000](http://localhost:3000)

---

##### ⚙️ Terminal 2: FastAPI Backend Server
```powershell
cd backend
poetry run uvicorn app.main:app --reload --port 8000
```
- **Interactive Swagger Docs:** [http://localhost:8000/api/v1/docs](http://localhost:8000/api/v1/docs)
- **OpenAPI JSON Spec:** [http://localhost:8000/api/v1/openapi.json](http://localhost:8000/api/v1/openapi.json)
- **Liveness Probe:** [http://localhost:8000/healthz](http://localhost:8000/healthz)
- **Readiness Probe:** [http://localhost:8000/readyz](http://localhost:8000/readyz)

---

##### 🤖 Terminal 3: Celery Agent Worker
```powershell
cd backend
poetry run celery -A agent_worker.celery_app worker --loglevel=info --concurrency=4
```
*(Handles async document ingestion, topological planning, LLM code generation, sandboxed test execution, and multi-target export).*

---

#### Step 3: First-Time User Flow

1. Open [http://localhost:3000](http://localhost:3000) in your browser.
2. Navigate to `/auth/login` and click **Register** to create your organization and initial admin user.
3. Click **New Project** on the dashboard.
4. Upload an API specification (`.json`, `.yaml`, `.pdf`, `.md`, or `.html`).
5. Review the topological dependency graph on the **Plan** screen, click **Approve**, and monitor autonomous agents generating, testing, and exporting SDKs in real-time!

---

## Verification & Automated Testing

### Frontend Suite (Vitest & ESLint)
```powershell
cd frontend
npm run lint          # ESLint with 0 warnings
npm test              # 19 unit & component tests across 4 test suites (100% pass)
npm run build         # Production Vite bundle compilation
```

### Backend Suite (Pytest & Ruff)
```powershell
cd backend
poetry run ruff check .      # Strict ruff linter check (0 errors)
poetry run pytest -v         # 316 unit, integration, and security tests (100% pass)
```

---

## Continuous Integration & Deployment (CI/CD)

The GitHub Actions workflow in [`.github/workflows/ci.yml`](.github/workflows/ci.yml) enforces production quality gates on every Pull Request and `push` to `main`:

1. **`test-backend`**: Runs in an isolated Linux environment with live PostgreSQL 16 and Redis 7 containers, running Ruff, Mypy, and Pytest with coverage.
2. **`test-frontend`**: Installs dependencies with npm cache, runs ESLint, Vitest component test suites, and compiles production Vite assets.
3. **`validate-infra`**: Validates AWS Terraform configurations (`terraform fmt -check`, `terraform init -backend=false`, `terraform validate`) and Docker Compose schemas.
4. **`security-scan`**: Scans the filesystem using Aqua Security Trivy for high/critical vulnerabilities.
5. **`build-and-push-images`**: On `main` branch, builds and pushes 4 production Docker containers to GitHub Container Registry (`ghcr.io`):
   - `api` (`backend/Dockerfile`)
   - `web` (`frontend/Dockerfile`)
   - `agent-worker` (`agent_worker/Dockerfile`)
   - `sandbox-python` (`infra/docker/Dockerfile.sandbox-python`)

---

## Documentation

Comprehensive design specifications and architectural blueprints live in [`Project-docs/`](Project-docs/):
- **[`PRD.md`](Project-docs/PRD.md)** — Product requirements and user journeys.
- **[`Architecture.md`](Project-docs/Architecture.md)** — System components and data flow.
- **[`Database.md`](Project-docs/Database.md)** — Relational schemas, partitioning, and indexing.
- **[`API.md`](Project-docs/API.md)** — REST, SSE, and WebSocket endpoint specifications.
- **[`Security.md`](Project-docs/Security.md)** — Authentication, RBAC matrix, and Vault secrets.
- **[`UIUX.md`](Project-docs/UIUX.md)** — Design system, screen wireframes, and component guidelines.
- **[`Deployment.md`](Project-docs/Deployment.md)** — AWS Terraform, Docker Compose topologies, and CI/CD pipelines.
