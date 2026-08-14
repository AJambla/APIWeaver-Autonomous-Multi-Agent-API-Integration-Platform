# Feature Documentation
## APIWeaver — Complete Feature Specification

Each feature below documents description, purpose, priority, workflow, edge cases, future improvements, dependencies, UI components, backend components, database tables, API endpoints, and involved AI agents.

---

## 1. Upload API Documentation

**Description:** Users upload OpenAPI/Swagger (JSON/YAML), Postman Collection (v2.1), or free-form documentation (PDF/Markdown/HTML).

**Purpose:** Entry point for all integration workflows; normalizes heterogeneous input formats into a canonical internal spec.

**Priority:** P0 (Critical)

**Workflow:**
1. User drags/selects file(s) or pastes a public docs URL.
2. Frontend uploads to `/api/v1/projects/{id}/upload` (multipart).
3. Backend stores raw file in S3, creates `document` record.
4. Documentation Agent is triggered asynchronously.
5. UI shows real-time parsing progress via WebSocket/SSE.

**Edge Cases:**
- Corrupted or invalid JSON/YAML file → graceful error with line-level diagnostics.
- Mixed-format uploads (e.g., Postman + supplementary PDF) → merge canonical spec.
- Extremely large specs (>500 endpoints) → chunked parsing with progress checkpoints.
- Password-protected PDFs → prompt user for password.
- Non-English documentation → flagged as unsupported in v1.0.

**Future Improvements:** URL-based auto-crawling of public API doc sites; support for `.har` files; video/screencast ingestion.

**Dependencies:** S3 storage, Documentation Agent, virus/malware scanning service.

**UI Components:** `UploadDropzone`, `FileList`, `ParsingProgressBar`, `FormatDetectorBadge`.

**Backend Components:** `upload_service`, `file_validator`, `s3_client`, `document_parser_dispatcher`.

**Database Tables:** `projects`, `documents`, `document_versions`.

**API Endpoints:** `POST /api/v1/projects/{id}/upload`, `GET /api/v1/projects/{id}/documents`.

**AI Agents Involved:** Documentation Agent.

---

## 2. Automatic Documentation Parsing

**Description:** Converts uploaded raw documentation into a normalized internal API model (endpoints, schemas, auth, examples).

**Purpose:** Provides a single canonical representation regardless of source format so downstream agents don't need per-format logic.

**Priority:** P0

**Workflow:**
1. Format detected (OpenAPI/Swagger/Postman/freeform).
2. Structured formats parsed directly via schema validators.
3. Freeform docs run through LLM-based extraction with structured-output (JSON schema) prompting.
4. Normalized `APISpec` object persisted.
5. Confidence score attached per endpoint (low-confidence entries flagged for user review).

**Edge Cases:** Ambiguous endpoint descriptions; undocumented required fields discovered only via example payloads; inconsistent base URLs across sections.

**Future Improvements:** Cross-referencing multiple doc sources to fill gaps; confidence-based active learning loop.

**Dependencies:** LLM provider, JSON Schema validator, Documentation Agent.

**UI Components:** `SpecPreviewTree`, `ConfidenceBadge`, `EndpointDiffViewer`.

**Backend Components:** `spec_normalizer`, `llm_extraction_service`, `confidence_scorer`.

**Database Tables:** `api_specs`, `endpoints`, `schemas`.

**API Endpoints:** `GET /api/v1/projects/{id}/spec`, `PATCH /api/v1/projects/{id}/spec/endpoints/{endpoint_id}`.

**AI Agents Involved:** Documentation Agent.

---

## 3. Authentication Detection

**Description:** Automatically identifies the API's authentication scheme(s) — API Key, Bearer/JWT, OAuth2 (multiple grant types), Basic Auth, HMAC request signing.

**Purpose:** Auth is the most error-prone part of manual integration; correct detection determines whether generated code works at all.

**Priority:** P0

