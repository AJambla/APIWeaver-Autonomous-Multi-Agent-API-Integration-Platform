export interface User {
  id: string;
  email: string;
  full_name?: string;
  role?: string;
}

export interface AuthTokens {
  access_token: string;
  refresh_token?: string;
  token_type?: string;
}

export interface OrganizationMembership {
  organization_id: string;
  organization_name: string;
  role: string;
}

export interface MeResponse {
  user: User;
  organizations: OrganizationMembership[];
}

export interface Pagination {
  next_cursor: string | null;
  has_more: boolean;
  limit: number;
}

export interface Page<T> {
  data: T[];
  pagination: Pagination;
}

export interface Project {
  id: string;
  name: string;
  status: string;
  organization_id: string;
  created_at: string;
  updated_at: string;
  archived_at?: string | null;
}

export interface ProjectSummary extends Project {
  endpoint_count: number;
  last_run_status: string | null;
}

export interface OrgMetrics {
  projects_count: number;
  total_workflow_runs: number;
  avg_test_pass_rate: number | null;
  monthly_token_spend_usd: number;
  tier_limit_workflow_triggers_hour: number;
}

export interface ProjectMetrics {
  avg_time_to_integration_minutes: number | null;
  test_pass_rate: number | null;
  monthly_token_spend_usd: number | null;
  total_workflow_runs: number;
  successful_exports: number;
}

export interface ApiSpec {
  id: string;
  title: string | null;
  base_url: string | null;
  raw_normalized: Record<string, unknown>;
  confidence_score: number | null;
}

export interface UploadResponse {
  document_id: string;
  status: string;
  workflow_run_id: string | null;
  api_spec_id: string | null;
  endpoints_discovered: number | null;
}

export interface SpecEndpoint {
  id: string;
  method: string;
  path: string;
  summary: string | null;
  deprecated: boolean;
  confidence_score: number | null;
}

export interface HistoryItem {
  id: string;
  workflow_run_id: string;
  status: string;
  stages: string[];
  started_at: string;
  completed_at: string | null;
  total_tokens: number;
}

export interface WorkflowRunInfo {
  id: string;
  status: string;
  current_node: string | null;
  progress_percent: number;
  started_at: string | null;
  completed_at: string | null;
  total_tokens_used: number;
}

export interface ToolCall {
  id: number;
  agent_event_id: number;
  tool_name: string;
  arguments: Record<string, unknown> | null;
  result: Record<string, unknown> | null;
  duration_ms: number | null;
}

export interface AgentEventLog {
  id: string;
  event_type: string;
  agent_name: string | null;
  payload: Record<string, unknown> | null;
  created_at: string | null;
}

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
  relationship: string;
}

export interface DependencyGraph {
  nodes: DependencyNode[];
  edges: DependencyEdge[];
}

export interface TriggerWorkflowResponse {
  workflow_run_id: string;
  status: string;
}

export interface TestRunTriggerResponse {
  test_run_id: string;
  status: string;
}

export interface TestResultItem {
  id: string;
  test_run_id: string;
  endpoint_id: string | null;
  status: string;
  status_code: number | null;
  latency_ms: number | null;
  error: string | null;
}

export interface TestRunSummary {
  test_run_id: string;
  status: string;
  summary: { total?: number; passed?: number; failed?: number; skipped?: number };
  results: TestResultItem[];
}

export interface ExportRecord {
  id: string;
  export_type: string;
  status: string;
  created_at: string | null;
}

export interface MCPExportResponse {
  mcp_manifest_url: string;
  tools_generated: number;
  flagged_destructive: number;
}

export interface ApiKey {
  id: string;
  prefix: string;
  name: string;
  project_id: string | null;
  created_at: string;
  expires_at: string | null;
  revoked_at: string | null;
}

export interface ApiKeyCreated {
  id: string;
  key: string;
  prefix: string;
  name: string;
  project_id: string | null;
  expires_at: string | null;
}

export interface GitHubStatus {
  connected: boolean;
  github_username: string | null;
  installations: Array<{ id: number; account: string; account_type: string }>;
}

export interface WorkflowEvent {
  id: string;
  timestamp: string;
  level: 'info' | 'success' | 'warn' | 'error';
  message: string;
  agent?: string;
}

export const PROJECT_STATUSES = ['draft', 'planning', 'building', 'testing', 'ready', 'failed', 'archived'] as const;
export const RUN_STATUSES = ['queued', 'running', 'paused_for_approval', 'completed', 'failed', 'cancelled'] as const;
