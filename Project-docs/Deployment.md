# Deployment Documentation
## APIWeaver

---

## 1. Development Environment

**Local setup via Docker Compose** — mirrors production topology at reduced scale.

```
git clone https://github.com/apiweaver/apiweaver.git
cd apiweaver
cp .env.example .env
docker compose -f docker-compose.dev.yml up --build
```

| Service | Local Port |
|---|---|
| Next.js frontend | 3000 |
| FastAPI backend | 8000 |
| PostgreSQL | 5432 |
| Redis | 6379 |
| Qdrant | 6333 |
| MinIO (S3-compatible, local) | 9000 |
| Local LLM (optional, Ollama/Llama) | 11434 |

Hot-reload enabled for both frontend (Next.js dev server) and backend (`uvicorn --reload`). Seed data script (`scripts/seed_dev.py`) populates a sample project with a pre-parsed OpenAPI spec for immediate UI development without needing a real upload.

---

## 2. Production Environment

Managed SaaS deployment runs on **AWS EKS** (see `Architecture.md §6` deployment diagram). Self-hosted customers deploy via the provided **Helm chart** or **Docker Compose (single-node)** for smaller installations.

---

## 3. Docker

**Backend `Dockerfile` (multi-stage):**
```dockerfile
FROM python:3.12-slim AS builder
WORKDIR /app
COPY pyproject.toml poetry.lock ./
RUN pip install --no-cache-dir poetry && \
    poetry export -f requirements.txt --output requirements.txt --without-hashes
RUN pip install --no-cache-dir -r requirements.txt --target=/deps

FROM python:3.12-slim
WORKDIR /app
COPY --from=builder /deps /usr/local/lib/python3.12/site-packages
COPY . .
RUN useradd -m appuser && chown -R appuser /app
USER appuser
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s CMD curl -f http://localhost:8000/healthz || exit 1
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
```

**Frontend `Dockerfile`:**
```dockerfile
FROM node:20-alpine AS builder
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci
COPY . .
RUN npm run build

FROM node:20-alpine
WORKDIR /app
ENV NODE_ENV=production
COPY --from=builder /app/.next/standalone ./
COPY --from=builder /app/.next/static ./.next/static
COPY --from=builder /app/public ./public
USER node
EXPOSE 3000
CMD ["node", "server.js"]
```

---

## 4. Docker Compose (self-hosted, single-node)

```yaml
version: "3.9"
services:
  web:
    image: apiweaver/web:latest
    ports: ["3000:3000"]
    env_file: .env
    depends_on: [api]

  api:
    image: apiweaver/api:latest
    ports: ["8000:8000"]
    env_file: .env
    depends_on: [postgres, redis, qdrant]

  agent-worker:
    image: apiweaver/agent-worker:latest
    env_file: .env
    depends_on: [postgres, redis, qdrant]
    deploy:
      replicas: 2
    command: celery -A agent_worker.celery_app worker --loglevel=info --concurrency=4
    environment:
      CELERY_BROKER_URL: redis://redis:6379/1
      CELERY_RESULT_BACKEND: redis://redis:6379/2

  postgres:
    image: postgres:16
    environment:
      POSTGRES_DB: apiweaver
      POSTGRES_USER: apiweaver
      POSTGRES_PASSWORD_FILE: /run/secrets/pg_password
    volumes: ["pgdata:/var/lib/postgresql/data"]
    secrets: [pg_password]

  redis:
    image: redis:7-alpine
    volumes: ["redisdata:/data"]

  qdrant:
    image: qdrant/qdrant:latest
    volumes: ["qdrantdata:/qdrant/storage"]

  vault:
    image: hashicorp/vault:latest
    cap_add: [IPC_LOCK]
    environment:
      VAULT_LOCAL_CONFIG: '{"storage":{"file":{"path":"/vault/file"}},"listener":{"tcp":{"address":"0.0.0.0:8200","tls_disable":0}}}'
    volumes: ["vaultdata:/vault/file"]

volumes:
  pgdata:
  redisdata:
  qdrantdata:
  vaultdata:

secrets:
  pg_password:
    file: ./secrets/pg_password.txt
```

---

## 5. Kubernetes

