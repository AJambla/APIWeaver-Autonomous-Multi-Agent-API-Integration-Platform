# APIWeaver — Project Scope, Changes & Future Roadmap

> **Status:** Proposed baseline / single source of truth

## 1. Project Definition

> **APIWeaver automatically converts REST APIs into verified, safety-gated MCP tools, with sandbox validation and optional live testing.**

APIWeaver is an **AI-powered REST-to-MCP conversion and verification platform**.

The primary transformation is:

```text
REST API / API Documentation
            ↓
      API Understanding
            ↓
    Dependency Analysis
            ↓
       MCP Generation
            ↓
       Safety Analysis
            ↓
      Sandbox Testing
            ↓
   Diagnose → Repair → Retest
            ↓
      Optional Live Test
            ↓
      Verified MCP Server
```

The project is **not** primarily an SDK generator, generic API integration platform, API proxy generator, or multi-output code generator.

---

# 2. Core Goal

APIWeaver should make it possible for a user to take an existing REST API and turn it into reliable AI-usable MCP tools without manually implementing every tool.

The core value comes from combining:

- API understanding
- dependency-aware planning
- MCP generation
- safety analysis
- sandbox verification
- automatic diagnosis and repair
- optional live testing

The main product output is a **verified MCP server/tool bundle**.

---

# 3. Primary Output

The primary output is:

> **A verified MCP server that exposes the target REST API as AI-usable tools.**

Conceptually:

```text
apiweaver-mcp/
├── MCP server
├── Tool definitions
├── Input/output schemas
├── Authentication integration
├── Safety metadata
├── Tests
├── Verification report
└── Documentation
```

The exact generated structure can evolve, but **MCP is the first-class and primary output**.

---

# 4. Inputs

## Structured inputs

- OpenAPI 3.x
- Swagger 2.0
- Postman collections

These should be processed deterministically wherever possible.

```text
OpenAPI
   ↓
Deterministic parser
   ↓
Normalized API representation
```

## Unstructured documentation

Keep support for:

- PDF
- HTML
- Markdown
- API documentation
- additional textual API information

These may contain authentication rules, pagination behavior, required headers, workflows, business rules, rate limits, and endpoint prerequisites that are not fully represented in an API schema.

---

# 5. RAG + Qdrant

## Decision: KEEP

RAG is useful for unstructured documentation.

```text
PDF / HTML / Markdown
          ↓
       Chunking
          ↓
      Embeddings
          ↓
        Qdrant
          ↓
   Relevant documentation
          ↓
          LLM
```

RAG should **not** replace deterministic OpenAPI parsing.

The intended architecture is:

```text
Structured API → Deterministic parser
Unstructured docs → RAG
                         ↓
                 Unified API Context
```

Qdrant is therefore a **supporting dependency**, not the center of the product.

For structured OpenAPI-only workflows, unnecessary RAG processing should be avoided.

---

# 6. API Understanding

APIWeaver should build a unified understanding from:

```text
OpenAPI / Swagger / Postman
+
PDF / HTML / Markdown
```

The result should contain:

- endpoints
- parameters
- request schemas
- response schemas
- authentication requirements
- documentation-derived rules
- endpoint relationships
- safety information

---

# 7. Dependency Analysis

Dependency awareness is a core differentiator.

An API is not merely a flat list of endpoints.

Example:

```text
Authenticate
     ↓
Create Account
     ↓
Get Account
     ↓
Create Transaction
     ↓
Get Transaction
```

APIWeaver should identify:

- ID dependencies
- authentication dependencies
- resource lifecycle relationships
- response-to-request parameter relationships
- prerequisite endpoints
- endpoint ordering

The dependency graph should be used when planning MCP tools and verification.

---

# 8. MCP Generation

The generator converts API operations into MCP tools.

Example:

```text
REST:
GET /users/{user_id}
```

becomes conceptually:

```text
MCP:
get_user(user_id)
```

Generated tools should contain:

