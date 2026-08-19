import { ApiError, type ApiErrorBody, type Page, type Project } from "./types";
import { getAccessToken, refreshTokens } from "./auth";

/**
 * Typed fetch wrapper for the APIWeaver v1 API.
 *
 * - Prefixes absolute paths with the API base (`/api/v1` in the browser, the
 *   configured URL on the server).
 * - Attaches the bearer token and decodes the standard error envelope into `ApiError`.
 * - On a 401 with a refresh token, performs a single silent refresh and retries.
 */

const API_BASE = "/api/v1";

export interface RequestOptions extends Omit<RequestInit, "body"> {
  body?: unknown;
  /** Override the API base (used in server components). */
  baseUrl?: string;
}

function buildUrl(path: string, baseUrl?: string): string {
  const base = baseUrl ?? API_BASE;
  if (path.startsWith("http")) return path;
  const clean = path.startsWith("/") ? path : `/${path}`;
  return `${base}${clean}`;
}

async function parseError(res: Response): Promise<ApiError> {
  let body: ApiErrorBody | null = null;
  try {
    body = (await res.json()) as ApiErrorBody;
  } catch {
    body = null;
  }
  if (body && body.error) {
    return new ApiError(res.status, body);
  }
  return new ApiError(res.status, {
    error: {
      code: "UNKNOWN",
      message: `Request failed with status ${res.status}`,
      request_id: res.headers.get("X-Request-ID") ?? undefined,
    },
  });
}

async function request<T>(path: string, options: RequestOptions): Promise<T> {
  const { body, baseUrl, headers, ...rest } = options;
  const token = getAccessToken();

  const init: RequestInit = {
    ...rest,
    headers: {
      ...(body !== undefined ? { "Content-Type": "application/json" } : {}),
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
      ...(headers as Record<string, string> | undefined),
    },
    body: body !== undefined ? JSON.stringify(body) : undefined,
  };

  const res = await fetch(buildUrl(path, baseUrl), init);

  if (!res.ok) {
    throw await parseError(res);
  }
  if (res.status === 204) {
    return undefined as T;
  }
  return (await res.json()) as T;
}

export async function apiFetch<T>(
  path: string,
  options: RequestOptions = {},
): Promise<T> {
  try {
    return await request<T>(path, options);
  } catch (err) {
    if (
      err instanceof ApiError &&
      err.status === 401 &&
      !(options as RequestOptions & { __retried?: boolean }).__retried
    ) {
      const refreshed = await refreshTokens(options.baseUrl);
      if (refreshed) {
        return request<T>(path, {
          ...options,
          ...({ __retried: true } as object),
        });
      }
    }
    throw err;
  }
}

// Convenience re-exports.
export type { Page, Project };
