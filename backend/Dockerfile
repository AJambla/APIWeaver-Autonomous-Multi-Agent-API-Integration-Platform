FROM python:3.12-slim AS builder

WORKDIR /app

COPY pyproject.toml poetry.lock* ./

RUN pip install --no-cache-dir poetry poetry-plugin-export && \
    poetry export -f requirements.txt \
    --output requirements.txt \
    --without-hashes


FROM python:3.12-slim

WORKDIR /app

# Copy requirements from builder
COPY --from=builder /app/requirements.txt .

# Install all dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY . .

RUN useradd -m appuser && chown -R appuser /app

USER appuser

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/healthz')" || exit 1

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
