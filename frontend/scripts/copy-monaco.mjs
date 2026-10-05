// Copies the prebuilt Monaco runtime into `public/` so the editor loads from this origin
// instead of cdn.jsdelivr.net (`audit M7`, see `src/lib/monaco.ts`).
//
// `public/` is Vite's static directory: files there are served as-is by `vite dev` and
// copied into `dist/` by `vite build`, so one location covers both modes. Putting this under
// `dist/` instead would only work in production, and `vite dev` answers an unknown path with
// `index.html` and a 200 — the editor would receive HTML where it expects JavaScript.
//
// The source is what `npm ci` installed, so the shipped runtime is the version the lockfile
// pins rather than the loader's baked-in CDN default. Fails the build if the package is
// missing: a silent skip here would put the editor back on a CDN with no test to notice.
import { access, cp, mkdir, readFile, rm } from 'node:fs/promises';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const root = path.dirname(path.dirname(fileURLToPath(import.meta.url)));
const packageDir = path.join(root, 'node_modules', 'monaco-editor');
const source = path.join(packageDir, 'min', 'vs');
const target = path.join(root, 'public', 'monaco', 'vs');

const { version } = JSON.parse(await readFile(path.join(packageDir, 'package.json'), 'utf8'));
await access(source);
await rm(target, { recursive: true, force: true });
await mkdir(path.dirname(target), { recursive: true });
await cp(source, target, { recursive: true });

console.log(`copied monaco-editor@${version} runtime to public/monaco/vs`);