**Helm chart structure:**
```
charts/apiweaver/
├── Chart.yaml
├── values.yaml
├── templates/
│   ├── web-deployment.yaml
│   ├── api-deployment.yaml
│   ├── agent-worker-deployment.yaml
│   ├── hpa.yaml
│   ├── ingress.yaml
│   ├── configmap.yaml
│   ├── secrets.yaml
│   └── networkpolicy.yaml
```

**Key `values.yaml` excerpt:**
```yaml
api:
  replicaCount: 5
  autoscaling:
    enabled: true
    minReplicas: 2
    maxReplicas: 20
    targetCPUUtilizationPercentage: 65
agentWorker:
  replicaCount: 10
  autoscaling:
    enabled: true
    minReplicas: 4
    maxReplicas: 50
    queueDepthTarget: 20
sandboxRunner:
  resources:
    limits: { cpu: "1", memory: "1Gi" }
  networkPolicy:
    egress: "allowlist-only"
```

**HPA example (queue-depth based, via KEDA):**
```yaml
apiVersion: keda.sh/v1alpha1
kind: ScaledObject
metadata:
  name: agent-worker-scaler
spec:
  scaleTargetRef:
    name: agent-worker
  minReplicaCount: 4
  maxReplicaCount: 50
  triggers:
    - type: redis
      metadata:
        address: redis.apiweaver.svc:6379
        listName: celery
        listLength: "20"
```

---

## 6. AWS

| Resource | Purpose |
|---|---|
| EKS | Kubernetes control plane + managed node groups |
| RDS PostgreSQL (Multi-AZ) | Primary database |
| ElastiCache Redis (cluster mode) | Cache, pub/sub, Celery broker |
| S3 | Uploads, generated artifacts, backups |
| CloudFront | CDN for frontend static assets |
| ALB | Layer-7 load balancing |
| Secrets Manager / self-hosted Vault | Secrets storage |
| KMS | Encryption key management |
| Route 53 | DNS |
| VPC (private subnets for data layer) | Network isolation |
| CloudWatch | AWS-native log/metric aggregation (feeds into OTel pipeline) |

---

## 7. Terraform

```hcl
module "eks" {
  source          = "terraform-aws-modules/eks/aws"
  cluster_name    = "apiweaver-prod"
  cluster_version = "1.30"
  vpc_id          = module.vpc.vpc_id
  subnet_ids      = module.vpc.private_subnets

  eks_managed_node_groups = {
    general = {
      instance_types = ["m6i.xlarge"]
      min_size       = 3
      max_size       = 10
      desired_size   = 4
    }
    agents = {
      instance_types = ["c6i.2xlarge"]
      min_size       = 2
      max_size       = 20
      desired_size   = 4
      taints = [{ key = "workload", value = "agents", effect = "NO_SCHEDULE" }]
    }
  }
}

module "rds" {
  source               = "terraform-aws-modules/rds/aws"
  engine               = "postgres"
  engine_version       = "16.3"
  instance_class       = "db.r6g.xlarge"
  multi_az             = true
  storage_encrypted    = true
  kms_key_id           = module.kms.key_arn
  backup_retention_period = 14
}

module "elasticache" {
  source           = "terraform-aws-modules/elasticache/aws"
  engine           = "redis"
  node_type        = "cache.r6g.large"
  num_cache_nodes  = 3
  at_rest_encryption_enabled = true
  transit_encryption_enabled = true
}
```

State managed remotely (S3 backend + DynamoDB lock table); all infrastructure changes go through pull-request review and `terraform plan` output posted to the PR before apply.

---

## 8. GitHub Actions (CI/CD)

```yaml
name: CI/CD
on:
  push:
    branches: [main]
  pull_request:

jobs:
  test:
    runs-on: ubuntu-latest
    services:
      postgres:
        image: postgres:16
        env: { POSTGRES_PASSWORD: test }
        ports: ["5432:5432"]
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with: { python-version: "3.12" }
      - run: pip install poetry && poetry install
      - run: poetry run pytest --cov=app --cov-report=xml
      - run: poetry run ruff check .
      - run: poetry run mypy app/

  build-and-push:
    needs: test
    if: github.ref == 'refs/heads/main'
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: docker/login-action@v3
        with:
          registry: ghcr.io
          username: ${{ github.actor }}
          password: ${{ secrets.GITHUB_TOKEN }}
      - uses: docker/build-push-action@v5
        with:
          push: true
          tags: ghcr.io/apiweaver/api:${{ github.sha }}

  deploy:
    needs: build-and-push
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - run: |
          aws eks update-kubeconfig --name apiweaver-prod
          helm upgrade apiweaver ./charts/apiweaver \
            --set api.image.tag=${{ github.sha }} \
            --namespace apiweaver --wait
```

