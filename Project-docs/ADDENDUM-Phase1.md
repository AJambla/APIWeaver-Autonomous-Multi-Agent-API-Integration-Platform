# Spec Addendum — Phase 1

Three tables are required by `Security.md` but absent from `Database.md §3`. They are
implemented in Phase 1 and documented here for folding back into `Database.md`.

---

## A.1 `refresh_tokens`

Required by **`Security.md §1`**: "rotating refresh tokens (7 days, single-use, detects
reuse as a compromise signal and revokes the token family)." Family-level revocation
needs a persisted family identifier and a per-token used/revoked marker — neither is
expressible in a stateless JWT, and Redis cannot provide the durable audit trail
`§17` expects for a compromise signal.

| Column | Type | Constraints |
|---|---|---|
| id | UUID | PK, default `gen_random_uuid()` |
| user_id | UUID | FK → users.id ON DELETE CASCADE, NOT NULL |
| family_id | UUID | NOT NULL — all tokens descended from one login share this |
| token_hash | CHAR(64) | UNIQUE, NOT NULL — SHA-256 of the opaque token |
| expires_at | TIMESTAMPTZ | NOT NULL |
| used_at | TIMESTAMPTZ | NULL — non-null means already redeemed; a second redemption is a replay |
| revoked_at | TIMESTAMPTZ | NULL |
| created_at | TIMESTAMPTZ | NOT NULL DEFAULT now() |

**Indexes:** `idx_refresh_tokens_user_id (user_id)`, `idx_refresh_tokens_family_id (family_id)`.

> The token itself is 32 random bytes, returned to the client once. Only its SHA-256 is
> stored, so this row is a lookup handle — not a credential at rest.

---

## A.2 `api_keys`

Required by **`Security.md §5`** and **`API.md §1`** (`POST /api/v1/org/{org_id}/api-keys`).
`§5` specifies salted-hash storage in Postgres with only the prefix retrievable,
per-organization scope with optional project restriction, and an expiry date.

| Column | Type | Constraints |
|---|---|---|
| id | UUID | PK |
| organization_id | UUID | FK → organizations.id ON DELETE CASCADE, NOT NULL |
| project_id | UUID | FK → projects.id ON DELETE CASCADE, NULL — optional restriction |
| name | VARCHAR(255) | NOT NULL |
| key_prefix | VARCHAR(20) | NOT NULL — e.g. `apw_live_`, the only retrievable part |
| key_hash | CHAR(64) | UNIQUE, NOT NULL |
| created_by | UUID | FK → users.id |
| expires_at | TIMESTAMPTZ | NULL |
| revoked_at | TIMESTAMPTZ | NULL |
| created_at | TIMESTAMPTZ | NOT NULL DEFAULT now() |

**Indexes:** `idx_api_keys_org_id (organization_id)`, `idx_api_keys_prefix (key_prefix)`.

---

## A.3 `audit_logs`

Required by **`Security.md §17`**, which names it explicitly: "a dedicated `audit_logs`
table for human actions, append-only at the database permission level."

| Column | Type | Constraints |
|---|---|---|
| id | BIGSERIAL | PK |
| organization_id | UUID | FK → organizations.id, NOT NULL |
| actor_user_id | UUID | FK → users.id, NULL (null for `system`/`agent` actors) |
| actor_type | VARCHAR(20) | NOT NULL CHECK IN ('user','agent','system') |
| action | VARCHAR(100) | NOT NULL |
| resource_type | VARCHAR(50) | NULL |
| resource_id | VARCHAR(100) | NULL |
| ip_address | INET | NULL |
| user_agent | VARCHAR(500) | NULL |
| event_metadata | JSONB | NULL |
| created_at | TIMESTAMPTZ | NOT NULL DEFAULT now() |

**Indexes:** `idx_audit_logs_org_created (organization_id, created_at)`, `idx_audit_logs_actor (actor_user_id)`.

> Column named `event_metadata` rather than `metadata` — `metadata` is reserved on
> SQLAlchemy's declarative base and cannot be used as an attribute name.

**Append-only enforcement** is a *database permission* concern per `§17`: the
application role is granted `INSERT`/`SELECT` but not `UPDATE`/`DELETE` on this table.
That `GRANT` belongs to infrastructure provisioning (Phase 6 / Terraform), not to a
schema migration, since Alembic runs as the owning role. Phase 1 enforces it at the
application layer — `audit_service` exposes no update or delete path — and the
restriction is tracked as a Phase 6 deliverable.

---

## A.4 Note on `tool_calls.agent_event_id`

`Database.md §3.17` declares `agent_event_id BIGINT FK → agent_events.id ON DELETE CASCADE`.
Because `agent_events` is partitioned by `created_at` (`§3.16`), Postgres requires the
partition key in any unique constraint — so its primary key is `(id, created_at)`, and
`id` alone is not a valid FK target. `tool_calls.agent_event_id` is therefore an indexed
`BIGINT` with integrity maintained by the application. Restoring a true FK would require
either a composite `(agent_event_id, agent_event_created_at)` column pair or dropping
partitioning; neither is worth the cost for an append-only trace table.
