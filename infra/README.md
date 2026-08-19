# infra

| Path | Contents | Phase |
|---|---|---|
| `docker/docker-compose.dev.yml` | Docker Compose for API-only local dev (Postgres + Redis) | Phase 1 |
| `docker/docker-compose.single-node.yml` | Full-stack self-hosted single-node Compose (web, api, agent-worker, postgres, redis, qdrant, vault, minio) | Phase 6 |
| `charts/apiweaver/` | Helm chart `apiweaver` per [`Deployment.md`](../Project-docs/Deployment.md) §5 | Phase 6 |
| `terraform/` | AWS infrastructure modules per [`Deployment.md`](../Project-docs/Deployment.md) §7 | Phase 6 |

## Local dev (Phase 1)

Phase 1 only needs Postgres and Redis:

```bash
docker compose -f infra/docker/docker-compose.dev.yml up -d
```

## Full-stack local dev (Phase 6)

For the complete APIWeaver topology including the Next.js frontend, Celery agent-worker, Qdrant vector DB, HashiCorp Vault, and MinIO object storage:

```bash
docker compose -f infra/docker/docker-compose.single-node.yml up --build
```

Services and default ports:
- Next.js frontend: http://localhost:3000
- FastAPI backend: http://localhost:8000
- PostgreSQL: localhost:5432
- Redis: localhost:6379
- Qdrant: http://localhost:6333
- MinIO: http://localhost:9000 (console: http://localhost:9001)
- Vault: http://localhost:8200

Vault runs in dev mode with root token from `.env` (`VAULT_DEV_ROOT_TOKEN_ID`, default `root`).
