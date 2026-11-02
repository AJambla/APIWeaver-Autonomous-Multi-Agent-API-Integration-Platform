# Medium Security Remediation Implementation Plan

> **Status:** COMPLETED. All 11 Medium security issues (SEC-MED-01 through SEC-MED-11) resolved and verified with automated test suites.

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

## Tasks & Execution Summary

### Task 1: SEC-MED-01: Dual Refresh Token Delivery Exposes Session to XSS via `sessionStorage`
- **Files Modified:**
  - `Frontend/src/lib/api.ts`
  - `Frontend/src/lib/auth-context.tsx`
  - `backend/app/schemas/auth.py`
  - `backend/tests/test_auth.py`
- **Completed Steps:**
  - [x] In `Frontend/src/lib/api.ts`, removed `sessionStorage.setItem('refresh_token', data.refresh_token)` in `rotateTokens()`. Keep only `access_token` in `sessionStorage`. Call `/auth/refresh` sending `{}` with `credentials: 'same-origin'`.
  - [x] In `Frontend/src/lib/auth-context.tsx`, removed `sessionStorage.setItem('refresh_token', tokens.refresh_token)` in `login()` and `register()`. In `logout()`, send `{}` body to `/auth/logout`.
  - [x] In `backend/app/schemas/auth.py`, made `refresh_token: str | None = Field(default=None, max_length=512)` in `RefreshRequest` and `TokenResponse`.
  - [x] In `backend/tests/test_auth.py`, added a test verifying that `POST /api/v1/auth/refresh` with an empty body `{}` and `refresh_token` cookie rotates successfully.
  - [x] Ran `pytest backend/tests/test_auth.py` to verify tests pass.
  - [x] **Committed:** `b4f68e5 fix(security): remove refresh token from sessionStorage and rely on HttpOnly cookie (SEC-MED-01)`

---

### Task 2: SEC-MED-02: Corporate NAT / Shared IP Lockout for JWT Users
- **Files Modified:**
  - `backend/app/core/ratelimit.py`
  - `backend/tests/test_client_ip.py`
- **Completed Steps:**
  - [x] In `backend/app/core/ratelimit.py`, updated `_client_identity(request: Request) -> str` to inspect `Authorization: Bearer <token>`. If present, extract token and return `f"jwt:{hash_opaque_token(token)[:16]}"`. Credential paths still fall back to `_ip_identity`.
  - [x] Wrote unit tests in `backend/tests/test_client_ip.py` confirming two distinct JWT tokens from the same client IP get isolated rate limit identities.
  - [x] Ran `pytest backend/tests/test_client_ip.py`.
  - [x] **Committed:** `f12296e fix(security): key rate limiter on JWT bearer tokens to prevent NAT lockout (SEC-MED-02)`

---

### Task 3: SEC-MED-05: Unredacted Response Headers & Tokens Forwarded to LLMs
- **Files Modified:**
  - `backend/app/services/sandbox_runners/runner.py`
  - `backend/tests/test_testing.py`
- **Completed Steps:**
  - [x] In `backend/app/services/sandbox_runners/runner.py`, updated `_snapshot()` to sanitize sensitive response and request headers (`authorization`, `set-cookie`, `cookie`, `x-api-key`, `x-auth-token`, `proxy-authorization`) replacing values with `[REDACTED]`.
  - [x] Added unit tests in `backend/tests/test_testing.py` verifying sensitive headers are masked before test snapshots are recorded.
  - [x] Ran `pytest backend/tests/test_testing.py`.
  - [x] **Committed:** `67ce4e6 fix(security): scrub sensitive auth headers from LLM test snapshots (SEC-MED-05)`

---

### Task 4: SEC-MED-06 & SEC-MED-07: Magic Bytes File Validation & PDF Extraction Ceilings
- **Files Modified:**
  - `backend/app/services/document_parser.py`
  - `backend/tests/test_documents.py`
- **Completed Steps:**
  - [x] In `backend/app/services/document_parser.py`:
    - Check magic bytes for PDF (`b"%PDF-"`). Raise `ValidationError("Invalid PDF: magic bytes missing")` if header is not present. Reject binary headers (PE/ELF) for text/html/md.
    - In `_extract_pdf`: enforced `MAX_PDF_PAGES = 100` and `MAX_EXTRACTED_CHARS = 500_000`. Stop extraction if either ceiling is reached.
  - [x] In `backend/tests/test_documents.py`, added tests for:
    - Masqueraded file (e.g. executable/text with `.pdf` extension) is rejected.
    - Page ceiling and character count limit halts extraction cleanly.
  - [x] Ran `pytest backend/tests/test_documents.py`.
  - [x] **Committed:** `9d2110a fix(security): validate upload magic bytes and enforce PDF page ceilings (SEC-MED-06, SEC-MED-07)`

---

### Task 5: SEC-MED-08: Unfenced Error and Endpoint Fields in Agent Prompts
- **Files Modified:**
  - `backend/app/workflows/agents/test_agent.py`
  - `backend/app/workflows/agents/code_agent.py`
  - `backend/tests/test_prompt_injection.py`
