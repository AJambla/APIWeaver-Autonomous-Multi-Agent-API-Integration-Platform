"""Testing Agent (`AI_Instruction.md §1, §2.5, §8`, `Feature.md §13-14`).

Executes generated code in a mock sandbox, classifies failures, and drives
the self-healing repair loop (max 3 attempts per failing test).
"""

from __future__ import annotations

import importlib.util
import json
import sys
import traceback
from pathlib import Path
from typing import Any

from app.core.logging import get_logger
from app.services.storage_service import storage_service
from app.workflows.agents.code_agent import run_code_agent
from app.workflows.llm import LLMClient
from app.workflows.state import WorkflowState

logger = get_logger(__name__)

FAILURE_CLASSIFICATION_PROMPT = """Classify this API test failure into exactly one category:
[auth_error, schema_mismatch, rate_limited, network_error, server_error,
 validation_error, unknown_api_bug, generated_code_bug]

Base your classification on the status code, response body, and whether the
same request pattern succeeded for other endpoints in this run.

Status: {status_code}
Response body: {response_body}
Endpoint history: {endpoint_history}

Respond with JSON: {{"classification": "...", "confidence": 0.0-1.0, "reasoning": "..."}}
"""

TEST_FIXTURE_GENERATION_PROMPT = """Generate a test fixture for the following endpoint.

Endpoint: {method} {path}
Request schema: {request_schema}
Response schemas: {response_schemas}
Parameters: {parameters}

Return a JSON object with:
{{
  "request": {{ ... }},  // Example request data matching the schema
  "expected_status": 200,
  "expected_response_shape": {{ ... }}  // Expected response structure
}}
"""


class MockSandboxClient:
    """In-process mock sandbox for executing generated Python code."""

    def __init__(self, generated_files: list[dict[str, Any]], spec: dict[str, Any]) -> None:
        self.generated_files = generated_files
        self.spec = spec
        self._modules: dict[str, Any] = {}
        self._load_modules()

    def _load_modules(self) -> None:
        """Load generated Python modules into memory."""
        # Create a temporary directory structure in memory
        for file_meta in self.generated_files:
            if file_meta.get("language") != "python":
                continue

            try:
                content = storage_service.download(file_meta["content_s3_key"])
                file_path = file_meta["file_path"]

                # Write to a temporary location for import
                import tempfile
                temp_dir = Path(tempfile.gettempdir()) / "apiweaver_sandbox" / file_meta.get("project_id", "default")
                temp_dir.mkdir(parents=True, exist_ok=True)

                full_path = temp_dir / file_path
                full_path.parent.mkdir(parents=True, exist_ok=True)
                full_path.write_bytes(content)

                # Add to sys.path if not already
                if str(temp_dir) not in sys.path:
                    sys.path.insert(0, str(temp_dir))

            except Exception as e:
                logger.warning("sandbox_module_load_failed", file=file_meta["file_path"], error=str(e))

    def _get_client_class(self) -> type | None:
        """Find and return the generated client class."""
        for file_meta in self.generated_files:
            if file_meta.get("language") == "python" and "client" in file_meta["file_path"]:
                module_name = file_meta["file_path"].replace("/", ".").replace(".py", "")
                try:
                    module = importlib.import_module(module_name)
                    for attr_name in dir(module):
                        attr = getattr(module, attr_name)
                        if isinstance(attr, type) and "Client" in attr_name:
                            return attr
                except Exception as e:
                    logger.warning("client_class_load_failed", module=module_name, error=str(e))
        return None

    async def execute_test(self, endpoint: dict[str, Any], fixture: dict[str, Any]) -> dict[str, Any]:
        """Execute a single test against the mock sandbox."""
        method = endpoint.get("method", "GET").upper()
        path = endpoint.get("path", "/")

        result = {
            "endpoint_id": endpoint.get("id"),
            "method": method,
            "path": path,
            "status": "passed",
            "status_code": None,
            "latency_ms": 0,
            "response_snapshot": None,
            "error": None,
            "stack_trace": None,
        }

        try:
            # Get the client class
            ClientClass = self._get_client_class()
            if not ClientClass:
                result["status"] = "failed"
                result["error"] = "Could not load generated client class"
                return result

            # Instantiate client with mock configuration
            import os
            os.environ["MOCK_MODE"] = "true"

            client = ClientClass(
                base_url="http://mock.local",
                api_key="test-key",
            )

            # Build request parameters from fixture
            request_data = fixture.get("request", {})
            params = request_data.get("params", {})
            body = request_data.get("body")

            # Call the appropriate method
            op_id = endpoint.get("operationId", path.replace("/", "_").replace("{", "").replace("}", "").replace("-", "_"))
            method_func = getattr(client, op_id, None)

            if not method_func:
                result["status"] = "failed"
                result["error"] = f"Method {op_id} not found on client"
                return result

            # Execute with timing
            import time
            start = time.perf_counter()
            response = await method_func(**params, body=body)
            result["latency_ms"] = int((time.perf_counter() - start) * 1000)

            # Capture response
            result["status_code"] = response.status_code
            result["response_snapshot"] = {
                "status_code": response.status_code,
                "headers": dict(response.headers),
                "body": response.json() if hasattr(response, "json") else response.text,
            }

            # Validate response
            expected_status = fixture.get("expected_status", 200)
            if response.status_code != expected_status:
                result["status"] = "failed"
                result["error"] = f"Expected status {expected_status}, got {response.status_code}"

            await client.close()

        except Exception as e:
            result["status"] = "failed"
            result["error"] = str(e)
            result["stack_trace"] = traceback.format_exc()

        return result


