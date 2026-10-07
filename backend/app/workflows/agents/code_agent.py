"""Code Generator Agent (`AI_Instruction.md §1, §2.3, §2.4`, `Feature.md §7-12`).

Generates idiomatic client code (Python + Node.js/TypeScript) from execution plan phases.
Supports chunked generation, cross-chunk consistency, and targeted self-healing repairs.
"""

from __future__ import annotations

import ast
import json
import re
import uuid
from pathlib import Path
from typing import Any

from app.core.logging import get_logger
from app.services.qdrant_service import QdrantClient
from app.services.storage_service import storage_service
from app.workflows.llm import LLMClient, fence_untrusted
from app.workflows.source_safety import (
    safe_endpoint,
    to_base_url,
    to_display_name,
    to_identifier,
    to_py_type,
    to_ts_type,
)
from app.workflows.state import WorkflowState

logger = get_logger(__name__)


def _language_for_path(file_path: str) -> str:
    """Language the pipeline stores a generated file under, from its extension."""
    return "python" if file_path.endswith(".py") else "node"


def _source_is_parseable(file_path: str, content: str) -> bool:
    """Cheap validity gate. Only Python can be checked here; other languages pass."""
    if not content or not content.strip():
        return False
    if file_path.endswith(".py"):
        try:
            ast.parse(content)
            return True
        except (SyntaxError, ValueError, MemoryError, RecursionError):
            return False
    return True


def _coerce_file_content(raw: Any, file_path: str) -> str | None:
    """Turn one LLM file value into source text.

    The generators are told to answer `file_path -> source`, but the model sometimes
    echoes the storage envelope (`{"content": ..., "language": ..., "file_type": ...}`)
    as the value. Pull the source out of it instead of writing the envelope to disk.
    """
    if isinstance(raw, str):
        return raw
    if isinstance(raw, dict):
        for key in ("content", "code", "source", "file_content", "text"):
            value = raw.get(key)
            if isinstance(value, str):
                return value
    logger.warning(
        "llm_file_content_unusable",
        file_path=file_path,
        returned_type=type(raw).__name__,
    )
    return None


def _defined_names(file_path: str, content: str) -> set[str]:
    """Top-level and method names declared in a Python file (empty if unparseable)."""
    if not file_path.endswith(".py") or not content.strip():
        return set()
    try:
        tree = ast.parse(content)
    except (SyntaxError, ValueError, MemoryError, RecursionError):
        return set()
    return {
        node.name
        for node in ast.walk(tree)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
    }


def _keep_parseable(existing_code: str, new_code: str, file_path: str = "") -> str:
    """Choose between two candidates when an AST merge could not run.

    Unparseable new code must not replace parseable existing code: that is how a file
    carrying every operation so far lost them. Non-Python files keep the previous
    behaviour of preferring the new code.
    """
    if not file_path.endswith(".py"):
        return new_code or existing_code

    existing_ok = _source_is_parseable(file_path, existing_code)
    new_ok = _source_is_parseable(file_path, new_code)
    if existing_ok and not new_ok:
        logger.warning("merge_rejects_unparseable_python", file_path=file_path)
        return existing_code
    if new_ok and not existing_ok:
        return new_code
    return existing_code or new_code


def _split_consistency_key(file_key: str) -> tuple[str | None, str]:
    """Split the pass's `language/path` key, tolerating a bare path answer."""
    head, sep, rest = file_key.partition("/")
    if sep and head in ("python", "node"):
        return head, rest
    return None, file_key


def _consistency_payload(files: dict[str, str], budget: int = 60000) -> str:
    """Serialise whole files up to `budget` characters; omit rather than truncate."""
    included: dict[str, str] = {}
    used = 0
    for key, body in files.items():
        cost = len(key) + len(body) + 8
        if used + cost > budget:
            logger.warning("consistency_file_omitted", file_key=key, chars=len(body))
            continue
        included[key] = body
        used += cost
    return json.dumps(included, indent=2)


