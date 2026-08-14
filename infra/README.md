# infra

| Path | Contents | Phase |
|---|---|---|
| `docker/` | Docker Compose files for local dev | Phase 1 (partial: postgres + redis), completed Phase 6 |
| `charts/` | Helm chart `apiweaver` per [`Deployment.md`](../Project-docs/Deployment.md) §5 | Phase 6 |
| `terraform/` | AWS infrastructure per [`Deployment.md`](../Project-docs/Deployment.md) §7 | Phase 6 |

## Local dev (Phase 1)

Phase 1 only needs Postgres and Redis:

```bash
docker compose -f infra/docker/docker-compose.dev.yml up -d
```

Qdrant, MinIO, Vault, and the application services join this file in the phases that
introduce them (Phase 2 for MinIO/Vault/Qdrant, Phase 6 for the full topology).
