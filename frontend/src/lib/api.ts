const API_PREFIX = '/api/v1';

let isRefreshing = false;
let failedQueue: Array<{
  resolve: (token: string) => void;
  reject: (error: unknown) => void;
}> = [];

const processQueue = (error: unknown, token: string | null = null) => {
  failedQueue.forEach(request => {
    if (error) {
      request.reject(error);
    } else {
      request.resolve(token!);
    }
  });
  failedQueue = [];
};

/** The request `endpoint` resolves to, and whether this origin owns it.
 *
 * An endpoint is either a path under `API_PREFIX` or, for a caller that really does mean
 * another origin, an absolute URL. Resolving through `URL` rather than trusting the
 * `startsWith` test keeps both meanings honest: that test is also true of a path like
 * `http-fault/list` and false of a protocol-relative `//host/path`.
 */
function resolveEndpoint(endpoint: string): { url: string; sameOrigin: boolean } {
  const candidate = endpoint.startsWith('http') ? endpoint : `${API_PREFIX}${endpoint}`;
  try {
    const url = new URL(candidate, window.location.origin);
    return { url: url.href, sameOrigin: url.origin === window.location.origin };
  } catch {
    // An address this unparsable is not one to hand a token to.
    return { url: candidate, sameOrigin: false };
  }
}

export async function apiFetch<T = unknown>(
  endpoint: string,
  options: RequestInit = {}
): Promise<T> {
  const { url, sameOrigin } = resolveEndpoint(endpoint);
  const token = sessionStorage.getItem('access_token');
  const headers = new Headers(options.headers);

  // The one place the token leaves the bag, so no call site can forget the origin rule.
  const authorize = (value: string) => {
    if (sameOrigin) headers.set('Authorization', `Bearer ${value}`);
  };

  if (!(options.body instanceof FormData) && !headers.has('Content-Type')) {
    headers.set('Content-Type', 'application/json');
  }

  if (token) {
    authorize(token);
  }

  const response = await fetch(url, { ...options, headers });

  if (response.status === 401 && !endpoint.includes('/auth/login') && !endpoint.includes('/auth/refresh')) {
    if (isRefreshing) {
      return new Promise<string>((resolve, reject) => {
        failedQueue.push({ resolve, reject });
      }).then(newToken => {
        authorize(newToken);
        return fetch(url, { ...options, headers }).then(res => res.json() as Promise<T>);
      });
    }

    isRefreshing = true;

    try {
      const refreshToken = sessionStorage.getItem('refresh_token');
      if (!refreshToken) {
        throw new Error('Your session has expired. Please sign in again.');
      }

      const refreshResponse = await fetch(`${API_PREFIX}/auth/refresh`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ refresh_token: refreshToken }),
      });

      if (!refreshResponse.ok) {
        throw new Error('Your session has expired. Please sign in again.');
      }

      const data = await refreshResponse.json() as { access_token: string; refresh_token: string };
      sessionStorage.setItem('access_token', data.access_token);
      sessionStorage.setItem('refresh_token', data.refresh_token);
      isRefreshing = false;
      processQueue(null, data.access_token);

      authorize(data.access_token);
      const retryResponse = await fetch(url, { ...options, headers });
      if (!retryResponse.ok) {
        throw new Error(await retryResponse.text());
      }
      return retryResponse.json() as Promise<T>;
    } catch (error) {
      isRefreshing = false;
      processQueue(error);
      sessionStorage.removeItem('access_token');
      sessionStorage.removeItem('refresh_token');
      window.location.href = '/login';
      throw error;
    }
  }

  if (!response.ok) {
    const errorBody = await response.text();
    let message = response.statusText;
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
      message = errorBody || message;
    }
    throw new Error(message);
  }

  if (response.status === 204) {
    return {} as T;
  }

  return response.json() as Promise<T>;
}
