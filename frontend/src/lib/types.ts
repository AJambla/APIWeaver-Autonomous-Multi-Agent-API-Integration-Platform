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

export interface Project {
  id: string;
  name: string;
  description?: string;
  status: string;
  created_at: string;
  updated_at?: string;
  repository_url?: string;
  progress?: number;
}

export interface WorkflowEvent {
  id: string;
  timestamp: string;
  level: 'info' | 'success' | 'warn' | 'error';
  message: string;
  agent?: string;
}
