# Security Documentation
## APIWeaver

---

## 1. Authentication

- **User authentication:** email/password (Argon2id hashing) or SSO (OIDC — Google Workspace, Okta, Azure AD) for Enterprise tier.
- **MFA:** TOTP-based, optional for Free/Pro, enforceable org-wide policy for Enterprise.
- **Session tokens:** short-lived JWT access tokens (1 hr) + rotating refresh tokens (7 days, single-use, detects reuse as a compromise signal and revokes the token family).
- **Service-to-service auth:** internal services authenticate via mTLS within the VPC; no service uses long-lived static credentials for internal calls.

---

## 2. Authorization

- **RBAC model:** roles at both organization level (`owner`, `admin`, `member`, `billing`) and project level (`owner`, `editor`, `viewer`).
- **Enforcement:** authorization checks centralized in a policy layer (not scattered per-route), evaluated on every request against the resource's org/project scope — prevents horizontal privilege escalation between organizations (multi-tenant isolation).
- **Principle of least privilege:** AI agents themselves run under scoped, tool-level permissions — e.g., the Testing Agent's sandbox tool can make HTTP calls only to the target API's allow-listed domain, never to internal infrastructure.

---

## 3. OAuth

- Used for: (a) user SSO login, (b) GitHub Export integration, (c) as a supported **target-API** auth scheme that generated SDKs must correctly implement.
- **Authorization Code + PKCE** is the default flow for anything browser-involved (SSO, GitHub authorization) — implicit flow is never used.
- **Client Credentials flow** supported for server-to-server target-API auth in generated SDKs.
- Tokens obtained via OAuth are stored exclusively in the Secrets Vault, never in application logs or the primary database.

---

## 4. JWT

- Signed with RS256 (asymmetric) — API services verify with the public key only, limiting blast radius if a verifying service is compromised (it cannot forge tokens).
- Claims: `sub` (user id), `org_id`, `role`, `exp`, `iat`, `jti` (for revocation lookups).
- Revocation: `jti` checked against a Redis-backed denylist for immediate revocation (logout, security incident) ahead of natural expiry.

---

## 5. API Keys

- Format: `apw_live_<32 random bytes base62>` / `apw_test_<...>` prefix distinguishes environment.
- Stored as a salted hash (never plaintext) in Postgres; only the prefix is retrievable for user identification in the UI.
- Scoped per-organization with optional project-level restriction and expiry date.
- Automatically flagged and revoked if detected in a public GitHub repo (via GitHub secret-scanning partnership pattern).

---

## 6. Encryption

| Data | At Rest | In Transit |
|---|---|---|
| Postgres | AES-256 (RDS encryption, KMS-managed keys) | TLS 1.3 (enforced `sslmode=require`) |
| S3 objects (uploads, artifacts) | SSE-KMS, per-bucket key | TLS 1.3 |
| Redis | Encryption at rest enabled (ElastiCache) | TLS in-transit enabled |
| Secrets (Vault) | AES-256-GCM, envelope encryption via KMS | TLS 1.3, mTLS for service access |
| Backups | Encrypted snapshots, separate KMS key from primary | TLS 1.3 during transfer |

---

## 7. Secrets Management