class FailureClassifier:
    """Classifies test failures using LLM."""

    def __init__(self, llm_client: LLMClient | None = None) -> None:
        self.client = llm_client or LLMClient()

    async def classify(self, error: dict[str, Any], endpoint: dict[str, Any], history: list[dict] | None = None) -> dict[str, Any]:
        """Classify a test failure."""
        endpoint_history = json.dumps(history or [], indent=2)

        prompt = FAILURE_CLASSIFICATION_PROMPT.format(
            status_code=error.get("status_code", 0),
            response_body=json.dumps(error.get("response_snapshot", {}), indent=2)[:2000],
            endpoint_history=endpoint_history,
        )

        try:
            classification_json, _ = await self.client.generate_json(
                system_prompt="",
                user_prompt=prompt,
                fallback_json={"classification": "generated_code_bug", "confidence": 0.5, "reasoning": "Default fallback"},
            )
            return classification_json
        except Exception as e:
            logger.warning("failure_classification_failed", error=str(e))
            return {"classification": "generated_code_bug", "confidence": 0.5, "reasoning": f"Classification failed: {e}"}


async def generate_test_fixtures(spec: dict[str, Any], llm_client: LLMClient | None = None) -> dict[str, Any]:
    """Generate test fixtures for all endpoints."""
    client = llm_client or LLMClient()
    fixtures = {}

    for ep in spec.get("endpoints", []):
        method = ep.get("method", "GET").upper()
        path = ep.get("path", "/")
        ep_key = f"{method} {path}"

        prompt = TEST_FIXTURE_GENERATION_PROMPT.format(
            method=method,
            path=path,
            request_schema=json.dumps(ep.get("request_schema") or {}, indent=2),
            response_schemas=json.dumps(ep.get("response_schemas") or {}, indent=2),
            parameters=json.dumps(ep.get("parameters") or [], indent=2),
        )

        try:
            fixture_json, _ = await client.generate_json(
                system_prompt="You are a test fixture generator. Output only valid JSON.",
                user_prompt=prompt,
                fallback_json={
                    "request": {"params": {}, "body": None},
                    "expected_status": 200,
                    "expected_response_shape": {},
                },
            )
            fixtures[ep_key] = fixture_json
        except Exception as e:
            logger.warning("fixture_generation_failed", endpoint=ep_key, error=str(e))
            fixtures[ep_key] = {
                "request": {"params": {}, "body": None},
                "expected_status": 200,
                "expected_response_shape": {},
            }

    return fixtures


