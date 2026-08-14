# Database Design
## APIWeaver

---

## 1. Overview

APIWeaver uses **PostgreSQL** as the system of record (relational, ACID-compliant), **Redis** for caching/pub-sub/queueing, and **Qdrant** for vector storage (semantic search over documentation and integration reuse). This document covers schema, indexes, relationships, constraints, migrations, caching strategy, and scalability.

---

## 2. ER Diagram (text form)

```
organizations ──< organization_members >── users
     │
     └──< projects >──< project_members >── users
              │
              ├──< documents >──< document_versions
              │
              ├──< api_specs >──< endpoints >──< endpoint_parameters
              │                         │
              │                         └──< endpoint_dependencies (self-referencing M:N)
              │
              ├──< auth_configs >──< secrets_refs
              │
              ├──< workflow_runs >──< workflow_checkpoints
              │              │
              │              └──< agent_events >──< tool_calls
              │
              ├──< code_generation_runs >──< generated_files
              │
              ├──< test_runs >──< test_results >──< repair_attempts
              │
              ├──< sdk_packages >──< sdk_versions
              │
              ├──< exports >── (github_exports | mcp_tools | docker artifacts via generated_files)
              │
              ├──< artifact_versions
              │
              └──< usage_metrics
```

---

## 3. Tables

### 3.1 `organizations`
| Column | Type | Constraints |
|---|---|---|
| id | UUID | PK, default `gen_random_uuid()` |
| name | VARCHAR(255) | NOT NULL |
| slug | VARCHAR(100) | UNIQUE, NOT NULL |
| plan_tier | VARCHAR(50) | NOT NULL, DEFAULT 'free' CHECK IN ('free','pro','enterprise') |
| created_at | TIMESTAMPTZ | NOT NULL DEFAULT now() |
| updated_at | TIMESTAMPTZ | NOT NULL DEFAULT now() |

### 3.2 `users`
| Column | Type | Constraints |
|---|---|---|
| id | UUID | PK |
| email | VARCHAR(255) | UNIQUE, NOT NULL |
| password_hash | VARCHAR(255) | NULL (nullable for SSO-only accounts) |
| full_name | VARCHAR(255) | NOT NULL |
| mfa_enabled | BOOLEAN | NOT NULL DEFAULT false |
| created_at | TIMESTAMPTZ | NOT NULL DEFAULT now() |

### 3.3 `organization_members`
| Column | Type | Constraints |
|---|---|---|
| organization_id | UUID | PK, FK → organizations.id ON DELETE CASCADE |
| user_id | UUID | PK, FK → users.id ON DELETE CASCADE |
| role | VARCHAR(50) | NOT NULL CHECK IN ('owner','admin','member','billing') |
| joined_at | TIMESTAMPTZ | NOT NULL DEFAULT now() |

### 3.4 `projects`
| Column | Type | Constraints |
|---|---|---|
| id | UUID | PK |
| organization_id | UUID | FK → organizations.id ON DELETE CASCADE, NOT NULL |
| name | VARCHAR(255) | NOT NULL |
| status | VARCHAR(50) | NOT NULL DEFAULT 'draft' CHECK IN ('draft','planning','building','testing','ready','failed','archived') |
| created_by | UUID | FK → users.id |
| created_at | TIMESTAMPTZ | NOT NULL DEFAULT now() |
| updated_at | TIMESTAMPTZ | NOT NULL DEFAULT now() |
| archived_at | TIMESTAMPTZ | NULL |

**Indexes:** `idx_projects_org_id (organization_id)`, `idx_projects_status (status)`.

### 3.5 `project_members`
| Column | Type | Constraints |
|---|---|---|
| project_id | UUID | PK, FK → projects.id ON DELETE CASCADE |
| user_id | UUID | PK, FK → users.id ON DELETE CASCADE |
| role | VARCHAR(50) | NOT NULL CHECK IN ('owner','editor','viewer') |

### 3.6 `documents`
| Column | Type | Constraints |
|---|---|---|
| id | UUID | PK |
| project_id | UUID | FK → projects.id ON DELETE CASCADE, NOT NULL |
| filename | VARCHAR(500) | NOT NULL |
| format | VARCHAR(50) | NOT NULL CHECK IN ('openapi','swagger','postman','markdown','pdf','html') |
| s3_key | VARCHAR(1000) | NOT NULL |
| checksum_sha256 | CHAR(64) | NOT NULL |
| uploaded_by | UUID | FK → users.id |
| uploaded_at | TIMESTAMPTZ | NOT NULL DEFAULT now() |

**Indexes:** `idx_documents_project_id (project_id)`, `uniq_documents_checksum (project_id, checksum_sha256)`.

