# Phase 3: Verification & Pre-Sandbox Repair Gate Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement Tier 1 deterministic safety classification, a pre-sandbox static validation gate (AST syntax and FastMCP tool contract validation) that intercepts invalid code before container spin-up, enhance the sandbox test runner with deterministic failure categorization, and generate multi-level Verification Reports (`STATIC`, `SANDBOX`, `LIVE`) embedded into the FastMCP bundle.

**Architecture:**
1. `backend/app/services/safety_service.py`: Deterministic HTTP method + semantic keyword safety classifier assigning `[SAFE]`, `[STATE-CHANGING]`, and `[DESTRUCTIVE]` badges with `requires_confirmation` flags.
2. `backend/app/services/validation_service.py`: Pre-sandbox static validation gate executing AST syntax parsing, import safety, and FastMCP tool contract validation before container invocation.
3. `backend/app/services/verification_service.py`: Multi-level verification engine generating `VERIFICATION_REPORT.json` and human-readable `VERIFICATION_REPORT.md` with explicit statuses (`STATIC: PASS`, `SANDBOX: PASS`, `LIVE: NOT RUN`, `Overall: SANDBOX VERIFIED`).
4. `backend/app/workflows/agents/code_agent.py` & `test_agent.py` & `repair_agent`: Integrated with `safety_service`, `validation_service`, and `verification_service`.
5. `backend/app/workflows/agents/export_agent.py`: Bundles `VERIFICATION_REPORT.json` and `VERIFICATION_REPORT.md` into the exported MCP ZIP archive.

**Tech Stack:** Python 3.12, ast, FastMCP, pytest, Docker sandbox runner.

**Spec:** `API_WEAVER_REFACTORING_BLUEPRINT.md §4, §5, §8, §10`

---

## Tasks

### Task 1: Deterministic Safety Rule Engine (`safety_service.py`)
**Files:**
- Create: `backend/app/services/safety_service.py`
- Create: `backend/tests/test_safety_service.py`

**Steps:**
- [ ] Implement `classify_safety(method: str, path: str, summary: str | None = None, operation_id: str | None = None) -> SafetyClassification`:
  - `DELETE` -> HIGH risk, `requires_confirmation=True`, `is_destructive=True`
  - Destructive keywords (`refund`, `transfer`, `terminate`, `drop`, `revoke`, `purge`, `cancel`, `payout`, `execute`) -> HIGH risk, `requires_confirmation=True`
  - `POST` / `PUT` / `PATCH` -> MEDIUM risk, `is_state_changing=True`
  - `GET` / `HEAD` / `OPTIONS` -> LOW risk, `is_safe=True`
- [ ] Implement FastMCP tool docstring / decorator metadata enrichment helper `enrich_tool_safety_metadata`.
- [ ] Unit tests for HTTP method rules, semantic keyword elevation, and edge cases.
- [ ] Run pytest on `backend/tests/test_safety_service.py`.
- [ ] Commit: `feat(safety): implement deterministic safety rule engine for MCP tools`

---

### Task 2: Pre-Sandbox Static Validation Gate (`validation_service.py`)
**Files:**
- Create: `backend/app/services/validation_service.py`
- Create: `backend/tests/test_validation_service.py`

**Steps:**
- [ ] Implement `validate_mcp_code_statically(code: str, file_path: str = "tools.py") -> StaticValidationResult`:
  - AST Syntax Check (`ast.parse(code)`): captures exact line, column, error message.
  - FastMCP Contract Check: verifies presence of `@mcp.tool` decorator, function docstring, type annotations, and proper FastMCP instance setup.
  - Import Safety Check: flags banned/malicious imports or syntax regressions.
- [ ] Unit tests for valid FastMCP code, syntax error detection, and missing decorator/docstrings.
- [ ] Run pytest on `backend/tests/test_validation_service.py`.
- [ ] Commit: `feat(validation): implement pre-sandbox static validation gate for MCP tools`

---

### Task 3: Multi-Level Verification Report Generator (`verification_service.py`)
**Files:**
- Create: `backend/app/services/verification_service.py`
- Create: `backend/tests/test_verification_service.py`

**Steps:**
- [ ] Implement `build_verification_report(...) -> VerificationReport`:
  - Level 1: Static Verification (`PASS` | `FAIL`)
  - Level 2: Sandbox Verification (`PASS` | `FAIL` | `PARTIAL`)
  - Level 3: Live API Verification (`NOT RUN` | `PASS` | `FAIL`)
  - Overall Status calculation: `SANDBOX VERIFIED`, `STATIC VERIFIED`, or `UNVERIFIED` (Never blindly claim "Production Verified" without live execution).
- [ ] Implement Markdown export `render_verification_report_md(report: VerificationReport) -> str`.
- [ ] Implement JSON export `render_verification_report_json(report: VerificationReport) -> dict[str, Any]`.
- [ ] Unit tests verifying status calculation, tool breakdown, and markdown rendering.
- [ ] Run pytest on `backend/tests/test_verification_service.py`.
- [ ] Commit: `feat(verification): implement multi-level verification report generator`

---

### Task 4: Integrate Safety, Validation, and Verification into Pipeline & Agents
**Files:**
- Modify: `backend/app/workflows/agents/code_agent.py`
- Modify: `backend/app/workflows/agents/test_agent.py`
- Modify: `backend/app/workflows/langgraph_pipeline.py`
- Modify: `backend/app/workflows/agents/export_agent.py`

**Steps:**
- [ ] In `code_agent.py`, tag generated FastMCP tools using `safety_service` and validate synthesized `tools.py` using `validation_service`.
- [ ] In `langgraph_pipeline.py` (`repair_agent_node`), validate patched code with `validation_service` *before* attempting test execution; if static validation fails, feed the error directly back to the LLM.
- [ ] In `test_agent.py`, execute sandbox tests, collect results, and generate `VERIFICATION_REPORT.json` and `VERIFICATION_REPORT.md`.
- [ ] In `export_agent.py`, include `VERIFICATION_REPORT.json` and `VERIFICATION_REPORT.md` in the exported MCP ZIP package.
- [ ] Run full test suite (`test_safety_service.py`, `test_validation_service.py`, `test_verification_service.py`, `test_export.py`, `test_codegen.py`, `test_langgraph_pipeline.py`).
- [ ] Commit: `feat(pipeline): integrate safety tags, static gate, and verification reports into MCP workflow`

---

### Task 5: Push Branch & Create Pull Request
**Steps:**
- [ ] Push `refactor/phase3-verification-repair` to GitHub.
- [ ] Create Pull Request with comprehensive release notes.
