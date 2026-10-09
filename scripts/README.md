# scripts

| Script | Purpose |
|---|---|
| `gen_jwt_keys.sh` | Generate the RS256 keypair into `secrets/` (see [`Security.md`](../Project-docs/Security.md) §4) |
| `migrate.py` | Run `alembic upgrade head` once per deploy (init container / job), never on API boot |
| `check_llm.py` | Send one request to the configured LLM provider and report success, latency and quota errors |
| `qdrant-healthcheck.sh` | Container healthcheck: `GET /readyz` on the local Qdrant without curl/wget |
