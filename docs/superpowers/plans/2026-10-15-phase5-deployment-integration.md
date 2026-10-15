# Phase 5: Single-Node Deployment & Integration Smoke Test Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Deliver a production-grade, single-command deployable stack (`docker compose up`) without HashiCorp Vault, with automated JWT & AES-GCM crypto bootstrapping, proper Docker socket sandbox permissions, and an end-to-end FastMCP integration smoke test.

**Architecture:**
1. Cross-platform Python bootstrap utility (`scripts/bootstrap.py`) creates secrets directory, RS256 JWT keypair, and AES-256-GCM encryption key.
2. Root `docker-compose.yml` orchestrates Postgres 16, Redis 7, Qdrant, MinIO (with bucket auto-init), DB migration, FastAPI backend, Celery worker, and Vite/Nginx frontend with Zero-Vault configuration.
3. Sandbox Python Dockerfile updated with pytest and MCP dependencies; Celery worker configured for non-root Docker socket interaction.
4. Comprehensive end-to-end integration test (`backend/tests/test_fastmcp_pipeline_e2e.py`) validating the complete lifecycle: Upload → Ingest → Dependencies → FastMCP Code Gen → Pre-Sandbox Static Gate → Sandbox Execution → Multi-Tier Verification Report → MCP ZIP Bundle.

**Tech Stack:** Docker Compose v2, Python 3.12, FastAPI, Celery, PostgreSQL 16, Redis 7, Qdrant, MinIO, Pytest, Cryptography (AES-256-GCM / RS256).

**Spec:** `API_WEAVER_REFACTORING_BLUEPRINT.md §6, §7, §9, §10`.

---

## Global Constraints
- Root `docker compose up` must work out of the box without manual `openssl` commands or Vault tokens.
- HashiCorp Vault is completely deleted from the compose architecture; credentials use internal `CryptoService` (`APP_ENCRYPTION_KEY`).
- Worker container must communicate with `/var/run/docker.sock` for sandbox execution without permission errors.
- Verification status naming must strictly follow: `STATIC: PASS`, `SANDBOX: PASS`, `LIVE: NOT RUN`, `Overall: SANDBOX VERIFIED`.

---

## Tasks

### Task 1: Automated JWT & Crypto Bootstrap Utility
- [ ] Create `scripts/bootstrap.py`:
  - Check for `secrets/jwt_private.pem` and `secrets/jwt_public.pem`.
  - Generate 2048-bit RSA keypair if missing using Python `cryptography` library.
  - Set 0600 file permissions on private key on POSIX systems.
  - Check for `APP_ENCRYPTION_KEY` in `.env` (or create `.env` from `.env.example` if missing); generate 32-byte urlsafe base64 key if not present.
- [ ] Update `scripts/gen_jwt_keys.py` as a standalone Python alternative to `gen_jwt_keys.sh`.
- [ ] Verify execution: run `python scripts/bootstrap.py`.
- [ ] Commit: `feat(infra): add automated JWT and AES-GCM crypto bootstrap script`.

### Task 2: Root `docker-compose.yml` (Zero-Vault Single-Node Deployment)
- [ ] Create root `docker-compose.yml`:
  - Services: `postgres`, `redis`, `qdrant`, `minio`, `minio-init`, `db-migration`, `api`, `agent-worker`, `web`.
  - Delete `vault` service. Remove all `VAULT_ADDR` and `VAULT_TOKEN` references.
  - Add `APP_ENCRYPTION_KEY` to `api` and `agent-worker`.
  - Add `init-bootstrap` service running `python scripts/bootstrap.py` so keys exist before `api` or `db-migration` start.
  - Configure `minio-init` to automatically create buckets `apiweaver-uploads` and `apiweaver-artifacts`.
- [ ] Update `infra/docker/docker-compose.single-node.yml` to reflect the removed Vault service and align with root compose.
- [ ] Update `.env.example` to ensure `APP_ENCRYPTION_KEY` and all dev defaults are documented cleanly.
- [ ] Commit: `feat(infra): create root docker-compose.yml with zero-vault architecture and automated bootstrap`.

### Task 3: Sandbox Environment & Worker Docker Socket Configuration
- [ ] Update `infra/docker/Dockerfile.sandbox-python`:
  - Add `pytest==8.3.4`, `pytest-asyncio==0.24.0`, and `fastmcp` dependencies so FastMCP test suites run inside ephemeral containers.
- [ ] Update `agent_worker/Dockerfile` and compose:
  - Remove read-only `:ro` restriction on `/var/run/docker.sock`.
  - Add `group_add: ["${DOCKER_GID:-999}"]` (or handle docker socket gid).
  - Verify worker container non-root permission handling.
- [ ] Commit: `feat(sandbox): update sandbox python image with pytest and configure worker docker socket permissions`.

### Task 4: FastMCP End-to-End Integration & Smoke Test
- [ ] Create `backend/tests/test_fastmcp_pipeline_e2e.py`:
  - Comprehensive end-to-end integration test driving:
    - User registration & organization setup.
    - Project creation.
    - Spec upload (Petstore OpenAPI 3.0 specification).
    - Ingestion and normalization into operations.
    - Topological DAG planning and dependency persistence.
    - Approval gate transition.
    - Code generator agent creating FastMCP `tools.py`, `server.py`, `manifest.json`, and `test_mcp.py`.
    - Pre-sandbox static validation gate (`validate_mcp_code_statically`).
    - Testing agent executing sandbox tests and producing `VERIFICATION_REPORT.json` and `VERIFICATION_REPORT.md`.
    - Export agent generating `apiweaver-mcp.zip` and manifest catalog.
    - Verify verification statuses: `STATIC: PASS`, `SANDBOX: PASS`, `LIVE: NOT RUN`, `Overall: SANDBOX VERIFIED`.
- [ ] Run test suite with pytest.
- [ ] Commit: `test(e2e): add end-to-end integration smoke test for FastMCP generation and verification`.

### Task 5: Push Branch & Create Pull Request
- [ ] Run full test suites and lint checks.
- [ ] Push `refactor/phase5-deployment-integration` to origin.
- [ ] Create PR using `gh pr create` with detailed architectural summary.
