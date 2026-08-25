# APIWeaver

> **Autonomous Multi-Agent API Integration Platform**  
> Ingests raw API specifications and unstructured documentation, computes topological dependency graphs, generates typed client code, executes sandboxed validation with iterative self-healing repairs, and exports production-ready SDKs, servers, Docker containers, and MCP tool servers.

---

## Current Status (Phases 1 → 7 Complete ✅)

- **Phase 1: Platform Foundation** ✅ — FastAPI architecture, Argon2id & RS256 JWT auth, RBAC matrix, project CRUD, PostgreSQL schema & Alembic migrations, Redis JTI denylist & rate limiting.
- **Phase 2: Document Ingestion & Vector RAG** ✅ — OpenAPI 3.x, Swagger 2.0, Postman v2.1 deterministic normalization + PDF/HTML/Markdown LLM fallback; Qdrant vector store with semantic chunking & 1536-dim embeddings; Planner agent with topological DAG execution plans.
- **Phase 3: Autonomous Code Generation, Sandbox Testing & Export** ✅ — Code Generator Agent (Python/TypeScript Jinja2 templates), Testing Agent (`MockSandboxClient`, 8-category failure classification, 3-attempt self-healing patch loop), Export Agent (8 packaging targets: SDK, Standalone Client, FastAPI, Docker, MCP, GitHub, Docs, CI/CD).
- **Phase 4: Async Workers, Streaming & Frontend Core** ✅ — Celery workers with Redis broker, Redis Streams SSE real-time streaming, Next.js 14 App Router UI, GitHub App & OAuth integration.
- **Phase 5: Frontend Feature Polish & Rich Visualizations** ✅ — Monaco Editor (read-only + diff views), interactive SVG Dependency Graph (pan/zoom/risk indicators), Recharts monitoring metrics, self-healing timeline, dedicated error boundaries.
- **Phase 6: Infrastructure & Observability** ✅ — AWS Terraform (9 modules), Kubernetes Helm charts (HPA, NetworkPolicy, Celery worker affinities), OpenTelemetry distributed tracing, Prometheus metrics, and single-node Docker Compose.
- **Phase 7: Hardening & Enterprise Controls** ✅ — Audit log DB-level immutability, enterprise per-organization rate-limit overrides, project Retry Policy API, non-blocking `aiobotocore` async S3 storage, and parallel agent execution.

---

## Repository Layout

```
API_Weaver/
├── frontend/                  # Next.js 14 Web App (App Router, Tailwind CSS, Monaco, Recharts)
├── backend/                   # FastAPI REST API & Core Services (SQLAlchemy, Alembic, Pydantic v2)
│   ├── alembic/               # 6 Database migrations
│   ├── app/                   # API routes, core auth/RBAC, models, and background services
│   │   ├── api/v1/            # 17 modular REST routers + SSE & WebSocket endpoints
│   │   ├── workflows/agents/  # DocAgent, PlannerAgent, CodeAgent, TestAgent, ExportAgent
│   │   └── services/          # Qdrant, Vault, GitHub, S3 Storage, Redis Event services
│   └── tests/                 # 20 pytest test suites + conftest fixtures
├── agent-worker/              # Celery background task worker definitions
├── infra/                     # Deployment configurations
│   ├── charts/apiweaver/      # Kubernetes Helm Chart (API, Web, Celery Worker, Ingress, HPA)
│   ├── terraform/             # AWS Terraform modules (VPC, EKS, RDS, ElastiCache, S3, Vault)
│   └── docker/                # Dockerfiles & Docker Compose files (single-node & dev)
├── monitoring/                # Grafana dashboards & Prometheus Alertmanager rules
├── secrets/                   # Local development RSA JWT key pairs
└── Project-docs/              # Complete PRD, architecture, security, and UI/UX specifications
```

---

## How to Run Locally

You can run APIWeaver either using **Option 1 (Docker Compose)** or **Option 2 (Bare-Metal Local Dev Mode)**.

---

### Option 1: Docker Compose (Full Stack Single-Node)

Best if you have Docker Desktop installed and want to start the full stack (Postgres, Redis, Qdrant, MinIO, Vault, FastAPI, Celery, and Next.js) with a single command.

```powershell
# 1. Copy environment variables
cp .env.example .env

# 2. Start all containers in the background
docker compose -f infra/docker/docker-compose.single-node.yml up -d
```

