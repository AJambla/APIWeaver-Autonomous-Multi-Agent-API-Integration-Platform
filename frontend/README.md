# Frontend

Vite + React 18 SPA for API Weaver. See `Project-docs/UIUX.md`
and `Project-docs/API.md` for design and API contracts.

## Stack

- Vite 5 + React 18 + TypeScript (strict)
- react-router-dom 6 (client-side routing)
- Tailwind CSS (dark theme via design tokens from `UIUX.md §1.2`)
- ESLint + Prettier

## Structure

```
index.html                 Vite entry
src/
  main.tsx                 Mounts <App />
  App.tsx                  Routes; unauthenticated visits to protected
                           pages redirect to /login
  pages/                   Landing, Login, Register, Dashboard, Specs,
                           SpecDetail, ProjectWorkspace, Overview, Runs,
                           RunDetail, Agents, Settings
  components/
    DashboardLayout.tsx    Authenticated app shell (nav + user header)
    ui.tsx                 Shared UI primitives (cards, badges, banners,
                           skeletons, page headers)
  lib/
    api.ts                 Typed fetch wrapper (bearer + silent refresh;
                           API_PREFIX /api/v1)
    auth.ts                Token storage (access in sessionStorage,
                           refresh in cookie)
    auth-context.tsx       React auth context (useAuth)
    use-workflow-events.ts EventSource hook for workflow run SSE (kept for
                           upcoming live-events wiring)
    format.ts              Formatting helpers
    types.ts               Shared API contract types
vite.config.ts             Dev server on :3000; proxies /api/v1 to
                           http://localhost:8000
```

## Auth model

- `POST /auth/login` and `/auth/register` return `access_token` + `refresh_token` (JSON).
- The access token is kept in sessionStorage; the refresh token is kept in a cookie
  (`aw_refresh`) so the refresh flow can exchange it via `POST /auth/refresh`.
- On a 401, `apiFetch` performs a single silent refresh and retries. (A true HttpOnly
  refresh cookie would require the backend to set it on login — future work.)
- Route protection is client-side only — the dev server has no auth middleware.

## Dev

```bash
cd frontend
npm ci
npm run dev        # :3000, /api/v1 proxied to http://localhost:8000
```

## Verify

```bash
npm run lint
npm run build      # tsc + vite build
```
