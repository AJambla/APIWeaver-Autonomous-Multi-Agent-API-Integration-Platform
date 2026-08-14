# API Documentation
## APIWeaver Platform API — v1

Base URL: `https://api.apiweaver.dev/api/v1`

---

## 1. Authentication

APIWeaver's own platform API supports two authentication modes:

| Mode | Use Case | Header |
|---|---|---|
| Bearer JWT | Interactive frontend/session use | `Authorization: Bearer <jwt>` |
| API Key | Programmatic/CI use (per-org) | `X-API-Key: <key>` |

**Obtaining a JWT:**
```
POST /api/v1/auth/login
Content-Type: application/json

{ "email": "maya@example.com", "password": "********" }
```
**Response 200:**
```json
{
  "access_token": "eyJhbGciOi...",
  "refresh_token": "eyJhbGciOi...",
  "expires_in": 3600,
  "token_type": "bearer"
}
```

**Refreshing:**
```
POST /api/v1/auth/refresh
{ "refresh_token": "eyJhbGciOi..." }
```

**API Keys:** created via `POST /api/v1/org/{org_id}/api-keys`, scoped per-organization, revocable, never displayed again after creation (only a prefix is stored for identification).

---

## 2. Versioning

- URL-path versioning: `/api/v1/...`. Breaking changes ship under a new prefix (`/api/v2/...`); non-breaking additions ship within `v1`.
- Deprecation policy: minimum 6 months notice via `Deprecation` and `Sunset` HTTP headers before a version is retired.
- Generated integration SDKs (the platform's *output*, not this API) are independently versioned per project — see `Database.md §artifact_versions`.

---

## 3. Rate Limiting

| Tier | Requests/min | Workflow triggers/hour |
|---|---|---|
| Free | 60 | 5 |
| Pro | 600 | 100 |
| Enterprise | Custom | Custom |

Rate limit headers returned on every response:
```
X-RateLimit-Limit: 600
X-RateLimit-Remaining: 587
X-RateLimit-Reset: 1755000000
```
Exceeding the limit returns `429 Too Many Requests` with a `Retry-After` header.

---

## 4. Pagination

Cursor-based pagination on all list endpoints.

**Request:** `GET /api/v1/projects?limit=25&cursor=eyJpZCI6...`

**Response:**
```json
{
  "data": [ /* items */ ],
  "pagination": {
    "next_cursor": "eyJpZCI6MTIzfQ==",
    "has_more": true,
    "limit": 25
  }
}
```

---

## 5. Standard Error Format

```json
{
  "error": {
    "code": "VALIDATION_ERROR",
    "message": "The uploaded file is not a valid OpenAPI document.",
    "details": [
      { "field": "file", "issue": "Missing required 'openapi' field at document root." }
    ],
    "request_id": "req_9f8a2c1b"
  }
}
```

### Status Codes

| Code | Meaning |
|---|---|
| 200 | Success |
| 201 | Resource created |
| 202 | Accepted (async workflow started) |
| 400 | Bad request / validation error |
| 401 | Unauthenticated |
| 403 | Forbidden (insufficient role/permissions) |
| 404 | Resource not found |
| 409 | Conflict (e.g., duplicate project name) |
| 422 | Unprocessable entity (spec parsed but semantically invalid) |
| 429 | Rate limit exceeded |
| 500 | Internal server error |
| 503 | Downstream dependency (LLM provider) unavailable |

---

## 6. Routes

### 6.1 Projects

#### `POST /api/v1/projects`
Create a new project.
```json
// Request
{ "name": "Stripe Payments Integration", "organization_id": "org_123" }
```
```json
// Response 201
{
  "id": "proj_abc123",
  "name": "Stripe Payments Integration",
  "status": "draft",
  "created_at": "2026-08-10T12:00:00Z"
}
```

#### `GET /api/v1/projects`
List projects (paginated, filterable by `status`, `organization_id`).

#### `GET /api/v1/projects/{id}`
Retrieve a single project with summary counts (endpoints, last run status).

#### `DELETE /api/v1/projects/{id}`
Soft-deletes (archives) a project. Requires `owner` or `admin` role.

---

### 6.2 Upload & Documentation

#### `POST /api/v1/projects/{id}/upload`
`Content-Type: multipart/form-data`

| Field | Type | Required |
|---|---|---|
| file | binary | yes |
| format_hint | string (`openapi`,`postman`,`freeform`) | no |

**Response 202:**
```json
{
  "document_id": "doc_789",
  "status": "processing",
  "workflow_run_id": "run_456"
}
```

#### `GET /api/v1/projects/{id}/spec`
Returns the normalized API spec once parsing completes.

**Errors:** `422 UNPARSEABLE_DOCUMENT` if the Documentation Agent cannot extract a valid spec.

---

### 6.3 Authentication Configuration

#### `GET /api/v1/projects/{id}/auth`
```json
{
  "scheme": "oauth2_client_credentials",
  "config_json": { "token_url": "https://api.target.com/oauth/token", "scopes": ["read","write"] },
  "verified": false
}
```

#### `PUT /api/v1/projects/{id}/auth`
```json
// Request
{
  "scheme": "oauth2_client_credentials",
  "config_json": { "token_url": "https://api.target.com/oauth/token", "scopes": ["read"] },
  "credentials": { "client_id": "abc", "client_secret": "***" }
}
```
> `credentials` is written directly to Vault and never echoed back or persisted in Postgres.

---

### 6.4 Workflows (Orchestration)

#### `POST /api/v1/projects/{id}/workflows`
Triggers the multi-agent pipeline.
```json
// Request
{ "stages": ["plan","generate","test","export"], "target_languages": ["python","node"] }
```
**Response 202:**
```json
{ "workflow_run_id": "run_456", "status": "queued" }
```

#### `GET /api/v1/workflows/{run_id}`
```json
{
  "id": "run_456",
  "status": "running",
  "current_node": "code_generator_agent",
  "progress_percent": 42,
  "started_at": "2026-08-14T09:00:00Z"
}
```

#### `POST /api/v1/workflows/{run_id}/approve`
Approves a human-in-the-loop gate (e.g., approving the execution plan before code generation begins).
```json
{ "approved": true, "notes": "Looks good, proceed." }
```

#### `POST /api/v1/workflows/{run_id}/cancel`
Cancels an in-progress workflow (idempotent).

#### `GET /api/v1/workflows/{run_id}/tool-calls`
Returns the tool-call trace for the run (paginated).

---

### 6.5 Endpoints & Dependency Graph

#### `GET /api/v1/projects/{id}/endpoints`
Filterable by `method`, `deprecated`, `confidence_min`.

#### `PATCH /api/v1/projects/{id}/spec/endpoints/{endpoint_id}`
Manual correction of a low-confidence endpoint (e.g., fixing an incorrectly inferred schema).

#### `GET /api/v1/projects/{id}/dependency-graph`
```json
{
  "nodes": [ { "id": "ep_1", "label": "POST /orders" } ],
  "edges": [ { "from": "ep_1", "to": "ep_2", "relationship": "requires_created_resource" } ]
}
```

---

### 6.6 Code Generation

#### `POST /api/v1/projects/{id}/generate`
```json
{ "target_languages": ["python"], "include_fastapi_wrapper": true }
```

#### `GET /api/v1/projects/{id}/files`
Lists generated files with metadata (path, language, size, file_type).

#### `GET /api/v1/projects/{id}/files/{file_id}/content`
Returns raw file content (or a presigned S3 URL for large files).

---

### 6.7 Testing

#### `POST /api/v1/projects/{id}/test`
```json
{ "environment": "sandbox", "endpoint_ids": null }
```
`endpoint_ids: null` runs the full suite; an array runs a targeted subset.

**Response 202:**
```json
{ "test_run_id": "trun_321", "status": "running" }
```

#### `GET /api/v1/projects/{id}/test-runs/{run_id}`
```json
{
  "id": "trun_321",
  "status": "completed",
  "summary": { "passed": 41, "failed": 3, "skipped": 1, "total": 45 }
}
```

#### `GET /api/v1/projects/{id}/test-runs/{run_id}/repairs`
Returns self-healing repair attempts for failed tests in this run.

---

### 6.8 Export

#### `POST /api/v1/projects/{id}/export`
```json
{ "types": ["sdk", "docker", "github", "mcp"], "github": { "repo_full_name": "myorg/stripe-integration" } }
```

#### `POST /api/v1/projects/{id}/export/mcp`
```json
// Response 200
{
  "mcp_manifest_url": "https://cdn.apiweaver.dev/exports/proj_abc/mcp/manifest.json",
  "tools_generated": 18,
  "flagged_destructive": 3
}
```

---

### 6.9 History & Versioning

#### `GET /api/v1/projects/{id}/history`
Paginated workflow run timeline.

#### `GET /api/v1/projects/{id}/versions`
#### `POST /api/v1/projects/{id}/versions/{version_id}/rollback`

---

### 6.10 Monitoring

#### `GET /api/v1/projects/{id}/metrics`
#### `GET /api/v1/org/{org_id}/metrics`
```json
{
  "avg_time_to_integration_minutes": 24.3,
  "test_pass_rate": 0.93,
  "monthly_token_spend_usd": 412.55
}
```

---

## 7. OpenAPI Specification Example (excerpt)

```yaml
openapi: 3.0.3
info:
  title: APIWeaver Platform API
  version: "1.0.0"
paths:
  /projects:
    post:
      summary: Create a new project
      operationId: createProject
      security:
        - bearerAuth: []
      requestBody:
        required: true
        content:
          application/json:
            schema:
              type: object
              required: [name, organization_id]
              properties:
                name:
                  type: string
                organization_id:
                  type: string
      responses:
        "201":
          description: Project created
          content:
            application/json:
              schema:
                $ref: "#/components/schemas/Project"
components:
  securitySchemes:
    bearerAuth:
      type: http
      scheme: bearer
      bearerFormat: JWT
  schemas:
    Project:
      type: object
      properties:
        id: { type: string }
        name: { type: string }
        status:
          type: string
          enum: [draft, planning, building, testing, ready, failed, archived]
        created_at: { type: string, format: date-time }
```

> Note: APIWeaver's platform API is itself fully documented via an auto-generated OpenAPI spec at `/api/v1/openapi.json`, dogfooding the same normalization format the product generates for user-uploaded APIs.