**Workflow:**
1. Documentation Agent scans `securitySchemes` (OpenAPI) or headers/auth blocks (Postman/freeform).
2. If ambiguous, LLM infers scheme from prose description and example curl commands.
3. User confirms/edits detected scheme and supplies credential placeholders (never real secrets at this stage).
4. Scheme persisted to `auth_configs`.

**Edge Cases:** APIs with per-endpoint auth overrides; multi-step OAuth2 with PKCE; rotating HMAC signatures with timestamp windows; undocumented auth discoverable only through 401 response inspection during testing.

**Future Improvements:** Auto-discovery via trial requests when docs are silent on auth; mTLS support.

**Dependencies:** Secrets Manager, Documentation Agent, Testing Agent (validates auth via live 200/401 checks).

**UI Components:** `AuthSchemeSelector`, `CredentialForm`, `OAuthFlowWizard`.

**Backend Components:** `auth_detector`, `secrets_vault_client`.

**Database Tables:** `auth_configs`, `secrets_refs` (references only — actual secrets in Vault/KMS).

**API Endpoints:** `GET /api/v1/projects/{id}/auth`, `PUT /api/v1/projects/{id}/auth`.

**AI Agents Involved:** Documentation Agent, Testing Agent.

---

## 4. Endpoint Discovery

**Description:** Enumerates all endpoints, methods, parameters, request/response schemas, and example payloads.

**Purpose:** Provides the complete inventory that the Planner and Code Generator agents operate on.

**Priority:** P0

**Workflow:** Extracted during parsing; each endpoint normalized with method, path, params, request body schema, response schemas per status code, and example values.

**Edge Cases:** Deprecated endpoints (flagged, excluded by default); versioned paths (`/v1/`, `/v2/`) requiring version selection; endpoints only discoverable via changelog prose.

**Future Improvements:** Automatic deprecation-aware migration suggestions.

**Dependencies:** Documentation Agent.

**UI Components:** `EndpointTable`, `EndpointDetailPanel`, `SchemaViewer`.

**Backend Components:** `endpoint_extractor`.

**Database Tables:** `endpoints`, `endpoint_parameters`, `schemas`.

**API Endpoints:** `GET /api/v1/projects/{id}/endpoints`.

**AI Agents Involved:** Documentation Agent.

---

## 5. Dependency Analysis

**Description:** Determines call-order dependencies between endpoints (e.g., must call `/auth/token` before any resource endpoint; must `POST /orders` before `GET /orders/{id}`).

**Purpose:** Enables the Planner Agent to build a correct execution graph rather than testing/generating endpoints in isolation and failing due to missing prerequisite state.

**Priority:** P1

**Workflow:** Static analysis of path parameters referencing other endpoints' response IDs; LLM reasoning over prose describing workflows; resulting dependency graph stored as DAG.

**Edge Cases:** Circular-looking dependencies (webhooks that trigger callback endpoints); optional vs. required dependencies; resources creatable via multiple paths.

**Future Improvements:** Learn dependency graphs from example Postman collections' folder ordering.

**Dependencies:** Planner Agent, Endpoint Discovery.

**UI Components:** `DependencyGraphView` (interactive Mermaid/D3 graph).

**Backend Components:** `dependency_graph_builder`.

**Database Tables:** `endpoint_dependencies`.

**API Endpoints:** `GET /api/v1/projects/{id}/dependency-graph`.

**AI Agents Involved:** Planner Agent.

---

## 6. Multi-Agent Workflow Orchestration

**Description:** Coordinates Documentation, Planner, Code Generator, Testing, and Export agents through a LangGraph state machine with checkpoints and human-in-the-loop approval gates.

**Purpose:** Ensures reliable, observable, resumable execution of a complex multi-step agentic pipeline.

**Priority:** P0

**Workflow:** LangGraph graph nodes per agent; shared state object passed/updated at each node; conditional edges route to retry/repair loops or human approval; checkpointed to Postgres for resumability.

