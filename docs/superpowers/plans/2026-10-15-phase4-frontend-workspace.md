# Phase 4: Frontend Workspace Realignment Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Realign `Frontend/src/pages/ProjectWorkspace.tsx` and supporting workspace components to the 5 outcome-driven stages (`Ingest` → `Dependencies` → `MCP Tools` → `Verify` → `MCP Result`), implement FastMCP tool and Monaco code inspection with deterministic safety badges, build the ephemeral Docker sandbox verification terminal with Level 3 Live Testing opt-in modal, and render the honest multi-tier Verification Summary card and bundle export.

**Architecture:** Decompose the monolithic `ProjectWorkspace.tsx` into modular, focused components under `Frontend/src/pages/workspace/` (`IngestTab`, `DependenciesTab`, `McpToolsTab`, `VerifyTab`, `LiveTestModal`, `McpResultTab`, `VerificationCard`). State is hoisted cleanly in `ProjectWorkspace.tsx` and shared via props. Target language for all MCP tooling and config snippets is Python FastMCP.

**Tech Stack:** React 18, TypeScript 5.5, Tailwind CSS 3.4, Monaco Editor (`@monaco-editor/react`), Lucide React icons, React Router v7, Vite.

**Spec:** `API_WEAVER_REFACTORING_BLUEPRINT.md §8`

## Global Constraints

- Stage IDs must strictly be `'ingest' | 'dependencies' | 'tools' | 'verify' | 'result' | 'logs' | 'settings'`.
- Naming of verification states must be honest and explicit: `STATIC: PASS`, `SANDBOX: PASS`, `LIVE: NOT RUN` (or `PASS` / `FAIL`), `Overall Status: SANDBOX VERIFIED` (or `STATIC VERIFIED`, `LIVE VERIFIED`). Never claim "Production Verified" unless live verification was run.
- Safety badges must be deterministic: `[SAFE]` (emerald), `[STATE-CHANGING]` (amber), and `[DESTRUCTIVE ⚠]` (rose) with clear `requires_confirmation` indicators.
- Live testing must NEVER expose raw API keys/tokens in the UI logs, generated code, or query params; Level 3 credentials are typed into the opt-in modal and securely transmitted.
- FastMCP configuration snippet must follow Claude Desktop / Cursor JSON specification.
- No legacy export types (SDK, FastAPI, Docker, GitHub, CI/CD) rendered in Stage 5 — exclusively FastMCP Server bundle (`apiweaver-mcp.zip`) and verification documentation (`VERIFICATION_REPORT.md` / `manifest.json`).

## Review Focus

1. **Empty/New Project State:** When a user navigates to a newly created project with no spec uploaded yet, subsequent stages (`dependencies`, `tools`, `verify`, `result`) must display friendly empty states pointing back to `Ingest` without crashing or throwing null property errors.
2. **Missing or Incomplete Verification Data:** If tests haven't been run or a test run errored early, `McpResultTab` must display `SANDBOX: NOT RUN` or `STATIC ONLY` instead of failing to render.
3. **Monaco Editor Loading and Tab Switching:** Switching between `tools.py`, `server.py`, `test_mcp.py`, and `manifest.json` in the Monaco inspector must smoothly update the model without memory leaks or race conditions.
4. **Live Test Network Modal Safeguards:** Opt-in to Level 3 Live Testing must require explicit confirmation checkboxes when destructive endpoints are detected.
5. **Real-time SSE Streaming vs REST Fallback:** The Verify terminal must display incoming SSE `agent.thought` and `workflow.progress` events in real-time, and seamlessly hydrate past logs on refresh.

---

### Task 1: Realign Stepper, Types, and Stage Navigation

**Files:**
- Modify: `Frontend/src/lib/types.ts`
- Modify: `Frontend/src/pages/ProjectWorkspace.tsx`
- Create: `Frontend/src/pages/workspace/IngestTab.tsx`
- Create: `Frontend/src/pages/workspace/DependenciesTab.tsx`

**Interfaces:**
- Consumes: `TabId = 'ingest' | 'dependencies' | 'tools' | 'verify' | 'result' | 'logs' | 'settings'`
- Produces: `CORE_STEPS` with labels `[1. Ingest]`, `[2. Dependencies]`, `[3. MCP Tools]`, `[4. Verify]`, `[5. MCP Result]`, and extracted `IngestTab` and `DependenciesTab` subcomponents.

- [ ] **Step 1: Update `Frontend/src/lib/types.ts` with FastMCP and Verification interfaces**
  Add `McpToolSummary`, `VerificationReportData`, `GeneratedFileMeta`, and `FileContentResult`.
- [ ] **Step 2: Update `TabId` and `CORE_STEPS` in `ProjectWorkspace.tsx`**
  Map `upload` → `ingest`, `plan` → `dependencies`, `build` → `tools`, `test` → `verify`, `export` → `result`. Add backward-compatible URL query param normalization so `?tab=upload` or `?tab=build` redirect to `ingest` / `tools`.
