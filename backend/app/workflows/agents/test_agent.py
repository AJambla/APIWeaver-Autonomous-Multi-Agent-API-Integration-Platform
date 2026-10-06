"""Testing Agent (`AI_Instruction.md §1, §2.5, §8`, `Feature.md §13-14`).

Executes generated code in a mock sandbox, classifies failures, and drives
the self-healing repair loop (max 3 attempts per failing test).
"""

from __future__ import annotations

import importlib.util
import json
import sys
import time
import traceback
import uuid
from pathlib import Path
from typing import Any

from sqlalchemy import select

from app.core.config import get_settings
from app.core.logging import get_logger
from app.models.auth_config import AuthConfig, SecretRef
from app.models.enums import AuthScheme
from app.services.sandbox_service import DockerSandboxExecutor, _safe_workspace_target
from app.services.storage_service import storage_service
from app.services.test_run_service import record_test_run_results
from app.services.vault_service import create_vault_client
from app.workflows.agents.code_agent import run_code_agent
from app.workflows.llm import LLMClient, fence_untrusted
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

    async def _load_modules(self) -> None:
        """Load generated Python modules into memory."""
        # Create a temporary directory structure in memory
        for file_meta in self.generated_files:
            if file_meta.get("language") != "python":
                continue

            try:
                content = await storage_service.download(file_meta["content_s3_key"])
                file_path = file_meta["file_path"]

                # Write to a temporary location for import
                import tempfile
                temp_dir = Path(tempfile.gettempdir()) / "apiweaver_sandbox" / file_meta.get("project_id", "default")
                temp_dir.mkdir(parents=True, exist_ok=True)

                full_path = _safe_workspace_target(temp_dir, file_path)
                if full_path is None:
                    logger.warning("sandbox_path_rejected", file=file_path)
                    continue
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

    async def cleanup(self) -> None:
        """Drop the sys.path entries added by _load_modules."""
        for entry in list(sys.path):
            if "apiweaver_sandbox" in entry:
                sys.path.remove(entry)


class FailureClassifier:
    """Classifies test failures using LLM."""

    def __init__(self, llm_client: LLMClient | None = None) -> None:
        self.client = llm_client or LLMClient()

    async def classify(self, error: dict[str, Any], endpoint: dict[str, Any], history: list[dict] | None = None) -> dict[str, Any]:
        """Classify a test failure."""
        response_body = fence_untrusted(
            "RESPONSE DATA", json.dumps(error.get("response_snapshot", {}), indent=2)[:2000]
        )
        endpoint_history = fence_untrusted("HISTORY DATA", json.dumps(history or [], indent=2))

        prompt = FAILURE_CLASSIFICATION_PROMPT.format(
            status_code=error.get("status_code", 0),
            response_body=response_body,
            endpoint_history=endpoint_history,
        )

        classification_json, _ = await self.client.generate_json(
            system_prompt="",
            user_prompt=prompt,
        )
        return classification_json


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
            request_schema=fence_untrusted(
                "REQUEST SCHEMA", json.dumps(ep.get("request_schema") or {}, indent=2)
            ),
            response_schemas=fence_untrusted(
                "RESPONSE SCHEMA", json.dumps(ep.get("response_schemas") or {}, indent=2)
            ),
            parameters=fence_untrusted(
                "PARAMETER DATA", json.dumps(ep.get("parameters") or [], indent=2)
            ),
        )

        fixture_json, _ = await client.generate_json(
            system_prompt="You are a test fixture generator. Output only valid JSON.",
            user_prompt=prompt,
        )
        fixtures[ep_key] = fixture_json

    return fixtures


# The generated-client contract accepts a single credential string (api_key);
# these are the common keys a project's Vault secret may hold, in preference order.
_CREDENTIAL_KEYS = (
    "api_key",
    "key",
    "token",
    "access_token",
    "bearer_token",
    "api_token",
    "client_secret",
)


def _credential_from_auth(auth: dict[str, Any] | None) -> str | None:
    """Pick the credential string the generated client constructor expects."""
    if not auth or auth.get("scheme") == AuthScheme.NONE.value:
        return None
    credentials = auth.get("credentials") or {}
    for key in _CREDENTIAL_KEYS:
        value = credentials.get(key)
        if isinstance(value, str) and value:
            return value
    return None


async def _resolve_target_auth(
    session_factory: Any,
    project_id: str | None,
    settings: Any,
) -> dict[str, Any] | None:
    """Load the project's target-API auth: scheme, non-secret config, Vault credentials.

    Returns None (testing proceeds without injected credentials) when there is no
    session, no auth config, or any lookup fails. Credential values are never logged.
    """
    if session_factory is None or not project_id:
        return None
    try:
        project_uuid = uuid.UUID(str(project_id))
    except ValueError:
        return None

    try:
        async with session_factory() as session:
            row = await session.execute(
                select(AuthConfig.scheme, AuthConfig.config_json, SecretRef.vault_path)
                .join(SecretRef, SecretRef.auth_config_id == AuthConfig.id)
                .where(AuthConfig.project_id == project_uuid)
                .limit(1)
            )
            found = row.first()
    except Exception as e:
        logger.warning("target_auth_lookup_failed", project_id=str(project_id), error=str(e))
        return None

    if found is None:
        return None
    scheme, config_json, vault_path = found

    try:
        secret = await create_vault_client(settings).read_secret(vault_path)
    except Exception as e:
        logger.warning(
            "target_auth_secret_read_failed",
            project_id=str(project_id),
            scheme=scheme,
            error=str(e),
        )
        return None
    if not secret:
        return None

    return {"scheme": scheme, "config": config_json or {}, "credentials": secret}