- tool name
- description
- input schema
- output schema
- request mapping
- authentication requirements
- safety metadata
- error behavior

**SDK generation is removed. MCP generation is the only primary code-generation target.**

---

# 9. Safety Gates

Safety is a first-class feature.

Example:

```text
GET /users
        ↓
Low risk

POST /users
        ↓
State changing

POST /transfer
        ↓
High risk

DELETE /users/{id}
        ↓
Destructive
```

Potentially destructive operations should require explicit confirmation.

Conceptually:

```text
requires_confirmation = true
```

The goal is to prevent an AI agent from silently performing dangerous actions.

---

# 10. Sandbox Verification

Docker remains important because sandbox execution is part of the core verification process.

Workflow:

```text
Generate MCP
     ↓
Create isolated sandbox
     ↓
Run tests
     ↓
Observe behavior
     ↓
Collect failures
     ↓
Clean up sandbox
```

Sandbox execution should enforce appropriate:

- CPU limits
- memory limits
- process limits
- timeouts
- filesystem restrictions
- network restrictions where appropriate
- non-root execution

The sandbox does not need to be a permanently running service. It should be created when execution/testing is required.

---

# 11. Verification Levels

The word **verified** must be precise.

## Level 1 — Static verification

Validate:

- API specification
- MCP schema
- tool definitions
- parameters
- generated structure
- configuration

## Level 2 — Sandbox verification

Validate:

- generated requests
- parameters
- schemas
- execution behavior
- tool-to-endpoint mapping
- error handling

## Level 3 — Optional live verification

The user explicitly enables testing against the real API.

Additional controls should include:

- credentials
- environment selection
- test data
- destructive-operation restrictions
- confirmation
- rate limits
- timeouts

### Important limitation

Passing sandbox/mock tests does **not** automatically prove production correctness against a third-party API.

The report should be explicit:

```text
Static verification: PASS
Sandbox verification: PASS
Live verification: NOT PERFORMED
Production behavior: NOT GUARANTEED
```

---

# 12. Self-Healing Repair Loop

The verification workflow should support:

```text
Generate
   ↓
Test
   ↓
PASS ─────────→ Continue
   │
   ↓ FAIL
Diagnose
   ↓
Repair
   ↓
Retest
   ↓
PASS ─────────→ Continue
   │
   ↓ FAIL
Retry / Stop
```

Potential failure categories include:

- authentication errors
- schema mismatches
- validation errors
- rate limiting
- network errors
- server errors
- generated-code bugs
- API-specific problems
- unknown failures

Repair attempts must be bounded.

---

# 13. LangGraph

## Decision: KEEP

LangGraph should be the primary AI workflow orchestration layer.

The workflow naturally contains:

- state
- branching
- retries
- checkpoints
- conditional transitions
- iterative repair

Conceptually:

```text
Understand
    ↓
Plan
    ↓
Generate
    ↓
Test
    ↓
 ┌── PASS
 │
 ↓ FAIL
Diagnose
    ↓
Repair
    ↓
Retest
```

Not every component should be an agent.

---

# 14. AI vs Deterministic Components

## Deterministic code should handle

- OpenAPI parsing
- schema validation
- MCP schema validation
- sandbox management
- resource limits
- execution
- persistence
- packaging
- authentication mechanics
- deterministic safety rules
- deterministic dependency extraction

## LLM/agent components should handle

- ambiguous documentation
- semantic interpretation
- planning
- MCP generation decisions
- tool descriptions
- failure diagnosis
- repair reasoning
- documentation interpretation

The target architecture is:

```text
Deterministic Engine
        +
       LLM
        +
    LangGraph
```

not “LLM does everything.”

---

# 15. FastAPI

## Decision

**KEEP FastAPI as APIWeaver's backend.**

It should provide:

- authentication
- project management
- API upload
- workflow creation
- workflow status
- verification results
- MCP bundle retrieval
- workflow events
- live-testing controls
- safety approval endpoints

Important distinction:

