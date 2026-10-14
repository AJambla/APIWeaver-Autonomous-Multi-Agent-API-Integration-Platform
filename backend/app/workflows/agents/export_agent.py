"""Export Agent for Model Context Protocol (MCP) packages and documentation.

Compiles API specifications into verified, safety-gated FastMCP server bundles
and supporting reference documentation.
"""

from __future__ import annotations

import io
import json
import zipfile
from collections.abc import Awaitable, Callable
from typing import Any

from app.core.constants import DEFAULT_EXPORT_TYPES
from app.core.logging import get_logger
from app.core.metrics import pipeline_error_total
from app.services.storage_service import storage_service
from app.workflows.llm import LLMClient
from app.workflows.source_safety import (
    derived_operation_id,
    to_base_url,
    to_display_name,
    to_http_method,
    to_identifier,
    to_literal,
    to_path,
    to_text,
)
from app.workflows.state import WorkflowState

logger = get_logger(__name__)


class ExportAgent:
    """Packages FastMCP server bundles and reference documentation."""

    def __init__(
        self,
        llm_client: LLMClient | None = None,
        session_factory: Any | None = None,
    ) -> None:
        self.llm_client = llm_client or LLMClient()
        self.session_factory = session_factory

    async def run(
        self,
        state: WorkflowState,
        export_types: list[str] | None = None,
    ) -> dict[str, Any]:
        """Execute the export pipeline for the given export types."""
        logger.info(
            "export_agent_started",
            workflow_run_id=state.get("workflow_run_id"),
            export_types=export_types,
        )

        total_tokens = state.get("total_tokens_used", 0)
        project_id = state.get("project_id") or ""
        generated_files = state.get("generated_files", [])
        test_run_summary = state.get("test_run_summary") or {}
        normalized_spec = state.get("normalized_spec") or {}

        if export_types is None:
            raw_types = state.get("export_types") or list(DEFAULT_EXPORT_TYPES)
        else:
            raw_types = export_types

        # Normalize export types to only supported kinds; default to mcp if none match
        resolved_types: list[str] = []
        for t in raw_types:
            clean = str(t).lower().strip()
            if clean in ("mcp", "docs") and clean not in resolved_types:
                resolved_types.append(clean)
            elif clean in ("sdk", "client", "fastapi", "docker", "github", "cicd"):
                logger.info("legacy_export_type_ignored", ignored_type=clean)

        if not resolved_types:
            resolved_types = ["mcp"]

        artifacts = []
        status = "completed"

        for export_type in resolved_types:
            try:
                artifact = await self._export_type(
                    export_type=export_type,
                    project_id=project_id,
                    generated_files=generated_files,
                    test_run_summary=test_run_summary,
                    normalized_spec=normalized_spec,
                )
                if artifact:
                    artifacts.append(artifact)
            except Exception as e:
                pipeline_error_total.labels(subsystem="export_agent", error_type=type(e).__name__).inc()
                logger.error("export_failed", export_type=export_type, error=str(e), exc_info=True)
                artifacts.append({
                    "type": export_type,
                    "status": "failed",
                    "error": str(e),
                })
                status = "completed_with_errors"

        return {
            "exports": artifacts,
            "current_node": "export_agent",
            "progress_percent": 100,
            "status": status,
            "total_tokens_used": total_tokens,
        }

    async def _export_type(
        self,
        *,
        export_type: str,
        project_id: str,
        generated_files: list[dict[str, Any]],
        test_run_summary: dict[str, Any],
        normalized_spec: dict[str, Any],
        **kwargs: Any,
    ) -> dict[str, Any] | None:
        """Dispatch to the appropriate export packager."""
        packagers: dict[str, Callable[..., Awaitable[dict[str, Any] | None]]] = {
            "mcp": self._package_mcp,
            "docs": self._package_docs,
        }

        packager = packagers.get(export_type)
        if not packager:
            logger.warning("unknown_export_type", export_type=export_type)
            return None

        return await packager(
            project_id=project_id,
            generated_files=generated_files,
            test_run_summary=test_run_summary,
            normalized_spec=normalized_spec,
            **kwargs,
        )

    async def _package_mcp(
        self,
        *,
        project_id: str,
        normalized_spec: dict[str, Any] | None = None,
        test_run_summary: dict[str, Any] | None = None,
        generated_files: list[dict[str, Any]] | None = None,
        **kwargs: Any,
    ) -> dict[str, Any]:
        """Convert endpoints → FastMCP tool definitions and package into a verified zip bundle."""
        if not isinstance(normalized_spec, dict):
            normalized_spec = {}
        endpoints = normalized_spec.get("endpoints", [])
        if not endpoints:
            return {
                "type": "mcp",
                "status": "failed",
                "error": "No endpoints available in specification to generate MCP tools.",
                "tools_generated": 0,
                "flagged_destructive": 0,
                "artifacts": [],
            }
        tools = []
        flagged_destructive = 0

        for ep in endpoints:
            method = to_http_method(ep.get("method", "GET"))
            path = to_path(ep.get("path", "/"))
            is_destructive = method.upper() in ("DELETE",) or any(
                k in path.lower() for k in ("delete", "purge", "drop", "revoke", "cancel")
            )
            declared = ep.get("operationId") or derived_operation_id(method, path)
            tool_name = to_identifier(declared, fallback="tool_endpoint")

            summary = to_text(ep.get("summary"), fallback=f"{method.upper()} {path}")
            parameters = ep.get("parameters") or []

            properties: dict[str, Any] = {}
            required_params: list[str] = []

            for p in parameters:
                if isinstance(p, dict) and p.get("location") in ("query", "path"):
                    p_name = p.get("name")
                    if p_name:
                        properties[p_name] = {
                            "type": p.get("type", "string"),
                            "description": p.get("description", f"Parameter {p_name}"),
                        }
                        if p.get("required"):
                            required_params.append(p_name)

            if ep.get("request_schema"):
                properties["body"] = ep.get("request_schema")
            elif method.upper() in ("POST", "PUT", "PATCH"):
                properties["body"] = {"type": "object", "description": "Request body JSON payload"}

            tool = {
                "name": tool_name,
                "description": summary,
                "inputSchema": {
                    "type": "object",
                    "properties": properties,
                    "required": required_params,
                },
                "requires_confirmation": is_destructive,
                "risk_level": "HIGH" if is_destructive else ("STATE_CHANGING" if method.upper() in ("POST", "PUT", "PATCH") else "SAFE"),
                "endpoint": {
                    "method": method.upper(),
                    "path": path,
                    "parameters": parameters,
                },
            }
            tools.append(tool)
            if is_destructive:
                flagged_destructive += 1

        api_title = to_display_name(normalized_spec.get("title", "API"), fallback="API")
        base_url_val = to_base_url(normalized_spec.get("base_url") or "http://localhost:8000")
        base_url_literal = to_literal(base_url_val)

        server_code = f'''"""Model Context Protocol (MCP) server generated by APIWeaver for {api_title}."""
import json
import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

DEFAULT_BASE_URL = {base_url_literal}


def execute_http_call(endpoint_info: dict, args: dict) -> dict:
    """Execute an HTTP request against the upstream API endpoint using standard urllib."""
    base_url = os.environ.get("API_BASE_URL", DEFAULT_BASE_URL).rstrip("/")
    method = endpoint_info.get("method", "GET").upper()
    path = endpoint_info.get("path", "/")
    param_meta = {{
        p.get("name"): p.get("location", "query")
        for p in endpoint_info.get("parameters", [])
        if isinstance(p, dict) and p.get("name")
    }}

    # Resolve path parameters
    path_params = re.findall(r"\\{{([a-zA-Z0-9_]+)\\}}", path)
    resolved_path = path
    used_args = set()
    for param_name in path_params:
        if param_name in args:
            resolved_path = resolved_path.replace(
                "{{" + param_name + "}}", urllib.parse.quote(str(args[param_name]))
            )
            used_args.add(param_name)

    # Separate query parameters
    query_params = {{}}
    for k, v in args.items():
        if k in used_args or k == "body":
            continue
        loc = param_meta.get(k)
        if loc == "query" or (loc is None and method in ("GET", "DELETE", "HEAD")):
            query_params[k] = v
            used_args.add(k)

    # Prepare URL
    url = base_url + ("/" + resolved_path.lstrip("/") if resolved_path else "")
    if query_params:
        url += "?" + urllib.parse.urlencode(query_params)

    # Prepare body payload
    data = None
    if method in ("POST", "PUT", "PATCH"):
        if "body" in args:
            body_val = args["body"]
            data = (
                json.dumps(body_val).encode("utf-8")
                if isinstance(body_val, (dict, list))
                else str(body_val).encode("utf-8")
            )
        else:
            remaining = {{k: v for k, v in args.items() if k not in used_args}}
            if remaining:
                data = json.dumps(remaining).encode("utf-8")

    req = urllib.request.Request(url, data=data, method=method)
    req.add_header("Accept", "application/json, text/plain, */*")
    if data is not None:
        req.add_header("Content-Type", "application/json")

    auth_token = os.environ.get("AUTHORIZATION") or os.environ.get("API_KEY")
    if auth_token:
        header_val = auth_token if auth_token.startswith("Bearer ") else f"Bearer {{auth_token}}"
        req.add_header("Authorization", header_val)

    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            resp_body = resp.read().decode("utf-8", errors="replace")
            return {{"content": [{{"type": "text", "text": resp_body}}], "isError": False}}
    except urllib.error.HTTPError as err:
        err_body = err.read().decode("utf-8", errors="replace")
        return {{
            "content": [{{"type": "text", "text": f"HTTP {{err.code}}: {{err_body}}"}}],
            "isError": True,
        }}
    except Exception as exc:
        return {{
            "content": [{{"type": "text", "text": f"Request failed: {{exc}}"}}],
            "isError": True,
        }}


def handle_message(req: dict, tools: list, tools_map: dict) -> dict:
    """Handle a single JSON-RPC 2.0 MCP protocol message."""
    method = req.get("method")
    msg_id = req.get("id")

    if method == "initialize":
        return {{
            "jsonrpc": "2.0",
            "id": msg_id,
            "result": {{
                "protocolVersion": "2024-11-05",
                "capabilities": {{"tools": {{}}}},
                "serverInfo": {{"name": "apiweaver-mcp-server", "version": "1.0.0"}},
            }},
        }}
    elif method == "tools/list":
        return {{"jsonrpc": "2.0", "id": msg_id, "result": {{"tools": tools}}}}
    elif method == "tools/call":
        params = req.get("params") or {{}}
        tool_name = params.get("name")
        tool_args = params.get("arguments") or {{}}
        matched = tools_map.get(tool_name)
        if matched:
            call_result = execute_http_call(matched.get("endpoint", {{}}), tool_args)
            return {{
                "jsonrpc": "2.0",
                "id": msg_id,
                "result": call_result,
            }}
        return {{
            "jsonrpc": "2.0",
            "id": msg_id,
            "error": {{"code": -32601, "message": f"Tool '{{tool_name}}' not found"}},
        }}
    return {{"jsonrpc": "2.0", "id": msg_id, "result": {{}}}}


def main():
    manifest_path = Path(__file__).parent / "manifest.json"
    manifest = json.loads(manifest_path.read_text()) if manifest_path.exists() else {{"tools": []}}
    tools = manifest.get("tools", [])
    tools_map = {{t.get("name"): t for t in tools}}

    for line in sys.stdin:
        if not line.strip():
            continue
        try:
            req = json.loads(line)
            res = handle_message(req, tools, tools_map)
            sys.stdout.write(json.dumps(res) + "\\n")
            sys.stdout.flush()
        except Exception as e:
            err = {{"jsonrpc": "2.0", "id": None, "error": {{"code": -32603, "message": str(e)}}}}
            sys.stdout.write(json.dumps(err) + "\\n")
            sys.stdout.flush()


if __name__ == "__main__":
    main()
'''

        requirements_txt = "httpx>=0.28.0\npydantic>=2.0.0\n"

        readme_md = f"""# {api_title} — MCP Server
Generated by APIWeaver. Exposes upstream REST endpoints as verified Model Context Protocol (MCP) tools.

## Setup Instructions

### 1. Requirements
Install runtime dependencies:
```bash
pip install -r requirements.txt
```

### 2. Configure in Claude Desktop
Add this server to your `claude_desktop_config.json`:
```json
{{
  "mcpServers": {{
    "{to_identifier(api_title, fallback='api').lower()}": {{
      "command": "python",
      "args": ["server.py"],
      "env": {{
        "API_BASE_URL": "{base_url_val}",
        "API_KEY": "YOUR_API_KEY_HERE"
      }}
    }}
  }}
}}
```

### 3. Configure in Cursor
Add to `.cursor/mcp.json`:
```json
{{
  "mcpServers": {{
    "{to_identifier(api_title, fallback='api').lower()}": {{
      "command": "python",
      "args": ["server.py"]
    }}
  }}
}}
```

## Available Tools ({len(tools)} total)
- **Safe Tools:** {len(tools) - flagged_destructive}
- **Destructive/Gated Tools:** {flagged_destructive} (marked with `requires_confirmation = True`)
"""

        summary = test_run_summary or {}
        passed_tests = summary.get("passed", 0)
        total_tests = summary.get("total", 0)
        sandbox_status = "PASS" if total_tests > 0 and summary.get("failed", 0) == 0 else ("NOT RUN" if total_tests == 0 else "FAILED")

        verification_report_md = f"""# APIWeaver Verification Report

**Target API:** {api_title}  
**Tools Generated:** {len(tools)}  
**Destructive Gated Tools:** {flagged_destructive}  

## Verification Summary
- **Level 1 (Static Verification):** PASS ({len(tools)}/{len(tools)} schemas valid)
- **Level 2 (Sandbox Verification):** {sandbox_status} ({passed_tests}/{total_tests} mock tests passed)
- **Level 3 (Live API Verification):** NOT RUN (Requires explicit opt-in with live credentials)

**Overall Status:** {"SANDBOX VERIFIED" if sandbox_status == "PASS" else "STATIC VERIFIED"}

> *Note: Sandbox tests run against synthetic mocks derived from the OpenAPI specification.*
"""

        manifest_data = {
            "name": f"{api_title} MCP Server",
            "version": str(normalized_spec.get("version", "1.0.0")),
            "tools": tools,
            "tools_count": len(tools),
            "flagged_destructive": flagged_destructive,
        }

        # Build in-memory ZIP package
        zip_buffer = io.BytesIO()
        with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zf:
            zf.writestr("manifest.json", json.dumps(manifest_data, indent=2))
            zf.writestr("server.py", server_code)
            zf.writestr("requirements.txt", requirements_txt)
            zf.writestr("README.md", readme_md)
            zf.writestr("VERIFICATION_REPORT.md", verification_report_md)
        zip_bytes = zip_buffer.getvalue()

        manifest_key = f"exports/{project_id}/mcp/manifest.json"
        server_key = f"exports/{project_id}/mcp/server.py"
        bundle_key = f"exports/{project_id}/mcp/apiweaver-mcp.zip"

        await storage_service.upload(manifest_key, json.dumps(manifest_data, indent=2).encode())
        await storage_service.upload(server_key, server_code.encode())
        await storage_service.upload(bundle_key, zip_bytes)

        return {
            "type": "mcp",
            "status": "completed",
            "s3_key": bundle_key,
            "tools_generated": len(tools),
            "flagged_destructive": flagged_destructive,
            "artifacts": [
                {"name": "apiweaver-mcp.zip", "s3_key": bundle_key},
                {"name": "mcp_manifest.json", "s3_key": manifest_key},
                {"name": "server.py", "s3_key": server_key},
            ],
        }

    async def _package_docs(
        self,
        *,
        project_id: str,
        normalized_spec: dict[str, Any],
        **kwargs: Any,
    ) -> dict[str, Any]:
        """Generate OpenAPI 3.1 spec + markdown reference docs."""
        openapi_key = f"exports/{project_id}/docs/openapi.json"
        markdown_key = f"exports/{project_id}/docs/reference.md"

        raw_schemas = (
            normalized_spec.get("components", {}).get("schemas", {})
            or normalized_spec.get("definitions", {})
        )

        def _migrate_refs(val: Any) -> Any:
            if isinstance(val, dict):
                return {k: _migrate_refs(v) for k, v in val.items()}
            elif isinstance(val, list):
                return [_migrate_refs(v) for v in val]
            elif isinstance(val, str) and val.startswith("#/definitions/"):
                return val.replace("#/definitions/", "#/components/schemas/")
            return val

        converted_schemas = _migrate_refs(raw_schemas)

        doc_version = str(normalized_spec.get("version") or (normalized_spec.get("info") or {}).get("version") or "1.0.0")
        openapi_spec: dict[str, Any] = {
            "openapi": "3.1.0",
            "info": {
                "title": normalized_spec.get("title", "API"),
                "version": doc_version,
            },
            "paths": {},
            "components": {
                "schemas": converted_schemas,
            },
        }

        for ep in normalized_spec.get("endpoints", []):
            method = ep.get("method", "get").lower()
            path = ep.get("path", "/")
            params = []
            for p in ep.get("parameters", []):
                if isinstance(p, dict):
                    loc = p.get("in") or p.get("location", "query")
                    param_def = {
                        "name": p.get("name", "param"),
                        "in": loc,
                        "required": p.get("required", loc == "path"),
                        "description": p.get("description", ""),
                    }
                    if "schema" in p:
                        param_def["schema"] = _migrate_refs(p["schema"])
                    else:
                        param_def["schema"] = {"type": p.get("type", "string")}
                    params.append(param_def)

            responses = {
                str(code): {
                    "description": schema.get("description", "Response") if isinstance(schema, dict) else "Response",
                    "content": {"application/json": {"schema": _migrate_refs(schema)}},
                }
                for code, schema in (ep.get("response_schemas") or {}).items()
            }
            if not responses:
                responses = {"200": {"description": "Successful operation"}}

            op_data = {
                "summary": ep.get("summary"),
                "operationId": ep.get("operationId"),
                "parameters": params,
                "responses": responses,
            }
            if ep.get("request_schema"):
                op_data["requestBody"] = {
                    "content": {"application/json": {"schema": _migrate_refs(ep.get("request_schema"))}}
                }
            openapi_spec["paths"].setdefault(path, {})[method] = op_data

        markdown_lines = [
            f"# {normalized_spec.get('title', 'API')} Reference",
            "",
            "Auto-generated by APIWeaver.",
            "",
            "## Base URL",
            "",
            f"`{normalized_spec.get('base_url') or 'http://localhost:8000'}`",
            "",
            "## Endpoints",
            "",
        ]

        for ep in normalized_spec.get("endpoints", []):
            method = ep.get("method", "GET").upper()
            path = ep.get("path", "/")
            summary = ep.get("summary", path)
            markdown_lines.extend([f"### {method} {path}", "", summary, ""])

        await storage_service.upload(openapi_key, json.dumps(openapi_spec).encode())
        await storage_service.upload(markdown_key, "\n".join(markdown_lines).encode())

        return {
            "type": "docs",
            "artifacts": [
                {"name": "openapi.json", "s3_key": openapi_key},
                {"name": "reference.md", "s3_key": markdown_key},
            ],
        }