const API_PREFIX = '/api/v1';

let isRefreshing = false;
let failedQueue: Array<{
  resolve: (token: string) => void;
  reject: (error: any) => void;
}> = [];

const processQueue = (error: any, token: string | null = null) => {
  failedQueue.forEach(prom => {
    if (error) {
      prom.reject(error);
    } else {
      prom.resolve(token!);
    }
  });
  failedQueue = [];
};

export async function apiFetch<T = any>(
  endpoint: string,
  options: RequestInit = {}
): Promise<T> {
  const token = sessionStorage.getItem('access_token');
  
  const headers: Record<string, string> = {
    'Content-Type': 'application/json',
    ...(options.headers as Record<string, string>),
  };

  if (token) {
    headers['Authorization'] = `Bearer ${token}`;
  }

  const url = endpoint.startsWith('http') ? endpoint : `${API_PREFIX}${endpoint}`;

  let response = await fetch(url, {
    ...options,
    headers,
  });

  if (response.status === 401 && !endpoint.includes('/auth/login') && !endpoint.includes('/auth/refresh')) {
    if (isRefreshing) {
      return new Promise((resolve, reject) => {
        failedQueue.push({ resolve, reject });
      }).then(newToken => {
        headers['Authorization'] = `Bearer ${newToken}`;
        return fetch(url, { ...options, headers }).then(res => res.json());
      });
    }

    isRefreshing = true;

    try {
      const refreshRes = await fetch(`${API_PREFIX}/auth/refresh`, {
        method: 'POST',
        credentials: 'include',
      });

      if (!refreshRes.ok) {
        throw new Error('Refresh token expired');
      }

      const data = await refreshRes.json();
      const newToken = data.access_token;
      sessionStorage.setItem('access_token', newToken);
      isRefreshing = false;
      processQueue(null, newToken);

      headers['Authorization'] = `Bearer ${newToken}`;
      const retryRes = await fetch(url, { ...options, headers });
      if (!retryRes.ok) {
        throw new Error(await retryRes.text());
      }
      return retryRes.json();
    } catch (err) {
      isRefreshing = false;
      processQueue(err, null);
      sessionStorage.removeItem('access_token');
      window.location.href = '/login';
      throw err;
    }
  }

  if (!response.ok) {
    const errorBody = await response.text();
    let message = response.statusText;
    try {
      const parsed = JSON.parse(errorBody);
      message = parsed.detail || parsed.message || message;
    } catch {
      message = errorBody || message;
    }
    throw new Error(message);
  }

  if (response.status === 204) {
    return {} as T;
  }

  return response.json();
}
