const API_PREFIX = '/api/v1';

/** The refresh in flight, shared by every caller in this tab.
 *
 * Refresh tokens are single use, and the backend revokes the whole token family when one
 * is presented twice. Two concurrent 401s (say, the event stream reconnecting while a
 * logs request retries) must therefore wait on one rotation instead of each redeeming
 * the same token.
 */
let refreshInFlight: Promise<string> | null = null;

function clearSessionAndRedirect(): void {
  sessionStorage.removeItem('access_token');
  sessionStorage.removeItem('refresh_token');
  window.location.href = '/login';
}

/** Thrown when the server rejected the refresh token: the session is really over. */
export class SessionExpiredError extends Error {
  constructor() {
    super('Your session has expired. Please sign in again.');
    this.name = 'SessionExpiredError';
  }
}

async function rotateTokens(): Promise<string> {
  const refreshToken = sessionStorage.getItem('refresh_token');
  if (!refreshToken) {
    throw new SessionExpiredError();
  }
  // A network error propagates as-is (not a SessionExpiredError): the session survives it.
  const refreshResponse = await fetch(`${API_PREFIX}/auth/refresh`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ refresh_token: refreshToken }),
  });
  if ([400, 401, 403].includes(refreshResponse.status)) {
    throw new SessionExpiredError();
  }
  if (!refreshResponse.ok) {
    // 429/5xx: the server could not answer, which says nothing about the token.
    throw new Error('The server could not refresh your session. Please retry.');
  }
  const data = (await refreshResponse.json()) as { access_token: string; refresh_token: string };
  sessionStorage.setItem('access_token', data.access_token);
  sessionStorage.setItem('refresh_token', data.refresh_token);
  return data.access_token;
}

/** Rotate the refresh token into a fresh pair. Concurrent callers share one rotation;
 * where the Web Locks API exists it also serializes rotations across tabs. Only a
 * rejected refresh token ends the session; a network blip or a 5xx used to log the user
 * out as well. */
export function refreshAccessToken(): Promise<string> {
  if (refreshInFlight) return refreshInFlight;
  const tokenBefore = sessionStorage.getItem('access_token');
  const run = async (): Promise<string> => {
    // Another holder of the lock may already have rotated; use its token if so.
    const current = sessionStorage.getItem('access_token');
    if (current && current !== tokenBefore) return current;
    return rotateTokens();
  };
  const locks = typeof navigator !== 'undefined' ? navigator.locks : undefined;
  refreshInFlight = (locks ? locks.request('apiweaver-token-refresh', run) : run())
    .catch((error: unknown) => {
      if (error instanceof SessionExpiredError) clearSessionAndRedirect();
      throw error;
    })
    .finally(() => {
      refreshInFlight = null;
    });
  return refreshInFlight;
}

