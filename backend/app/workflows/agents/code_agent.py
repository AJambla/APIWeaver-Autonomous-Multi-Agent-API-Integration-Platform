"""Code Generator Agent (`AI_Instruction.md §1, §2.3, §2.4`, `Feature.md §7-12`).

Generates idiomatic client code (Python + Node.js/TypeScript) from execution plan phases.
Supports chunked generation, cross-chunk consistency, and targeted self-healing repairs.
"""

from __future__ import annotations

import json
import uuid
from pathlib import Path
from typing import Any

from app.core.logging import get_logger
from app.services.storage_service import storage_service
from app.workflows.llm import LLMClient
from app.workflows.state import WorkflowState

logger = get_logger(__name__)

TEMPLATE_DIR = Path(__file__).parent.parent / "templates"

CODE_GENERATOR_SYSTEM_PROMPT = """You are the Code Generator Agent. Generate {target_language} client code for
the following endpoint group, following the project's style guide:

- Python: PEP 8, type hints on all functions, Pydantic v2 models, httpx for
  HTTP, structured custom exceptions per error class, docstrings (Google style).
- Node.js: TypeScript strict mode, Zod schemas, native fetch, ESM modules.

Always implement: retry with exponential backoff for 429/500/502/503,
pagination helpers if the endpoint response indicates pagination
(cursor/offset/page), and auth injection via the configured scheme
({auth_scheme}) — read credentials from environment variables, NEVER hardcode
any credential value, including ones seen in example payloads.

Endpoint group: {endpoint_group_json}

Return a JSON object mapping file_path -> file_content.
"""

REPAIR_SYSTEM_PROMPT = """You are repairing generated code that failed a live test.

Original code:
{file_content}

Failure context:
- Endpoint: {method} {path}
- Request sent: {request_snapshot}
- Response received: {response_snapshot} (status {status_code})
- Failure classification: {failure_classification}
- Previous repair attempts (if any): {prior_attempts_summary}

Produce a MINIMAL, targeted patch that addresses the specific failure. Do not
rewrite unrelated code. Explain your diagnosis in ≤2 sentences in the
`diagnosis` field, then return the corrected file content in full.

Respond with JSON matching schema: {repair_output_schema}
"""

CONSISTENCY_SYSTEM_PROMPT = """You are performing a cross-chunk consistency pass on generated code.

Files to review:
{files_json}

Check for:
1. Duplicate or conflicting imports
2. Inconsistent naming (e.g., same model defined differently in two files)
3. Inconsistent auth injection patterns
4. Inconsistent error handling / exception types
5. Cross-reference validation (e.g., a model used in client.py must match models.py)

Return a JSON object mapping file_path -> corrected_file_content (only for files needing changes).
If no changes needed, return empty object {{}}.
"""

SELF_REVIEW_SYSTEM_PROMPT = """You are performing a self-review of generated API client code.

Files to review:
{files_json}

Check for:
1. Auth correctly wired (credentials read from environment variables, not hardcoded)
2. No hardcoded secrets, tokens, or API keys
3. Error handling present (try/except, custom exceptions, retry logic)
4. Matches target schema (request/response models match the API spec)
5. No obvious security issues (SSRF, injection, unsafe deserialization)

Return a JSON object:
{{
  "passed": true/false,
  "issues": [{{"file": "path", "issue": "description", "severity": "critical|warning|info"}}],
  "summary": "string"
}}
"""


def _build_endpoint_group(
    spec: dict[str, Any], phase: dict[str, Any] | None, target_languages: list[str]
) -> dict[str, Any]:
    """Filter spec endpoints to those in the current phase."""
    if phase is None:
        return spec

    phase_endpoints = set(phase.get("endpoints", []))
    filtered_endpoints = [
        ep for ep in spec.get("endpoints", [])
        if f"{ep.get('method', '').upper()} {ep.get('path', '')}" in phase_endpoints
    ]
    return {**spec, "endpoints": filtered_endpoints}


