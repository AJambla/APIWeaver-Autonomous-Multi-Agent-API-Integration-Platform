# Technology Stack & Rationale
## APIWeaver

This document explains every major technology choice, including comparisons against leading alternatives, advantages, disadvantages, and the specific reasoning that led to each decision for this project.

---

## 1. Frontend

### Next.js + React + TypeScript + Tailwind CSS + shadcn/ui

**Why chosen:** Next.js App Router gives server components for fast initial loads of data-heavy dashboards, built-in API routes for lightweight BFF endpoints, and excellent streaming support (needed for real-time agent status). TypeScript enforces type safety across the large surface area of generated-code previews and API contracts. Tailwind + shadcn/ui gives a consistent, accessible component baseline without owning a full design-system codebase from scratch.

| Aspect | Advantage | Disadvantage |
|---|---|---|
| Next.js | SSR/streaming, file-based routing, strong ecosystem, Vercel-grade DX | Opinionated structure; App Router has a learning curve; server/client component boundary adds complexity |
| TypeScript | Catches integration bugs at compile time; excellent editor tooling | Slower initial dev velocity; build step required |
| Tailwind | Fast iteration, small production CSS, design-token friendly | Verbose className strings; requires discipline to avoid inconsistency |
| shadcn/ui | Copy-in components (full control, no black-box dependency), accessible by default | Not a traditional npm package — updates are manual |

### Next.js vs Vite (comparison)

| Criteria | Next.js | Vite (+ React) |
|---|---|---|
| Rendering | SSR, SSG, ISR, streaming out of the box | Client-only by default (SSR needs extra setup, e.g. Vite SSR or separate framework) |
| Routing | File-based, built-in | Requires React Router or similar |
| Best for | Content + data heavy apps needing SEO/fast TTFB, dashboards with server data | Pure SPA tooling speed, simplest possible dev server |
| Build speed | Good (Turbopack in dev) | Excellent (esbuild-based, very fast HMR) |
| **Decision** | **Chosen** — APIWeaver's dashboard needs server-rendered project data, streaming agent status, and SEO for the marketing/landing pages, which Vite doesn't provide natively. |

---

## 2. Backend

### Python + FastAPI