- [ ] **Step 3: Extract `IngestTab.tsx` and `DependenciesTab.tsx` into `Frontend/src/pages/workspace/`**
  Encapsulate the spec upload, raw Monaco editor, URL fetcher, and dependency graph topology view into dedicated components.
- [ ] **Step 4: Verify TypeScript build**
  Run: `npm --prefix Frontend run build`
  Expected: Clean build with 0 type errors.
- [ ] **Step 5: Commit**
  ```bash
  git add Frontend/src/lib/types.ts Frontend/src/pages/ProjectWorkspace.tsx Frontend/src/pages/workspace/IngestTab.tsx Frontend/src/pages/workspace/DependenciesTab.tsx
  git commit -m "feat(workspace): realign stepper to 5-stage MCP pipeline"
  ```

---

### Task 2: Implement Stage 3 (MCP Tools & Monaco Code Inspector)

**Files:**
- Create: `Frontend/src/pages/workspace/McpToolsTab.tsx`
- Modify: `Frontend/src/pages/ProjectWorkspace.tsx`

**Interfaces:**
- Consumes: Project ID, endpoints list, `/projects/{id}/files`, `/projects/{id}/files/{file_id}/content`, `/projects/{id}/generate`
- Produces: FastMCP tools list with safety badges (`[SAFE]`, `[STATE-CHANGING]`, `[DESTRUCTIVE ⚠]`), typed input schema viewer, file selector tab (`tools.py`, `server.py`, `test_mcp.py`, `manifest.json`), and integrated Monaco code editor.

- [ ] **Step 1: Create `McpToolsTab.tsx`**
  - Render list of synthesized FastMCP tools with `MethodChip`, path, description, and input schema preview.
  - Implement deterministic safety badges:
    - Safe: `[SAFE]` in emerald border/text (`bg-emerald-500/10 text-emerald-400 border-emerald-500/30`).
    - State-changing: `[STATE-CHANGING]` in amber (`bg-amber-500/10 text-amber-400 border-amber-500/30`).
    - Destructive: `[DESTRUCTIVE ⚠]` in rose (`bg-rose-500/10 text-rose-400 border-rose-500/30`) with `requires_confirmation: true` badge.
  - Render file selector tabs for generated FastMCP files (`tools.py`, `server.py`, `test_mcp.py`, `manifest.json`).
  - Embed Monaco Editor displaying the selected file's content in dark theme with syntax highlighting and read-only mode (or live edit).
  - Add "Generate / Re-synthesize FastMCP Server" trigger button with running progress bar and token spend indicator.
- [ ] **Step 2: Mount `McpToolsTab` in `ProjectWorkspace.tsx`**
  Wire `activeTab === 'tools'` to render `McpToolsTab` with active run state and project endpoints.
- [ ] **Step 3: Verify TypeScript build**
  Run: `npm --prefix Frontend run build`
  Expected: Build passes.
- [ ] **Step 4: Commit**
  ```bash
  git add Frontend/src/pages/workspace/McpToolsTab.tsx Frontend/src/pages/ProjectWorkspace.tsx
  git commit -m "feat(workspace): add FastMCP tools inspector with safety badges and Monaco code viewer"
  ```

---

### Task 3: Implement Stage 4 (Verification Runner & Level 3 Live Testing Modal)

**Files:**
- Create: `Frontend/src/pages/workspace/VerifyTab.tsx`
- Create: `Frontend/src/pages/workspace/LiveTestModal.tsx`
- Modify: `Frontend/src/pages/ProjectWorkspace.tsx`

**Interfaces:**
- Consumes: Test runs, SSE workflow events, `/projects/{id}/test`, `/projects/{id}/test-runs/latest`
- Produces: Live ephemeral Docker execution terminal, Pre-Sandbox Static Check status indicators (AST parse, JSON Schema validation), Pytest result summary, and Level 3 Live Testing modal with credential inputs and safety confirmation gates.

- [ ] **Step 1: Create `LiveTestModal.tsx`**
  - Modal with API Base URL input, Authentication scheme selection (Bearer Token, API Key header, Basic Auth), sensitive credential input (password masked).
  - Safety Warning: Notice stating "Level 3 Live Testing executes real HTTP requests against your target API".
  - If project has destructive endpoints, display warning banner and require checkbox: "I understand destructive endpoints (DELETE/PUT) will execute against the target system".
  - "Run Live Verification" submit button calling `/projects/{id}/test` with `environment: 'live'`.
