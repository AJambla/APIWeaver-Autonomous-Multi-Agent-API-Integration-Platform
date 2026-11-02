# Critical & High Security Remediation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Remediate all Critical and High severity security vulnerabilities identified in the Phase A audit that do not require user manual intervention (SEC-CRIT-01, SEC-CRIT-02, SEC-HIGH-03, SEC-HIGH-04, SEC-HIGH-05).

**Architecture:** Apply targeted, minimal fixes following the Ponytail principle (shortest working diff, reuse existing codebase validators, minimal code). Each fix addresses the vulnerability at the root cause, is verified with automated tests, and is committed atomically to git.

**Tech Stack:** Python 3.12, FastAPI, SQLAlchemy 2.0 (asyncio), Docker Compose, Alembic, pytest.

**Spec:** [`SECURITY_AUDIT_REPORT.md`](file:///C:/Users/WELCOME/.gemini/antigravity/brain/c6255af6-f700-44a9-a050-680515723f79/SECURITY_AUDIT_REPORT.md)

## Global Constraints
- **Atomic Commits:** Commit immediately after each task is implemented and verified.
- **Ponytail Philosophy:** Smallest complete change that solves the problem; no over-engineering or unused abstractions.
- **TDD & Evidence:** Every non-trivial fix must have an automated test asserting the vulnerable condition cannot reoccur.
- **Secrets Protection:** Never commit or print unmasked secrets.

## Review Focus
1. **Host Escape Prevention:** Celery worker container runs as non-root `appuser` without root group membership.
2. **Reversible Migrations:** `alembic downgrade base` can execute cleanly on PostgreSQL without `UndefinedTable` trigger drop errors.
3. **Zip Slip Neutralization:** MCP export bundle rejects or skips relative traversal paths (`..`, leading `/`, drive letters) via `validate_storage_key`.
4. **Readiness Probe DoS Defense:** `/readyz` is protected from unauthenticated database connection pool starvation by rate limiting.
5. **Workflow Dispatch Race Defense:** Concurrent `POST /projects/{id}/workflows` requests are serialized per-project via row-level locking (`with_for_update()`).

---

## Tasks

### Task 1: Drop Root Execution in Celery Worker Container (SEC-CRIT-01) - COMPLETED

**Files:**
- Modify: `infra/docker/docker-compose.single-node.yml:186-215`
- Modify: `agent_worker/Dockerfile:31-38`

**Steps:**
- [x] Remove `user: "0:0"` from `agent-worker` service in `infra/docker/docker-compose.single-node.yml`.
- [x] Remove `C_FORCE_ROOT: "true"` from `agent-worker` environment in `infra/docker/docker-compose.single-node.yml`.
- [x] Remove root group `"0"` from `group_add` in `infra/docker/docker-compose.single-node.yml`, leaving only `"${DOCKER_GID:-999}"`.
- [x] In `agent_worker/Dockerfile`, remove `(usermod -aG root appuser || true) && \` so `appuser` belongs only to `docker`, not `root`.
- [x] Verify Compose file syntax and Dockerfile structure.
- [x] Commit: `52509bf fix(security): drop root execution in agent-worker container (SEC-CRIT-01)`.

---

### Task 2: Fix Alembic Downgrade Trigger Drop Ordering (SEC-CRIT-02) - COMPLETED

**Files:**
- Modify: `backend/alembic/versions/0001_initial_schema.py:574-584`
- Modify: `backend/tests/test_audit_immutability.py`

**Steps:**
- [x] Write a test in `backend/tests/test_audit_immutability.py` (`test_downgrade_drops_triggers_before_dropping_audit_logs`) capturing the downgrade operation sequence and asserting trigger drops precede `op.drop_table('audit_logs')`.
- [x] Run test to verify it fails with the current ordering: `pytest backend/tests/test_audit_immutability.py` (Failed: `assert 35 < 32`).
- [x] In `backend/alembic/versions/0001_initial_schema.py`, move the `bind.dialect.name == "postgresql"` trigger and function drops block to execute before `op.drop_table('audit_logs')`.
- [x] Run `pytest backend/tests/test_audit_immutability.py` and verify all tests pass (`6 passed, 2 skipped`).
- [x] Commit: `ddf4215 fix(security): drop audit triggers before audit_logs table on alembic downgrade (SEC-CRIT-02)`.

---

### Task 3: Sanitize File Paths in MCP Export Zip Bundle (SEC-HIGH-03) - COMPLETED

**Files:**
- Modify: `backend/app/workflows/agents/export_agent.py:521-536`
- Modify: `backend/tests/test_export_agent_fastmcp.py`

**Steps:**
- [x] Write a test in `backend/tests/test_export_agent_fastmcp.py` (`test_export_agent_skips_path_traversal_zip_slip`) asserting that generated files with traversal paths (`../../etc/cron.d/job`, `/evil.py`, `tools/../../evil.py`) cannot escape into the zip bundle and are safely omitted.
- [x] Run test to observe failure (`AssertionError: Zip Slip traversal path found in zip: ../../etc/cron.d/pwned`).
- [x] In `backend/app/workflows/agents/export_agent.py`, import `validate_storage_key` from `app.services.storage_service`.
- [x] Wrap `file_path` resolution in `export_agent.py`: validate `file_path` with `validate_storage_key(file_path)` and skip unsafe paths with a warning log.
- [x] Run `pytest backend/tests/test_export_agent_fastmcp.py` and `test_export.py` and verify all tests pass (`2 passed` in fastmcp, `7 passed` in export).
- [x] Commit: `84fb874 fix(security): sanitize file paths in MCP export zip bundle to prevent Zip Slip (SEC-HIGH-03)`.

---

### Task 4: Protect `/readyz` Probe from Connection Pool Exhaustion DoS (SEC-HIGH-04) - COMPLETED

**Files:**
- Modify: `backend/app/core/ratelimit.py:72-76`
- Modify: `backend/tests/test_health.py`

**Steps:**
- [x] In `backend/tests/test_health.py`, add test `test_readyz_is_rate_limited_under_flood` that fires requests beyond `ANONYMOUS_REQUESTS_PER_MINUTE` to `/readyz` and verifies it receives HTTP 429 rather than continuously consuming DB connections.
- [x] Run test to confirm it fails (`AssertionError: [200, 200, 200, 200, 200] assert 200 == 429`).
- [x] In `backend/app/core/ratelimit.py`, remove `/readyz` from `EXEMPT_PATHS` (`EXEMPT_PATHS = frozenset({"/healthz", "/metrics"})`).
- [x] Run `pytest backend/tests/test_health.py` and verify all 26 tests pass (`26 passed`).
- [x] Commit: `6049bb9 fix(security): protect /readyz probe against connection pool exhaustion DoS (SEC-HIGH-04)`.

---

### Task 5: Serialize Concurrent Workflow Triggers with Row Lock (SEC-HIGH-05) - COMPLETED

**Files:**
- Modify: `backend/app/api/v1/workflows.py:73-86`
- Modify: `backend/tests/test_concurrency.py`

**Steps:**
- [x] Write a test in `backend/tests/test_concurrency.py` (`test_concurrent_workflow_triggers_serialize_per_project`) simulating concurrent `trigger_workflow` calls on the same project and verifying row locking serializes execution without race conditions.
- [x] Run test to observe failure (`AssertionError: Expected exactly 1 queued run, found: ['queued', 'queued', 'queued', 'queued']`).
- [x] In `backend/app/api/v1/workflows.py`, add `select(Project.id).where(Project.id == project.id).with_for_update()` and update the project's `updated_at` before selecting active runs to lock the project row across transactions.
- [x] Also add `.with_for_update()` to the `WorkflowRun` query that selects active runs.
- [x] Run `pytest backend/tests/test_concurrency.py` and verify all 7 tests pass (`7 passed`).
- [x] Commit: `07dba2c fix(security): serialize concurrent workflow triggers per project with row lock (SEC-HIGH-05)`.