**Edge Cases:** Agent timeout/crash mid-workflow; user cancels mid-execution; partial completion (e.g., 80% of endpoints generated) requiring resumable state.

**Future Improvements:** Parallel agent execution for independent endpoint groups; pluggable custom agent nodes.

**Dependencies:** LangGraph, all agents, Redis (pub/sub for progress events).

**UI Components:** `WorkflowTimeline`, `AgentStatusCard`, `ApprovalGateModal`.

**Backend Components:** `orchestrator_service`, `workflow_state_store`.

**Database Tables:** `workflow_runs`, `workflow_checkpoints`, `agent_events`.

**API Endpoints:** `POST /api/v1/projects/{id}/workflows`, `GET /api/v1/workflows/{run_id}`, `POST /api/v1/workflows/{run_id}/approve`.

**AI Agents Involved:** All (Orchestrator coordinates Documentation, Planner, Code Generator, Testing, Export).

---

## 7. Tool Calling

**Description:** Agents use structured tool calls (function calling) to interact with the parsed spec, sandbox execution environment, file system, GitHub API, and Docker builder.

**Purpose:** Grounds LLM reasoning in real, verifiable actions rather than free-text generation alone.

**Priority:** P0

**Workflow:** Each agent registered with a scoped toolset (least privilege); tool calls validated against JSON schema before execution; results fed back into agent context.

**Edge Cases:** Tool call with invalid/malformed arguments; tool timeout; tool call attempting out-of-scope action (blocked by policy layer).

**Future Improvements:** Dynamic tool discovery via MCP for third-party extensions.

**Dependencies:** LLM function-calling support, sandbox executor.

**UI Components:** `ToolCallLogViewer`.

**Backend Components:** `tool_registry`, `tool_policy_enforcer`.

**Database Tables:** `tool_calls`.

**API Endpoints:** `GET /api/v1/workflows/{run_id}/tool-calls`.

**AI Agents Involved:** All agents.

---

## 8. Automatic Code Generation

**Description:** Generates idiomatic, typed, production-quality client code (Python and Node.js/TypeScript) implementing every discovered endpoint.

**Purpose:** The core value delivery — eliminates manual client-writing.

**Priority:** P0

**Workflow:** Planner's execution plan → Code Generator Agent produces per-endpoint methods, request/response models (Pydantic/Zod), auth handling, pagination helpers, retry/backoff wrappers → code assembled into project template → linted/type-checked.

**Edge Cases:** Endpoints with inconsistent naming conventions requiring normalization; binary/file upload endpoints; deeply nested/recursive schemas; APIs exceeding context window (chunked generation with cross-file consistency pass).

**Future Improvements:** Go and Java targets; GraphQL client generation.

**Dependencies:** Planner Agent, LLM, linters (ruff/eslint), type checkers (mypy/tsc).

**UI Components:** `CodeGenProgressPanel`, `CodePreviewEditor` (Monaco).

**Backend Components:** `code_generator_service`, `template_engine`, `linter_runner`.

**Database Tables:** `generated_files`, `code_generation_runs`.

**API Endpoints:** `POST /api/v1/projects/{id}/generate`, `GET /api/v1/projects/{id}/files`.

**AI Agents Involved:** Code Generator Agent.

---

## 9. SDK Generation

**Description:** Packages generated code into a distributable, versioned SDK with README, type stubs, and package metadata (`pyproject.toml` / `package.json`).

**Purpose:** Makes the integration reusable and publishable, not just a one-off script.

**Priority:** P1

**Workflow:** Code Generator output → Export Agent adds packaging metadata, semantic version, changelog, README with usage examples → zipped/tarballed.

**Edge Cases:** Naming collisions with existing published packages; license selection.

**Future Improvements:** Direct publish to PyPI/npm with user consent.

**Dependencies:** Code Generation, Export Agent.

**UI Components:** `SDKExportPanel`, `VersionSelector`.

**Backend Components:** `sdk_packager`.

**Database Tables:** `sdk_packages`, `sdk_versions`.

