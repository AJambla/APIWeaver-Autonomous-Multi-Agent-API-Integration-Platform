/**
 * Monaco is loaded from this origin, never from a CDN (`audit M7`).
 *
 * `@monaco-editor/react` defaults its loader to
 * `https://cdn.jsdelivr.net/npm/monaco-editor@<ver>/min/vs`, which runs third-party
 * JavaScript inside an origin that holds the access and refresh tokens in
 * `sessionStorage`: one substituted or compromised CDN file reads both. It also made a
 * same-origin-only CSP impossible, which is why `nginx.conf` had to stay header-free.
 *
 * Pointing `paths.vs` at `/monaco/vs` keeps the runtime itself out of the bundle:
 * `scripts/copy-monaco.mjs` copies the package's prebuilt `min/vs` into `public/monaco/vs`,
 * Vite's static directory, so it is still fetched on demand — from `vite dev` as well as from
 * the built site — and only from here, at the version in the lockfile rather than whatever the
 * CDN default happened to pin.
 *
 * Imported for its side effect, before any `<Editor>` mounts.
 */
import { loader } from '@monaco-editor/react';

loader.config({ paths: { vs: '/monaco/vs' } });
