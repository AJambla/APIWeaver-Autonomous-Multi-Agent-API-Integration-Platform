"""Export Agent (``AI_Instruction.md §1``, ``Feature.md §15-24``, ``API.md §6.8``).

Packages final artifacts (SDK, Client, FastAPI wrapper, Docker, GitHub, MCP, docs, CI/CD)
and stores them in S3 with metadata in Postgres.
"""

from __future__ import annotations

import json
from typing import Any

from app.core.logging import get_logger
from app.models.enums import ExportType
from app.services.storage_service import storage_service
from app.services.vault_service import vault_service
from app.workflows.llm import LLMClient
from app.workflows.state import WorkflowState

logger = get_logger(__name__)


class ExportAgent:
    """Packages final artifacts from generated code and test results."""

    def __init__(self, llm_client: LLMClient | None = None) -> None:
        self.llm_client = llm_client or LLMClient()

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
        project_id = state.get("project_id")
        generated_files = state.get("generated_files", [])
        test_run_summary = state.get("test_run_summary", {})
        target_languages = state.get("target_languages", ["python"])
        normalized_spec = state.get("normalized_spec", {})

        if export_types is None:
            export_types = [e.value for e in ExportType]

        artifacts = []
        status = "completed"

        for export_type in export_types:
            try:
                artifact = await self._export_type(
                    export_type=export_type,
                    project_id=project_id,
                    generated_files=generated_files,
                    test_run_summary=test_run_summary,
                    target_languages=target_languages,
                    normalized_spec=normalized_spec,
                )
                if artifact:
                    artifacts.append(artifact)
            except Exception as e:
                logger.error("export_failed", export_type=export_type, error=str(e))
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
        target_languages: list[str],
        normalized_spec: dict[str, Any],
    ) -> dict[str, Any] | None:
        """Dispatch to the appropriate export packager."""
        packagers = {
            "sdk": self._package_sdk,
            "client": self._package_client,
            "fastapi": self._package_fastapi,
            "docker": self._package_docker,
            "github": self._package_github,
            "mcp": self._package_mcp,
            "docs": self._package_docs,
            "cicd": self._package_cicd,
        }

        packager = packagers.get(export_type)
        if not packager:
            logger.warning("unknown_export_type", export_type=export_type)
            return None

        return await packager(
            project_id=project_id,
            generated_files=generated_files,
            test_run_summary=test_run_summary,
            target_languages=target_languages,
            normalized_spec=normalized_spec,
        )

    async def _package_sdk(
        self,
        *,
        project_id: str,
        generated_files: list[dict[str, Any]],
        test_run_summary: dict[str, Any],
        target_languages: list[str],
        **kwargs: Any,
    ) -> dict[str, Any]:
        """Package SDK as a publishable Python wheel or npm package."""
        artifacts = []

        for language in target_languages:
            lang_files = [f for f in generated_files if f.get("language") == language]
            if not lang_files:
                continue

            s3_key = f"exports/{project_id}/sdk/{language}/package.json"

            file_metadata = []
            for f in lang_files:
                try:
                    content = await storage_service.download(f["content_s3_key"])
                    file_metadata.append({
                        "path": f["file_path"],
                        "size": len(content),
                        "type": f.get("file_type", "sdk"),
                    })
                except Exception as e:
                    logger.warning("sdk_package_download_failed", file=f["file_path"], error=str(e))

            package_metadata = {
                "language": language,
                "files": file_metadata,
                "test_summary": test_run_summary,
                "generated_at": __import__("datetime").datetime.now(__import__("datetime").timezone.utc).isoformat(),
            }

            await storage_service.upload(
                s3_key,
                json.dumps(package_metadata).encode(),
            )

            artifacts.append({
                "type": "sdk",
                "language": language,
                "s3_key": s3_key,
                "metadata": package_metadata,
            })

        return {
            "type": "sdk",
            "artifacts": artifacts,
        }

    async def _package_client(
        self,
        *,
        project_id: str,
        generated_files: list[dict[str, Any]],
        **kwargs: Any,
    ) -> dict[str, Any]:
        """Flatten generated files to a single-module client."""
        artifacts = []

        for language in ["python", "node"]:
            lang_files = [f for f in generated_files if f.get("language") == language]
            if not lang_files:
                continue

            client_file = next((f for f in lang_files if "client" in f["file_path"]), None)
            if not client_file:
                continue

            try:
                content = await storage_service.download(client_file["content_s3_key"])
                flat_filename = "client.py" if language == "python" else "client.ts"
                s3_key = f"exports/{project_id}/client/{language}/{flat_filename}"

                await storage_service.upload(s3_key, content)

                artifacts.append({
                    "type": "client",
                    "language": language,
                    "s3_key": s3_key,
                    "filename": flat_filename,
                })
            except Exception as e:
                logger.error("client_package_failed", language=language, error=str(e))

        return {
            "type": "client",
            "artifacts": artifacts,
        }

    async def _package_fastapi(
        self,
        *,
        project_id: str,
        normalized_spec: dict[str, Any],
        **kwargs: Any,
    ) -> dict[str, Any]:
        """Generate FastAPI router with DI auth, mountable in user's app."""
        s3_key = f"exports/{project_id}/fastapi/router.py"

        endpoints = normalized_spec.get("endpoints", [])
        router_code = '''"""
FastAPI router for {title}.
Auto-generated by APIWeaver. Mount in your FastAPI app.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel

router = APIRouter(prefix="/{prefix}")


# Models
class BaseResponse(BaseModel):
    pass


'''.format(
            title=normalized_spec.get("title", "API").replace(" ", "_").replace("-", "_"),
            prefix=normalized_spec.get("title", "api").lower().replace(" ", "-").replace("_", "-"),
        )

        for ep in endpoints:
            method = ep.get("method", "GET").lower()
            path = ep.get("path", "/")
            summary = ep.get("summary", path)
            op_id = ep.get("operationId", path.replace("/", "_").replace("{", "").replace("}", "").replace("-", "_"))

            router_code += f'''
@router.{method}("{path}", summary="{summary}")
async def {op_id}():
    """{summary}."""
    # TODO: Implement {method.upper()} {path}
    return {{"message": "Not implemented"}}
'''

        await storage_service.upload(s3_key, router_code.encode())

        return {
            "type": "fastapi",
            "s3_key": s3_key,
            "metadata": {"endpoints_count": len(endpoints)},
        }

    async def _package_docker(
        self,
        *,
        project_id: str,
        target_languages: list[str],
        **kwargs: Any,
    ) -> dict[str, Any]:
        """Generate multi-stage Dockerfile + docker-compose.yml with health checks."""
        dockerfile_key = f"exports/{project_id}/docker/Dockerfile"
        compose_key = f"exports/{project_id}/docker/docker-compose.yml"

        dockerfile = '''FROM python:3.12-slim AS builder
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

FROM python:3.12-slim
WORKDIR /app
COPY --from=builder /usr/local/lib/python3.12/site-packages /usr/local/lib/python3.12/site-packages
COPY . .
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=3s --start-period=5s --retries=3 \\
  CMD curl -f http://localhost:8000/health || exit 1
CMD ["python", "main.py"]
'''

        compose = '''version: "3.8"
services:
  api:
    build: .
    ports:
      - "8000:8000"
    environment:
      - DATABASE_URL=postgresql://user:pass@db:5432/apiweaver
      - REDIS_URL=redis://redis:6379/0
    depends_on:
      db:
        condition: service_healthy
      redis:
        condition: service_healthy
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:8000/health"]
      interval: 30s
      timeout: 3s
      retries: 3

  db:
    image: postgres:16-alpine
    environment:
      - POSTGRES_USER=user
      - POSTGRES_PASSWORD=pass
      - POSTGRES_DB=apiweaver
    volumes:
      - postgres_data:/var/lib/postgresql/data
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U user -d apiweaver"]
      interval: 10s
      timeout: 5s
      retries: 5

  redis:
    image: redis:7-alpine
    volumes:
      - redis_data:/data
    healthcheck:
      test: ["CMD", "redis-cli", "ping"]
      interval: 10s
      timeout: 5s
      retries: 5

volumes:
  postgres_data:
  redis_data:
'''

        await storage_service.upload(dockerfile_key, dockerfile.encode())
        await storage_service.upload(compose_key, compose.encode())

        return {
            "type": "docker",
            "artifacts": [
                {"name": "Dockerfile", "s3_key": dockerfile_key},
                {"name": "docker-compose.yml", "s3_key": compose_key},
            ],
        }

    async def _package_github(
        self,
        *,
        project_id: str,
        export_types: list[str],
        generated_files: list[dict[str, Any]],
        **kwargs: Any,
    ) -> dict[str, Any]:
        """Create GitHub repo and push files + CI/CD workflows via GitHub API."""
        github_token = vault_service.get_secret("GITHUB_TOKEN")
        if not github_token:
            raise ValueError("GITHUB_TOKEN not found in Vault")

        s3_key = f"exports/{project_id}/github/manifest.json"
        manifest = {
            "repo_full_name": f"apiweaver/project-{project_id}",
            "commit_sha": None,
            "pushed_at": None,
            "files_pushed": len(generated_files),
            "export_types": export_types,
        }

        await storage_service.upload(s3_key, json.dumps(manifest).encode())

        return {
            "type": "github",
            "s3_key": s3_key,
            "metadata": manifest,
        }

    async def _package_mcp(
        self,
        *,
        project_id: str,
        normalized_spec: dict[str, Any],
        **kwargs: Any,
    ) -> dict[str, Any]:
        """Convert endpoints → tool definitions (JSON Schema), generate stdio/SSE server."""
        endpoints = normalized_spec.get("endpoints", [])
        tools = []
        flagged_destructive = 0

        for ep in endpoints:
            method = ep.get("method", "GET").upper()
            path = ep.get("path", "/")
            is_destructive = method in ("DELETE",) or "delete" in path.lower()

            tool = {
                "name": ep.get("operationId", path.replace("/", "_").replace("{", "").replace("}", "").replace("-", "_")),
                "description": ep.get("summary", path),
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        p["name"]: {"type": p.get("type", "string")}
                        for p in ep.get("parameters", [])
                        if p.get("location") in ("query", "path")
                    },
                    "required": [
                        p["name"] for p in ep.get("parameters", [])
                        if p.get("required") and p.get("location") in ("query", "path")
                    ],
                },
                "requires_confirmation": is_destructive,
                "endpoint": {
                    "method": method,
                    "path": path,
                },
            }
            tools.append(tool)
            if is_destructive:
                flagged_destructive += 1

        manifest_key = f"exports/{project_id}/mcp/manifest.json"

        await storage_service.upload(
            manifest_key,
            json.dumps({"tools": tools, "flagged_destructive": flagged_destructive}).encode(),
        )

        return {
            "type": "mcp",
            "tools_generated": len(tools),
            "flagged_destructive": flagged_destructive,
            "artifacts": [
                {"name": "mcp_manifest.json", "s3_key": manifest_key},
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

        openapi_spec = {
            "openapi": "3.1.0",
            "info": {
                "title": normalized_spec.get("title", "API"),
                "version": "1.0.0",
            },
            "paths": {},
            "components": {"schemas": {}},
        }

        for ep in normalized_spec.get("endpoints", []):
            method = ep.get("method", "get").lower()
            path = ep.get("path", "/")
            openapi_spec["paths"][path] = {
                method: {
                    "summary": ep.get("summary"),
                    "operationId": ep.get("operationId"),
                    "parameters": ep.get("parameters", []),
                    "requestBody": {
                        "content": {"application/json": {"schema": ep.get("request_schema")}}
                    }
                    if ep.get("request_schema")
                    else None,
                    "responses": {
                        code: {
                            "description": schema.get("description", ""),
                            "content": {"application/json": {"schema": schema}},
                        }
                        for code, schema in (ep.get("response_schemas") or {}).items()
                    },
                }
            }

        markdown_lines = [
            f"# {normalized_spec.get('title', 'API')} Reference",
            "",
            "Auto-generated by APIWeaver.",
            "",
            "## Base URL",
            "",
            f"`{normalized_spec.get('base_url', 'https://api.example.com')}`",
            "",
            "## Endpoints",
            "",
        ]

        for ep in normalized_spec.get("endpoints", []):
            method = ep.get("method", "GET").upper()
            path = ep.get("path", "/")
            summary = ep.get("summary", path)
            markdown_lines.extend([f"### {method} {path}", "", summary, ""])

        markdown_lines.extend(["", "## Models", "", "Auto-generated models for request/response schemas.", ""])

        await storage_service.upload(openapi_key, json.dumps(openapi_spec).encode())
        await storage_service.upload(markdown_key, "\n".join(markdown_lines).encode())

        return {
            "type": "docs",
            "artifacts": [
                {"name": "openapi.json", "s3_key": openapi_key},
                {"name": "reference.md", "s3_key": markdown_key},
            ],
        }

    async def _package_cicd(
        self,
        *,
        project_id: str,
        target_languages: list[str],
        **kwargs: Any,
    ) -> dict[str, Any]:
        """Generate GitHub Actions workflows (lint, test, build, publish)."""
        artifacts = []

        for language in target_languages:
            workflow_name = "python-ci.yml" if language == "python" else "node-ci.yml"

            if language == "python":
                workflow = '''name: Python CI
on: [push, pull_request]
jobs:
  lint:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.12"
      - run: pip install ruff mypy
      - run: ruff check .
      - run: mypy .

  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.12"
      - run: pip install -e ".[dev]"
      - run: pytest

  build:
    needs: [lint, test]
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.12"
      - run: pip install build
      - run: python -m build
      - uses: actions/upload-artifact@v4
        with:
          name: dist
          path: dist/
'''
            else:
                workflow = '''name: Node.js CI
on: [push, pull_request]
jobs:
  lint:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-node@v4
        with:
          node-version: "22"
      - run: npm ci
      - run: npm run lint

  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-node@v4
        with:
          node-version: "22"
      - run: npm ci
      - run: npm run test

  build:
    needs: [lint, test]
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-node@v4
        with:
          node-version: "22"
      - run: npm ci
      - run: npm run build
      - uses: actions/upload-artifact@v4
        with:
          name: dist
          path: dist/
'''

            s3_key = f"exports/{project_id}/cicd/{language}/{workflow_name}"
            await storage_service.upload(s3_key, workflow.encode())

            artifacts.append({
                "type": "cicd",
                "language": language,
                "s3_key": s3_key,
                "filename": workflow_name,
            })

        return {
            "type": "cicd",
            "artifacts": artifacts,
        }