**API Endpoints:** `POST /api/v1/projects/{id}/export/sdk`.

**AI Agents Involved:** Export Agent.

---

## 10. API Client Generation

**Description:** Lightweight single-file/module client (as opposed to full SDK package) for quick embedding into existing codebases.

**Purpose:** Supports users who want minimal footprint rather than a full package dependency.

**Priority:** P2

**Workflow:** Subset of Code Generator output flattened into a single importable module.

**Edge Cases:** Large APIs producing unwieldy single files → auto-split with warning.

**Future Improvements:** Framework-specific variants (Django, NestJS).

**Dependencies:** Code Generator Agent.

**UI Components:** `ClientExportOption` toggle within export panel.

**Backend Components:** `client_flattener`.

**Database Tables:** `generated_files`.

**API Endpoints:** `POST /api/v1/projects/{id}/export/client`.

**AI Agents Involved:** Code Generator Agent, Export Agent.

---

## 11. FastAPI Integration Generation

**Description:** Wraps the generated client as a ready-to-mount FastAPI router/service, exposing the third-party API through the user's own backend.

**Purpose:** Common pattern — proxy/normalize a third-party API behind the user's own API surface.

**Priority:** P1

**Workflow:** Generates FastAPI `APIRouter` with Pydantic request/response models, dependency-injected auth, and passthrough/normalized endpoints.

**Edge Cases:** Conflicting route naming with user's existing app; streaming responses.

**Future Improvements:** Auto-generated OpenAPI docs for the wrapped router.

**Dependencies:** Code Generator Agent, FastAPI templates.

**UI Components:** Export option checkbox `Generate FastAPI wrapper`.

**Backend Components:** `fastapi_template_generator`.

**Database Tables:** `generated_files`.

**API Endpoints:** `POST /api/v1/projects/{id}/export/fastapi`.

**AI Agents Involved:** Code Generator Agent.

---

## 12. Node.js Integration Generation

**Description:** Generates a TypeScript/Node.js client and optional Express middleware wrapper.

**Purpose:** Covers JS/TS ecosystem parity with the Python offering.

**Priority:** P1

**Workflow:** Mirrors Python generation pipeline using TS-specific templates (Zod schemas, fetch/axios client, Express router option).

**Edge Cases:** ESM vs CommonJS target selection; strict TypeScript mode compatibility.

**Future Improvements:** Deno/Bun runtime targets.

**Dependencies:** Code Generator Agent.

**UI Components:** `LanguageTargetSelector`.

**Backend Components:** `node_template_generator`.

**Database Tables:** `generated_files`.

**API Endpoints:** `POST /api/v1/projects/{id}/generate?target=node`.

**AI Agents Involved:** Code Generator Agent.

---

## 13. Automatic Testing

**Description:** Generates and executes tests against every endpoint using sandbox or user-supplied live credentials.

**Purpose:** Validates that generated code actually works, not just that it compiles.

**Priority:** P0

**Workflow:** Testing Agent generates request fixtures from schema examples → executes in sandboxed runner → captures response, status, latency → compares against expected schema → pass/fail recorded.

**Edge Cases:** Endpoints requiring pre-existing data (e.g., a valid order ID) → dependency-aware test ordering; destructive endpoints (DELETE) → dry-run/mock mode by default; rate-limited APIs → throttled test execution.

**Future Improvements:** Property-based/fuzz testing for schema edge cases; contract testing against future spec changes.

**Dependencies:** Testing Agent, sandbox executor, Dependency Analysis.

**UI Components:** `TestRunPanel`, `EndpointTestResultRow`, `TestCoverageChart`.

**Backend Components:** `test_generator`, `sandbox_runner`, `test_result_analyzer`.

**Database Tables:** `test_runs`, `test_results`.

**API Endpoints:** `POST /api/v1/projects/{id}/test`, `GET /api/v1/projects/{id}/test-runs/{run_id}`.

**AI Agents Involved:** Testing Agent.

