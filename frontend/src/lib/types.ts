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