def _get_auth_scheme(spec: dict[str, Any]) -> str:
    """Extract auth scheme from spec."""
    auth_schemes = spec.get("auth_schemes") or spec.get("security") or []
    if isinstance(auth_schemes, list) and auth_schemes:
        return auth_schemes[0].get("type", "bearer_jwt")
    return "bearer_jwt"


async def _run_self_review(
    generated_files: list[dict[str, Any]],
    state: WorkflowState,
    llm_client: LLMClient,
) -> dict[str, Any]:
    """Lightweight self-review pass (`AI_Instruction.md §9`)."""
    if not generated_files:
        return {"self_review_passed": True, "self_review_issues": [], "self_review_summary": "No files to review"}

    file_contents = {}
    for f in generated_files:
        try:
            content = await storage_service.download(f["content_s3_key"])
            file_contents[f["file_path"]] = content.decode()
        except Exception as e:
            logger.warning("self_review_download_failed", file=f["file_path"], error=str(e))

    if not file_contents:
        return {"self_review_passed": True, "self_review_issues": [], "self_review_summary": "No file contents available"}

    review_prompt = SELF_REVIEW_SYSTEM_PROMPT.format(files_json=json.dumps(file_contents, indent=2)[:20000])
    try:
        review_json, tokens = await llm_client.generate_json(
            system_prompt=review_prompt,
            user_prompt="Review the generated files for correctness and security.",
            fallback_json={"passed": True, "issues": [], "summary": "Self-review skipped"},
        )
        return {
            "self_review_passed": review_json.get("passed", True),
            "self_review_issues": review_json.get("issues", []),
            "self_review_summary": review_json.get("summary", ""),
        }
    except Exception as e:
        logger.warning("self_review_failed", error=str(e))
        return {"self_review_passed": True, "self_review_issues": [], "self_review_summary": f"Review failed: {e}"}


async def _render_templates(
    language: str,
    spec: dict[str, Any],
    phase: dict[str, Any] | None,
    endpoint_group: dict[str, Any],
) -> dict[str, str]:
    """Render Jinja2 templates for the given language."""
    from jinja2 import Environment, FileSystemLoader

    env = Environment(loader=FileSystemLoader(TEMPLATE_DIR / language))

    title = spec.get("title", "API Client")
    base_url = spec.get("base_url", "https://api.example.com")
    endpoints = endpoint_group.get("endpoints", [])
    auth_scheme = _get_auth_scheme(spec)

    # Group endpoints by resource for template context
    resources: dict[str, list[dict]] = {}
    for ep in endpoints:
        # Simple resource extraction from path
        path = ep.get("path", "/")
        parts = [p for p in path.split("/") if p and not p.startswith("{")]
        resource = parts[0] if parts else "root"
        resources.setdefault(resource, []).append(ep)

    context = {
        "title": title,
        "base_url": base_url,
        "endpoints": endpoints,
        "resources": resources,
        "auth_schemes": [auth_scheme],
        "phase": phase,
    }

    files = {}
    template_files = {
        "python": ["models.py.j2", "client.py.j2", "__init__.py.j2", "pyproject.toml.j2"],
        "node": ["types.ts.j2", "client.ts.j2", "index.ts.j2", "package.json.j2", "tsconfig.json.j2"],
    }

    for tmpl_name in template_files.get(language, []):
        try:
            template = env.get_template(tmpl_name)
            output_path = tmpl_name.replace(".j2", "")
            content = template.render(**context)
            files[output_path] = content
        except Exception as e:
            logger.warning("template_render_failed", template=tmpl_name, error=str(e))

    return files