def _merge_python_code(existing_code: str, new_code: str, file_path: str = "") -> str:
    """Merge new Python code into existing code via AST, preserving all methods and models."""
    if not existing_code.strip():
        return new_code
    if not new_code.strip():
        return existing_code

    try:
        tree_orig = ast.parse(existing_code)
        tree_new = ast.parse(new_code)
    except Exception:
        return _keep_parseable(existing_code, new_code, file_path)

    try:
        # Merge imports
        existing_import_sigs = {
            ast.dump(n) for n in tree_orig.body if isinstance(n, (ast.Import, ast.ImportFrom))
        }
        new_imports = [
            n for n in tree_new.body
            if isinstance(n, (ast.Import, ast.ImportFrom)) and ast.dump(n) not in existing_import_sigs
        ]
        insert_idx = 0
        for i, node in enumerate(tree_orig.body):
            if isinstance(node, (ast.Import, ast.ImportFrom)):
                insert_idx = i + 1
        for ni in reversed(new_imports):
            tree_orig.body.insert(insert_idx, ni)

        orig_classes = {
            node.name: node for node in tree_orig.body if isinstance(node, ast.ClassDef)
        }

        for node in tree_new.body:
            if isinstance(node, ast.ClassDef):
                if node.name in orig_classes:
                    target_cls = orig_classes[node.name]
                    target_methods = {
                        m.name: idx
                        for idx, m in enumerate(target_cls.body)
                        if isinstance(m, (ast.FunctionDef, ast.AsyncFunctionDef))
                    }
                    for member in node.body:
                        if isinstance(member, (ast.FunctionDef, ast.AsyncFunctionDef)):
                            if member.name in target_methods:
                                target_cls.body[target_methods[member.name]] = member
                            else:
                                target_cls.body.append(member)
                else:
                    tree_orig.body.append(node)
            elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                orig_funcs = {
                    fn.name: idx
                    for idx, fn in enumerate(tree_orig.body)
                    if isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef))
                }
                if node.name in orig_funcs:
                    tree_orig.body[orig_funcs[node.name]] = node
                else:
                    tree_orig.body.append(node)

        return ast.unparse(tree_orig)
    except Exception as exc:
        logger.warning("python_ast_merge_failed", file_path=file_path, error=str(exc))
        return _keep_parseable(existing_code, new_code, file_path)


def _merge_ts_code(existing_code: str, new_code: str, file_path: str = "") -> str:
    """Merge TypeScript code, injecting new methods into the client class."""
    if not existing_code.strip():
        return new_code
    if not new_code.strip():
        return existing_code

    if "class " in existing_code and "class " in new_code:
        new_methods = re.findall(
            r'(async\s+[a-zA-Z0-9_]+\([^)]*\)[\s\S]*?^  \})', new_code, re.MULTILINE
        )
        if new_methods:
            added = []
            for m in new_methods:
                m_match = re.search(r'async\s+([a-zA-Z0-9_]+)', m)
                if m_match:
                    mname = m_match.group(1)
                    if f"{mname}(" not in existing_code:
                        added.append(m)
            if added:
                last_brace = existing_code.rfind("}")
                if last_brace != -1:
                    injection = "\n\n  " + "\n\n  ".join(added) + "\n"
                    return existing_code[:last_brace] + injection + existing_code[last_brace:]

    return new_code or existing_code

TEMPLATE_DIR = Path(__file__).parent.parent / "templates"