```text
FastAPI as APIWeaver backend → KEEP
Generated FastAPI proxy       → REMOVE
```

---

# 16. Frontend

The frontend should focus on outcomes and evidence rather than agent choreography.

Preferred UI flow:

```text
API
 ↓
Understanding
 ↓
Dependencies
 ↓
MCP tools
 ↓
Safety
 ↓
Verification
 ↓
Result
```

Useful UI areas:

- API/documentation upload
- dependency graph
- generated MCP tools
- generated code viewer
- test results
- repair history
- safety flags
- approval controls
- verification report
- live-testing controls
- workflow events

Avoid making the main UX:

```text
Agent 1 → Agent 2 → Agent 3 → Agent 4
```

---

# 17. SSE

## Decision: KEEP

SSE should stream workflow progress to the frontend.

Example:

```text
Parsing API
Building dependency graph
Generating tools
Running sandbox
Test failed
Diagnosing
Repairing
Retesting
Verification complete
```

SSE is supporting infrastructure, not a product output.

---

# 18. PostgreSQL

## Decision: KEEP

PostgreSQL can store:

- users
- projects
- API specifications
- documentation metadata
- workflow runs
- workflow state
- agent events
- test results
- verification results
- safety decisions
- MCP metadata
- audit information

### Remove unnecessary database complexity

Do not initially use:

- date partitioning
- complicated tenant schemas
- excessive enterprise abstractions

Use normal relational tables until actual scale requires more.

---

# 19. Secrets

## Vault: REMOVE

Vault is too heavy for the current small-scale architecture.

However, secure credential handling remains mandatory.

Credentials must never be:

- sent to the LLM
- embedded in generated source code
- exposed to the frontend
- written to logs
- placed into prompts

Preferred model:

```text
User credential
      ↓
Encrypted secure storage
      ↓
Execution layer
      ↓
Runtime injection
      ↓
API request
```

A future deployment can use cloud KMS/secret-management services without making Vault a mandatory application dependency.

---

# 20. Authentication / Authorization

## Keep

- authentication
- basic authorization
- project-level access control

## Remove initially

- extensive enterprise RBAC
- complex tenant isolation
- organization hierarchy
- granular enterprise permission matrices
- enterprise billing architecture

Initial model:

```text
User
 ↓
Project
 ↓
API
 ↓
Workflow
 ↓
MCP
```

not:

```text
Organization
 ↓
Tenant
 ↓
Team
 ↓
Role
 ↓
Permission
 ↓
Policy
```

Enterprise access control can be added later when there is a real requirement.

---

# 21. Celery + Redis Decision

## Recommended decision: KEEP BOTH, BUT KEEP THEM SIMPLE

This is the main architectural decision to make carefully.

APIWeaver workflows can involve:

```text
LLM calls
+
RAG
+
generation
+
sandbox startup
+
testing
+
repair
+
retesting
+
optional live testing
```

These may take longer than a normal HTTP request.

Therefore, background execution is useful for production.

Recommended architecture:

```text
Frontend
   ↓
FastAPI
   ↓
Create workflow
   ↓
Queue task
   ↓
Redis
   ↓
Celery Worker
   ↓
LangGraph
   ↓
Sandbox / RAG / Generation
   ↓
PostgreSQL
   ↓
SSE
   ↓
Frontend
```

### Why keep Celery?

Celery provides:

- background execution
- task retries
- worker isolation
- task time limits
- controlled concurrency
- mature task execution

### Why keep Redis?

Redis should initially have one clear job:

> **Celery broker / task transport.**

Do not make Redis a general-purpose dependency for caching, streams, sessions, rate limiting, etc. unless a real requirement appears.

### Small-scale production setup

Start with:

```text
1 FastAPI backend
1 Celery worker
1 Redis
1 PostgreSQL
1 Qdrant
1 sandbox mechanism
```

Scale workers only when actual workload requires it.

### Final decision

```text
Celery → KEEP
Redis   → KEEP
```

They are **supporting infrastructure**, not product features.