async def run_test_agent(
    state: WorkflowState,
    llm_client: LLMClient | None = None,
) -> dict[str, Any]:
    """Execution node for the Testing Agent."""
    logger.info("test_agent_started", workflow_run_id=state.get("workflow_run_id"))

    client = llm_client or LLMClient()
    total_tokens = state.get("total_tokens_used", 0)

    spec = state.get("normalized_spec")
    generated_files = state.get("generated_files", [])

    if not spec:
        return {
            "current_node": "test_agent",
            "progress_percent": 50,
            "status": "failed",
            "errors": ["Cannot run tests without a normalized API spec."],
        }

    if not generated_files:
        return {
            "current_node": "test_agent",
            "progress_percent": 50,
            "status": "failed",
            "errors": ["No generated files to test."],
        }

    # Generate test fixtures
    fixtures = await generate_test_fixtures(spec, client)

    # Create sandbox client
    sandbox = MockSandboxClient(generated_files, spec)
    classifier = FailureClassifier(client)

    # Run tests for each endpoint
    test_results = []
    all_passed = True

    for ep in spec.get("endpoints", []):
        method = ep.get("method", "GET").upper()
        path = ep.get("path", "/")
        ep_key = f"{method} {path}"
        fixture = fixtures.get(ep_key, {})

        result = await sandbox.execute_test(ep, fixture)
        test_results.append(result)

        if result["status"] != "passed":
            all_passed = False

    # Self-healing repair loop (max 3 attempts)
    repair_attempts = []
    max_attempts = 3

    for attempt in range(1, max_attempts + 1):
        failed_tests = [r for r in test_results if r["status"] == "failed"]
        if not failed_tests:
            break

        logger.info("repair_attempt_started", attempt=attempt, failed_count=len(failed_tests))

        for failed_test in failed_tests:
            # Find the endpoint
            endpoint = next(
                (ep for ep in spec.get("endpoints", [])
                 if f"{ep.get('method', '').upper()} {ep.get('path', '')}" == f"{failed_test['method']} {failed_test['path']}"),
                None
            )
            if not endpoint:
                continue

            # Classify failure
            classification = await classifier.classify(
                failed_test,
                endpoint,
                test_results,
            )

            # Find the file to repair (client file for the endpoint's language)
            target_files = [
                f for f in generated_files
                if f.get("language") == "python" and "client" in f["file_path"]
            ]
            if not target_files:
                continue

            target_file = target_files[0]["file_path"]

            # Prepare failure diagnosis
            failure_diagnosis = {
                "method": failed_test["method"],
                "path": failed_test["path"],
                "status_code": failed_test.get("status_code"),
                "request_snapshot": fixture.get("request", {}),
                "response_snapshot": failed_test.get("response_snapshot", {}),
                "classification": classification.get("classification"),
                "confidence": classification.get("confidence"),
                "reasoning": classification.get("reasoning"),
                "prior_attempts": [
                    ra.get("diff_summary") for ra in repair_attempts
                    if ra.get("target_file") == target_file
                ],
            }

            # Trigger repair via Code Generator Agent
            repair_result = await run_code_agent(
                state,
                failure_diagnosis=failure_diagnosis,
                target_file=target_file,
                llm_client=client,
            )

            # Re-run the failed test
            new_result = await sandbox.execute_test(endpoint, fixture)

            repair_attempt = {
                "attempt_number": attempt,
                "endpoint_id": failed_test.get("endpoint_id"),
                "target_file": target_file,
                "classification": classification,
                "diff_summary": repair_result.get("generated_files", [{}])[0].get("repair_diagnosis", "Unknown"),
                "outcome": "resolved" if new_result["status"] == "passed" else "still_failing",
            }
            repair_attempts.append(repair_attempt)

            # Update test result
            failed_test.update(new_result)
            if new_result["status"] == "passed":
                all_passed = True
                break

        # Check if all resolved
        if all(r["status"] == "passed" for r in test_results):
            all_passed = True
            break

    # Escalate remaining failures
    for failed_test in [r for r in test_results if r["status"] == "failed"]:
        repair_attempts.append({
            "attempt_number": max_attempts + 1,
            "endpoint_id": failed_test.get("endpoint_id"),
            "target_file": "escalated",
            "classification": {"classification": "escalated", "confidence": 1.0, "reasoning": "Max repair attempts exceeded"},
            "diff_summary": None,
            "outcome": "escalated",
        })

    # Build test run summary
    passed = sum(1 for r in test_results if r["status"] == "passed")
    failed = sum(1 for r in test_results if r["status"] == "failed")
    skipped = sum(1 for r in test_results if r["status"] == "skipped")

    test_run_summary = {
        "total": len(test_results),
        "passed": passed,
        "failed": failed,
        "skipped": skipped,
        "pass_rate": passed / len(test_results) if test_results else 0,
        "repair_attempts": len(repair_attempts),
    }

    return {
        "test_suite": test_results,
        "test_run_summary": test_run_summary,
        "repair_attempts": repair_attempts,
        "current_node": "test_agent",
        "progress_percent": 85,
        "status": "completed" if all_passed else "completed_with_failures",
        "total_tokens_used": total_tokens,
    }