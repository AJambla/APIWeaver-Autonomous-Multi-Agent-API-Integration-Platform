# agent-worker (`orchestrator-service`)

LangGraph orchestrator + Celery worker. Implemented in **Phase 3** — see [`AI_Instruction.md`](../Project-docs/AI_Instruction.md) §6 and [`Architecture.md`](../Project-docs/Architecture.md) §4.

## Running the Celery Worker

```bash
# From the repo root
pip install celery[redis] flower

# Start the worker
celery -A agent_worker.celery_app worker --loglevel=info --concurrency=4

# Optional: start Flower monitoring
celery -A agent_worker.celery_app flower --port=5555
```

## Environment Variables

| Variable | Default | Description |
|---|---|---|
| `CELERY_BROKER_URL` | `redis://redis:6379/1` | Redis broker for task queue |
| `CELERY_RESULT_BACKEND` | `redis://redis:6379/2` | Redis backend for task results |