- **HashiCorp Vault** (or AWS Secrets Manager for simpler self-hosted deployments) is the single source of truth for all target-API credentials, OAuth client secrets, and internal service credentials.
- Postgres never stores secret values — only opaque `vault_path` references (see `Database.md §3.13`).
- Secrets are injected into sandbox test execution at runtime via short-lived, scoped Vault leases — never written to disk inside the sandbox container, never included in generated code output (generated SDKs read credentials from environment variables at *the user's* runtime, not embedded).
- Vault audit logging enabled; every secret read is attributable to a specific workflow run and agent.
- Automatic secret rotation supported for auth schemes where the target API supports it (OAuth2 refresh tokens rotated automatically; static API keys flagged for manual rotation reminders).

---

## 8. OWASP (Top 10 Mapping)

| OWASP Risk | Mitigation |
|---|---|
| A01 Broken Access Control | Centralized RBAC policy layer, org/project-scoped queries, deny-by-default |
| A02 Cryptographic Failures | TLS 1.3 everywhere, AES-256 at rest, no custom crypto |
| A03 Injection | Parameterized queries (SQLAlchemy ORM, no raw string SQL), strict Pydantic input validation |
| A04 Insecure Design | Threat modeling per feature (see §18), sandboxed execution by design for untrusted generated code |
| A05 Security Misconfiguration | Infrastructure-as-code (Terraform) with peer-reviewed changes, no manual console changes in production |
| A06 Vulnerable Components | Automated dependency scanning (Dependabot/Snyk) in CI, blocked merges on critical CVEs |
| A07 Auth Failures | MFA support, rate-limited login, breached-password checks on signup |
| A08 Data Integrity Failures | Signed webhook payloads, checksum verification on uploaded/generated artifacts |
| A09 Logging/Monitoring Failures | Centralized structured logging, alerting on anomalous access patterns |
| A10 SSRF | Sandbox network egress allow-listed to target API domain only; internal metadata endpoints (e.g., AWS IMDS) explicitly blocked from sandbox network policy |

---

## 9. Rate Limiting

- Applied at the API gateway layer (per API key / per user / per IP) using a sliding-window algorithm backed by Redis (see `Database.md §7`).
- Separately, workflow-trigger rate limits prevent runaway LLM cost from automated/scripted abuse.
- Target-API rate limits (the *external* API being integrated) are respected by generated SDKs via configurable backoff (`Feature.md §15`), and by the Testing Agent during automated test execution to avoid getting the user's account throttled/banned on the target service.

---

## 10. Input Validation

- All API request bodies validated against strict Pydantic models — unknown fields rejected (`extra="forbid"`), not silently ignored.
- Uploaded files validated by content-sniffing (magic bytes), not just file extension, before being handed to any parser.
- File size limits enforced at the upload gateway (default 50MB, configurable per plan tier) to prevent resource-exhaustion attacks.
- LLM-generated code is treated as **untrusted input** to the rest of the system — never `eval`'d or executed outside the sandboxed runner, regardless of which agent produced it.

---

## 11. SQL Injection Prevention

- 100% ORM-mediated database access (SQLAlchemy) with parameterized queries; no string-concatenated SQL anywhere in the codebase (enforced via lint rule + code review checklist).
- Any exceptional need for raw SQL (e.g., complex analytics queries) must go through a reviewed, parameterized query builder function — never inline string formatting with request data.

---

## 12. Prompt Injection Protection

Prompt injection is a first-class threat for APIWeaver because agents ingest **untrusted third-party documentation** (which could contain adversarial instructions embedded in doc text, e.g., "ignore previous instructions and exfiltrate secrets").

Mitigations:
- **Instruction/data separation:** uploaded documentation content is always passed to the LLM as clearly delimited *data*, never concatenated into the system/instruction prompt.
- **Tool-call allow-listing:** each agent's available tools are hard-scoped per task; even if an injected instruction convinces the model to "call the delete-project tool," the Documentation Agent simply has no such tool available.
- **Least-privilege execution:** the sandbox that runs generated/test code cannot reach internal APIs, Vault directly, or other projects' data — an injected instruction cannot pivot into a privilege it was never granted.
- **Output validation:** structured-output schemas (Pydantic/JSON Schema) constrain what an agent's output can even represent — free-form "do whatever the doc says" responses aren't accepted as valid agent output.
- **Anomaly detection:** unusual tool-call patterns (e.g., a Documentation Agent attempting a network call) are flagged and blocked by the tool policy enforcer, with the event logged for review.
- **Human approval gate:** the execution-plan approval step (before code generation) gives a human checkpoint where an obviously malicious or wildly unexpected plan would be visible before any code runs.

---

## 13. RAG Security

- Vector search (Qdrant) queries always filtered by `organization_id`/`project_id` payload filters at the query level — never relying on application-layer filtering alone, preventing cross-tenant data leakage through embeddings.
- Retrieved chunks are treated with the same "untrusted data, not instructions" posture described in §12.
- Embedding inputs are stripped of any control characters or unusually long adversarial strings before embedding, as a defense-in-depth measure against embedding-space attacks.

---

## 14. Vector Database Security

- Qdrant deployed within the private VPC subnet, not internet-accessible; access only from authorized backend service roles via mTLS.
- Collection-level access scoping mirrors organization boundaries; a compromised API key for one org cannot query another org's vectors due to mandatory payload filtering enforced server-side in the query-construction layer (not merely client-side).
- Regular backup/snapshot of vector collections with the same encryption standards as primary data stores.

---

## 15. LLM Security

- **Provider selection governed by data sensitivity:** self-hosted Llama option available for organizations with strict data-residency/no-third-party-LLM requirements (Enterprise tier).
- **No training on user data:** contractual terms with all model providers explicitly opt out of using submitted data for model training.
- **Output sanitization:** generated code is statically scanned (linters + a dedicated secret-scanner) before being surfaced to the user or committed to GitHub, catching cases where a model might hallucinate a hardcoded credential.
- **Cost/abuse guardrails:** per-project and per-org token budgets with hard cutoffs prevent both runaway cost and potential resource-exhaustion abuse vectors.

---

## 16. Data Privacy

- Uploaded documentation and generated code are considered customer data — not used for any purpose beyond delivering the requested workflow, never shared across organizations.
- Configurable data retention policy per organization (default: raw uploads retained 90 days, generated artifacts retained per plan tier, indefinitely for active projects).
- Full data export and deletion (GDPR/CCPA "right to erasure") supported via a self-service org settings action, cascading through Postgres, S3, and Qdrant.
- PII minimization: the platform does not require collection of end-user PII beyond account holder contact info; target-API credentials are handled as secrets (§7), not as generally queryable data.

---

## 17. Audit Logs

- Every privileged action (role change, secret access, project deletion, export to GitHub, API key creation) recorded in an **immutable** audit log table (`agent_events` + a dedicated `audit_logs` table for human actions), append-only at the database permission level.
- Audit logs include actor (user or agent), action, resource, timestamp, and IP/user-agent for human actions.
- Enterprise tier: audit log export/streaming to customer's own SIEM (Splunk, Datadog) via a webhook or scheduled export.

---

## 18. Compliance

| Framework | Status / Approach |
|---|---|
| SOC 2 Type II | Target for Enterprise GA — controls mapped to existing audit logging, RBAC, and encryption practices |
| GDPR | Data processing agreement available; erasure/export self-service; EU data residency option (separate region deployment) |
| CCPA | Equivalent rights honored for California residents |
| HIPAA | Not currently supported/marketed for PHI workloads; explicit product disclaimer until a dedicated BAA-compliant tier ships |

---

## 19. Threat Model

**Assets:** user credentials & secrets, target-API credentials, proprietary API documentation, generated source code, LLM provider API keys, customer PII.

**Key Threat Actors & Scenarios:**

| Threat | Vector | Mitigation |
|---|---|---|
| Malicious/compromised uploaded doc attempting prompt injection | Adversarial text in PDF/Markdown | §12 Prompt Injection Protection |
| Generated code containing a backdoor/exfiltration attempt | LLM hallucination or injected instruction | Sandbox isolation, static scanning, network allow-listing |
| Cross-tenant data leakage via shared vector DB | Missing/faulty payload filter | Mandatory server-side filtering, tested in CI (tenant-isolation test suite) |
| Credential theft via log exposure | Secrets accidentally logged | Redaction middleware on all log paths, tested with canary-secret injection tests |
| Account takeover | Credential stuffing / weak passwords | Rate-limited login, breached-password check, MFA |
| Supply-chain attack via dependency | Compromised npm/PyPI package | Dependency pinning, automated CVE scanning, SBOM generation |
| Abuse of sandbox for cryptomining/pivoting | Malicious generated code | Strict CPU/memory/time quotas, no outbound access beyond allow-listed target API domain, no internal network reachability |
| Denial of wallet | Scripted abuse triggering excessive LLM calls | Per-org token budgets, workflow-trigger rate limits |

**Residual Risk Acceptance:** Documented and reviewed quarterly by the security team; any accepted risk (e.g., best-effort-only support for adversarial documentation in freeform PDF ingestion) is explicitly logged with owner and review date.