---

## 9. Environment Variables

| Variable | Description | Required |
|---|---|---|
| `DATABASE_URL` | Postgres connection string | yes |
| `REDIS_URL` | Redis connection string | yes |
| `QDRANT_URL` | Qdrant endpoint | yes |
| `S3_BUCKET_UPLOADS` | Bucket for raw uploads | yes |
| `S3_BUCKET_ARTIFACTS` | Bucket for generated artifacts | yes |
| `VAULT_ADDR` / `VAULT_TOKEN` | Secrets backend | yes |
| `OPENAI_API_KEY` | Model provider key (optional if using Llama only) | conditional |
| `ANTHROPIC_API_KEY` | Model provider key | conditional |
| `JWT_PUBLIC_KEY` / `JWT_PRIVATE_KEY` | RS256 signing keys | yes |
| `GITHUB_APP_ID` / `GITHUB_APP_PRIVATE_KEY` | GitHub Export integration | conditional |
| `GITHUB_APP_CLIENT_ID` / `GITHUB_APP_CLIENT_SECRET` | GitHub OAuth integration | conditional |
| `GITHUB_OAUTH_REDIRECT_URI` | OAuth callback URL | conditional |
| `GITHUB_WEBHOOK_SECRET` | Webhook verification secret | conditional |
| `SANDBOX_MAX_CPU` / `SANDBOX_MAX_MEMORY` / `SANDBOX_TIMEOUT_SECONDS` | Sandbox resource quotas | yes |
| `LANGSMITH_API_KEY` | Agent tracing | recommended |
| `OTEL_EXPORTER_OTLP_ENDPOINT` | Observability collector | recommended |

Secrets injected via Kubernetes Secrets (sourced from Vault via the Vault Agent Injector sidecar) — never baked into container images.

---

## 10. Monitoring (Deployment-level)

- Prometheus scrapes all pods via annotations (`prometheus.io/scrape: true`).
- Grafana dashboards provisioned as code (`/monitoring/dashboards/*.json`) and version-controlled alongside the application.
- Alertmanager routes critical alerts (error rate spike, pod crash-loop, queue depth sustained high) to PagerDuty/Slack.

---

## 11. Logging

- Container stdout/stderr collected by Fluent Bit DaemonSet → shipped to Loki (self-hosted) or CloudWatch Logs (AWS-native option).
- Log retention: 30 days hot, 1 year cold storage (S3) for compliance-sensitive audit logs.
- Structured JSON logging enforced application-wide; correlation IDs (`request_id`, `workflow_run_id`) propagated across all services for cross-service tracing.

---

## 12. Scaling

Summarized from `Architecture.md §7`; deployment-specific note: agent-worker node group uses a dedicated taint/toleration so bursty agent workloads never starve the always-on web/API node group during scale-up events.

---

## 13. Backup

| Data | Backup Method | Frequency | Retention |
|---|---|---|---|
| PostgreSQL | Automated RDS snapshots + continuous WAL archiving (PITR) | Daily snapshot, continuous WAL | 14 days PITR window, monthly snapshot retained 1 year |
| S3 artifacts | Versioning enabled + cross-region replication | Continuous | Per plan-tier retention policy |
| Qdrant | Snapshot API to S3 | Daily | 30 days |
| Vault | Raft snapshot | Daily | 30 days, encrypted separately |

---

## 14. Disaster Recovery

- **RPO (Recovery Point Objective):** ≤ 5 minutes (via continuous WAL archiving for Postgres).
- **RTO (Recovery Time Objective):** ≤ 1 hour for full regional failover.
- **DR strategy:** warm standby in a secondary AWS region — RDS cross-region read replica promoted on failover, S3 cross-region replication already in place, EKS cluster provisioned via the same Terraform module in the secondary region (infrastructure-as-code enables fast stand-up).
- **DR drills:** conducted quarterly; failover runbook version-controlled and tested end-to-end, not just documented.
- **Communication plan:** status page (status.apiweaver.dev) updated automatically via incident-management integration during any DR event.