async def _create_sandbox(
    state: WorkflowState,
    generated_files: list[dict[str, Any]],
    spec: dict[str, Any],
    auth: dict[str, Any] | None = None,
) -> MockSandboxClient | DockerSandboxExecutor:
    """Build the sandbox backend selected by settings (mock by default).

    Live credentials are only handed to the Docker executor — the mock backend
    runs generated code in-process, which must never see target-API secrets
    (Security.md §19).
    """
    settings = get_settings()
    if settings.sandbox_backend != "docker":
        sandbox = MockSandboxClient(generated_files, spec)
        await sandbox._load_modules()
        return sandbox

    target_languages = state.get("target_languages", ["python"])
    preferred_lang = "python" if "python" in target_languages else ("node" if "node" in target_languages else "python")

    files: dict[str, str] = {}
    for file_meta in generated_files:
        lang = file_meta.get("language")
        if lang not in ("python", "node"):
            continue
        # If testing a specific language, filter to files of that language
        if preferred_lang and lang != preferred_lang:
            continue
        try:
            raw = await storage_service.download(file_meta["content_s3_key"])
            files[file_meta["file_path"]] = (
                raw.decode("utf-8") if isinstance(raw, bytes) else str(raw)
            )
        except Exception as e:
            logger.warning(
                "sandbox_file_download_failed", file=file_meta.get("file_path"), error=str(e)
            )

    executor = DockerSandboxExecutor(settings)
    await executor.load(
        project_id=state.get("project_id"),
        files=files,
        base_url=spec.get("base_url"),
        api_key=_credential_from_auth(auth),
    )
    return executor


async def run_test_agent(
    state: WorkflowState,
    llm_client: LLMClient | None = None,
    session_factory: Any | None = None,
) -> dict[str, Any]:
    """Execution node for the Testing Agent."""
    logger.info("test_agent_started", workflow_run_id=state.get("workflow_run_id"))

    client = llm_client or LLMClient()
    total_tokens = state.get("total_tokens_used", 0)

    spec = state.get("normalized_spec")
    generated_files = state.get("generated_files", [])

    async def _record_failure(error: str) -> None:
        if session_factory is None:
            return
        await record_test_run_results(
            session_factory,
            workflow_run_id=state.get("workflow_run_id"),
            project_id=state.get("project_id"),
            status="failed",
            errors=[error],
        )

    if not spec:
        await _record_failure("Cannot run tests without a normalized API spec.")
        return {
            "current_node": "test_agent",
            "progress_percent": 50,
            "status": "failed",
            "errors": ["Cannot run tests without a normalized API spec."],
        }

    if not generated_files:
        await _record_failure("No generated files to test.")
        return {
            "current_node": "test_agent",
            "progress_percent": 50,
            "status": "failed",
            "errors": ["No generated files to test."],
        }

    auth = None
    if session_factory is not None:
        auth = await _resolve_target_auth(
            session_factory, state.get("project_id"), get_settings()
        )
        if auth:
            logger.info(
                "target_auth_resolved",
                workflow_run_id=state.get("workflow_run_id"),
                scheme=auth.get("scheme"),
            )

    # Generate test fixtures
    fixtures = await generate_test_fixtures(spec, client)

    # Create sandbox client
    sandbox = await _create_sandbox(state, generated_files, spec, auth=auth)
    classifier = FailureClassifier(client)

    test_start_time = time.perf_counter()
    try:
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

        # Classify any failing tests so failure details and diagnosis are available
        failed_tests = [r for r in test_results if r["status"] == "failed"]
        for failed_test in failed_tests:
            endpoint = next(
                (
                    ep
                    for ep in spec.get("endpoints", [])
                    if f"{ep.get('method', '').upper()} {ep.get('path', '')}"
                    == f"{failed_test['method']} {failed_test['path']}"
                ),
                None,
            )
            try:
                classification = await classifier.classify(
                    failed_test,
                    endpoint or {"method": failed_test["method"], "path": failed_test["path"]},
                    test_results,
                )
                failed_test["classification"] = classification
            except Exception as classify_err:
                logger.warning("failure_classification_failed", error=str(classify_err))
                failed_test["classification"] = {
                    "classification": "generated_code_bug",
                    "confidence": 0.5,
                    "reasoning": str(classify_err),
                }

        # Track existing repair attempts from workflow state
        repair_attempts = list(state.get("repair_attempts", []))

        # Build test run summary
        passed = sum(1 for r in test_results if r["status"] == "passed")
        failed = sum(1 for r in test_results if r["status"] == "failed")
        skipped = sum(1 for r in test_results if r["status"] == "skipped")
        total_duration_ms = max(
            int((time.perf_counter() - test_start_time) * 1000),
            sum(r.get("latency_ms") or 0 for r in test_results),
        )

        test_run_summary = {
            "total": len(test_results),
            "passed": passed,
            "failed": failed,
            "skipped": skipped,
            "pass_rate": passed / len(test_results) if test_results else 0,
            "repair_attempts": len(repair_attempts),
            "duration_ms": total_duration_ms,
        }

        if session_factory is not None:
            await record_test_run_results(
                session_factory,
                workflow_run_id=state.get("workflow_run_id"),
                project_id=state.get("project_id"),
                test_suite=test_results,
                summary=test_run_summary,
                status="completed" if all_passed else "completed_with_failures",
            )

        return {
            "test_suite": test_results,
            "test_run_summary": test_run_summary,
            "repair_attempts": repair_attempts,
            "current_node": "test_agent",
            "progress_percent": 85,
            "status": "completed" if all_passed else "completed_with_failures",
            "total_tokens_used": total_tokens,
        }
    finally:
        await sandbox.cleanup()