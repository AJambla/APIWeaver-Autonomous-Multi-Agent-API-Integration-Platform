# Dockerfile for the agent-worker service.
# The repository root remains the build context so this image can copy backend and agent_worker.

FROM python:3.12-slim AS builder

WORKDIR /app

ENV PYTHONPATH=/app/backend:/app

# Copy backend dependency files
COPY backend/pyproject.toml backend/poetry.lock ./backend/

# Copy agent_worker package
COPY agent_worker ./agent_worker

# Install poetry and export requirements
RUN pip install --no-cache-dir poetry poetry-plugin-export && \
    cd backend && poetry export -f requirements.txt --output ../requirements.txt --only main --without-hashes


FROM python:3.12-slim

WORKDIR /app

# Copy requirements from builder
COPY --from=builder /app/requirements.txt .

# Install all dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Copy backend application code
COPY backend ./backend

# Copy agent_worker package
COPY agent_worker ./agent_worker

# Create non-root user
RUN useradd -m appuser && chown -R appuser /app

USER appuser

# Healthcheck for celery worker
HEALTHCHECK --interval=30s --timeout=5s \
    CMD celery -A agent_worker.celery_app inspect ping || exit 1

# Run celery worker
CMD ["celery", "-A", "agent_worker.celery_app", "worker", "--loglevel=info", "--concurrency=4"]
