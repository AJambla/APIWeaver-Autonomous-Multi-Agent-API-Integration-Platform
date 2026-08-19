# Phase 5 Implementation Plan — Backend API Routes

## Goal
Implement the remaining backend API routes: history/versioning, monitoring metrics, org API-key management, dependency graph, and spec patch endpoints. Frontend is out of scope.

---

## Prerequisites (Already Complete)
- `backend/app/models/versioning.py` — `ArtifactVersion` model exists
- `backend/app/models/metrics.py` — `UsageMetric` model exists  
- `backend/app/models/user.py` — `APIKey` model exists
- `backend/app/models/spec.py` — `Endpoint`, `EndpointDependency` models exist
- `backend/app/rbac/policy.py` — `ORG_MANAGE_API_KEYS` permission exists

---

## Task 1: History & Versioning Routes

### Files to Create/Modify
- `backend/app/api/v1/history.py` (new)
- `backend/app/schemas/history.py` (new)
- `backend/app/rbac/policy.py` (add permissions)

### Endpoints
```
GET /api/v1/projects/{id}/history
  - Paginated list of workflow runs for the project
  - Filter by status, date range
  - Returns: { data: [WorkflowRunSummary], pagination }

GET /api/v1/projects/{id}/versions
  - List artifact versions (SDK, client, etc.)
  - Filter by artifact_type
  - Returns: { data: [ArtifactVersion], pagination }

POST /api/v1/projects/{id}/versions/{version_id}/rollback
  - Rollback to a previous artifact version
  - Creates new version pointing to previous artifact
  - Returns: { version_id, rolled_back_from, status }
```

### Permissions to Add
```python
HISTORY_READ = "history:read"
VERSION_READ = "version:read"
VERSION_ROLLBACK = "version:rollback"
```

### RBAC Requirements
- `HISTORY_READ` → Viewer+
- `VERSION_READ` → Viewer+
- `VERSION_ROLLBACK` → Owner+

---

## Task 2: Monitoring Metrics Routes

### Files to Create/Modify
- `backend/app/api/v1/metrics.py` (new)
- `backend/app/schemas/metrics.py` (new)
- `backend/app/services/metrics_service.py` (new)

### Endpoints
```
GET /api/v1/projects/{id}/metrics
  - Project-level metrics aggregation
  - Query params: period (7d, 30d, 90d)
  - Returns: {
      workflow_success_rate: float,
      avg_time_to_integration_minutes: float,
      test_pass_rate: float,
      total_token_spend: int,
      estimated_cost_usd: decimal
    }

GET /api/v1/org/{org_id}/metrics
  - Organization-level metrics aggregation
  - Query params: period (7d, 30d, 90d)
  - Returns: {
      avg_time_to_integration_minutes: float,
      test_pass_rate: float,
      monthly_token_spend_usd: decimal,
      active_projects: int,
      total_workflows: int
    }
```

### Permissions to Add
```python
PROJECT_METRICS_READ = "project:metrics_read"
ORG_METRICS_READ = "org:metrics_read"
```

### RBAC Requirements
- `PROJECT_METRICS_READ` → Viewer+
- `ORG_METRICS_READ` → Member+

### Implementation Notes
- Query `usage_metrics` table (partitioned by day)
- Query `workflow_runs` for success rate calculations
- Use time-range filtering with `recorded_at` partition key
- Consider caching with Redis (5-minute TTL)

---

## Task 3: Org API-Key Management Routes

### Files to Create/Modify
- `backend/app/api/v1/api_keys.py` (new)
- `backend/app/schemas/api_key.py` (new)
- `backend/app/services/api_key_service.py` (new or extend auth_service)

### Endpoints
```
POST /api/v1/org/{org_id}/api-keys
  - Create new API key for organization
  - Request: { name: str, project_id?: uuid, expires_at?: datetime }
  - Returns: { id, name, key: "apw_live_xxx", key_prefix, expires_at }
  - NOTE: Full key returned ONLY on creation (Security.md §5)

GET /api/v1/org/{org_id}/api-keys
  - List API keys for organization
  - Returns: { data: [{ id, name, key_prefix, project_id, created_at, expires_at, is_active }] }

DELETE /api/v1/org/{org_id}/api-keys/{key_id}
  - Revoke an API key (soft delete via revoked_at)
  - Returns: 204 No Content
```

### Permissions
- Already exists: `ORG_MANAGE_API_KEYS` → Admin+

### Implementation Notes
- Generate key with `apw_live_` prefix (or `apw_test_` for test mode)
- Store only SHA-256 hash (`key_hash`) and prefix (`key_prefix`)
- Audit log on create/revoke (`api_key.created`, `api_key.revoked`)
- Validate project_id is in same org if specified

---

## Task 4: Dependency Graph Endpoint

