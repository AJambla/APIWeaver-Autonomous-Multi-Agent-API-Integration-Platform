# Medium Security Remediation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Remediate all 11 Medium severity security vulnerabilities identified in the Phase A audit report (`SECURITY_AUDIT_REPORT.md`): SEC-MED-01 through SEC-MED-11.

**Architecture:** Minimal, surgical changes following the Ponytail principle (shortest working diff, reuse existing helpers, zero unnecessary bloat). Each fix addresses the vulnerability at the root cause, is verified with automated tests, and is committed atomically to git.

**Tech Stack:** Python 3.12, FastAPI, SQLAlchemy 2.0 (asyncio), Redis, Docker, Celery, React/TypeScript.

**Spec:** [`SECURITY_AUDIT_REPORT.md`](file:///C:/Users/WELCOME/.gemini/antigravity/brain/c6255af6-f700-44a9-a050-680515723f79/SECURITY_AUDIT_REPORT.md)

## Global Constraints
- **Atomic Commits:** Commit to git immediately after each issue is implemented and verified.
- **Ponytail Mode:** Shortest working diff, reuse existing codebase helpers (`hash_opaque_token`, `fence_untrusted`, `validate_storage_key`), no bloat.
- **TDD & Verification:** Every fix must be verified with automated tests before committing.
- **Secrets Protection:** Never print or commit unmasked secrets.
- **Local Testing Only:** No external requests or attacks against outside systems.

---

## Tasks

### Task 1: SEC-MED-01: Dual Refresh Token Delivery Exposes Session to XSS via `sessionStorage`
- **Files to Modify:**
  - `Frontend/src/lib/api.ts`
  - `Frontend/src/lib/auth-context.tsx`
  - `backend/app/schemas/auth.py`
  - `backend/app/api/v1/auth.py`
  - `backend/tests/test_auth.py`
- **Steps:**
  - [ ] In `Frontend/src/lib/api.ts`, remove `sessionStorage.setItem('refresh_token', data.refresh_token)` in `rotateTokens()`. Keep only `access_token` in `sessionStorage`. Call `/auth/refresh` sending `{}` with `credentials: 'same-origin'`.
  - [ ] In `Frontend/src/lib/auth-context.tsx`, remove `sessionStorage.setItem('refresh_token', tokens.refresh_token)` in `login()` and `register()`. In `logout()`, send `{}` body to `/auth/logout`.
  - [ ] In `backend/app/schemas/auth.py`, make `refresh_token: str | None = Field(default=None, max_length=512)` in `RefreshRequest` and `TokenResponse`.
  - [ ] In `backend/tests/test_auth.py`, add a test verifying that `POST /api/v1/auth/refresh` with an empty body `{}` and `refresh_token` cookie rotates successfully.
  - [ ] Run `pytest backend/tests/test_auth.py` to verify all 36 tests pass.
  - [ ] Commit: `fix(security): remove refresh token from sessionStorage and rely on HttpOnly cookie (SEC-MED-01)`.

---

### Task 2: SEC-MED-02: Corporate NAT / Shared IP Lockout for JWT Users
- **Files to Modify:**
  - `backend/app/core/ratelimit.py:154-175`
  - `backend/tests/test_access_control.py` (or new test)
- **Steps:**
  - [ ] In `backend/app/core/ratelimit.py`, update `_client_identity(request: Request) -> str` to inspect `Authorization: Bearer <token>`. If present, extract token and return `f"jwt:{hash_opaque_token(token)[:16]}"`.
  - [ ] Write a test in `backend/tests/test_access_control.py` confirming two distinct JWT tokens from the same client IP get isolated rate limit identities.
  - [ ] Run `pytest backend/tests/test_access_control.py`.
  - [ ] Commit: `fix(security): key rate limiter on JWT bearer tokens to prevent NAT lockout (SEC-MED-02)`.

---

### Task 3: SEC-MED-05: Unredacted Response Headers & Tokens Forwarded to LLMs
- **Files to Modify:**
  - `backend/app/services/sandbox_runners/runner.py:219-232`
  - `backend/tests/test_testing.py`
- **Steps:**
  - [ ] In `backend/app/services/sandbox_runners/runner.py`, update `_snapshot()` to sanitize sensitive response and request headers (`authorization`, `set-cookie`, `cookie`, `x-api-key`, `x-auth-token`, `proxy-authorization`) replacing values with `[REDACTED]`.
  - [ ] Add a unit test verifying sensitive headers are masked before test snapshots are recorded.
  - [ ] Run `pytest backend/tests/test_testing.py`.
  - [ ] Commit: `fix(security): scrub sensitive auth headers from LLM test snapshots (SEC-MED-05)`.

---

### Task 4: SEC-MED-06 & SEC-MED-07: Magic Bytes File Validation & PDF Extraction Ceilings
- **Files to Modify:**
  - `backend/app/services/document_parser.py`
  - `backend/tests/test_documents.py`
- **Steps:**
  - [ ] In `backend/app/services/document_parser.py`:
    - Check magic bytes for PDF (`b"%PDF-"`). Raise `ValidationError("Invalid PDF: magic bytes missing")` if header is not present.
    - In `_extract_pdf`: enforce `MAX_PDF_PAGES = 100` and `MAX_EXTRACTED_CHARS = 500_000`. Stop extraction if either ceiling is reached.
  - [ ] In `backend/tests/test_documents.py`, add tests for:
    - Masqueraded file (e.g. executable/text with `.pdf` extension) is rejected.
    - Page ceiling and character count limit halts extraction cleanly.
  - [ ] Run `pytest backend/tests/test_documents.py`.
  - [ ] Commit: `fix(security): validate upload magic bytes and enforce PDF page ceilings (SEC-MED-06, SEC-MED-07)`.

---

### Task 5: SEC-MED-08: Unfenced Error and Endpoint Fields in Agent Prompts
- **Files to Modify:**
  - `backend/app/workflows/agents/test_agent.py`
  - `backend/app/workflows/agents/code_agent.py`
  - `backend/tests/test_prompt_injection.py`
- **Steps:**
  - [ ] In `backend/app/workflows/agents/test_agent.py` and `code_agent.py`, wrap untrusted fields (`error`, `method`, `path`) using `fence_untrusted()` before interpolating into repair prompts.
  - [ ] Add a test in `backend/tests/test_prompt_injection.py` confirming injection delimiters in `error` or `path` are enclosed in fences.
  - [ ] Run `pytest backend/tests/test_prompt_injection.py`.
  - [ ] Commit: `fix(security): fence error and endpoint parameters in LLM prompts (SEC-MED-08)`.

---

### Task 6: SEC-MED-09: Unbounded Server-Sent Events (SSE) Stream Connection Holding
- **Files to Modify:**
  - `backend/app/api/v1/events.py`
  - `backend/tests/test_events.py`
- **Steps:**
  - [ ] In `backend/app/api/v1/events.py`, limit concurrent active SSE streams per client identity (max 5) using Redis key `ratelimit:sse:conn:{identity}` with `INCR` / `DECR`.
  - [ ] Raise HTTP 429 `RateLimitExceededError` if limit is exceeded.
  - [ ] In generator `finally:` block, decrement connection count.
  - [ ] Add test in `backend/tests/test_events.py` verifying the 6th concurrent stream returns 429.
  - [ ] Run `pytest backend/tests/test_events.py`.
  - [ ] Commit: `fix(security): enforce concurrency limits on SSE event streams (SEC-MED-09)`.

---

### Task 7: SEC-MED-10: Incomplete Health Probe / Readiness Contract
- **Files to Modify:**
  - `backend/app/api/v1/health.py`
  - `backend/tests/test_health.py`
- **Steps:**
  - [ ] In `backend/app/api/v1/health.py`, update `/readyz` to check Qdrant and S3 connectivity alongside PostgreSQL and Redis with 1s timeout.
  - [ ] In `backend/tests/test_health.py`, update readiness tests to assert all 4 dependencies are verified.
  - [ ] Run `pytest backend/tests/test_health.py`.
  - [ ] Commit: `fix(security): complete /readyz probe contract with Qdrant and S3 checks (SEC-MED-10)`.

---

### Task 8: SEC-MED-11: Celery Worker Tasks Orphaned on Workflow Cancellation
- **Files to Modify:**
  - `backend/app/workflows/dispatch.py`
  - `backend/app/api/v1/workflows.py`
  - `backend/tests/test_workflows.py`
- **Steps:**
  - [ ] In `backend/app/workflows/dispatch.py`, store Celery `task_id` in Redis: `await redis_client.set(f"workflow:celery_task:{run.id}", task.id, ex=86400)`.
  - [ ] In `backend/app/api/v1/workflows.py:cancel_workflow_run`, retrieve `celery_task_id` from Redis, and invoke `celery_app.control.revoke(task_id, terminate=True, signal="SIGTERM")` if present.
  - [ ] In `backend/tests/test_workflows.py`, add a test verifying cancellation issues a Celery revoke.
  - [ ] Run `pytest backend/tests/test_workflows.py`.
  - [ ] Commit: `fix(security): revoke celery worker tasks on workflow cancellation (SEC-MED-11)`.

---

### Task 9: SEC-MED-03: Sandbox Live Mode DNS Rebinding SSRF
- **Files to Modify:**
  - `backend/app/services/sandbox_service.py`
  - `backend/tests/test_sandbox_executor.py`
- **Steps:**
  - [ ] In `backend/app/services/sandbox_service.py`, capture the validated IP from `resolve_public_address`.
  - [ ] Pass `extra_hosts={target_host: pinned_ip}` to Docker container run configuration to pin the hostname to the validated IP.
  - [ ] Add a unit test verifying `extra_hosts` pinning is configured.
  - [ ] Run `pytest backend/tests/test_sandbox_executor.py`.
  - [ ] Commit: `fix(security): pin resolved IP in sandbox live network mode to prevent DNS rebinding (SEC-MED-03)`.

---

### Task 10: SEC-MED-04: Supply Chain Vulnerabilities (Dependency Version Floors)
- **Files to Modify:**
  - `backend/pyproject.toml`
- **Steps:**
  - [ ] In `backend/pyproject.toml`, bump minimum version floors for vulnerable packages: `starlette >= 0.46.2`, `pypdf >= 6.21.4`, `aiohttp >= 3.14.4`, `filelock >= 4.2.1`, `certifi >= 2024.7.4`.
  - [ ] Verify test suite passes with updated constraints.
  - [ ] Commit: `fix(security): upgrade vulnerable dependencies to patched versions (SEC-MED-04)`.