If later measurements prove workflows can be handled more simply, the task execution layer can be replaced. Keep the workflow interface abstract enough to allow that.

---

# 22. Terraform

## Decision: KEEP

Terraform is useful for deploying APIWeaver to AWS/cloud infrastructure.

Terraform is separate from product logic:

```text
APIWeaver
    ↓
REST → MCP
```

versus:

```text
Terraform
    ↓
Provision cloud infrastructure
```

Terraform can manage:

- networking
- compute
- databases
- storage
- IAM
- security groups
- monitoring infrastructure
- deployment resources

Terraform should remain deployment infrastructure, not application logic.

---

# 23. Docker

## Keep

Docker has two important roles:

1. sandbox execution
2. application/service deployment

## Remove

Do not generate Docker packages as a user-facing APIWeaver output.

```text
Docker sandbox       → KEEP
Docker deployment    → KEEP
Docker export        → REMOVE
```

---

# 24. Prometheus + Grafana

## Decision: KEEP

Useful production metrics include:

- workflow duration
- workflow success/failure
- sandbox execution time
- repair attempts
- API latency
- queue depth
- worker utilization
- error counts
- LLM-related metrics

Prometheus collects metrics and Grafana visualizes them.

They are operational infrastructure, not part of the MCP output.

---

# 25. Langfuse

## Decision: KEEP

Langfuse is useful because APIWeaver is LLM-heavy.

It can provide:

- LLM traces
- prompts/responses
- token usage
- latency
- model behavior
- agent execution debugging
- cost analysis
- failure investigation

Langfuse should remain an observability layer, not a hard dependency of the core business logic.

---

# 26. Recommended Small-Scale Production Stack

```text
Frontend
    React
      │
      ↓
Backend
    FastAPI
      │
      ├────────────→ PostgreSQL
      │
      ├────────────→ Redis
      │                  │
      │                  ↓
      │               Celery
      │                  │
      │                  ↓
      │              LangGraph
      │                  │
      │                  ↓
      │               Sandbox
      │
      ├────────────→ Qdrant
      │
      └────────────→ LLM Provider

Observability:
    Prometheus
    Grafana
    Langfuse

Deployment:
    Docker
    Terraform
```

Every retained component has a defined purpose.

---

# 27. Component Classification

| Component | Decision | Role |
|---|---|---|
| MCP generation | CORE | Main product output |
| Safety gates | CORE | Protect AI-driven API actions |
| Sandbox | CORE | Verification |
| LangGraph | CORE | AI workflow orchestration |
| LLM | CORE | Understanding/generation/diagnosis |
| OpenAPI parser | CORE | Deterministic API understanding |
| Dependency graph | CORE | Endpoint relationships |
| PDF/HTML/Markdown | CORE capability | Documentation understanding |
| RAG | SUPPORTING | Unstructured documentation retrieval |
| Qdrant | SUPPORTING | RAG vector store |
| Live testing | CORE capability, optional execution | Real API verification |
| PostgreSQL | CORE infrastructure | Persistent state |
| FastAPI | CORE infrastructure | Backend |
| React | CORE infrastructure | UI |
| SSE | SUPPORTING | Real-time workflow updates |
| Docker | CORE/SUPPORTING | Sandbox + deployment |
| Secure secret handling | CORE | Credential protection |
| Celery | SUPPORTING | Background workflows |
| Redis | SUPPORTING | Celery broker |
| Terraform | INFRASTRUCTURE | Cloud provisioning |
| Prometheus | INFRASTRUCTURE | Metrics |
| Grafana | INFRASTRUCTURE | Visualization |
| Langfuse | INFRASTRUCTURE | LLM observability |
| SDK generation | REMOVE | Outside scope |
| FastAPI proxy export | REMOVE | Outside scope |
| GitHub export | REMOVE | Outside scope |
| Docker package export | REMOVE | Outside scope |
| Vault | REMOVE | Too heavy for current scale |
| Extensive RBAC | REMOVE | Premature |
| Multi-tenancy | REMOVE | Premature |
| DB partitioning | REMOVE | Premature |
| Kubernetes/Helm | FUTURE | Only when scale requires it |

