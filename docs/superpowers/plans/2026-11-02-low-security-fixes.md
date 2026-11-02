# Low Security Remediation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Plan and implement all 11 Low severity security vulnerabilities identified in the Phase A audit report (`SECURITY_AUDIT_REPORT.md`) that do not require user manual action: SEC-LOW-01, SEC-LOW-02, SEC-LOW-03, SEC-LOW-04, SEC-LOW-05, SEC-LOW-06, SEC-LOW-07, SEC-LOW-08, SEC-LOW-09, SEC-LOW-11, SEC-LOW-12 (SEC-LOW-10 is excluded as it requires user manual action to scrub git author history).

**Architecture:** Minimal, surgical changes following the Ponytail principle (shortest working diff, reuse existing helpers, zero unnecessary bloat). Each fix addresses the vulnerability at the root cause, is verified with automated tests, and is committed atomically to git.

**Tech Stack:** Python 3.12, FastAPI, SQLAlchemy 2.0 (asyncio), Redis, Alembic, React/TypeScript.

**Spec:** [`SECURITY_AUDIT_REPORT.md`](file:///C:/Users/WELCOME/.gemini/antigravity/brain/c6255af6-f700-44a9-a050-680515723f79/SECURITY_AUDIT_REPORT.md)

## Global Constraints
- **Atomic Commits:** Commit to git immediately after each issue is implemented and verified.
- **Ponytail Mode:** Shortest working diff, reuse existing codebase helpers (`hash_opaque_token`, `validate_storage_key`, `resolve_org_role`, `audit_service`), no bloat.
- **TDD & Verification:** Every fix must be verified with automated tests before committing.
- **Secrets Protection:** Never print or commit unmasked secrets.
- **Local Testing Only:** No external requests or attacks against outside systems.

---

## Tasks

### Task 1: SEC-LOW-12: String Prefix Confusion in `LocalFileSystemObjectStorage`
- **Files to Modify:**
  - `backend/app/services/storage_service.py:184-191`
  - `backend/tests/test_storage.py` (or verify with tests)
- **Steps:**
  - [ ] Replace `not str(target).startswith(str(self._base_dir))` in `_resolve_path()` with `not target.resolve().is_relative_to(self._base_dir.resolve())`.
  - [ ] Run test suite to verify path resolution and traversal rejection.
  - [ ] Commit: `fix(security): prevent string prefix confusion in local object storage (SEC-LOW-12)`.

---

### Task 2: SEC-LOW-02: Insecure Fallback Development AES Key
- **Files to Modify:**
  - `backend/app/services/crypto_service.py:56-62`
  - `backend/tests/test_crypto_service.py` (or unit test)
- **Steps:**
  - [ ] In `backend/app/services/crypto_service.py`, replace static sha256 default key with `secrets.token_bytes(32)`.
  - [ ] Verify `CryptoService` initializes and encrypts/decrypts correctly.
  - [ ] Commit: `fix(security): use ephemeral random key for development fallback encryption (SEC-LOW-02)`.

---

### Task 3: SEC-LOW-03: Unhandled Path Traversal Sequence in `POST /projects/{id}/weaver/apply`
- **Files to Modify:**
  - `backend/app/api/v1/weaver.py:324-328`
  - `backend/tests/test_weaver.py` (or unit test)
- **Steps:**
  - [ ] In `backend/app/api/v1/weaver.py`, validate `clean_path` using `validate_storage_key(clean_path)` and convert `ValueError` to `ValidationError` (HTTP 422/400).
  - [ ] Add unit test verifying `../` paths in `weaver/apply` return 422 instead of unhandled 500.
  - [ ] Commit: `fix(security): validate path traversal in weaver apply endpoint (SEC-LOW-03)`.

---

### Task 4: SEC-LOW-05: Unauthenticated `/metrics` Endpoint in Non-Production
- **Files to Modify:**
  - `backend/app/main.py:204-220`
  - `backend/tests/test_security_hardening.py`
- **Steps:**
  - [ ] In `backend/app/main.py:_mount_metrics`, if `settings.metrics_token is None` in non-production, check that `request.client.host` is loopback (`127.0.0.1`, `::1`, `localhost`, `testclient`). If not, raise HTTP 403 Forbidden.
  - [ ] Add unit test verifying external host access without token is rejected while loopback/testclient is accepted.
  - [ ] Commit: `fix(security): restrict unauthenticated metrics endpoint to loopback (SEC-LOW-05)`.

---

### Task 5: SEC-LOW-06: Deprecated `X-XSS-Protection` and Missing `preload` on HSTS
- **Files to Modify:**
  - `backend/app/core/middleware.py:87-90`
  - `frontend/nginx.conf:50`
  - `backend/tests/test_security_hardening.py:119`
- **Steps:**
  - [ ] In `backend/app/core/middleware.py`, change `X-XSS-Protection` to `"0"` and add `preload` to `Strict-Transport-Security`.
  - [ ] In `frontend/nginx.conf`, add `preload` to `Strict-Transport-Security`.
  - [ ] Update assertion in `backend/tests/test_security_hardening.py`.
  - [ ] Commit: `fix(security): update X-XSS-Protection to 0 and add preload to HSTS (SEC-LOW-06)`.

---

### Task 6: SEC-LOW-11: Permanent Project Deletion Authorized for Org Admins
- **Files to Modify:**
  - `backend/app/api/v1/projects.py:234-256`
  - `backend/tests/test_projects.py` (or RBAC tests)
- **Steps:**
  - [ ] In `backend/app/api/v1/projects.py:archive_project`, if `permanent=True`, call `resolve_org_role(session, principal, project.organization_id)` and verify `org_role == OrgRole.OWNER`. Raise `ForbiddenError("Permanent project deletion requires organization Owner role.")` if not.
  - [ ] Add unit test verifying an Org Admin cannot permanently delete a project (only soft-archive it).
  - [ ] Commit: `fix(security): restrict permanent project deletion to org owner (SEC-LOW-11)`.

---

### Task 7: SEC-LOW-04: Omission of Audit Logging on Administrative and Mutation Endpoints
- **Files to Modify:**
  - `backend/app/api/v1/organizations.py`
  - `backend/app/api/v1/github.py`
  - `backend/app/api/v1/settings.py`
- **Steps:**
  - [ ] Add `audit_service.record()` calls for:
    - `organization.created` in `POST /org/`
    - `organization.rate_limit_override_updated` in `PUT /org/{id}/rate-limit-override`
    - `github.connected` in `GET /callback`
    - `github.disconnected` in `DELETE /disconnect`
    - `project.settings_updated` in `PUT /projects/{id}/settings`
  - [ ] Verify audit log recordings with tests.
  - [ ] Commit: `fix(security): add audit logging to administrative and mutation endpoints (SEC-LOW-04)`.

---

### Task 8: SEC-LOW-07: Missing Foreign Key Indexes on PostgreSQL Tables
- **Files to Modify:**
  - `backend/app/models/organization.py`
  - `backend/app/models/project.py`
  - `backend/app/models/spec.py`
  - `backend/app/models/testing.py`
  - `backend/alembic/versions/0002_add_foreign_key_indexes.py` (new migration)
- **Steps:**
  - [ ] Add `index=True` on `organization_members.user_id`, `project_members.user_id`, `api_specs.source_document_id`, and `test_runs.workflow_run_id`.
  - [ ] Create migration `backend/alembic/versions/0002_add_foreign_key_indexes.py` with `upgrade()` and `downgrade()` creating and dropping the indexes.
  - [ ] Verify models and migration definitions.
  - [ ] Commit: `fix(security): add foreign key indexes for postgres performance and locking safety (SEC-LOW-07)`.

---

### Task 9: SEC-LOW-08: Missing Custom 404 Error Page
- **Files to Modify:**
  - `Frontend/src/pages/NotFoundPage.tsx` (new file)
  - `Frontend/src/App.tsx`
- **Steps:**
  - [ ] Create `Frontend/src/pages/NotFoundPage.tsx` with clear message, back to dashboard navigation, and styled with existing Tailwind theme.
  - [ ] In `Frontend/src/App.tsx`, route `path="*"` to `<NotFoundPage />`.
  - [ ] Commit: `feat(frontend): add dedicated 404 not found page (SEC-LOW-08)`.

---

### Task 10: SEC-LOW-09: Missing Terms of Service & Privacy Policy Documents
- **Files to Modify:**
  - `Frontend/src/pages/TermsPage.tsx` (new file)
  - `Frontend/src/pages/PrivacyPage.tsx` (new file)
  - `Frontend/src/App.tsx`
- **Steps:**
  - [ ] Create `Frontend/src/pages/TermsPage.tsx` and `PrivacyPage.tsx` covering GDPR, data retention, LLM processing disclaimers, and user rights.
  - [ ] Register `/terms` and `/privacy` in `Frontend/src/App.tsx`.
  - [ ] Commit: `feat(frontend): add terms of service and privacy policy pages (SEC-LOW-09)`.

---

### Task 11: SEC-LOW-01: Missing Password Reset and Account Recovery Flow
- **Files to Modify:**
  - `backend/app/schemas/auth.py`
  - `backend/app/services/auth_service.py`
  - `backend/app/api/v1/auth.py`
  - `backend/tests/test_auth.py`
- **Steps:**
  - [ ] In `backend/app/schemas/auth.py`, add `ForgotPasswordRequest` (`email: EmailStr`) and `ResetPasswordRequest` (`token: str`, `new_password: str`).
  - [ ] In `backend/app/services/auth_service.py`, add `request_password_reset(email)` storing token in Redis with 15m expiry, and `reset_password(token, new_password)` verifying token, rehashing password, revoking user token families, and deleting Redis key.
  - [ ] In `backend/app/api/v1/auth.py`, add `POST /auth/forgot-password` and `POST /auth/reset-password`.
  - [ ] Add tests in `backend/tests/test_auth.py` verifying full forgot-password and reset-password cycle, including anti-enumeration and expired token rejection.
  - [ ] Commit: `feat(auth): implement secure password reset and account recovery flow (SEC-LOW-01)`.