### 3.7 `document_versions`
| Column | Type | Constraints |
|---|---|---|
| id | UUID | PK |
| document_id | UUID | FK → documents.id ON DELETE CASCADE |
| version_number | INT | NOT NULL |
| diff_summary | JSONB | NULL |
| created_at | TIMESTAMPTZ | NOT NULL DEFAULT now() |

### 3.8 `api_specs`
| Column | Type | Constraints |
|---|---|---|
| id | UUID | PK |
| project_id | UUID | FK → projects.id ON DELETE CASCADE, NOT NULL |
| source_document_id | UUID | FK → documents.id |
| title | VARCHAR(255) | |
| base_url | VARCHAR(1000) | |
| raw_normalized | JSONB | NOT NULL — full canonical spec |
| confidence_score | NUMERIC(3,2) | CHECK (confidence_score BETWEEN 0 AND 1) |
| created_at | TIMESTAMPTZ | NOT NULL DEFAULT now() |

### 3.9 `endpoints`
| Column | Type | Constraints |
|---|---|---|
| id | UUID | PK |
| api_spec_id | UUID | FK → api_specs.id ON DELETE CASCADE, NOT NULL |
| method | VARCHAR(10) | NOT NULL CHECK IN ('GET','POST','PUT','PATCH','DELETE') |
| path | VARCHAR(1000) | NOT NULL |
| summary | TEXT | |
| request_schema | JSONB | |
| response_schemas | JSONB | NOT NULL — keyed by status code |
| deprecated | BOOLEAN | NOT NULL DEFAULT false |
| is_destructive | BOOLEAN | NOT NULL DEFAULT false |
| confidence_score | NUMERIC(3,2) | |

**Indexes:** `idx_endpoints_spec_id (api_spec_id)`, `uniq_endpoint_method_path (api_spec_id, method, path)`.

### 3.10 `endpoint_parameters`
| Column | Type | Constraints |
|---|---|---|
| id | UUID | PK |
| endpoint_id | UUID | FK → endpoints.id ON DELETE CASCADE |
| name | VARCHAR(255) | NOT NULL |
| location | VARCHAR(20) | NOT NULL CHECK IN ('path','query','header','body') |
| type | VARCHAR(50) | NOT NULL |
| required | BOOLEAN | NOT NULL DEFAULT false |

### 3.11 `endpoint_dependencies`
| Column | Type | Constraints |
|---|---|---|
| id | UUID | PK |
| project_id | UUID | FK → projects.id ON DELETE CASCADE |
| from_endpoint_id | UUID | FK → endpoints.id ON DELETE CASCADE |
| to_endpoint_id | UUID | FK → endpoints.id ON DELETE CASCADE |
| relationship | VARCHAR(50) | CHECK IN ('requires_auth','requires_created_resource','optional_precedes') |

**Constraint:** `CHECK (from_endpoint_id <> to_endpoint_id)` — prevents trivial self-loop.

### 3.12 `auth_configs`
| Column | Type | Constraints |
|---|---|---|
| id | UUID | PK |
| project_id | UUID | FK → projects.id ON DELETE CASCADE, UNIQUE |
| scheme | VARCHAR(50) | NOT NULL CHECK IN ('api_key','bearer_jwt','oauth2_client_credentials','oauth2_auth_code','basic','hmac','none') |
| config_json | JSONB | NOT NULL — non-secret config (header names, token URLs, scopes) |
| verified | BOOLEAN | NOT NULL DEFAULT false |

### 3.13 `secrets_refs`
| Column | Type | Constraints |
|---|---|---|
| id | UUID | PK |
| auth_config_id | UUID | FK → auth_configs.id ON DELETE CASCADE |
| vault_path | VARCHAR(1000) | NOT NULL — pointer only, never the secret value |
| created_at | TIMESTAMPTZ | NOT NULL DEFAULT now() |

> **Security note:** No secret value is ever stored in Postgres. `secrets_refs` stores only a reference path into HashiCorp Vault / AWS Secrets Manager.

### 3.14 `workflow_runs`
| Column | Type | Constraints |
|---|---|---|
| id | UUID | PK |
| project_id | UUID | FK → projects.id ON DELETE CASCADE |
| triggered_by | UUID | FK → users.id |
| status | VARCHAR(50) | NOT NULL CHECK IN ('queued','running','paused_for_approval','completed','failed','cancelled') |
| started_at | TIMESTAMPTZ | |
| completed_at | TIMESTAMPTZ | |
| total_tokens_used | BIGINT | DEFAULT 0 |
| estimated_cost_usd | NUMERIC(10,4) | DEFAULT 0 |