**Why chosen:** Python is the dominant language for AI/LLM tooling (LangGraph, LangChain, most model SDKs), so backend and AI orchestration share one language and one deployable service where practical. FastAPI provides async-first request handling (critical for concurrently orchestrating many long-running agent workflows), automatic OpenAPI generation (ironically dogfooding APIWeaver's own domain), and Pydantic-based validation that maps directly onto the same models used for generated SDKs.

### FastAPI vs Express (comparison)

| Criteria | FastAPI (Python) | Express (Node.js) |
|---|---|---|
| Performance | High (ASGI, async/await, Starlette core) | High (event loop), comparable for I/O-bound workloads |
| Type Safety | Native via Pydantic + type hints | Requires TypeScript layer on top (not native to Express) |
| AI/LLM Ecosystem | Best-in-class (LangGraph, LangChain, most agent frameworks are Python-first) | Growing (LangChain.js) but generally behind Python in agent tooling maturity |
| Auto Docs | Built-in OpenAPI/Swagger generation | Requires manual setup (swagger-jsdoc etc.) |
| Learning Curve | Moderate (async patterns, Pydantic) | Low (widely known, minimal patterns) |
| **Decision** | **Chosen** — the deciding factor is ecosystem alignment: our core product logic (multi-agent orchestration) is Python-native, so keeping backend and AI layer in one language reduces serialization overhead and operational complexity. Node.js is still used, but only for generated SDK output, not our own backend. |

---

## 3. AI / Agent Orchestration

### LangGraph

**Why chosen:** APIWeaver's workflow is a stateful, cyclic graph (plan → generate → test → repair → re-test), not a simple linear chain. LangGraph models this natively as a state machine with explicit nodes, conditional edges, and built-in checkpointing (resumable workflows survive process restarts — essential given multi-hour generation runs on large APIs).

### LangGraph vs CrewAI (comparison)

| Criteria | LangGraph | CrewAI |
|---|---|---|
| Execution Model | Explicit graph/state machine, full control over transitions | Role-based "crew" abstraction (agents + tasks), higher-level, more opinionated |
| Cyclic workflows (retry/repair loops) | First-class support via conditional edges | Possible but less native; typically simpler sequential/hierarchical flows |
| Observability | Deep integration with LangSmith, per-node tracing | Good, but less granular state inspection |
| Checkpointing/Resumability | Built-in (Postgres/SQLite checkpointer) | Not a core primitive |
| Learning curve | Steeper (graph thinking required) | Gentler (declarative agent/task definitions) |
| **Decision** | **Chosen** — the self-healing repair loop (generate → test → fail → repair → re-test) is fundamentally cyclic and needs durable checkpointing across potentially long-running, resumable workflows. LangGraph's explicit state machine model fits this far better than CrewAI's higher-level abstraction. |

### Model Providers: OpenAI GPT-5.5, Claude, Llama, PydanticAI (optional)

- **Multi-provider by design:** different agents have different requirements — Documentation Agent benefits from long-context, high-accuracy extraction; Code Generator benefits from strong code-specific performance; cost-sensitive bulk operations (e.g., generating boilerplate test fixtures) can route to smaller/local Llama models.
- **PydanticAI (optional):** used selectively for agents needing strict, validated structured output where LangGraph's raw tool-calling needs an extra validation layer — provides typed agent outputs with automatic retry-on-validation-failure.
- **Routing strategy:** documented in `AI_Instruction.md` §"Model Selection."

---

## 4. Database

### PostgreSQL (primary) + Redis (cache/pubsub) + Qdrant (vector)

### Postgres vs MongoDB (comparison)

| Criteria | PostgreSQL | MongoDB |
|---|---|---|
| Data shape | Highly relational (projects → endpoints → tests → versions → dependencies) | Best for loosely structured/document-first data |
| Transactions | Full ACID, multi-table transactions | Multi-document transactions supported but less idiomatic |
| JSON support | `JSONB` gives document flexibility where needed (e.g., raw spec storage) within a relational core | Native JSON but weaker relational integrity |
| Ecosystem | Mature, excellent with SQLAlchemy/Alembic, strong extension ecosystem (pgvector) | Mature, flexible schema evolution |
| **Decision** | **Chosen** — the domain model (project → document → endpoint → dependency graph → workflow run → test result → version) is deeply relational with strong referential integrity needs (e.g., a test result must reference a real endpoint and workflow run). `JSONB` columns cover the semi-structured parts (raw specs, LLM outputs) without needing a second database. |

### Redis

Used for: pub/sub of real-time workflow/agent events to the frontend (SSE/WebSocket fan-out), short-lived caching (parsed spec fragments, rate-limit counters), and Celery/task-queue broker for async job dispatch.

### Redis vs Memcached (comparison)

| Criteria | Redis | Memcached |
|---|---|---|
| Data structures | Rich (lists, sets, sorted sets, streams, pub/sub) | Simple key-value only |
| Persistence | Optional RDB/AOF persistence | None (pure in-memory cache) |
| Pub/Sub | Native, used for real-time workflow events | Not supported |
| **Decision** | **Chosen** — Redis Streams/Pub-Sub is required for pushing live agent status to the frontend; Memcached cannot fulfill this role, only the pure caching role, so choosing Redis avoids running two separate systems. |

### Vector Database — Qdrant

Used for: semantic search over previously ingested API docs (reuse patterns across similar APIs), RAG retrieval for the Documentation Agent when cross-referencing large freeform docs, and similarity search for the future integration marketplace (find similar existing integrations).

### Qdrant vs Pinecone (comparison)

| Criteria | Qdrant | Pinecone |
|---|---|---|
| Deployment | Self-hostable (Docker/K8s) and managed cloud option | Fully managed only (no self-host) |
| Cost model | Free self-hosted; pay only for managed tier if used | Usage-based managed pricing only |
| Filtering | Rich payload filtering (metadata + vector combined) | Strong filtering, mature at scale |
| Open-source | Yes (Apache 2.0) | No |
| **Decision** | **Chosen** — since APIWeaver ships both a self-hosted/open-source option and a managed SaaS tier (see PRD business goals), Qdrant's self-hostability is essential; Pinecone would force all self-hosted users into a hard external dependency. |

### Embeddings — BGE + OpenAI Embeddings

BGE (open-source, self-hostable) used as the default for self-hosted deployments to avoid mandatory external API dependency; OpenAI embeddings offered as a higher-accuracy managed-tier option. Both indexed into the same Qdrant collections via a pluggable embedding interface.

---

## 5. Storage

### AWS S3

Stores raw uploaded documents, generated artifact bundles (zips), and Docker build contexts. Chosen for durability (11 nines), lifecycle policies (auto-archive old versions to Glacier), and native presigned-URL support for secure direct browser uploads/downloads without proxying large files through the API layer.

---

## 6. Deployment

### Docker + Kubernetes + AWS

**Why chosen:** Docker for reproducible builds of both the platform itself and every generated integration artifact (APIWeaver generates Dockerfiles as a product feature, so the platform's own use of Docker is dogfooding). Kubernetes for orchestrating the variable, bursty workload of agent workers (horizontal pod autoscaling based on queue depth). AWS as the cloud provider for its maturity in managed Postgres (RDS), managed Redis (ElastiCache), EKS, and S3 integration.

### Docker vs Podman (comparison)

| Criteria | Docker | Podman |
|---|---|---|
| Daemon model | Client-server (dockerd) | Daemonless, rootless by default |
| Ecosystem | Universal — every CI system, every cloud, every tutorial assumes Docker | Growing but smaller ecosystem; Docker CLI-compatible |
| K8s alignment | `docker build` output is standard OCI, works everywhere | Also OCI-compliant, works everywhere |
| **Decision** | **Chosen (Docker)** — since generated artifacts are meant for end users to run themselves, and the overwhelming majority of target users already have Docker (not Podman) installed, Docker maximizes out-of-the-box compatibility for exported integrations. Podman's rootless security benefits are valuable but not decisive enough to trade off ecosystem ubiquity for the exported-artifact use case. |

---

## 7. Monitoring

### LangSmith + OpenTelemetry + Prometheus + Grafana

- **LangSmith:** purpose-built for LLM/agent tracing — captures full prompt/response/tool-call traces per LangGraph node, essential for debugging agent reasoning and evaluating prompt changes.
- **OpenTelemetry:** vendor-neutral instrumentation standard for the rest of the system (API latency, DB query time, queue depth) so the platform isn't locked into one observability vendor.
- **Prometheus + Grafana:** metrics storage and dashboarding for infrastructure and business metrics (test pass rate, TTI, cost per integration) surfaced in the in-app Monitoring Dashboard feature.

---

## 8. CI/CD

### GitHub Actions

Chosen for tight integration with the GitHub Export feature (same platform users already push generated code to), first-class Docker build/push actions, and matrix-build support for testing generated SDKs across multiple Python/Node versions simultaneously.

---

## 9. React vs Vue (comparison)

| Criteria | React | Vue |
|---|---|---|
| Ecosystem size | Larger — critical for shadcn/ui, Monaco integration, Recharts, D3 wrappers | Smaller but high quality (Vuetify, etc.) |
| Team hiring pool | Larger talent pool for an open-source project seeking contributors | Smaller pool |
| TypeScript support | Excellent, especially with Next.js | Excellent (Vue 3 + `<script setup>`) |
| **Decision** | **Chosen (React)** — the deciding factors are ecosystem breadth (Monaco code-preview integration, complex graph visualizations) and the larger open-source contributor pool, which matters given this project's intent to be open-sourced and community-extended. |

---

## 10. Summary Table

| Layer | Technology | Primary Reason |
|---|---|---|
| Frontend Framework | Next.js | SSR/streaming for real-time agent dashboards |
| UI Library | React + TypeScript | Ecosystem breadth, type safety |
| Styling | Tailwind + shadcn/ui | Fast, consistent, accessible, ownable components |
| Backend | FastAPI (Python) | Async, Pydantic validation, AI ecosystem alignment |
| Orchestration | LangGraph | Native cyclic state machine + checkpointing |
| Models | GPT-5.5 / Claude / Llama | Multi-provider routing by task and cost |
| Primary DB | PostgreSQL | Relational integrity for complex domain model |
| Cache/Queue | Redis | Pub/sub for real-time events + task broker |
| Vector DB | Qdrant | Self-hostable, open-source, rich filtering |
| Embeddings | BGE / OpenAI | Self-hosted default + managed-tier option |
| Object Storage | AWS S3 | Durable, presigned URLs, lifecycle policies |
| Containerization | Docker | Ecosystem ubiquity for exported artifacts |
| Orchestration (infra) | Kubernetes | Autoscaling bursty agent workloads |
| Cloud | AWS | Managed Postgres/Redis/S3/EKS maturity |
| Tracing | LangSmith | Purpose-built LLM/agent observability |
| Metrics | OpenTelemetry + Prometheus + Grafana | Vendor-neutral, standard operational stack |
| CI/CD | GitHub Actions | Integrates with GitHub Export feature |
