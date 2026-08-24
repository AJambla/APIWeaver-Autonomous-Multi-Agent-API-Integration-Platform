/** Shared API contract types mirroring the backend Pydantic models (Project-docs/API.md). */

export type ProjectStatus =
  | "draft"
  | "planning"
  | "building"
  | "testing"
  | "ready"
  | "failed";

export interface Project {
  id: string;
  name: string;
  status: ProjectStatus;
  organization_id: string;
  created_at: string;
  endpoint_count?: number;
  last_run_status?: string | null;
}

export interface Page<T> {
  data: T[];
  pagination: {
    next_cursor: string | null;
    has_more: boolean;
    limit: number;
  };
}

export interface AuthTokens {
  access_token: string;
  refresh_token: string;
  expires_in: number;
  token_type: string;
}

export interface User {
  id: string;
  email: string;
  full_name: string;
  organization_id: string;
  organization_name?: string;
}

export interface ApiErrorBody {
  error: {
    code: string;
    message: string;
    details?: Array<{ field: string; issue: string }>;
    request_id?: string;
  };
}

export class ApiError extends Error {
  code: string;
  status: number;
  details?: Array<{ field: string; issue: string }>;

  constructor(status: number, body: ApiErrorBody) {
    super(body.error.message);
    this.name = "ApiError";
    this.status = status;
    this.code = body.error.code;
    this.details = body.error.details;
  }
}

// ---------------------------------------------------------------------------
// Monitoring (backend/app/schemas/monitoring.py)
// ---------------------------------------------------------------------------

export interface ProjectMetrics {
  avg_time_to_integration_minutes: number | null;
  test_pass_rate: number | null;
  monthly_token_spend_usd: number | null;
  total_workflow_runs: number;
  successful_exports: number;
}

export interface OrgMetrics {
  projects_count: number;
  total_workflow_runs: number;
  avg_test_pass_rate: number | null;
  monthly_token_spend_usd: number;
  tier_limit_workflow_triggers_hour: number;
}

// ---------------------------------------------------------------------------
// Dependency graph (backend/app/schemas/dependency_graph.py)
// ---------------------------------------------------------------------------

export type DependencyRelationship =
  | "requires_auth"
  | "requires_created_resource"
  | "optional_precedes";

export interface DependencyNode {
  id: string;
  label: string;
  method: string;
  path: string;
  is_destructive: boolean;
}

export interface DependencyEdge {
  from_id: string;
  to_id: string;
  relationship: DependencyRelationship;
}

export interface DependencyGraph {
  nodes: DependencyNode[];
  edges: DependencyEdge[];
}

// ---------------------------------------------------------------------------
// Workflows (backend/app/schemas/workflow.py)
// ---------------------------------------------------------------------------

export type WorkflowStatus =
  | "queued"
  | "running"
  | "paused_for_approval"
  | "completed"
  | "failed"
  | "cancelled";

export interface WorkflowRun {
  id: string;
  status: WorkflowStatus | string;
  current_node: string | null;
  progress_percent: number;
  started_at: string | null;
  completed_at: string | null;
  total_tokens_used: number;
}

export const WORKFLOW_STAGES = [
  "plan",
  "generate",
  "test",
  "export",
] as const;
export type WorkflowStage = (typeof WORKFLOW_STAGES)[number];

// ---------------------------------------------------------------------------
// Testing (backend/app/schemas/testing.py)
// ---------------------------------------------------------------------------

export type TestStatus = "passed" | "failed" | "skipped" | "running" | "pending";

export interface TestRun {
  id: string;
  status: string;
  environment: string;
  summary: {
    passed: number;
    failed: number;
    skipped: number;
    total: number;
  } | null;
  created_at: string;
}

export interface TestResult {
  id: string;
  test_run_id: string;
  endpoint_id: string | null;
  status: TestStatus | string;
  status_code: number | null;
  latency_ms: number | null;
  error: string | null;
  response_snapshot: Record<string, any> | null;
  stack_trace: string | null;
}

export interface RepairAttempt {
  id: string;
  test_result_id: string;
  attempt_number: number;
  failure_classification: string | null;
  diff_summary: Record<string, any> | null;
  outcome: string | null;
}

// ---------------------------------------------------------------------------
// History & Versioning (backend/app/schemas/history.py)
// ---------------------------------------------------------------------------

export interface HistoryItem {
  id: string;
  workflow_run_id: string;
  status: string;
  stages: string[];
  started_at: string;
  completed_at: string | null;
  total_tokens: number;
}

export interface VersionItem {
  id: string;
  artifact_type: string;
  version_number: number;
  created_at: string;
  diff_ref: string | null;
  is_active: boolean;
}

// ---------------------------------------------------------------------------
// Auth config (backend/app/schemas/auth_config.py)
// ---------------------------------------------------------------------------

export interface AuthConfig {
  scheme: string;
  config_json: Record<string, any>;
  verified: boolean;
}

// ---------------------------------------------------------------------------
// Org API keys (backend/app/schemas/api_key.py)
// ---------------------------------------------------------------------------

export interface APIKey {
  id: string;
  prefix: string;
  name: string;
  project_id: string | null;
  created_at: string;
  expires_at: string | null;
  revoked_at: string | null;
}

// ---------------------------------------------------------------------------
// Retry policy (frontend-only stub — backend endpoint not implemented)
// ---------------------------------------------------------------------------

export interface RetryPolicy {
  max_attempts: number;
  backoff_base_seconds: number;
  retryable_status_codes: number[];
}
