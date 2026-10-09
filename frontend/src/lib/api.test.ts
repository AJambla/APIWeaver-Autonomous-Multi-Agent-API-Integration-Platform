import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { apiFetch, apiFetchAll, mapSettled, resolveEndpoint } from './api';

const json = (body: unknown, status = 200) =>
  new Response(JSON.stringify(body), { status, headers: { 'content-type': 'application/json' } });

describe('apiFetch token refresh', () => {
  beforeEach(() => {
    sessionStorage.setItem('access_token', 'expired');
    sessionStorage.setItem('refresh_token', 'refresh-1');
  });
  afterEach(() => {
    vi.unstubAllGlobals();
    sessionStorage.clear();
  });

  it('redeems the single-use refresh token once for concurrent 401s', async () => {
    let refreshCalls = 0;
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      if (url.endsWith('/auth/refresh')) {
        refreshCalls += 1;
        await new Promise(r => setTimeout(r, 10));
        return json({ access_token: 'fresh', refresh_token: 'refresh-2' });
      }
      const auth = new Headers(init?.headers).get('Authorization');
      return auth === 'Bearer fresh' ? json({ ok: true }) : json({ error: { message: 'expired' } }, 401);
    });
    vi.stubGlobal('fetch', fetchMock);

    const results = await Promise.all([apiFetch('/a'), apiFetch('/b'), apiFetch('/c')]);

    expect(results).toEqual([{ ok: true }, { ok: true }, { ok: true }]);
    expect(refreshCalls).toBe(1);
    expect(sessionStorage.getItem('refresh_token')).toBe('refresh-2');
  });

  it('surfaces a failed retry as an error instead of returning the error body', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async (input: RequestInfo | URL) => {
        const url = String(input);
        if (url.endsWith('/auth/refresh')) return json({ access_token: 'fresh', refresh_token: 'r2' });
        if (url.endsWith('/thing') && sessionStorage.getItem('access_token') === 'fresh') {
          return json({ error: { message: 'Not allowed' } }, 403);
        }
        return json({}, 401);
      }),
    );

    await expect(apiFetch('/thing')).rejects.toThrow('Not allowed');
  });
});

describe('resolveEndpoint', () => {
  it('accepts paths that already carry the API prefix', () => {
    expect(resolveEndpoint('/api/v1/projects/1/exports/2/download').url).toMatch(
      /\/api\/v1\/projects\/1\/exports\/2\/download$/,
    );
    expect(resolveEndpoint('/projects').url).toMatch(/\/api\/v1\/projects$/);
  });
});

describe('apiFetchAll', () => {
  afterEach(() => vi.unstubAllGlobals());

  it('follows next_cursor until has_more is false', async () => {
    const pages: Record<string, unknown> = {
      first: { data: [1, 2], pagination: { next_cursor: 'c2', has_more: true, limit: 2 } },
      c2: { data: [3], pagination: { next_cursor: null, has_more: false, limit: 2 } },
    };
    vi.stubGlobal(
      'fetch',
      vi.fn(async (input: RequestInfo | URL) => {
        const cursor = new URL(String(input)).searchParams.get('cursor');
        return json(pages[cursor ?? 'first']);
      }),
    );

    await expect(apiFetchAll<number>('/projects?limit=2')).resolves.toEqual([1, 2, 3]);
  });
});

describe('mapSettled', () => {
  it('never runs more than `limit` tasks at once and keeps result order', async () => {
    let inFlight = 0;
    let peak = 0;
    const results = await mapSettled([1, 2, 3, 4, 5, 6], 2, async n => {
      inFlight += 1;
      peak = Math.max(peak, inFlight);
      await new Promise(r => setTimeout(r, 5));
      inFlight -= 1;
      if (n === 4) throw new Error('boom');
      return n * 10;
    });
    expect(peak).toBe(2);
    expect(results.map(r => (r.status === 'fulfilled' ? r.value : 'x'))).toEqual([10, 20, 30, 'x', 50, 60]);
  });
});
