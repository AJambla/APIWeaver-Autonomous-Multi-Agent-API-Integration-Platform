# Phase 2: Database Schema & Secrets Simplification Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Simplify secret management and persistence architecture by replacing HashiCorp Vault with internal AES-256-GCM authenticated encryption, removing range-partitioned database tables and maintenance loops, consolidating Alembic migrations into a single clean schema, and fixing the Celery worker task timeout bug.

**Architecture:**
1. `backend/app/services/crypto_service.py` implements AES-256-GCM authenticated encryption using `cryptography` library.
2. In development, secret keys are derived from `APP_ENCRYPTION_KEY` in `.env` (or generated on the fly); production connects to AWS Secrets Manager / KMS.
3. HashiCorp Vault dependencies and `vault_service.py` are completely deleted.
4. Range partitioning on `agent_events` and `usage_metrics` is replaced with standard indexed relational tables, removing `backend/app/db/partitions.py` and the lifespan background loop.
5. The 14 fragmented Alembic migrations are consolidated into a clean, single `0001_initial_schema.py`.
6. Celery's hardcoded 300s timeout is updated to read `WORKFLOW_TASK_TIME_LIMIT_SECONDS` (3600s).

**Tech Stack:** Python 3.12, cryptography (AESGCM), SQLAlchemy, Alembic, PostgreSQL, Celery.

**Spec:** `C:\Users\WELCOME\.gemini\antigravity\brain\21068cce-9a93-4d38-93de-f85001610bf5\API_WEAVER_REFACTORING_BLUEPRINT.md`

## Global Constraints
- Cryptography algorithm: Authenticated **AES-256-GCM** (NIST SP 800-38D).
- Zero external Vault dependency.
- Database: Standard relational PostgreSQL tables without partitioning DDL or dropped foreign keys.
- Celery task time limit: 3600s (`WORKFLOW_TASK_TIME_LIMIT_SECONDS`).
- Commit atomically after completing each task.
- Follow the Ponytail principle: write the smallest complete code that solves the task.

## Review Focus
1. `AESGCM` encryption generates unique 12-byte random nonces per encryption to prevent nonce reuse attacks.
2. `CryptoService.read_secret` and `write_secret` handle credential payloads correctly without leaking raw data into logs.
3. `auth_config.py` and `test_agent.py` function seamlessly without `vault_service`.
4. `main.py` starts and stops cleanly without partition maintenance tasks.
5. Alembic migration `0001_initial_schema.py` defines all tables cleanly with correct foreign keys.

---

### Task 1: AES-256-GCM CryptoService Implementation

**Files:**
- Create: `backend/app/services/crypto_service.py`
- Create: `backend/tests/test_crypto_service.py`

**Steps:**
- [ ] Create `backend/app/services/crypto_service.py` with `CryptoService` implementing:
  - `encrypt(data: dict[str, Any] | str) -> str` using `AESGCM` with random 12-byte nonce.
  - `decrypt(ciphertext: str) -> dict[str, Any] | str`.
  - `write_secret(path: str, data: dict[str, Any]) -> None`.
  - `read_secret(path: str) -> dict[str, Any] | None`.
  - `delete_secret(path: str) -> None`.
- [ ] Add unit tests in `backend/tests/test_crypto_service.py` validating encryption round-trip, tamper resistance, and path sanitization.
- [ ] Run pytest on `backend/tests/test_crypto_service.py`.
- [ ] Commit: `feat(crypto): implement AES-256-GCM CryptoService for credential storage`

---

### Task 2: Replace Vault Dependencies & Decommission `vault_service.py`

**Files:**
- Modify: `backend/app/api/v1/auth_config.py`
- Modify: `backend/app/api/v1/github.py`
- Modify: `backend/app/services/github_service.py`
- Modify: `backend/app/workflows/agents/test_agent.py`
- Modify: `backend/app/core/config.py`
- Delete: `backend/app/services/vault_service.py`
- Modify: `backend/tests/conftest.py`
- Modify: `backend/tests/test_auth_config.py`

**Steps:**
- [ ] Replace `VaultClient` and `create_vault_client` in `auth_config.py`, `test_agent.py`, `github.py`, and `github_service.py` with `CryptoService` / `create_crypto_service`.
- [ ] Remove `vault_addr`, `vault_token`, and `vault_mount_path` from `backend/app/core/config.py`. Add `app_encryption_key: str | None = None`.
- [ ] Delete `backend/app/services/vault_service.py`.
- [ ] Update `backend/tests/conftest.py` and `backend/tests/test_auth_config.py` to use `CryptoService`.
- [ ] Run pytest on `backend/tests/test_auth_config.py`.
- [ ] Commit: `refactor(secrets): decommission HashiCorp Vault in favor of CryptoService`

---

### Task 3: Remove Database Partitioning & Maintenance Loop

**Files:**
- Modify: `backend/app/main.py`
- Delete: `backend/app/db/partitions.py`
- Modify: `backend/tests/test_partitions.py`

**Steps:**
- [ ] In `backend/app/main.py`, remove `run_partition_maintenance_forever` import, background task creation, and cancellation in lifespan.
- [ ] Delete `backend/app/db/partitions.py`.
- [ ] Remove `test_partitions.py` or update to assert that standard tables are used.
- [ ] Commit: `refactor(db): remove range-partitioned table maintenance loop`

---

### Task 4: Consolidate Alembic Migrations into Clean `0001_initial_schema.py`

**Files:**
- Modify: `backend/alembic/versions/0001_initial_schema.py`
- Delete: `backend/alembic/versions/0002_partitioned_tables.py` through `0014_workflow_runs_heartbeat.py`

**Steps:**
- [ ] Update `backend/alembic/versions/0001_initial_schema.py` to include:
  - Standard `agent_events` table with single bigint PK, foreign key to `workflow_runs.id`, and b-tree indexes.
  - Standard `usage_metrics` table with single bigint PK, foreign key to `organizations.id`, and b-tree indexes.
  - All schema enhancements from migrations 0003–0014 (GitHub connections, heartbeat columns, rate limit overrides).
- [ ] Delete `0002_partitioned_tables.py` through `0014_workflow_runs_heartbeat.py`.
- [ ] Commit: `refactor(migrations): consolidate Alembic revisions into unified clean 0001 schema`

---

### Task 5: Fix Celery Task Timeouts & Verify Full Test Suite

**Files:**
- Modify: `agent_worker/celery_app.py`

**Steps:**
- [ ] In `agent_worker/celery_app.py`, update `task_time_limit` from hardcoded 300 to `int(os.environ.get("WORKFLOW_TASK_TIME_LIMIT_SECONDS", "3600"))` and `task_soft_time_limit` to `int(os.environ.get("WORKFLOW_TASK_SOFT_TIME_LIMIT_SECONDS", "3300"))`.
- [ ] Run pytest on all affected test suites (`test_crypto_service.py`, `test_auth_config.py`, `test_export.py`, `test_codegen.py`, `test_langgraph_pipeline.py`).
- [ ] Commit: `fix(worker): align Celery task time limits with workflow configuration`
