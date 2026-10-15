# Docker Cleanup, Layer Optimization & Ignore Rules Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Modernize all `.dockerignore` files to prevent build leaks, eliminate layer-doubling in Dockerfiles, and reclaim ~22 GB of disk space from stale build cache, orphaned volumes, and obsolete images.

**Architecture:** Update build-ignore specifications in root, `backend/`, and `Frontend/`; optimize Docker multi-stage layers with `COPY --chown=appuser:appuser` to avoid overlay2 duplicate layer copies; prune BuildKit cache and delete legacy images (Vault, Grafana, RabbitMQ, duplicate Postgres tags).

**Tech Stack:** Docker, BuildKit, Docker Compose, Linux/Windows CLI.

---

## Files to Create & Modify

1. **Modify:** `.dockerignore` — Add `storage/`, `docs/`, `.planning/`, `backend/tests/`.
2. **Modify:** `backend/.dockerignore` — Add `tests/`, `storage/`, `docs/`, `.planning/`.
3. **Modify:** `Frontend/.dockerignore` — Add `docs/`, `.planning/`.
4. **Modify:** `backend/Dockerfile` — Create `appuser` early; use `COPY --chown=appuser:appuser . .` to eliminate `chown -R` layer duplication.
5. **Modify:** `agent_worker/Dockerfile` — Create `appuser` early; use `COPY --chown=appuser:appuser` for backend and agent_worker.
6. **Cleanup:** Execute Docker BuildKit prune, obsolete image removal, and clean stale `.claude/worktrees/`.

---

## Implementation Tasks

### Task 1: Update `.dockerignore` Files

- [ ] Update `backend/.dockerignore` to exclude `tests/`, `storage/`, `docs/`, and `.planning/`.
- [ ] Update root `.dockerignore` to exclude `storage/`, `docs/`, and `.planning/`.
- [ ] Update `Frontend/.dockerignore` to exclude `docs/` and `.planning/`.
- [ ] Commit changes: `chore(docker): update dockerignore rules to prevent test and storage leaks`.

### Task 2: Optimize Dockerfile Layering to Eliminate `chown -R` Layer Duplication

- [ ] In `backend/Dockerfile`, define `appuser` prior to copying application code and use `COPY --chown=appuser:appuser . .`. Remove redundant `RUN chown -R appuser /app`.
- [ ] In `agent_worker/Dockerfile`, define `appuser` prior to copying code and use `COPY --chown=appuser:appuser`. Remove redundant `RUN chown -R appuser:appuser /app`.
- [ ] Commit changes: `perf(docker): optimize image layers using COPY --chown to avoid layer doubling`.

### Task 3: Prune Stale Build Cache, Orphaned Volumes, and Obsolete Images

- [ ] Prune Docker BuildKit cache (`docker builder prune -af`) to reclaim ~16 GB.
- [ ] Remove obsolete images: `hashicorp/vault:latest`, `grafana/grafana:latest`, `rabbitmq:3.13-management-alpine`, stale `postgres` duplicates, and test images.
- [ ] Prune orphaned volumes not connected to active containers (`docker volume prune -f`).
- [ ] Remove stale `.claude/worktrees/` directory from filesystem.

### Task 4: Verification and System Audit

- [ ] Run `docker system df` to verify reclaimed disk space.
- [ ] Verify active running containers (`apiweaver-postgres`, `apiweaver-redis`, `apiweaver-qdrant`, `apiweaver-minio`) remain healthy and uninterrupted.
- [ ] Run backend verification tests to ensure no development regressions.