- **Web Dashboard:** [http://localhost:3000](http://localhost:3000)
- **API Swagger Docs:** [http://localhost:8000/api/v1/docs](http://localhost:8000/api/v1/docs)
- **MinIO Console:** [http://localhost:9001](http://localhost:9001)
- **Qdrant Dashboard:** [http://localhost:6333/dashboard](http://localhost:6333/dashboard)

---

### Option 2: Bare-Metal Local Dev Mode

Best for active local code editing with instant hot-reloading.

#### Prerequisites Installation

1. **Python 3.12+**: Download & install from [python.org](https://www.python.org/downloads/) (make sure to check "Add Python to PATH").
2. **Node.js 18+ & npm**: Download & install LTS from [nodejs.org](https://nodejs.org/).
3. **PostgreSQL 16**: Download & install from [postgresql.org](https://www.postgresql.org/download/) or run via Docker:
   ```powershell
   docker run -d --name apiweaver-postgres -p 5432:5432 -e POSTGRES_USER=apiweaver -e POSTGRES_PASSWORD=apiweaver -e POSTGRES_DB=apiweaver postgres:16
   ```
4. **Redis 7**: Download & install from [redis.io](https://redis.io/) or run via Docker:
   ```powershell
   docker run -d --name apiweaver-redis -p 6379:6379 redis:7-alpine
   ```

---

#### Step 1: First-Time Setup & Installation Commands

Open PowerShell in the project root (`D:\ML Projects\API_Weaver`):

```powershell
# 1. Clone or navigate to the repository root
cd "D:\ML Projects\API_Weaver"

# 2. Copy the environment configuration
cp .env.example .env

# 3. Generate RSA JWT Keys (if not already present in secrets/)
mkdir -p secrets
# On Windows PowerShell with OpenSSL installed:
# openssl genrsa -out secrets/jwt_private.pem 2048
# openssl rsa -in secrets/jwt_private.pem -pubout -out secrets/jwt_public.pem

# 4. Backend Python Virtual Environment Setup & Dependency Installation
cd backend
python -m venv .venv
.\.venv\Scripts\Activate.ps1

# Upgrade pip & install all backend package dependencies
python -m pip install --upgrade pip
pip install -e .
pip install prometheus-client prometheus-fastapi-instrumentator aiobotocore celery pytest pytest-asyncio

# 5. Apply Database Migrations (Creates all 28+ tables and partitioned logs)
alembic upgrade head

# 6. Frontend Dependency Installation
cd ..\frontend
npm install
```

---

#### Step 2: Running the Services (Start in 3 Separate Terminals)

Once the one-time installation is finished, start each service in its own terminal:

##### 🖥️ Terminal 1: Next.js Frontend
```powershell
cd "D:\ML Projects\API_Weaver\frontend"
npm run dev
```
- **UI Address:** [http://localhost:3000](http://localhost:3000)

---

##### ⚙️ Terminal 2: FastAPI Backend Server
```powershell
cd "D:\ML Projects\API_Weaver\backend"
.\.venv\Scripts\Activate.ps1
uvicorn app.main:app --reload --port 8000
```
- **Swagger Interactive API Docs:** [http://localhost:8000/api/v1/docs](http://localhost:8000/api/v1/docs)
- **OpenAPI JSON Spec:** [http://localhost:8000/api/v1/openapi.json](http://localhost:8000/api/v1/openapi.json)
- **Health Check Probe:** [http://localhost:8000/healthz](http://localhost:8000/healthz)

---

##### 🤖 Terminal 3: Celery Agent Worker (Background Task Orchestrator)
```powershell
cd "D:\ML Projects\API_Weaver\backend"
.\.venv\Scripts\Activate.ps1
celery -A agent_worker.celery_app worker --loglevel=info --concurrency=4
```
*(Handles async document ingestion, LLM chunk extraction, sandboxed testing, and packaging).*

---

#### Step 3: First-Time User Flow

1. Open [http://localhost:3000](http://localhost:3000) in your web browser.
2. Navigate to `/auth/login` and click **Register** to create your organization and admin user.
3. Click **New Project** on the dashboard.
4. Upload an API specification (`.json`, `.yaml`, `.pdf`, `.md`, or `.html`).
5. Review the generated dependency graph on the **Plan** screen, click **Approve**, and watch the autonomous agents generate, test, and export your SDK!


---

## Verification & Testing

### Frontend Typecheck & Lint
```powershell
cd frontend
npm run typecheck
npm run lint
```

### Backend Automated Test Suite
```powershell
cd backend
.\.venv\Scripts\Activate.ps1
pytest -q
ruff check app tests
mypy app
```

---

## Documentation

Comprehensive design specifications and architectural blueprints live in [`Project-docs/`](Project-docs/):
- **[`PRD.md`](Project-docs/PRD.md)** — Product requirements and user journeys.
- **[`Architecture.md`](Project-docs/Architecture.md)** — System components and data flow.
- **[`Database.md`](Project-docs/Database.md)** — Relational schemas, partitioning, and indexing.
- **[`API.md`](Project-docs/API.md)** — REST, SSE, and WebSocket endpoint specifications.
- **[`Security.md`](Project-docs/Security.md)** — Authentication, RBAC matrix, and Vault secrets.
- **[`UIUX.md`](Project-docs/UIUX.md)** — Design system, screen wireframes, and component guidelines.
- **[`Deployment.md`](Project-docs/Deployment.md)** — Kubernetes Helm, AWS Terraform, and CI/CD pipelines.