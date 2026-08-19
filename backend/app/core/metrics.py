"""Custom Prometheus metrics for APIWeaver.

Defines application-level metrics that are not covered by `prometheus-fastapi-instrumentator`
(default request latency/status by route).

Metrics:
- `apiweaver_active_workflow_runs` — current number of in-flight workflow runs
- `apiweaver_celery_queue_depth` — Celery task queue depth
- `apiweaver_s3_upload_bytes_total` / `apiweaver_s3_download_bytes_total`
- `apiweaver_llm_tokens_spent_total` — LLM token consumption per org
- `apiweaver_auth_success_total` / `apiweaver_auth_failure_total`
"""

from __future__ import annotations

from prometheus_client import Counter, Gauge
from prometheus_client.registry import CollectorRegistry

registry = CollectorRegistry()

active_workflow_runs = Gauge(
    "apiweaver_active_workflow_runs",
    "Number of workflow runs currently in progress",
    registry=registry,
)

celery_queue_depth = Gauge(
    "apiweaver_celery_queue_depth",
    "Number of tasks pending in the Celery queue",
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