CODE_GENERATOR_SYSTEM_PROMPT = """You are the Code Generator Agent. Generate {target_language} client code for
the following endpoint group, following the project's style guide:

- Python: PEP 8, type hints on all functions, Pydantic v2 models, httpx for
  HTTP, structured custom exceptions per error class, docstrings (Google style).
  Use standard library, httpx, and pydantic ONLY. Do not import external packages like tenacity (implement retries using standard loops / asyncio.sleep).
  CRITICAL CONSTRUCTOR REQUIREMENT: The main Client class __init__ MUST accept:
  def __init__(self, base_url: str | None = None, api_key: str | None = None, **kwargs: Any) -> None:
  Never omit api_key or **kwargs from __init__.
  IMPORTANT IMPORT RULE: For Python sibling modules, always use top-level imports (e.g. `from models import *` or `import models`, NOT package-relative `from .models import *`) so modules can be imported directly when staged in sys.path without package parent context.
- Node.js: TypeScript strict mode, Zod schemas, native fetch, ESM modules.
  Client constructor MUST accept an optional config object: constructor(config?: {{ baseUrl?: string; apiKey?: string; [key: string]: any }})

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
- Error: {error}
- Stack trace: {stack_trace}
- Request sent: {request_snapshot}
- Response received: {response_snapshot} (status {status_code})
- Failure classification: {failure_classification}
- Previous repair attempts (if any): {prior_attempts_summary}

Produce a MINIMAL, targeted patch that addresses the specific failure. Do not
rewrite unrelated code. Use standard library and httpx/pydantic only.
CRITICAL: If the error mentions constructor / __init__ arguments (e.g. unexpected keyword argument 'api_key'),
ensure __init__(self, base_url: str | None = None, api_key: str | None = None, **kwargs: Any) accepts both base_url and api_key and **kwargs!
Explain your diagnosis in ≤2 sentences in the `diagnosis` field, then return the corrected file content in full.

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

    phase_endpoints = set()
    for item in phase.get("endpoints", []):
        if isinstance(item, str):
            phase_endpoints.add(item.strip())
        elif isinstance(item, dict):
            m = str(item.get("method", "")).upper()
            p = str(item.get("path", "")).strip()
            phase_endpoints.add(f"{m} {p}")

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
            key = f"{f.get('language') or 'sdk'}/{f['file_path']}"
            file_contents[key] = content.decode()
        except Exception as e:
            logger.warning("self_review_download_failed", file=f.get("file_path"), error=str(e))

    if not file_contents:
        return {"self_review_passed": True, "self_review_issues": [], "self_review_summary": "No file contents available"}

    review_prompt = SELF_REVIEW_SYSTEM_PROMPT.format(
        files_json=fence_untrusted("FILE CONTENTS", json.dumps(file_contents, indent=2)[:20000])
    )
    try:
        review_json, tokens = await llm_client.generate_json(
            system_prompt=review_prompt,
            user_prompt="Review the generated files for correctness and security.",
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

    # A spec type name is not a TypeScript or Python type, so templates translate through them.
    env.filters["ts_type"] = to_ts_type
    env.filters["py_type"] = to_py_type

    title = to_display_name(spec.get("title"), fallback="API Client")
    base_url = to_base_url(spec.get("base_url"))
    raw_spec_endpoints = spec.get("endpoints", [])
    if isinstance(raw_spec_endpoints, list) and raw_spec_endpoints:
        endpoints = [
            safe_endpoint(ep) for ep in raw_spec_endpoints if isinstance(ep, dict)
        ]
    else:
        endpoints = [
            safe_endpoint(ep) for ep in endpoint_group.get("endpoints", []) if isinstance(ep, dict)
        ]
    auth_scheme = _get_auth_scheme(spec)

    # Group endpoints by resource for template context
    resources: dict[str, list[dict]] = {}
    for ep in endpoints:
        # Simple resource extraction from path
        path = ep.get("path", "/")
        parts = [p for p in path.split("/") if p and not p.startswith("{")]
        resource = to_identifier(parts[0], fallback="root") if parts else "root"
        resources.setdefault(resource, []).append(ep)

    info = spec.get("info") or {}
    license_info = info.get("license") or {}
    license_name = license_info.get("name") if isinstance(license_info, dict) else (license_info if isinstance(license_info, str) else "MIT")
    contact_info = info.get("contact") or {}
    author_name = contact_info.get("name") if isinstance(contact_info, dict) else "APIWeaver"
    author_email = contact_info.get("email") if isinstance(contact_info, dict) else "support@apiweaver.dev"

    context = {
        "title": title,
        "base_url": base_url,
        "endpoints": endpoints,
        "resources": resources,
        "auth_schemes": [auth_scheme],
        "phase": phase,
        "version": str(spec.get("version") or info.get("version") or "0.1.0"),
        "license": license_name or "MIT",
        "author_name": author_name or "APIWeaver",
        "author_email": author_email or "support@apiweaver.dev",
    }

    files = {}
    template_files = {
        "python": ["models.py.j2", "client.py.j2", "__init__.py.j2", "pyproject.toml.j2", "README.md.j2"],
        "node": ["types.ts.j2", "client.ts.j2", "index.ts.j2", "package.json.j2", "tsconfig.json.j2", "README.md.j2"],
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
    qdrant_client: QdrantClient | None = None,
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
    target_languages = state.get("target_languages") or ["python", "node"]
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
        # Find the file to repair, matching language for the target file
        file_meta = next(
            (
                f for f in generated_files
                if isinstance(f, dict) and f.get("file_path") == target_file
                and f.get("language") == _language_for_path(target_file)
            ),
            None,
        )
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
            file_content=fence_untrusted("FILE CONTENT", file_content),
            method=failure_diagnosis.get("method", ""),
            path=failure_diagnosis.get("path", ""),
            error=failure_diagnosis.get("error", "Unknown test failure"),
            stack_trace=fence_untrusted("STACK TRACE", failure_diagnosis.get("stack_trace") or "None"),
            request_snapshot=fence_untrusted(
                "REQUEST DATA", json.dumps(failure_diagnosis.get("request_snapshot", {}))
            ),
            response_snapshot=fence_untrusted(
                "RESPONSE DATA", json.dumps(failure_diagnosis.get("response_snapshot", {}))
            ),
            status_code=failure_diagnosis.get("status_code", 0),
            failure_classification=failure_diagnosis.get("classification", "unknown"),
            prior_attempts_summary=fence_untrusted(
                "PRIOR ATTEMPTS", failure_diagnosis.get("prior_attempts", "None")
            ),
            repair_output_schema=json.dumps({
                "diagnosis": "string",
                "corrected_content": "string"
            })
        )

        user_prompt = fence_untrusted(
            "FAILURE DIAGNOSIS", json.dumps(failure_diagnosis, indent=2)
        )

        if qdrant_client is not None and state.get("project_id"):
            try:
                query_text = f"Failure: {failure_diagnosis.get('method')} {failure_diagnosis.get('path')} {failure_diagnosis.get('error')}"
                query_vec = await client.generate_embedding(query_text)
                scored_chunks = await qdrant_client.search(
                    project_id=uuid.UUID(str(state["project_id"])),
                    query_vector=query_vec,
                    limit=3,
                )
                if scored_chunks:
                    rag_doc = "\n---\n".join(c.text for c in scored_chunks if c.text)
                    user_prompt += f"\n{fence_untrusted('RELEVANT DOCUMENTATION', rag_doc)}"
            except Exception as e:
                logger.debug("code_agent_repair_rag_search_failed", error=str(e))

        repair_json, tokens = await client.generate_json(
            system_prompt=repair_prompt,
            user_prompt=user_prompt,
        )
        total_tokens += tokens

        corrected_content = _coerce_file_content(
            repair_json.get("corrected_content", ""), target_file
        )
        diagnosis = repair_json.get("diagnosis", "No diagnosis provided")

        if not corrected_content or not _source_is_parseable(target_file, corrected_content):
            raise ValueError(
                f"Repair of {target_file} returned "
                f"{'no usable content' if not corrected_content else 'unparseable content'}; "
                "keeping the previous version."
            )

        # Upload corrected file to S3
        s3_key = f"generated/{state['project_id']}/{uuid.uuid4()}/{target_file}"
        encoded_b = corrected_content.encode("utf-8")
        await storage_service.upload(s3_key, encoded_b)

        # Update file metadata
        target_lang = file_meta.get("language")
        for f in new_generated_files:
            if (
                isinstance(f, dict)
                and f.get("file_path") == target_file
                and (not target_lang or f.get("language") == target_lang)
            ):
                f["content_s3_key"] = s3_key
                f["repair_diagnosis"] = diagnosis
                f["size_bytes"] = len(encoded_b)
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
            if not isinstance(f, dict) or not f.get("file_path") or not f.get("content_s3_key"):
                continue
            try:
                content = await storage_service.download(f["content_s3_key"])
                key = f"{f.get('language') or 'sdk'}/{f['file_path']}"
                all_files[key] = content.decode()
            except Exception as e:
                logger.warning("consistency_download_failed", file=f.get("file_path"), error=str(e))

        if all_files:
            consistency_prompt = CONSISTENCY_SYSTEM_PROMPT.format(
                files_json=fence_untrusted("FILE CONTENTS", _consistency_payload(all_files))
            )

            consistency_json, tokens = await client.generate_json(
                system_prompt=consistency_prompt,
                user_prompt="Review the above files for cross-chunk consistency issues.",
            )
            total_tokens += tokens

            # Apply consistency fixes
            for file_key, raw_content in consistency_json.items():
                language, pure_path = _split_consistency_key(file_key)
                corrected_content = _coerce_file_content(raw_content, pure_path)
                if not corrected_content:
                    continue

                matches = [
                    f
                    for f in new_generated_files
                    if isinstance(f, dict)
                    and f.get("file_path") == pure_path
                    and (language is None or f.get("language") == language)
                ]
                if len(matches) != 1:
                    logger.warning(
                        "consistency_target_unresolved",
                        file_key=file_key,
                        candidates=len(matches),
                    )
                    continue
                target = matches[0]

                if not _source_is_parseable(pure_path, corrected_content):
                    logger.warning("consistency_rejects_unparseable", file_key=file_key)
                    continue

                original = all_files.get(
                    f"{target.get('language') or 'sdk'}/{pure_path}", ""
                )
                dropped = _defined_names(pure_path, original) - _defined_names(
                    pure_path, corrected_content
                )
                if dropped:
                    logger.warning(
                        "consistency_rejects_dropped_declarations",
                        file_key=file_key,
                        dropped=sorted(dropped)[:12],
                    )
                    continue

                s3_key = f"generated/{state['project_id']}/{uuid.uuid4()}/{pure_path}"
                encoded_b = corrected_content.encode("utf-8")
                await storage_service.upload(s3_key, encoded_b)
                target["content_s3_key"] = s3_key
                target["size_bytes"] = len(encoded_b)

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
            endpoint_group_json=fence_untrusted(
                "ENDPOINT GROUP DATA", json.dumps(endpoint_group, indent=2)[:60000]
            ),
        )

        rag_context = ""
        if qdrant_client is not None and state.get("project_id"):
            try:
                query_text = f"API endpoints for {language}: " + ", ".join(
                    f"{e.get('method')} {e.get('path')} {e.get('summary', '')}"
                    for e in endpoint_group.get("endpoints", [])[:5]
                )
                query_vec = await client.generate_embedding(query_text)
                scored_chunks = await qdrant_client.search(
                    project_id=uuid.UUID(str(state["project_id"])),
                    query_vector=query_vec,
                    limit=3,
                )
                if scored_chunks:
                    rag_context = "\n---\n".join(c.text for c in scored_chunks if c.text)
            except Exception as e:
                logger.debug("code_agent_rag_search_failed", error=str(e))

        endpoint_list = json.dumps(
            [f'{e.get("method")} {e.get("path")}' for e in endpoint_group.get("endpoints", [])],
            indent=2,
        )
        phase_label = current_phase.get("name") if current_phase else "complete API"
        user_prompt = (
            f"Generate {language} code for phase "
            f"{current_phase.get('phase_number') if current_phase else 'all'}.\n"
            f"{fence_untrusted('PHASE NAME', phase_label)}\n"
            f"Endpoints:\n{fence_untrusted('ENDPOINT LIST', endpoint_list)}"
        )
        if rag_context:
            user_prompt += f"\n{fence_untrusted('RELEVANT DOCUMENTATION', rag_context)}"

        llm_files, tokens = await client.generate_json(
            system_prompt=llm_prompt,
            user_prompt=user_prompt,
        )
        total_tokens += tokens

        # Collect existing files for this language (from earlier phases)
        existing_lang_files: dict[str, str] = {}
        for f in new_generated_files:
            if f.get("language") == language and f.get("file_path") and f.get("content_s3_key"):
                try:
                    raw_b = await storage_service.download(f["content_s3_key"])
                    existing_lang_files[f["file_path"]] = (
                        raw_b.decode("utf-8") if isinstance(raw_b, bytes) else str(raw_b)
                    )
                except Exception as e:
                    logger.debug("existing_file_download_failed", file=f.get("file_path"), error=str(e))

        # Smart merge: start with existing files or template files
        all_files: dict[str, str] = dict(existing_lang_files)
        for fp, tmpl_content in template_files.items():
            if fp not in all_files:
                if fp.endswith(".py") and not _source_is_parseable(fp, tmpl_content):
                    logger.error("template_syntax_error_phase1", file=fp)
                    raise SyntaxError(f"Rendered template {fp} has syntax error on initial phase")
                all_files[fp] = tmpl_content
            elif fp.endswith(".py"):
                all_files[fp] = _merge_python_code(all_files[fp], tmpl_content, fp)
            elif fp.endswith(".ts"):
                all_files[fp] = _merge_ts_code(all_files[fp], tmpl_content, fp)

        # Merge LLM-generated files
        for fp, raw_llm_content in llm_files.items():
            llm_content = _coerce_file_content(raw_llm_content, fp)
            if llm_content is None:
                continue
            if fp not in all_files:
                all_files[fp] = llm_content
            elif fp.endswith(".py"):
                all_files[fp] = _merge_python_code(all_files[fp], llm_content, fp)
            elif fp.endswith(".ts"):
                all_files[fp] = _merge_ts_code(all_files[fp], llm_content, fp)
            else:
                all_files[fp] = llm_content

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

            prior_content = existing_lang_files.get(file_path, "")
            if (
                file_path.endswith(".py")
                and not _source_is_parseable(file_path, content)
                and _source_is_parseable(file_path, prior_content)
            ):
                logger.warning(
                    "upload_rejects_unparseable_python",
                    file_path=file_path,
                    phase_number=current_phase.get("phase_number") if current_phase else None,
                    rejected_chars=len(content),
                    kept_chars=len(prior_content),
                )
                content = prior_content

            encoded_b = content.encode("utf-8") if isinstance(content, str) else content
            size_bytes = len(encoded_b)
            s3_key = f"generated/{state['project_id']}/{uuid.uuid4()}/{file_path}"
            await storage_service.upload(s3_key, encoded_b)

            entry = {
                "file_path": file_path,
                "content_s3_key": s3_key,
                "language": language,
                "file_type": file_type,
                "size_bytes": size_bytes,
                "phase_number": current_phase.get("phase_number") if current_phase else None,
            }
            existing_idx = next(
                (
                    i
                    for i, f in enumerate(new_generated_files)
                    if f.get("file_path") == file_path and f.get("language") == language
                ),
                None,
            )
            if existing_idx is not None:
                new_generated_files[existing_idx] = entry
            else:
                new_generated_files.append(entry)

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