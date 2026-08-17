# Phase 4 Implementation Plan

## Goal
Implement GitHub Export, WebSocket/SSE real-time progress, and Celery task queue integration.

## Completed (already in repo)
- `backend/app/models/github.py` — `GitHubOAuthState`, `GitHubConnection`
- `backend/app/core/config.py` — GitHub settings fields added
- `backend/app/services/github_service.py` — `GitHubAppClient`, `GitHubOAuthClient`
- `backend/app/api/v1/github.py` — OAuth routes (`/connect`, `/callback`, `/status`, `/disconnect`, `/repos`)
- `backend/app/workflows/agents/export_agent.py` — `_package_github()` enhanced with Git Data API push
- `backend/app/rbac/policy.py` — `GITHUB_CONNECT`, `GITHUB_EXPORT` permissions added
- `backend/app/api/v1/router.py` — github router registered

## TODO (execute in order)

### 1. Fix `event_publisher.py`
- File exists with only "TEST" content
- Write full `EventPublisher` class using `edit` tool
- Must include: `publish()`, `publish_workflow_started()`, `publish_workflow_progress()`, `publish_node_completed()`, `publish_workflow_completed()`, `publish_test_result()`, `publish_repair_attempt()`, `publish_export_progress()`
- Redis XADD to `workflow_events:{run_id}` and `project_events:{project_id}`

### 2. Integrate EventPublisher into Orchestrator
- `backend/app/workflows/orchestrator.py`: inject `EventPublisher`
- Emit `workflow.started`, `workflow.progress`, `node_completed`, `workflow.completed` at each transition

### 3. Create WebSocket/SSE endpoints
- New file `backend/app/api/v1/events.py`
- Routes: `GET /ws/workflows/{run_id}`, `GET /sse/workflows/{run_id}`
- Subscribe to Redis Streams via `XREAD`, authenticate with initial message

### 4. Celery task queue (`agent-worker/`)
- `agent-worker/celery_app.py` — broker Redis `redis://redis:6379/1`
- `agent-worker/tasks/` — `document_tasks.py`, `codegen_tasks.py`, `testing_tasks.py`, `export_tasks.py`
- Refactor `Orchestrator` to support `execution_mode: "sync" | "async"`

### 5. Alembic migration
- New migration for `github_oauth_states`, `github_connections` tables

### 6. Tests
- `tests/test_github_oauth.py`, `tests/test_github_export.py`, `tests/test_events.py`, `tests/test_celery_tasks.py`

### 7. Docs
- Update `Project-docs/API.md` with GitHub OAuth and WebSocket endpoints
- Update `Project-docs/Deployment.md` with Celery worker and GitHub App setup

## Validation
- `ruff check backend/`
- `mypy backend/`
- `pytest backend/tests/`