---

## 14. Error Recovery / Self-Healing

**Description:** When a test fails, the Testing Agent diagnoses the failure and feeds a repair prompt back to the Code Generator Agent, which patches the code; the cycle repeats up to a bounded retry count.

**Purpose:** Reduces human debugging effort; core differentiator of the "self-healing" pipeline.

**Priority:** P0

**Workflow:** Failure captured (stack trace, response body, status) → root-cause classification (auth error / schema mismatch / rate limit / network) → targeted patch generated → re-test → success or escalate to human review after max retries (default 3).

**Edge Cases:** Flaky third-party API causing false failures → retry with backoff before treating as a real failure; unfixable failures (API bug, undocumented breaking change) → clearly surfaced to user rather than looping forever.

**Future Improvements:** Learn common failure→fix patterns across projects to speed future repairs.

**Dependencies:** Testing Agent, Code Generator Agent, Retry Mechanism.

**UI Components:** `SelfHealingTimeline`, `DiffViewer` (before/after patch).

**Backend Components:** `failure_classifier`, `repair_orchestrator`.

**Database Tables:** `repair_attempts`.

**API Endpoints:** `GET /api/v1/projects/{id}/test-runs/{run_id}/repairs`.

**AI Agents Involved:** Testing Agent, Code Generator Agent.

---

## 15. Retry Mechanism

**Description:** Configurable retry policy (exponential backoff + jitter) applied both to (a) live HTTP calls made by generated SDKs and (b) agent-level repair loops.

**Purpose:** Resilience against transient failures at runtime and during generation.

**Priority:** P1

**Workflow:** Generated client code includes a `RetryPolicy` (max attempts, backoff base, retryable status codes 429/500/502/503); agent-level retries bounded separately and logged.

**Edge Cases:** Non-idempotent operations (POST) should not be blindly retried without idempotency keys — flagged and handled explicitly.

**Future Improvements:** Circuit breaker pattern for consistently failing endpoints.

**Dependencies:** Code Generator Agent, Testing Agent.

**UI Components:** `RetryPolicyConfigForm`.

**Backend Components:** `retry_policy_engine`.

**Database Tables:** `retry_configs`.

**API Endpoints:** `PUT /api/v1/projects/{id}/settings/retry-policy`.

**AI Agents Involved:** Code Generator Agent.

---

## 16. Logging

**Description:** Structured logs for every agent action, tool call, HTTP request/response (with secrets redacted), and system event.

**Purpose:** Debuggability, auditability, compliance.

**Priority:** P0

**Workflow:** Central structured logger (JSON) → shipped to OpenTelemetry collector → stored/queryable in Grafana Loki or equivalent.

**Edge Cases:** Secret redaction must be airtight across all log paths; extremely verbose LLM traces need sampling to control cost/volume.

**Future Improvements:** Natural-language log search ("show me why endpoint X failed yesterday").

**Dependencies:** OpenTelemetry, LangSmith.

**UI Components:** `LogViewer`, `LogFilterBar`.

**Backend Components:** `logging_middleware`, `redaction_service`.

**Database Tables:** `logs` (or external log store reference).

**API Endpoints:** `GET /api/v1/projects/{id}/logs`.

**AI Agents Involved:** All (log emission is cross-cutting).

---

## 17. Execution History

**Description:** Full timeline of every workflow run, agent step, generated artifact, and test result for a project.

**Purpose:** Enables audit, rollback, and understanding of "what happened and why."

**Priority:** P1

**Workflow:** Every workflow run persisted with immutable step records; UI renders as a chronological, filterable timeline.

**Edge Cases:** Very long-running projects with hundreds of runs → pagination and search required.

**Future Improvements:** Diff-based history view comparing any two runs.

**Dependencies:** Orchestrator, database.

**UI Components:** `HistoryTimeline`, `RunComparisonView`.

**Backend Components:** `history_service`.

**Database Tables:** `workflow_runs`, `agent_events`.

