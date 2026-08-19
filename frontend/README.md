# Frontend (`web-bff`)

Next.js 14 (App Router) web application — Phase 5 scaffold. See `Project-docs/UIUX.md`
and `Project-docs/API.md` for design and API contracts.

## Stack

- Next.js 14 + React 18 + TypeScript (strict)
- Tailwind CSS with design tokens from `UIUX.md §1.2` (light/dark via CSS variables)
- ESLint (`next/core-web-vitals`) + Prettier

## Structure

```
src/
  app/
    layout.tsx              Root layout, mounts <Providers>
    providers.tsx           ToastProvider + AuthProvider (client)
    page.tsx               Landing → redirects to /dashboard if authed
    auth/login/page.tsx    Login / register (posts to /auth/login, /auth/register)
    dashboard/page.tsx      Project list + create-project modal
    projects/[id]/page.tsx  Project detail with Overview/Spec tabs (+ placeholders)
  components/              Button, Card, Table, Modal, Toast, Tabs, StatusBadge, AppShell
  lib/
    api.ts                 Typed fetch wrapper (bearer + silent refresh + error envelope)
    auth.ts                Token storage (access in memory, refresh in cookie)
    auth-context.tsx       React auth context (useAuth)
    types.ts               Shared API contract types
    cn.ts                  className combiner
middleware.ts             Gates /dashboard and /projects behind the refresh cookie
```

## Auth model

- `POST /auth/login` and `/auth/register` return `access_token` + `refresh_token` (JSON).
- Access token is held in memory (sessionStorage); refresh token is kept in a cookie
  (`aw_refresh`) so `middleware.ts` can gate protected routes and the refresh flow can
  exchange it via `POST /auth/refresh`.
- On a 401, `apiFetch` performs a single silent refresh and retries. (A true HttpOnly
  refresh cookie would require the backend to set it on login — future work.)

## Dev

```bash
cd frontend
npm install
cp .env.example .env.local
npm run dev        # :3000, API rewrites to http://localhost:8000/api/v1
```

## Verify

```bash
npm run lint
npm run typecheck
```