**Indexes:** `idx_workflow_runs_project_id (project_id)`, `idx_workflow_runs_status (status)`.

### 3.15 `workflow_checkpoints`
| Column | Type | Constraints |
|---|---|---|
| id | UUID | PK |
| workflow_run_id | UUID | FK → workflow_runs.id ON DELETE CASCADE |
| node_name | VARCHAR(100) | NOT NULL |
| state_snapshot | JSONB | NOT NULL |
| created_at | TIMESTAMPTZ | NOT NULL DEFAULT now() |

### 3.16 `agent_events`
| Column | Type | Constraints |
|---|---|---|
| id | BIGSERIAL | PK |
| workflow_run_id | UUID | FK → workflow_runs.id ON DELETE CASCADE |
| agent_name | VARCHAR(100) | NOT NULL |
| event_type | VARCHAR(50) | NOT NULL |
| payload | JSONB | |
| created_at | TIMESTAMPTZ | NOT NULL DEFAULT now() |

**Partitioning:** partitioned by month (`created_at`) — high write volume table.

### 3.17 `tool_calls`
| Column | Type | Constraints |
|---|---|---|
| id | BIGSERIAL | PK |
| agent_event_id | BIGINT | FK → agent_events.id ON DELETE CASCADE |
| tool_name | VARCHAR(100) | NOT NULL |
| arguments | JSONB | |
| result | JSONB | |
| duration_ms | INT | |

### 3.18 `code_generation_runs`
| Column | Type | Constraints |
|---|---|---|
| id | UUID | PK |
| workflow_run_id | UUID | FK → workflow_runs.id ON DELETE CASCADE |
| target_language | VARCHAR(20) | NOT NULL CHECK IN ('python','node') |
| status | VARCHAR(50) | NOT NULL |

### 3.19 `generated_files`
| Column | Type | Constraints |
|---|---|---|
| id | UUID | PK |
| code_generation_run_id | UUID | FK → code_generation_runs.id ON DELETE CASCADE |
| file_path | VARCHAR(1000) | NOT NULL |
| content_s3_key | VARCHAR(1000) | NOT NULL |
| language | VARCHAR(20) | |
| file_type | VARCHAR(50) | CHECK IN ('sdk','test','dockerfile','ci_cd','readme','mcp_manifest') |

### 3.20 `test_runs`
| Column | Type | Constraints |
|---|---|---|
| id | UUID | PK |
| project_id | UUID | FK → projects.id ON DELETE CASCADE |
| workflow_run_id | UUID | FK → workflow_runs.id |
| environment | VARCHAR(20) | NOT NULL CHECK IN ('sandbox','live') |
| started_at | TIMESTAMPTZ | |
| completed_at | TIMESTAMPTZ | |

### 3.21 `test_results`
| Column | Type | Constraints |
|---|---|---|
| id | UUID | PK |
| test_run_id | UUID | FK → test_runs.id ON DELETE CASCADE |
| endpoint_id | UUID | FK → endpoints.id |
| status | VARCHAR(20) | NOT NULL CHECK IN ('passed','failed','skipped') |
| status_code | INT | |
| latency_ms | INT | |
| response_snapshot | JSONB | |

**Indexes:** `idx_test_results_run_id (test_run_id)`, `idx_test_results_endpoint_id (endpoint_id)`.

### 3.22 `repair_attempts`
| Column | Type | Constraints |
|---|---|---|
| id | UUID | PK |
| test_result_id | UUID | FK → test_results.id ON DELETE CASCADE |
| attempt_number | INT | NOT NULL |
| failure_classification | VARCHAR(50) | |
| diff_summary | JSONB | |
| outcome | VARCHAR(20) | CHECK IN ('resolved','still_failing','escalated') |

### 3.23 `sdk_packages` / `sdk_versions`
| Column | Type | Constraints |
|---|---|---|
| id | UUID | PK |
| project_id | UUID | FK → projects.id |
| language | VARCHAR(20) | NOT NULL |
| package_name | VARCHAR(255) | NOT NULL |

`sdk_versions`: `id`, `sdk_package_id (FK)`, `semver`, `s3_key`, `created_at`.

### 3.24 `exports`
| Column | Type | Constraints |
|---|---|---|
| id | UUID | PK |
| project_id | UUID | FK → projects.id ON DELETE CASCADE |
| export_type | VARCHAR(50) | CHECK IN ('sdk','client','docker','github','mcp','docs','cicd') |
| status | VARCHAR(20) | |
| created_at | TIMESTAMPTZ | NOT NULL DEFAULT now() |

### 3.25 `github_exports`
| id (UUID PK) | export_id (FK) | repo_full_name | commit_sha | pushed_at |