### Files to Create/Modify
- `backend/app/api/v1/dependency.py` (new)
- `backend/app/schemas/dependency.py` (new)

### Endpoints
```
GET /api/v1/projects/{id}/dependency-graph
  - Returns: {
      nodes: [{ id: endpoint_id, label: "POST /orders", method, path }],
      edges: [{ from: endpoint_id, to: endpoint_id, relationship: "requires_created_resource" }]
    }
```

### Permissions
- Already exists: `SPEC_READ` → Viewer+

### Implementation Notes
- Query `endpoint_dependencies` table joined with `endpoints`
- Build nodes from all endpoints in project's current spec
- Build edges from `endpoint_dependencies` rows
- Include endpoint metadata (method, path, summary) in nodes

---

## Task 5: Spec Patch Endpoint

### Files to Create/Modify
- Extend `backend/app/api/v1/documents.py` or create new file
- `backend/app/schemas/spec.py` (new or extend)

### Endpoints
```
PATCH /api/v1/projects/{id}/spec/endpoints/{endpoint_id}
  - Manual correction of low-confidence endpoint
  - Request: {
      path?: str,
      method?: str,
      summary?: str,
      request_schema?: dict,
      response_schemas?: dict,
      parameters?: [ParameterUpdate],
      confidence_score?: decimal  // Set to 1.0 for manual override
    }
  - Returns: { endpoint_id, updated_fields, confidence_score }
```

### Permissions
- Already exists: `SPEC_UPDATE` → Editor+

### Implementation Notes
- Validate endpoint belongs to project's current spec
- Audit log the change with before/after values
- Bump `confidence_score` to 1.0 on manual edit (per AI_Instruction.md)
- Consider creating `document_versions` entry for rollback capability

---

## Task 6: Register Routes in Router

### File to Modify
- `backend/app/api/v1/router.py`

### Changes
```python
from app.api.v1 import history, metrics, api_keys, dependency

api_router.include_router(history.router, prefix="/projects")
api_router.include_router(metrics.router)
api_router.include_router(api_keys.router, prefix="/org")
api_router.include_router(dependency.router, prefix="/projects")
```

---

## Task 7: Tests

### Files to Create
- `backend/tests/test_history.py`
- `backend/tests/test_metrics.py`
- `backend/tests/test_api_keys.py`
- `backend/tests/test_dependency.py`
- `backend/tests/test_spec_patch.py`

### Test Coverage
- Auth required on all endpoints
- RBAC enforcement (viewer vs editor vs owner)
- Pagination on list endpoints
- API key creation returns full key only once
- Rollback creates new version record
- Metrics aggregation queries

---

## Task 8: Alembic Migration

### Check if Needed
- `ArtifactVersion` table should exist (check migration 0001)
- `APIKey` table should exist (check migration 0001)
- `EndpointDependency` table should exist (check migration 0001)

If any missing, create migration:
```bash
alembic revision --autogenerate -m "add_phase5_tables"
```

---

## Validation Checklist
- [ ] `ruff check backend/`
- [ ] `mypy backend/`
- [ ] `pytest backend/tests/ -v`
- [ ] All new endpoints return correct HTTP status codes
- [ ] Audit logs recorded for create/revoke/patch operations
- [ ] RBAC permissions enforced

---

## Open Questions (Decide Before Implementation)

### Q1: Metrics Period Granularity
API.md shows `period` query param. Options:
- **Fixed periods**: `7d`, `30d`, `90d` (simpler, matches spec)
- **Custom range**: `start_date` + `end_date` params (more flexible)

**Recommendation**: Fixed periods per spec. Add custom range in future if needed.

### Q2: API Key Rotation
Should there be a "rotate" endpoint that creates a new key and immediately revokes the old one?

**Recommendation**: No, keep it simple. User creates new key, updates their systems, then revokes old key. Add rotation endpoint in future if needed.

### Q3: Rollback Behavior
When rolling back a version, should it:
- **Option A**: Create a new version record pointing to the old artifact (audit trail preserved)
- **Option B**: Update the "current" pointer to the old version (simpler)

**Recommendation**: Option A per audit requirements. Every action creates a traceable record.

---

## Risks & Mitigations

| Risk | Mitigation |
|------|------------|
| `usage_metrics` table is partitioned — queries must include `recorded_at` | Ensure all metrics queries filter by date range |
| API key displayed only once | Store only hash, return key in creation response only |
| Spec patch could break generated code | Document that re-generation is needed after patch |
| Rollback could be destructive | Require explicit confirmation, audit log everything |

---

## Estimated Scope
- ~5 new API route files
- ~5 new schema files
- ~5 new test files
- ~1 new service file (metrics_service)
- ~8 new permissions
- Router registration updates

This is a moderate scope implementation focused purely on backend API completion.