- **Completed Steps:**
  - [x] In `backend/app/workflows/agents/test_agent.py` and `code_agent.py`, wrapped untrusted fields (`error`, `method`, `path`) using `fence_untrusted()` before interpolating into repair prompts.
  - [x] Added tests in `backend/tests/test_prompt_injection.py` confirming injection delimiters in `error` or `path` are enclosed in fences.
  - [x] Ran `pytest backend/tests/test_prompt_injection.py`.
  - [x] **Committed:** `e5b6412 fix(security): fence error and endpoint parameters in LLM prompts (SEC-MED-08)`

---

### Task 6: SEC-MED-09: Unbounded Server-Sent Events (SSE) Stream Connection Holding
- **Files Modified:**
  - `backend/app/api/v1/events.py`
  - `backend/tests/conftest.py`
  - `backend/tests/test_events.py`
- **Completed Steps:**
  - [x] In `backend/app/api/v1/events.py`, limited concurrent active SSE streams per client identity (max 5) using Redis key `ratelimit:sse:conn:{identity}` with `INCR` / `DECR`.
  - [x] Raised HTTP 429 `RateLimitExceededError` if limit is exceeded.
  - [x] In generator `finally:` block, decremented connection count.
  - [x] Added tests in `backend/tests/test_events.py` verifying the 6th concurrent stream returns 429.
  - [x] Ran `pytest backend/tests/test_events.py`.
  - [x] **Committed:** `b6a576f fix(security): enforce concurrency limits on SSE event streams (SEC-MED-09)`

---

### Task 7: SEC-MED-10: Incomplete Health Probe / Readiness Contract
- **Files Modified:**
  - `backend/app/api/v1/health.py`
  - `backend/app/services/qdrant_service.py`
  - `backend/app/services/storage_service.py`
  - `backend/tests/conftest.py`
  - `backend/tests/test_health.py`
- **Completed Steps:**
  - [x] In `backend/app/api/v1/health.py`, updated `/readyz` to check Qdrant and S3 connectivity alongside PostgreSQL and Redis with 1s timeout.
  - [x] In `backend/tests/test_health.py`, updated readiness tests to assert all 4 dependencies are verified.
  - [x] Ran `pytest backend/tests/test_health.py`.
  - [x] **Committed:** `86a5348 fix(security): complete /readyz probe contract with Qdrant and S3 checks (SEC-MED-10)`

---

### Task 8: SEC-MED-11: Celery Worker Tasks Orphaned on Workflow Cancellation
- **Files Modified:**
  - `backend/app/core/celery_client.py`
  - `backend/app/workflows/dispatch.py`
  - `backend/app/api/v1/workflows.py`
  - `backend/tests/conftest.py`
  - `backend/tests/test_workflows.py`
- **Completed Steps:**
  - [x] In `backend/app/workflows/dispatch.py`, stored Celery `task_id` in Redis: `await redis_client.set(f"workflow:celery_task:{run.id}", task.id, ex=86400)`.
  - [x] In `backend/app/api/v1/workflows.py:cancel_workflow_run`, retrieved `celery_task_id` from Redis, and invoked `celery_client.revoke_task(celery_task_id, terminate=True, signal="SIGTERM")`.
  - [x] In `backend/tests/test_workflows.py`, added tests verifying cancellation issues a Celery revoke.
  - [x] Ran `pytest backend/tests/test_workflows.py`.
  - [x] **Committed:** `839281b fix(security): revoke celery worker tasks on workflow cancellation (SEC-MED-11)`

---

### Task 9: SEC-MED-03: Sandbox Live Mode DNS Rebinding SSRF
- **Files Modified:**
  - `backend/app/services/sandbox_service.py`
  - `backend/tests/test_sandbox_executor.py`
- **Completed Steps:**
  - [x] In `backend/app/services/sandbox_service.py`, captured the validated IP from `assert_public_target` / `resolve_public_address`.
  - [x] Passed `extra_hosts={hostname: pinned_ip}` to Docker container run configuration to pin the hostname to the validated IP.
  - [x] Added unit tests in `backend/tests/test_sandbox_executor.py` verifying `extra_hosts` pinning is configured.
  - [x] Ran `pytest backend/tests/test_sandbox_executor.py`.
  - [x] **Committed:** `dbbcf92 fix(security): pin resolved IP in sandbox live network mode to prevent DNS rebinding (SEC-MED-03)`

---

### Task 10: SEC-MED-04: Supply Chain Vulnerabilities (Dependency Version Floors)
- **Files Modified:**
  - `backend/pyproject.toml`
- **Completed Steps:**
  - [x] In `backend/pyproject.toml`, bumped minimum version floors for vulnerable packages: `starlette >= 0.49.2`, `pypdf >= 6.21.4`, `aiohttp >= 3.14.4`, `filelock >= 4.2.1`, `certifi >= 2026.10.19`.
  - [x] Verified test suite passes with updated constraints.
  - [x] **Committed:** `f0d2897 fix(security): upgrade vulnerable dependencies to patched versions (SEC-MED-04)`

---

## Final Verification
- Full test suite across all 9 touched modules: **242 passed, 0 failed** in 170.54s.