### 3.26 `mcp_tools`
| id (UUID PK) | project_id (FK) | tool_name | input_schema (JSONB) | requires_confirmation (BOOLEAN) |

### 3.27 `artifact_versions`
| id (UUID PK) | project_id (FK) | artifact_type | version_number | diff_ref | created_at |

### 3.28 `usage_metrics`
| id (BIGSERIAL PK) | organization_id (FK) | metric_name | value | recorded_at | — partitioned by day, TTL 90 days (rolled up into aggregate tables beyond that).

---

## 4. Relationships Summary

| Relationship | Type |
|---|---|
| organizations → projects | 1:N |
| projects → documents | 1:N |
| documents → api_specs | 1:1 (per active version) |
| api_specs → endpoints | 1:N |
| endpoints ↔ endpoints (dependencies) | M:N (self-referencing via `endpoint_dependencies`) |
| projects → workflow_runs | 1:N |
| workflow_runs → agent_events | 1:N |
| workflow_runs → code_generation_runs | 1:N |
| code_generation_runs → generated_files | 1:N |
| test_runs → test_results | 1:N |
| test_results → repair_attempts | 1:N |
| projects → exports | 1:N |

---

## 5. Constraints Philosophy

- All foreign keys use `ON DELETE CASCADE` within a project's owned subtree (deleting a project cleanly removes all derived data) except `secrets_refs`, which triggers an explicit Vault-deletion hook before DB cascade (application-level, not DB-level, to guarantee secret cleanup ordering).
- `CHECK` constraints enforce enum-like fields at the DB layer as a second line of defense beyond application validation.
- `UNIQUE` constraints prevent duplicate endpoint records per spec and duplicate document uploads (via checksum) within a project.

---

## 6. Migration Strategy

- **Tooling:** Alembic (SQLAlchemy) for all schema migrations, versioned and checked into the repo (`/migrations`).
- **Process:** every migration is additive-first (expand/contract pattern) — new columns nullable initially, backfilled, then constrained in a follow-up migration to avoid locking large tables during deploy.
- **Zero-downtime:** migrations run automatically via CI/CD pre-deploy step; `agent_events` and `usage_metrics` (high-volume, partitioned) migrations always tested against a production-sized snapshot in staging first.
- **Rollback:** every migration ships a paired `downgrade()`; destructive migrations (column drops) are deferred to a second release after confirming the column is unused.

---

## 7. Caching Strategy (Redis)

| Cache Key Pattern | Data | TTL |
|---|---|---|
| `spec:{project_id}:normalized` | Normalized API spec (avoid re-parsing on every read) | 1 hour, invalidated on re-upload |
| `workflow:{run_id}:status` | Live workflow status for fast dashboard polling fallback | 5 min |
| `ratelimit:{org_id}:{window}` | Sliding-window rate limit counters | 1 min window |
| `session:{user_id}` | Auth session data | 24 hr |
| `dep_graph:{project_id}` | Computed dependency graph (expensive to rebuild) | 30 min, invalidated on spec change |

Redis Streams (`workflow:{run_id}:events`) used for real-time pub/sub of agent events consumed by the SSE/WebSocket gateway.

---

## 8. Vector Storage (Qdrant)

| Collection | Purpose | Vector Source |
|---|---|---|
| `doc_chunks` | Semantic retrieval over large freeform documentation during LLM extraction (RAG) | BGE / OpenAI embeddings of chunked doc text |
| `endpoint_embeddings` | Similarity search for "APIs similar to this one" (marketplace, reuse suggestions) | Embeddings of endpoint summaries |
| `error_patterns` | Retrieval-augmented repair — find similar past failures and their successful fixes | Embeddings of failure signatures |

Each point stores a payload with `project_id`, `org_id` for filtered search (multi-tenant isolation enforced at the query filter level, not just application logic).

---

## 9. Scalability

- **Read replicas:** Postgres read replicas for dashboard/history queries, primary reserved for write-heavy workflow execution paths.
- **Partitioning:** `agent_events` and `usage_metrics` partitioned by time range; old partitions rolled up/archived to S3 (via `pg_partman` + export job).
- **Connection pooling:** PgBouncer in transaction-pooling mode in front of Postgres given high concurrent short-lived connections from many agent workers.
- **Horizontal scaling:** stateless FastAPI instances behind a load balancer; agent workers scale independently via Kubernetes HPA keyed on Redis/Celery queue depth.
- **Sharding path (future):** if a single org's `agent_events` volume becomes extreme, org-based sharding is the planned next step (schema already organization-scoped via `organization_id` on all top-level tables).
