"""Custom Prometheus metrics for APIWeaver.

Defines application-level metrics that are not covered by `prometheus-fastapi-instrumentator`
(request count/latency by `handler`, `method` and grouped `status`, e.g. "5xx").

The pipeline runs in the Celery worker in production, so the worker serves these too:
with PROMETHEUS_MULTIPROC_DIR set, every prefork child writes its samples to that
directory and the worker's parent process exposes the aggregate on WORKER_METRICS_PORT
(see agent_worker/celery_app.py). Metrics recorded in the worker were invisible before.

Metrics:
- `apiweaver_workflow_runs_total{status}` / `apiweaver_workflow_duration_seconds{status}`
- `apiweaver_agent_step_duration_seconds{agent_type}` — per graph node
- `apiweaver_repair_attempts_total{agent_type,success}`
- `apiweaver_llm_tokens_spent_total{org_id}`
- `apiweaver_s3_upload_bytes_total` / `apiweaver_s3_download_bytes_total`
- `apiweaver_auth_success_total` / `apiweaver_auth_failure_total{reason}`
- `apiweaver_pipeline_error_total{subsystem,error_type}`
"""

from __future__ import annotations

from prometheus_client import Counter, Histogram
from prometheus_client.registry import CollectorRegistry

registry = CollectorRegistry()

workflow_runs_total = Counter(
    "apiweaver_workflow_runs_total",
    "Workflow executions finished, by final status",
    ["status"],
    registry=registry,
)

workflow_duration_seconds = Histogram(
    "apiweaver_workflow_duration_seconds",
    "Wall-clock duration of one workflow execution",
    ["status"],
    buckets=(10, 30, 60, 120, 300, 600, 1200, 1800, 3600),
    registry=registry,
)

agent_step_duration_seconds = Histogram(
    "apiweaver_agent_step_duration_seconds",
    "Duration of one pipeline node (agent) execution",
    ["agent_type"],
    buckets=(0.5, 1, 2.5, 5, 10, 30, 60, 120, 300, 600),
    registry=registry,
)

repair_attempts_total = Counter(
    "apiweaver_repair_attempts_total",
    "Self-healing repair attempts, by outcome",
    ["agent_type", "success"],
    registry=registry,
)

s3_upload_bytes_total = Counter(
    "apiweaver_s3_upload_bytes_total",
    "Total bytes uploaded to S3/MinIO",
    registry=registry,
)

s3_download_bytes_total = Counter(
    "apiweaver_s3_download_bytes_total",
    "Total bytes downloaded from S3/MinIO",
    registry=registry,
)

llm_tokens_spent_total = Counter(
    "apiweaver_llm_tokens_spent_total",
    "Total LLM tokens spent per organization",
    ["org_id"],
    registry=registry,
)

auth_success_total = Counter(
    "apiweaver_auth_success_total",
    "Total successful authentication attempts",
    registry=registry,
)

auth_failure_total = Counter(
    "apiweaver_auth_failure_total",
    "Total failed authentication attempts",
    ["reason"],
    registry=registry,
)

pipeline_error_total = Counter(
    "apiweaver_pipeline_error_total",
    "Total errors encountered in background tasks or pipeline nodes",
    ["subsystem", "error_type"],
    registry=registry,
)