---

# 28. Core Architecture

```text
                         APIWeaver
                            │
                            ↓
                ┌───────────────────────┐
                │      API Ingestion     │
                └───────────┬───────────┘
                            │
              ┌─────────────┴─────────────┐
              ↓                           ↓
       Structured APIs             Documentation
       OpenAPI/Swagger             PDF/HTML/MD
              ↓                           ↓
      Deterministic Parser              RAG
              └─────────────┬─────────────┘
                            ↓
                   Unified API Context
                            ↓
                  Dependency Analysis
                            ↓
                       LangGraph
                            ↓
                  MCP Tool Generation
                            ↓
                     Safety Analysis
                            ↓
                     Sandbox Tests
                            ↓
                    ┌───────┴───────┐
                    ↓               ↓
                  PASS             FAIL
                    ↓               ↓
                 Continue        Diagnose
                                    ↓
                                  Repair
                                    ↓
                                  Retest
                                    ↓
                              PASS / STOP
                                    ↓
                         Optional Live Testing
                                    ↓
                         Verification Report
                                    ↓
                           MCP Server Bundle
```

---

# 29. User Journey

## Step 1 — Provide API

Upload:

```text
OpenAPI
Swagger
Postman
```

Optionally:

```text
PDF
HTML
Markdown
```

## Step 2 — Understand

APIWeaver identifies:

- endpoints
- parameters
- schemas
- authentication
- dependencies
- documentation rules

## Step 3 — Plan

Build endpoint relationships and dependencies.

## Step 4 — Generate MCP

Generate MCP tools.

## Step 5 — Safety Analysis

Identify potentially dangerous operations.

## Step 6 — Sandbox Verification

Execute generated tools in isolation.

## Step 7 — Repair

If tests fail:

```text
Failure
 ↓
Diagnosis
 ↓
Repair
 ↓
Retest
```

## Step 8 — Optional Live Test

User explicitly enables live testing.

## Step 9 — Result

User receives:

```text
Verified MCP Server
+
Tests
+
Verification Report
+
Documentation
```

---

# 30. Verification Report

The system should generate a first-class verification report.

It should include:

## API understanding

- endpoints discovered
- schemas discovered
- documentation sources used

## Dependency analysis

- dependencies
- lifecycle relationships
- unresolved dependencies

## MCP generation

- tools generated
- schemas generated
- safety classifications

## Testing

- static tests
- sandbox tests
- live tests if enabled

## Repair

- failures
- diagnoses
- repair attempts
- final outcomes

## Security

- destructive tools
- confirmation requirements
- credential handling

## Limitations

Example:

```text
Sandbox verification: PASS
Live verification: NOT PERFORMED
Production API behavior: NOT GUARANTEED
```

---

# 31. Changes From the Previous Project

## Remove product outputs

- Python SDK generation
- TypeScript SDK generation
- generic SDK generation
- FastAPI proxy generation
- GitHub export
- Docker package export

## Remove/simplify infrastructure

- Vault
- extensive RBAC
- extensive multi-tenancy
- database partitioning
- unnecessary enterprise abstractions

## Keep infrastructure with a direct purpose

- PostgreSQL
- Redis
- Celery
- Qdrant
- Docker
- Terraform
- Prometheus
- Grafana
- Langfuse

## Reposition the project

Old direction:

> General autonomous API integration platform.

New direction:

> **Autonomous REST-to-MCP conversion and verification platform.**

---

# 32. Refactoring Priorities

## Priority 1 — MCP-first product

Every feature should answer:

> Does this help turn an API into a reliable MCP tool?

If not, it should not be a first-choice feature.

## Priority 2 — Remove unnecessary outputs

Delete or isolate:

- SDK generation
- FastAPI export
- GitHub export
- Docker export

## Priority 3 — Simplify infrastructure