**API Endpoints:** `GET /api/v1/projects/{id}/history`.

**AI Agents Involved:** N/A (data aggregation layer).

---

## 18. Versioning

**Description:** Every generated artifact (spec, code, SDK) is versioned; users can compare and roll back to prior versions.

**Purpose:** Supports iterative refinement and safe regeneration.

**Priority:** P1

**Workflow:** Semantic versioning applied on each successful generation; diffs computed and stored; rollback restores prior artifact set as "active."

**Edge Cases:** Partial regeneration (only Node.js SDK) must not silently version-bump unrelated Python artifacts.

**Future Improvements:** Branching (like git) for experimental regenerations.

**Dependencies:** Export Agent, database.

**UI Components:** `VersionHistoryPanel`, `RollbackButton`.

**Backend Components:** `versioning_service`.

**Database Tables:** `artifact_versions`.

**API Endpoints:** `GET /api/v1/projects/{id}/versions`, `POST /api/v1/projects/{id}/versions/{version_id}/rollback`.

**AI Agents Involved:** N/A.

---

## 19. Project Workspace

**Description:** Persistent container for a single integration effort — holds spec, auth config, generated code, tests, history, and settings.

**Purpose:** Organizational unit that lets teams manage multiple integrations in parallel.

**Priority:** P0

**Workflow:** Created on first upload; supports team membership, sharing, and archiving.

**Edge Cases:** Concurrent edits by multiple team members → optimistic locking with conflict resolution UI.

**Future Improvements:** Project templates/cloning.

**Dependencies:** Auth/RBAC system.

**UI Components:** `ProjectDashboard`, `ProjectSettingsPanel`, `TeamMembersList`.

**Backend Components:** `project_service`, `rbac_service`.

**Database Tables:** `projects`, `project_members`, `organizations`.

**API Endpoints:** `POST /api/v1/projects`, `GET /api/v1/projects`, `GET /api/v1/projects/{id}`.

**AI Agents Involved:** N/A.

---

## 20. Integration Export

**Description:** Unified export flow letting users choose one or more output formats (SDK/Client/Docker/GitHub/MCP/Docs) in a single action.

**Purpose:** Single point of delivery for the entire pipeline's output.

**Priority:** P0

**Workflow:** User selects export targets → Export Agent assembles each in parallel → zipped bundle or direct integrations (e.g., GitHub push) delivered.

**Edge Cases:** Partial export failures (e.g., GitHub push fails due to auth) should not block other successful exports.

**Future Improvements:** Scheduled/automatic re-export on spec change.

**Dependencies:** Export Agent, all generation features.

**UI Components:** `ExportWizard`.

**Backend Components:** `export_orchestrator`.

**Database Tables:** `exports`.

**API Endpoints:** `POST /api/v1/projects/{id}/export`.

**AI Agents Involved:** Export Agent.

---

## 21. MCP Tool Generation

**Description:** Converts the API into an MCP-compatible tool server/manifest so LLM agents can call it directly as a tool.

**Purpose:** Bridges traditional REST APIs into the agentic tool-calling ecosystem without manual wrapping.

**Priority:** P0

**Workflow:** Endpoint schemas converted to MCP tool definitions (name, description, input schema) → lightweight MCP server generated (stdio or SSE transport) → manifest validated against MCP spec.

**Edge Cases:** APIs with 200+ endpoints exceeding practical tool-count limits for a single agent → tool grouping/namespacing; endpoints unsafe for autonomous agent use (destructive) flagged as `requires_confirmation`.

**Future Improvements:** Auto-generated tool descriptions optimized for LLM tool-selection accuracy (evaluated via test harness).

**Dependencies:** Endpoint Discovery, Code Generator Agent.

**UI Components:** `MCPToolPreview`, `ToolSafetyFlagEditor`.

**Backend Components:** `mcp_generator`.

**Database Tables:** `mcp_tools`.

**API Endpoints:** `POST /api/v1/projects/{id}/export/mcp`.

