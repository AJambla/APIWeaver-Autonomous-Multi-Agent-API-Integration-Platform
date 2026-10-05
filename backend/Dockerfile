# Base image pinned by digest (`audit M10`): the requirements are hash-pinned, and a
# floating `python:3.12-slim` under them would still let the interpreter change silently.
FROM python:3.12.15-slim@sha256:02108f5d322dd89f1c9e552442c25acb0543dfdbc455693a5599624f20d9155d AS builder

WORKDIR /app

COPY pyproject.toml poetry.lock ./

RUN pip install --no-cache-dir poetry poetry-plugin-export && \
    poetry export -f requirements.txt \
    --output requirements.txt \
    --only main


FROM python:3.12.15-slim@sha256:02108f5d322dd89f1c9e552442c25acb0543dfdbc455693a5599624f20d9155d

WORKDIR /app

# Copy requirements from builder
COPY --from=builder /app/requirements.txt .

# Every requirement carries the sha256 hashes poetry.lock already records, so a wheel
# swapped on the index for a pinned version fails this build instead of being installed.
RUN pip install --no-cache-dir --require-hashes -r requirements.txt

# Copy application code
COPY . .

RUN useradd -m appuser && chown -R appuser /app

USER appuser

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/healthz')" || exit 1

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