- [ ] **Step 2: Create `VerifyTab.tsx`**
  - Verification controls: Environment selector (`Sandbox (Synthetic Mocks)` vs `Live API`), Run Verification button.
  - Pre-Sandbox Static Gate badge: Displays `AST Syntax: PASS` and `MCP Schema: PASS` before container execution.
  - Live Docker Execution Terminal (SSE streamed logs, agent thoughts, pytest output) with auto-scroll and copy.
  - Test Results table with status, status code, latency, and failure classifier / repair attempt indicator.
  - "Launch Level 3 Live Verification..." button triggering `LiveTestModal`.
- [ ] **Step 3: Mount `VerifyTab` and `LiveTestModal` in `ProjectWorkspace.tsx`**
  Connect `activeTab === 'verify'` to `VerifyTab`.
- [ ] **Step 4: Verify TypeScript build**
  Run: `npm --prefix Frontend run build`
  Expected: Build passes.
- [ ] **Step 5: Commit**
  ```bash
  git add Frontend/src/pages/workspace/VerifyTab.tsx Frontend/src/pages/workspace/LiveTestModal.tsx Frontend/src/pages/ProjectWorkspace.tsx
  git commit -m "feat(workspace): implement sandbox verification runner and live testing modal"
  ```

---

### Task 4: Implement Stage 5 (MCP Result Tab with Honest Verification Summary)

**Files:**
- Create: `Frontend/src/pages/workspace/McpResultTab.tsx`
- Create: `Frontend/src/pages/workspace/VerificationReportModal.tsx`
- Modify: `Frontend/src/pages/ProjectWorkspace.tsx`

**Interfaces:**
- Consumes: Project ID, latest test run, exports list, `/projects/{id}/export/mcp`, `/projects/{id}/exports/{export_id}/download`
- Produces: Honest Verification Summary card (`Level 1: STATIC`, `Level 2: SANDBOX`, `Level 3: LIVE`, `Overall Status`), ZIP bundle download button, Verification Report modal (MD / JSON), and Claude Desktop configuration snippet with copy button.

- [ ] **Step 1: Create `VerificationReportModal.tsx`**
  - Displays full `VERIFICATION_REPORT.md` and structured JSON with per-tool status, safety badges, and repair history.
- [ ] **Step 2: Create `McpResultTab.tsx`**
  - Honest Multi-tier Verification Summary card:
    - `Level 1 (Static Verification): PASS (x/x tools valid)`
    - `Level 2 (Sandbox Verification): PASS (x/x mock tests)` (or `NOT RUN`)
    - `Level 3 (Live API Verification): NOT RUN` (or `PASS` / `FAIL`)
    - `Overall Status: SANDBOX VERIFIED` (badge in emerald or amber; never "Production Verified" unless live passed).
  - Primary Action: `[Download MCP Bundle (ZIP)]` triggering `/projects/{id}/export/mcp` and direct ZIP download (`apiweaver-mcp.zip`).
  - Secondary Action: `[View Verification Report]` opening `VerificationReportModal`.
  - Claude Desktop Configuration snippet:
    ```json
    {
      "mcpServers": {
        "<project-slug>": {
          "command": "python",
          "args": ["-m", "server"],
          "env": {
            "API_KEY": "your_api_key_here"
          }
        }
      }
    }
    ```
    with one-click "Copy Config" button and instructions on pasting into `claude_desktop_config.json` or Cursor Settings.
- [ ] **Step 3: Mount `McpResultTab` in `ProjectWorkspace.tsx`**
  Replace legacy export grid with `McpResultTab`.
- [ ] **Step 4: Verify TypeScript build**
  Run: `npm --prefix Frontend run build`
  Expected: Build passes.
- [ ] **Step 5: Commit**
  ```bash
  git add Frontend/src/pages/workspace/McpResultTab.tsx Frontend/src/pages/workspace/VerificationReportModal.tsx Frontend/src/pages/ProjectWorkspace.tsx
  git commit -m "feat(workspace): implement MCP result stage with verification summary and config snippet"
  ```

---

### Task 5: AgentsPage Streamlining & Full Frontend Verification

**Files:**
- Modify: `Frontend/src/pages/AgentsPage.tsx`
- Run: Full build and lint checks

**Interfaces:**
- Consumes: `AgentsPage.tsx`
- Produces: Updated pipeline overview reflecting FastMCP synthesis and verification pipeline.

- [ ] **Step 1: Update pipeline description in `AgentsPage.tsx`**
  Update `PIPELINE` items in `AgentsPage.tsx` from generic SDK/Docker exporters to FastMCP Server Synthesis, Deterministic Safety Analysis, Pre-Sandbox Static Check, Docker Sandbox Verification, and Verified MCP Server Bundle Export.
- [ ] **Step 2: Run frontend build and tests**
  Run: `npm --prefix Frontend run build`
  Run: `npm --prefix Frontend test` (if vitest suites exist)
- [ ] **Step 3: Commit**
  ```bash
  git add Frontend/src/pages/AgentsPage.tsx
  git commit -m "feat(agents): align agent pipeline overview with FastMCP architecture"
  ```