/** True when the path part of `endpoint` has a `.` or `..` segment, encoded or not. */
export function hasDotSegment(endpoint: string): boolean {
  const path = endpoint.split(/[?#]/, 1)[0];
  return path.split('/').some((segment) => {
    let decoded = segment;
    try {
      decoded = decodeURIComponent(segment);
    } catch {
      // A malformed escape is not a dot segment; the server will reject it.
    }
    return decoded === '.' || decoded === '..';
  });
}

/** The request `endpoint` resolves to, and whether this origin owns it.
 *
 * An endpoint is either a path under `API_PREFIX` or, for a caller that really does mean
 * another origin, an absolute URL. Resolving through `URL` rather than trusting the
 * `startsWith` test keeps both meanings honest: that test is also true of a path like
 * `http-fault/list` and false of a protocol-relative `//host/path`.
 */
export function resolveEndpoint(endpoint: string): { url: string; sameOrigin: boolean } {
  if (hasDotSegment(endpoint)) {
    // `new URL` would resolve `..` and send the bearer token to wherever it led.
    throw new Error('Refusing a request path with "." or ".." segments.');
  }
  const candidate =
    endpoint.startsWith('http') || endpoint.startsWith(`${API_PREFIX}/`)
      ? endpoint
      : `${API_PREFIX}${endpoint}`;
  try {
    const url = new URL(candidate, window.location.origin);
    return { url: url.href, sameOrigin: url.origin === window.location.origin };
  } catch {
    // An address this unparsable is not one to hand a token to.
    return { url: candidate, sameOrigin: false };
  }
}

/** The API's error envelope (`{error: {message, details}}`), FastAPI's `detail`, or text. */
async function errorFrom(response: Response): Promise<Error> {
  const errorBody = await response.text();
  let message = response.statusText || `Request failed (${response.status})`;
  try {
    const parsed = JSON.parse(errorBody) as {
      detail?: string;
      message?: string;
      error?: { message?: string; details?: Array<{ field?: string; issue?: string }> };
    };
    message = parsed.error?.message || parsed.detail || parsed.message || message;
    const details = (parsed.error?.details ?? [])
      .map(d => [d.field, d.issue].filter(Boolean).join(': '))
      .filter(s => s.length > 0);
    if (details.length > 0) {
      message = `${message} ${details.join(' | ')}`;
    }
  } catch {
    // A proxy's HTML error page (e.g. 413 from nginx) is not worth showing verbatim.
    if (response.status === 413) message = 'The file is larger than the server accepts.';
    else if (errorBody && !errorBody.trimStart().startsWith('<')) message = errorBody;
  }
  const error = new Error(message) as Error & { status?: number };
  error.status = response.status;
  return error;
}

/** fetch with the bearer token, one transparent refresh-and-retry on 401. */
async function authorizedFetch(endpoint: string, options: RequestInit = {}): Promise<Response> {
  const { url, sameOrigin } = resolveEndpoint(endpoint);
  const headers = new Headers(options.headers);

  // The one place the token leaves the bag, so no call site can forget the origin rule.
  const authorize = (value: string | null) => {
    if (sameOrigin && value) headers.set('Authorization', `Bearer ${value}`);
  };

  if (options.body && !(options.body instanceof FormData) && !headers.has('Content-Type')) {
    headers.set('Content-Type', 'application/json');
  }
  if (!headers.has('X-Correlation-ID')) {
    const traceId = typeof crypto !== 'undefined' && crypto.randomUUID ? crypto.randomUUID() : Math.random().toString(36).slice(2);
    headers.set('X-Correlation-ID', traceId);
  }
  authorize(sessionStorage.getItem('access_token'));

  const response = await fetch(url, { ...options, headers });
  const isAuthCall = endpoint.includes('/auth/login') || endpoint.includes('/auth/refresh');
  if (response.status !== 401 || isAuthCall || !sameOrigin) {
    return response;
  }

  authorize(await refreshAccessToken());
  const retry = await fetch(url, { ...options, headers });
  if (retry.status === 401) {
    clearSessionAndRedirect();
  }
  return retry;
}

export async function apiFetch<T = unknown>(endpoint: string, options: RequestInit = {}): Promise<T> {
  const response = await authorizedFetch(endpoint, options);
  if (!response.ok) {
    throw await errorFrom(response);
  }
  if (response.status === 204 || response.headers.get('content-length') === '0') {
    return {} as T;
  }
  return response.json() as Promise<T>;
}

/** Binary downloads (export bundles) with the same auth, refresh and error handling. */
export async function apiFetchBlob(
  endpoint: string,
  options: RequestInit = {},
): Promise<{ blob: Blob; filename: string | null }> {
  const response = await authorizedFetch(endpoint, options);
  if (!response.ok) {
    throw await errorFrom(response);
  }
  const disposition = response.headers.get('content-disposition') || '';
  const match = /filename\*?=(?:UTF-8'')?"?([^";]+)"?/i.exec(disposition);
  return { blob: await response.blob(), filename: match ? decodeURIComponent(match[1]) : null };
}

/** Every item of a cursor-paginated collection (`{data, pagination}`), up to `maxItems`. */
export async function apiFetchAll<T>(endpoint: string, maxItems = 500, options: RequestInit = {}): Promise<T[]> {
  const items: T[] = [];
  let cursor: string | null = null;
  do {
    const sep = endpoint.includes('?') ? '&' : '?';
    const page: { data: T[]; pagination?: { next_cursor: string | null; has_more: boolean } } =
      await apiFetch(cursor ? `${endpoint}${sep}cursor=${encodeURIComponent(cursor)}` : endpoint, options);
    items.push(...page.data);
    cursor = page.pagination?.has_more ? page.pagination.next_cursor : null;
  } while (cursor && items.length < maxItems);
  return items.slice(0, maxItems);
}

/** `Promise.allSettled(items.map(fn))` with at most `limit` requests in flight, so a
 * page that fans out per project stays inside the org's rate limit. */
export async function mapSettled<I, O>(
  items: I[],
  limit: number,
  fn: (item: I) => Promise<O>,
): Promise<PromiseSettledResult<O>[]> {
  const results: PromiseSettledResult<O>[] = new Array(items.length);
  let next = 0;
  const workers = Array.from({ length: Math.min(limit, items.length) }, async () => {
    while (next < items.length) {
      const index = next++;
      try {
        results[index] = { status: 'fulfilled', value: await fn(items[index]) };
      } catch (reason) {
        results[index] = { status: 'rejected', reason };
      }
    }
  });
  await Promise.all(workers);
  return results;
}