Remove:

- Vault
- extensive tenant architecture
- enterprise RBAC
- DB partitioning

Keep:

- PostgreSQL
- Redis/Celery
- Qdrant/RAG
- Docker
- observability
- Terraform

## Priority 4 — Robust workflow

Make this reliable:

```text
Ingest
 ↓
Understand
 ↓
Plan
 ↓
Generate
 ↓
Safety
 ↓
Sandbox
 ↓
Diagnose
 ↓
Repair
 ↓
Retest
 ↓
Verify
 ↓
MCP
```

## Priority 5 — Production deployment

Ensure:

- clean Docker deployment
- required secrets/bootstrap process
- PostgreSQL initialization
- Qdrant initialization
- Redis startup
- Celery worker startup
- sandbox image build
- health checks
- configuration management
- Terraform deployment path
- Prometheus/Grafana integration
- Langfuse integration

---

# 33. Architecture Principles

## Principle 1 — MCP First

MCP is the product.

Everything else supports:

- understanding
- generation
- verification
- safety
- reliability
- delivery

## Principle 2 — Deterministic Where Possible

Do not use an LLM for something that can be reliably solved with deterministic code.

## Principle 3 — AI Where Reasoning Is Needed

Use AI for:

- semantic interpretation
- planning
- generation
- diagnosis
- repair

## Principle 4 — Verification Is Part of Generation

Generation is not the end.

```text
Generate
   ↓
Execute
   ↓
Observe
   ↓
Repair
   ↓
Verify
```

## Principle 5 — Security Before Convenience

Never expose credentials to:

- LLMs
- logs
- frontend
- generated source code

## Principle 6 — Infrastructure Must Earn Its Place

A service should exist because APIWeaver needs it.

## Principle 7 — Small-Scale Production First

Build production-conscious architecture without pretending to be hyperscale.

Start small and scale based on evidence.

---

# 34. Future Roadmap

## Phase 1 — Focused Production Core

Build and stabilize:

```text
REST/OpenAPI
+
PDF/HTML/MD
+
RAG
+
Dependency Planning
+
MCP Generation
+
Safety
+
Sandbox
+
Repair
+
Verification
```

Infrastructure:

```text
FastAPI
PostgreSQL
Redis
Celery
Qdrant
Docker
Terraform
Prometheus
Grafana
Langfuse
```

---

# 35. Phase 2 — Better Verification

Potential improvements:

- better live testing
- test environment management
- API behavior comparison
- stronger mock generation
- improved failure classification
- richer verification reports
- regression testing
- test replay
- verification history

---

# 36. Phase 3 — Better MCP Compatibility

Potential improvements:

- additional MCP capabilities
- improved tool metadata
- richer authentication patterns
- better resource handling
- MCP compatibility testing
- broader AI-client integrations

---

# 37. Phase 4 — Scale Only When Necessary

Only after real usage requires it:

- multiple Celery workers
- distributed execution
- Kubernetes
- Helm
- advanced Redis usage
- horizontal scaling
- advanced observability
- multi-region deployment

---

# 38. Phase 5 — Enterprise Features

Only when real demand exists:

- multi-tenancy
- enterprise RBAC
- organizations
- SSO
- advanced audit controls
- enterprise secret management
- billing
- compliance features

These should be future product capabilities, not initial architectural requirements.

---

# 39. Features That Must Not Return Without Justification

Do not reintroduce the following simply because they seem useful:

```text
SDK generators
FastAPI export
GitHub export
Docker export
Vault
complex RBAC
multi-tenancy
database partitioning
Kubernetes
large distributed worker clusters
```

Any reintroduction must answer:

1. What user problem does it solve?
2. Why can't the current architecture solve it?
3. What scale/usage requirement requires it?
4. What complexity does it add?
5. Is that complexity justified?

---

# 40. Definition of Done

The refactored APIWeaver should allow a user to:

1. Upload an OpenAPI/Swagger/Postman specification.
2. Add optional PDF/HTML/Markdown documentation.
3. Start an APIWeaver workflow.
4. See API understanding progress.
5. See endpoint dependencies.
6. See generated MCP tools.
7. See dangerous operations identified.
8. Run sandbox verification.
9. See failures.
10. See automatic repair attempts.
11. See final verification status.
12. Optionally enable live API testing.
13. Download/use the generated MCP server.
14. Inspect a verification report.

The user should not need to understand:

- LangGraph
- Celery
- Redis
- Qdrant
- Docker
- Prometheus
- Grafana
- Langfuse

Those are implementation/infrastructure details.

---

# 41. Final Product Mental Model

> **APIWeaver is an API-to-tool compiler with an automated verification and repair loop.**

```text
REST API
   ↓
Understand
   ↓
Dependency Graph
   ↓
MCP Tools
   ↓
Safety Gates
   ↓
Sandbox Execution
   ↓
Failure Detection
   ↓
Automatic Repair
   ↓
Retest
   ↓
Optional Live Validation
   ↓
Verified MCP Server
```

---

# 42. Final Strategic Position

APIWeaver should not primarily compete as:

```text
Another SDK generator
Another API client generator
Another API documentation tool
```

The stronger position is:

> **APIWeaver: The autonomous REST-to-MCP bridge for AI agents.**

Differentiation comes from:

```text
REST → MCP
     +
Dependency awareness
     +
RAG-powered documentation understanding
     +
Sandbox verification
     +
Automatic repair
     +
Safety gates
     +
Optional live testing
```

---

# 43. Final Scope Statement

> **APIWeaver automatically converts REST APIs into verified, safety-gated MCP tools, using structured API specifications and unstructured documentation, with dependency-aware planning, sandbox validation, automatic repair, and optional live testing.**

The project should optimize for:

**Correctness → Safety → Verification → Simplicity → Production readiness → Scale**

not:

**Maximum services → Maximum outputs → Maximum enterprise features.**

---

# 44. Final Architecture Decision Summary

## Core

```text
MCP
LangGraph
LLM
Dependency analysis
Safety gates
Sandbox verification
Repair loop
OpenAPI/Swagger parsing
PDF/HTML/Markdown understanding
Optional live testing
```

## Supporting

```text
RAG
Qdrant
PostgreSQL
FastAPI
React
SSE
Docker
Celery
Redis
Secure secret handling
```

## Production infrastructure

```text
Terraform
Prometheus
Grafana
Langfuse
```

## Removed

```text
SDK generation
FastAPI proxy export
GitHub export
Docker package export
Vault
Extensive RBAC
Multi-tenancy
Database partitioning
```

## Future

```text
Kubernetes
Helm
Distributed workers
Advanced multi-tenancy
Enterprise RBAC
SSO
Enterprise secret management
Advanced scaling
```

---

# 45. Guiding Rule for Future Development

Before adding any technology, feature, service, or abstraction, ask:

> **Does this directly improve API understanding, MCP generation, MCP safety, MCP verification, MCP reliability, or production operation of APIWeaver?**

If yes:

> Consider it.

If no:

> Do not add it to the core project.

This rule exists to prevent APIWeaver from returning to an architecture where infrastructure and features grow faster than the core product.

---

# 46. Current Decision on Celery + Redis

For the current **small-scale production** target:

> **KEEP Celery and Redis, but keep them simple and purpose-specific.**

Reason:

APIWeaver's workflow can involve long-running, multi-step execution:

```text
LLM
+
RAG
+
generation
+
sandbox
+
testing
+
repair
+
retesting
```

These should not depend on one long-lived HTTP request.

Therefore:

```text
Celery = background workflow execution
Redis  = Celery broker
```

Start with one worker and scale only when actual workload requires it.

The goal is **not** to build a distributed enterprise task platform.

The goal is to make the APIWeaver workflow reliable in a small production deployment.

If future measurements prove Celery unnecessary, the workflow execution layer should be replaceable without redesigning the product.
