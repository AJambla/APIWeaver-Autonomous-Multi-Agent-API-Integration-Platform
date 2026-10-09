# Dockerfile for the agent-worker service.
# The repository root remains the build context so this image can copy backend and agent_worker.

FROM python:3.12.15-slim@sha256:02108f5d322dd89f1c9e552442c25acb0543dfdbc455693a5599624f20d9155d AS builder

WORKDIR /app

ENV PYTHONPATH=/app/backend:/app

# Copy backend dependency files
COPY backend/pyproject.toml backend/poetry.lock ./backend/

# Copy agent_worker package
COPY agent_worker ./agent_worker

# Install poetry and export requirements
RUN pip install --no-cache-dir poetry poetry-plugin-export && \
    cd backend && poetry export -f requirements.txt --output ../requirements.txt --only main


FROM python:3.12.15-slim@sha256:02108f5d322dd89f1c9e552442c25acb0543dfdbc455693a5599624f20d9155d

WORKDIR /app

# Copy requirements from builder
COPY --from=builder /app/requirements.txt .

# Hashes come from poetry.lock; a substituted wheel fails this build.
RUN pip install --no-cache-dir --require-hashes -r requirements.txt

# Copy backend application code
COPY backend ./backend

# Copy agent_worker package
COPY agent_worker ./agent_worker

# `ENV` does not cross `FROM`: the builder's PYTHONPATH is gone here, and without it
# `agent_worker.tasks.base` cannot import `app` and the worker exits on boot.
ENV PYTHONPATH=/app/backend:/app

# Create non-root user
RUN useradd -m appuser && chown -R appuser /app

USER appuser

# No HEALTHCHECK here (`audit M10`). The previous one,
# `celery -A agent_worker.celery_app inspect ping`, cannot pass: celery 5.6.3 does not exit
# after a successful inspect, so the daemon kills the check at its timeout and the container is
# reported unhealthy even while a worker replies `pong`. Measured, with controls and the leaked
# processes, in the `agent-worker` service of
# infra/docker/docker-compose.single-node.yml.

# Run celery worker
# Consume the dead-letter queue too: nothing else reads `dlq`.
CMD ["celery", "-A", "agent_worker.celery_app", "worker", "--loglevel=info", "--concurrency=4", "-Q", "celery,dlq"]