**AI Agents Involved:** Code Generator Agent, Export Agent.

---

## 22. GitHub Export

**Description:** Pushes the generated project directly to a new or existing GitHub repository, including CI/CD workflow files.

**Purpose:** Integrates output directly into the user's normal development lifecycle.

**Priority:** P1

**Workflow:** User authorizes GitHub OAuth app → selects target repo/org → Export Agent commits generated files, README, and `.github/workflows/*.yml` via GitHub API.

**Edge Cases:** Repo name collisions; insufficient OAuth scopes; large file pushes exceeding API limits (use Git Data API for tree/blob creation).

**Future Improvements:** Auto-PR on subsequent regenerations instead of direct push to main.

**Dependencies:** GitHub OAuth, Export Agent.

**UI Components:** `GitHubExportModal`, `RepoSelector`.

**Backend Components:** `github_export_service`.

**Database Tables:** `github_exports`.

**API Endpoints:** `POST /api/v1/projects/{id}/export/github`.

**AI Agents Involved:** Export Agent.

---

## 23. Docker Generation

**Description:** Generates a `Dockerfile` and optional `docker-compose.yml` to run the integration (e.g., FastAPI wrapper or MCP server) as a container.

**Purpose:** Enables immediate, reproducible deployment.

**Priority:** P1

**Workflow:** Export Agent selects base image per language, adds dependency installation layer, exposes correct port, sets non-root user, healthcheck.

**Edge Cases:** Native dependency compilation requirements (e.g., cryptography libs) → multi-stage build fallback.

**Future Improvements:** Distroless/slim image variants for production hardening.

**Dependencies:** Export Agent, Code Generation.

**UI Components:** `DockerExportOption`.

**Backend Components:** `docker_generator`.

**Database Tables:** `generated_files`.

**API Endpoints:** `POST /api/v1/projects/{id}/export/docker`.

**AI Agents Involved:** Export Agent.

---

## 24. CI/CD Generation

**Description:** Generates GitHub Actions workflows for lint, type-check, test, build, and (optionally) publish/deploy steps.

**Purpose:** Ensures generated projects are production-ready from day one, not just locally runnable.

**Priority:** P2

**Workflow:** Export Agent selects workflow template matching language target and export options (e.g., adds Docker build/push step if Docker export selected).

**Edge Cases:** Secrets required in CI (API keys) → documented as required GitHub repo secrets, never embedded.

**Future Improvements:** GitLab CI / CircleCI template variants.

**Dependencies:** GitHub Export, Docker Generation.

**UI Components:** `CICDPreviewPanel`.

**Backend Components:** `cicd_template_generator`.

**Database Tables:** `generated_files`.

**API Endpoints:** `POST /api/v1/projects/{id}/export/cicd`.

**AI Agents Involved:** Export Agent.

---

## 25. Monitoring Dashboard

**Description:** Real-time dashboard showing workflow run status, test pass rates, agent token/cost usage, and system health.

**Purpose:** Operational visibility for both individual projects and platform-wide usage.

**Priority:** P1

**Workflow:** Metrics emitted via OpenTelemetry/Prometheus → aggregated → visualized in Grafana-backed or native dashboard views.

**Edge Cases:** High-cardinality metrics (per-endpoint) requiring careful aggregation to avoid dashboard/storage overload.

**Future Improvements:** Configurable alerting (Slack/email) on failure-rate thresholds or cost overruns.

**Dependencies:** Prometheus, Grafana, OpenTelemetry.

**UI Components:** `MetricsDashboard`, `CostUsageChart`, `AgentHealthPanel`.

**Backend Components:** `metrics_service`.

**Database Tables:** `usage_metrics` (or Prometheus TSDB, referenced not duplicated).

**API Endpoints:** `GET /api/v1/projects/{id}/metrics`, `GET /api/v1/org/{org_id}/metrics`.

**AI Agents Involved:** N/A (observability layer, cross-cutting).
