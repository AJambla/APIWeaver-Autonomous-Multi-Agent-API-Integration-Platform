# Security Policy

APIWeaver is an enterprise-grade autonomous API integration platform. We take the security of our platform, user credentials, and customer APIs with utmost seriousness.

---

## Supported Versions

We actively maintain and provide security patches for the following versions of APIWeaver:

| Version | Supported          | Security Maintenance Status |
| :------ | :----------------- | :-------------------------- |
| 1.0.x   | :white_check_mark: | Currently Supported         |
| < 1.0   | :x:                | End of Life                 |

---

## Reporting a Vulnerability

If you discover a security vulnerability in APIWeaver, please **do not open a public issue**. Instead, follow responsible disclosure practices:

1. **Email:** Send your report to `security@apiweaver.dev` (or through GitHub's [Private Vulnerability Reporting](https://github.com/AJambla/APIWeaver-Autonomous-Multi-Agent-API-Integration-Platform/security/advisories)).
2. **Details to Include:**
   - Detailed description of the vulnerability and potential impact.
   - Exact steps or proof-of-concept (PoC) code to reproduce the issue.
   - Affected components (API, Frontend, Worker, Docker Sandbox, Vault Integration).
   - Any remediation suggestions you may have.

### Our Response Timeline
- **Initial Acknowledgment:** Within 24 hours of receipt.
- **Triage & Assessment:** Within 72 hours of receipt.
- **Remediation & Fix Release:** Critical vulnerabilities are prioritized for resolution within 7 business days.
- **Public Disclosure:** Coordinated disclosure after patches have been published.

---

## Core Security & Architecture Controls

APIWeaver incorporates defense-in-depth principles across all architectural tiers:

### 1. Authentication & Credentials
- **Argon2id Hashing:** User passwords hashed using RFC-recommended parameters (`m=64MiB, t=3, p=4`).
- **RS256 JWT Access Tokens:** 60-minute lifetime cryptographically signed using private/public key pairs.
- **Token Rotation & Replay Protection:** Single-use refresh tokens with automatic token family invalidation upon reuse detection.
- **Redis JTI Denylist:** Immediate session termination capability ahead of token expiration.
- **API Keys:** Opaque high-entropy tokens (`apw_live_*`), stored exclusively as SHA-256 hex digests.

### 2. Secrets Management & Isolation
- **HashiCorp Vault KV v2:** Target API credentials and OAuth access/refresh tokens are written directly to Vault and never stored in PostgreSQL or returned in API responses.
- **Automatic Token Purging:** When external connections (e.g., GitHub OAuth) are disconnected or revoked, corresponding secrets are permanently purged from Vault.
- **Path Traversal Protection:** Vault paths and object storage keys are strictly validated against directory traversal attacks (`..`).

### 3. Untrusted Code Execution & Sandbox Defense
- **Production Sandbox Isolation:** LLM-generated client code and validation suites are strictly prohibited from in-process execution in `production` and `staging` environments.
- **Docker Sandbox Executor:** Generated code runs in unprivileged (`nobody:nobody`), network-restricted Docker containers with strict CPU, memory, PID, and timeout caps.

### 4. Multi-Tenancy & Data Integrity
- **Query-Level Scoping:** All database operations and vector similarity queries enforce strict `organization_id` / `project_id` containment filters.
- **Database Immutability:** Audit logs enforce append-only policies (`audit_logs` table disallows updates and deletions).
- **Security Response Headers:** Enforces `X-Content-Type-Options: nosniff`, `X-Frame-Options: DENY`, `X-XSS-Protection: 1; mode=block`, and `Referrer-Policy: strict-origin-when-cross-origin`.