async def run_code_agent(
    state: WorkflowState,
    phase_number: int | None = None,
    failure_diagnosis: dict[str, Any] | None = None,
    target_file: str | None = None,
    llm_client: LLMClient | None = None,
) -> dict[str, Any]:
    """Execution node for the Code Generator Agent.

    Args:
        state: Current workflow state
        phase_number: Specific phase to process (None = all phases / consistency pass)
        failure_diagnosis: Repair context for self-healing
        target_file: Specific file to repair
    """
    logger.info(
        "code_agent_started",
        workflow_run_id=state.get("workflow_run_id"),
        phase=phase_number,
        repair=bool(failure_diagnosis),
    )

    client = llm_client or LLMClient()
    total_tokens = state.get("total_tokens_used", 0)

    spec = state.get("normalized_spec")
    execution_plan = state.get("execution_plan")
    target_languages = state.get("target_languages", ["python"])
    generated_files = state.get("generated_files", [])

    if not spec:
        return {
            "current_node": "code_agent",
            "progress_percent": 50,
            "status": "failed",
            "errors": ["Cannot generate code without a normalized API spec."],
        }

    # Determine which phase to process
    phases = execution_plan.get("phases", []) if execution_plan else []
    current_phase = None
    if phase_number is not None:
        current_phase = next((p for p in phases if p.get("phase_number") == phase_number), None)
        if not current_phase:
            return {
                "current_node": "code_agent",
                "progress_percent": 50,
                "status": "failed",
                "errors": [f"Phase {phase_number} not found in execution plan."],
            }

    # Build endpoint group for this phase
    endpoint_group = _build_endpoint_group(spec, current_phase, target_languages)

    new_generated_files = list(generated_files)

    # Handle repair mode
    if failure_diagnosis and target_file:
        # Find the file to repair
        file_meta = next((f for f in generated_files if f["file_path"] == target_file), None)
        if not file_meta:
            return {
                "current_node": "code_agent",
                "progress_percent": 50,
                "status": "failed",
                "errors": [f"Target file {target_file} not found for repair."],
            }

        # Get file content from S3
        try:
            file_content = await storage_service.download(file_meta["content_s3_key"])
        except Exception as e:
            return {
                "current_node": "code_agent",
                "progress_percent": 50,
                "status": "failed",
                "errors": [f"Failed to download file from S3: {e}"],
            }

        # Build repair prompt
        repair_prompt = REPAIR_SYSTEM_PROMPT.format(
            file_content=file_content,
            method=failure_diagnosis.get("method", ""),
            path=failure_diagnosis.get("path", ""),
            request_snapshot=json.dumps(failure_diagnosis.get("request_snapshot", {})),
            response_snapshot=json.dumps(failure_diagnosis.get("response_snapshot", {})),
            status_code=failure_diagnosis.get("status_code", 0),
            failure_classification=failure_diagnosis.get("classification", "unknown"),
            prior_attempts_summary=failure_diagnosis.get("prior_attempts", "None"),
            repair_output_schema=json.dumps({
                "diagnosis": "string",
                "corrected_content": "string"
            })
        )

        user_prompt = f"Failure Diagnosis:\n{json.dumps(failure_diagnosis, indent=2)}"

        repair_json, tokens = await client.generate_json(
            system_prompt=repair_prompt,
            user_prompt=user_prompt,
        )
        total_tokens += tokens

        corrected_content = repair_json.get("corrected_content", "")
        diagnosis = repair_json.get("diagnosis", "No diagnosis provided")

        # Upload corrected file to S3
        s3_key = f"generated/{state['project_id']}/{uuid.uuid4()}/{target_file}"
        await storage_service.upload(s3_key, corrected_content.encode())

        # Update file metadata
        for f in new_generated_files:
            if f["file_path"] == target_file:
                f["content_s3_key"] = s3_key
                f["repair_diagnosis"] = diagnosis
                break

        return {
            "generated_files": new_generated_files,
            "current_node": "code_agent",
            "progress_percent": 75,
            "status": "repaired",
            "total_tokens_used": total_tokens,
        }

    # Handle consistency pass (phase_number=None with all phases done)
    if phase_number is None and generated_files:
        # Collect all generated files for consistency check
        all_files = {}
        for f in generated_files:
            try:
                content = await storage_service.download(f["content_s3_key"])
                all_files[f["file_path"]] = content.decode()
            except Exception as e:
                logger.warning("consistency_download_failed", file=f["file_path"], error=str(e))

        if all_files:
            consistency_prompt = CONSISTENCY_SYSTEM_PROMPT.format(
                files_json=json.dumps(all_files, indent=2)[:15000]
            )

            consistency_json, tokens = await client.generate_json(
                system_prompt=consistency_prompt,
                user_prompt="Review the above files for cross-chunk consistency issues.",
                fallback_json={},
            )
            total_tokens += tokens

            # Apply consistency fixes
            for file_path, corrected_content in consistency_json.items():
                if corrected_content:
                    s3_key = f"generated/{state['project_id']}/{uuid.uuid4()}/{file_path}"
                    await storage_service.upload(s3_key, corrected_content.encode())
                    for f in new_generated_files:
                        if f["file_path"] == file_path:
                            f["content_s3_key"] = s3_key
                            break

        return {
            "generated_files": new_generated_files,
            "current_node": "code_agent",
            "progress_percent": 90,
            "status": "consistency_complete",
            "total_tokens_used": total_tokens,
        }

    # Normal generation mode: process phase or all phases
    for language in target_languages:
        # Render templates
        template_files = await _render_templates(language, spec, current_phase, endpoint_group)

        # Also call LLM for complex logic (client methods, etc.)
        llm_prompt = CODE_GENERATOR_SYSTEM_PROMPT.format(
            target_language=language,
            auth_scheme=_get_auth_scheme(spec),
            endpoint_group_json=json.dumps(endpoint_group, indent=2)[:12000],
        )

        user_prompt = (
            f"Generate {language} code for phase {current_phase.get('phase_number') if current_phase else 'all'} "
            f"({current_phase.get('name') if current_phase else 'complete API'}).\n"
            f"Endpoints: {json.dumps([f'{e.get('method')} {e.get('path')}' for e in endpoint_group.get('endpoints', [])], indent=2)}"
        )

        fallback_files = template_files  # Use templates as fallback

        llm_files, tokens = await client.generate_json(
            system_prompt=llm_prompt,
            user_prompt=user_prompt,
            fallback_json=fallback_files,
        )
        total_tokens += tokens

        # Merge template and LLM output (LLM takes precedence for overlapping files)
        all_files = {**template_files, **llm_files}

        # Upload to S3 and record metadata
        for file_path, content in all_files.items():
            # Determine file type
            if file_path.endswith((".py", ".ts")):
                if "model" in file_path or "type" in file_path or "schema" in file_path:
                    file_type = "sdk"
                elif "test" in file_path:
                    file_type = "test"
                elif "client" in file_path:
                    file_type = "sdk"
                else:
                    file_type = "sdk"
            elif file_path in ("pyproject.toml", "package.json", "tsconfig.json"):
                file_type = "sdk"
            elif file_path == "Dockerfile":
                file_type = "dockerfile"
            elif file_path.endswith((".yml", ".yaml")) and "github" in file_path:
                file_type = "ci_cd"
            else:
                file_type = "sdk"

            s3_key = f"generated/{state['project_id']}/{uuid.uuid4()}/{file_path}"
            await storage_service.upload(s3_key, content.encode())

            new_generated_files.append({
                "file_path": file_path,
                "content_s3_key": s3_key,
                "language": language,
                "file_type": file_type,
                "phase_number": current_phase.get("phase_number") if current_phase else None,
            })

    # Self-review reflection pass before returning
    review = await _run_self_review(new_generated_files, state, client)
    total_tokens += review.get("self_review_tokens", 0)

    return {
        "generated_files": new_generated_files,
        "current_node": "code_agent",
        "progress_percent": 75,
        "status": "generated",
        "total_tokens_used": total_tokens,
        "self_review_passed": review.get("self_review_passed", True),
        "self_review_issues": review.get("self_review_issues", []),
        "self_review_summary": review.get("self_review_summary", ""),
    }


async def patch(
    state: WorkflowState,
    failure_diagnosis: dict[str, Any],
    file_path: str,
    llm_client: LLMClient | None = None,
) -> dict[str, Any]:
    """Convenience method for targeted repair (called by Testing Agent)."""
    return await run_code_agent(
        state,
        failure_diagnosis=failure_diagnosis,
        target_file=file_path,
        llm_client=llm_client,
    )