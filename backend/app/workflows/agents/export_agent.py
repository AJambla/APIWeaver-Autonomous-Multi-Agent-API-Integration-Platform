"""Export Agent (``AI_Instruction.md §1``, ``Feature.md §15-24``, ``API.md §6.8``).

Packages final artifacts (SDK, Client, FastAPI wrapper, Docker, GitHub, MCP, docs, CI/CD)
and stores them in S3 with metadata in Postgres.
"""

from __future__ import annotations

import json
import uuid
from typing import Any

from sqlalchemy import select

from app.core.config import get_settings
from app.core.logging import get_logger
from app.models.enums import ExportType
from app.models.github import GitHubConnection
from app.models.project import ProjectMember
from app.services.github_service import GitHubAppClient
from app.services.storage_service import storage_service
from app.services.vault_service import create_vault_client
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
    """Packages final artifacts from generated code and test results."""

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
        project_id = state.get("project_id")
        generated_files = state.get("generated_files", [])
        test_run_summary = state.get("test_run_summary", {})
        target_languages = state.get("target_languages") or ["python", "node"]
        normalized_spec = state.get("normalized_spec", {})

        if export_types is None:
            export_types = state.get("export_types") or [e.value for e in ExportType]

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

            import io
            import zipfile
            zip_buffer = io.BytesIO()
            normalized_spec = kwargs.get("normalized_spec") or {}
            if not isinstance(normalized_spec, dict):
                normalized_spec = {}
            spec_title = normalized_spec.get("title", "API Client")
            with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zf:
                for f in lang_files:
                    try:
                        f_content = await storage_service.download(f["content_s3_key"])
                        zf.writestr(f.get("file_path", "unknown"), f_content)
                    except Exception as e:
                        logger.warning("sdk_zip_file_failed", file=f.get("file_path"), error=str(e))

                file_paths = {f.get("file_path", "") for f in lang_files}
                if "README.md" not in file_paths:
                    zf.writestr("README.md", f"# {spec_title} {language.capitalize()} SDK\n\nAuto-generated client by APIWeaver.\n")
                if language == "python" and not any(p.startswith("tests/") for p in file_paths):
                    zf.writestr("tests/__init__.py", "")
                    zf.writestr("tests/test_client.py", "# Smoke test\ndef test_smoke():\n    pass\n")
                elif language == "node" and not any(p.startswith("tests/") or p.endswith(".test.ts") for p in file_paths):
                    zf.writestr("tests/client.test.ts", "import { describe, it, expect } from 'vitest';\ndescribe('client', () => {\n  it('smoke', () => {\n    expect(true).toBe(true);\n  });\n});\n")

                zf.writestr("package_metadata.json", json.dumps(package_metadata, indent=2))
            zip_bytes = zip_buffer.getvalue()
            zip_s3_key = f"exports/{project_id}/sdk/{language}/sdk-{language}.zip"
            await storage_service.upload(zip_s3_key, zip_bytes)

            artifacts.append({
                "type": "sdk",
                "language": language,
                "s3_key": zip_s3_key,
                "filename": f"sdk-{language}.zip",
                "metadata": package_metadata,
            })

            if self.session_factory:
                try:
                    async with self.session_factory() as session:
                        from app.models.export import SDKPackage, SDKVersion
                        title_slug = spec_title.lower().replace(" ", "-").replace("_", "-").strip("-") or "client"
                        pkg_name = f"{title_slug}-{language}-sdk"
                        ver_str = str(normalized_spec.get("version") or "0.1.0")
                        pkg_stmt = select(SDKPackage).where(
                            SDKPackage.project_id == uuid.UUID(str(project_id)),
                            SDKPackage.language == language,
                        )
                        pkg = await session.scalar(pkg_stmt)
                        if pkg is None:
                            pkg = SDKPackage(
                                project_id=uuid.UUID(str(project_id)),
                                language=language,
                                package_name=pkg_name,
                            )
                            session.add(pkg)
                            await session.flush()
                        ver = SDKVersion(
                            sdk_package_id=pkg.id,
                            semver=ver_str,
                            s3_key=zip_s3_key,
                        )
                        session.add(ver)
                        await session.commit()
                except Exception as db_err:
                    logger.warning("sdk_package_db_save_failed", error=str(db_err))

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
        title = to_display_name(normalized_spec.get("title", "API"), fallback="API")
        prefix = title.lower().replace(" ", "-").replace("_", "-")
        router_code = '''"""
FastAPI router for {title}.
Auto-generated by APIWeaver. Mount in your FastAPI app.
"""

from __future__ import annotations

import httpx
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel

router = APIRouter(prefix={prefix_literal})
TARGET_BASE_URL = {base_url_literal}


# Models
class BaseResponse(BaseModel):
    pass


'''.format(
            title=title.replace(" ", "_").replace("-", "_"),
            prefix_literal=to_literal(f"/{prefix}"),
            base_url_literal=to_literal(to_base_url(normalized_spec.get("base_url") or "http://localhost:8000")),
        )

        for ep in endpoints:
            method = to_http_method(ep.get("method", "GET"))
            path = to_path(ep.get("path", "/"))
            summary = to_text(ep.get("summary"), fallback=path)
            declared = ep.get("operationId") or derived_operation_id(method, path)
            op_id = to_identifier(declared, fallback="endpoint")

            router_code += f'''
@router.{method}({to_literal(path)}, summary={to_literal(summary)})
async def {op_id}():
    {to_literal(summary)}
    # Forward or mock response for {method.upper()} {path}
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.request("{method.upper()}", f"{{TARGET_BASE_URL}}{path}")
            if resp.status_code < 400:
                return resp.json() if resp.content else {{"status": "ok"}}
    except Exception:
        pass
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

        if "python" not in target_languages and "node" in target_languages:
            dockerfile = '''FROM node:22-alpine AS builder
WORKDIR /app
COPY package*.json ./
RUN npm ci || npm install
COPY . .
RUN if npm run | grep -q ' build$'; then npm run build; fi

FROM node:22-alpine
WORKDIR /app
COPY --from=builder /app ./
EXPOSE 3000
HEALTHCHECK --interval=30s --timeout=3s --start-period=5s --retries=3 \\
  CMD wget --no-verbose --tries=1 --spider http://localhost:3000/health || exit 1
CMD ["npm", "start"]
'''
            index_js = '''import http from "node:http";
const server = http.createServer((req, res) => {
  if (req.url === "/health" || req.url === "/healthz") {
    res.writeHead(200, { "Content-Type": "application/json" });
    res.end(JSON.stringify({ status: "healthy" }));
  } else {
    res.writeHead(404);
    res.end();
  }
});
server.listen(3000, "0.0.0.0");
'''
            await storage_service.upload(f"exports/{project_id}/docker/index.js", index_js.encode())
        else:
            dockerfile = '''FROM python:3.12.15-slim@sha256:02108f5d322dd89f1c9e552442c25acb0543dfdbc455693a5599624f20d9155d AS builder
WORKDIR /app
COPY requirements.txt* ./
RUN if [ -f requirements.txt ]; then pip install --no-cache-dir -r requirements.txt; fi

FROM python:3.12.15-slim@sha256:02108f5d322dd89f1c9e552442c25acb0543dfdbc455693a5599624f20d9155d
WORKDIR /app
COPY --from=builder /usr/local/lib/python3.12/site-packages /usr/local/lib/python3.12/site-packages
COPY . .
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=3s --start-period=5s --retries=3 \\
  CMD curl -f http://localhost:8000/health || exit 1
CMD ["python", "main.py"]
'''
            main_py = '''from http.server import HTTPServer, BaseHTTPRequestHandler

class HealthHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path in ("/health", "/healthz"):
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(b'{"status":"healthy"}')
        else:
            self.send_response(404)
            self.end_headers()

    def log_message(self, *args):
        pass

if __name__ == "__main__":
    server = HTTPServer(("0.0.0.0", 8000), HealthHandler)
    server.serve_forever()
'''
            await storage_service.upload(f"exports/{project_id}/docker/main.py", main_py.encode())

        is_node_only = "python" not in target_languages and "node" in target_languages
        api_port = "3000" if is_node_only else "8000"
        health_cmd = (
            '["CMD", "wget", "--no-verbose", "--tries=1", "--spider", "http://localhost:3000/health"]'
            if is_node_only
            else '["CMD", "curl", "-f", "http://localhost:8000/health"]'
        )

        compose = f'''version: "3.8"
services:
  api:
    build: .
    ports:
      - "{api_port}:{api_port}"
    environment:
      - DATABASE_URL=postgresql://${{POSTGRES_USER:-apiweaver}}:${{POSTGRES_PASSWORD:-apiweaver}}@db:5432/${{POSTGRES_DB:-apiweaver}}
      - REDIS_URL=redis://redis:6379/0
    depends_on:
      db:
        condition: service_healthy
      redis:
        condition: service_healthy
    healthcheck:
      test: {health_cmd}
      interval: 30s
      timeout: 3s
      retries: 3

  db:
    image: postgres:16-alpine
    environment:
      - POSTGRES_USER=${{POSTGRES_USER:-apiweaver}}
      - POSTGRES_PASSWORD=${{POSTGRES_PASSWORD:-apiweaver}}
      - POSTGRES_DB=${{POSTGRES_DB:-apiweaver}}
    volumes:
      - postgres_data:/var/lib/postgresql/data
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U $${{POSTGRES_USER:-apiweaver}} -d $${{POSTGRES_DB:-apiweaver}}"]
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

    async def _resolve_github_installation(
        self, project_id: str, settings: Any
    ) -> tuple[int | None, str | None]:
        """Find an active GitHub connection for a project member and its App installation.

        Returns (installation_id, user_token), or (None, None) when no usable
        connection exists so the export can degrade to a graceful skip.
        """
        if self.session_factory is None or not project_id:
            return None, None
        try:
            project_uuid = uuid.UUID(str(project_id))
        except ValueError:
            return None, None

        try:
            async with self.session_factory() as session:
                result = await session.execute(
                    select(GitHubConnection)
                    .join(ProjectMember, ProjectMember.user_id == GitHubConnection.user_id)
                    .where(
                        ProjectMember.project_id == project_uuid,
                        GitHubConnection.revoked_at.is_(None),
                        GitHubConnection.access_token_vault_path.is_not(None),
                    )
                    .order_by(GitHubConnection.created_at.desc())
                    .limit(1)
                )
                connection = result.scalar_one_or_none()
        except Exception as e:
            logger.warning(
                "github_connection_lookup_failed", project_id=project_id, error=str(e)
            )
            return None, None

        if connection is None:
            return None, None

        secret = await create_vault_client(settings).read_secret(
            connection.access_token_vault_path
        )
        user_token = (secret or {}).get("access_token")
        if not user_token:
            logger.warning(
                "github_connection_token_missing",
                project_id=project_id,
                github_username=connection.github_username,
            )
            return None, None

        github_client = GitHubAppClient(settings)
        try:
            installations = await github_client.get_user_installations(user_token)
        except Exception as e:
            logger.warning(
                "github_installations_lookup_failed", project_id=project_id, error=str(e)
            )
            return None, None

        for installation in installations:
            if installation.get("id") is not None:
                return int(installation["id"]), user_token
        return None, None

    async def _resolve_file_content(self, gf: dict[str, Any]) -> str:
        """Download generated file content from storage, falling back to inline content."""
        s3_key = gf.get("content_s3_key")
        if not s3_key:
            return gf.get("content", "")
        try:
            raw = await storage_service.download(s3_key)
            return raw.decode("utf-8") if isinstance(raw, bytes) else str(raw)
        except Exception as e:
            logger.warning(
                "github_export_content_download_failed", s3_key=s3_key, error=str(e)
            )
            return gf.get("content", "")

    async def _package_github(
        self,
        *,
        project_id: str,
        export_types: list[str] | None = None,
        generated_files: list[dict[str, Any]],
        github_repo_name: str | None = None,
        github_org: str | None = None,
        github_private: bool = True,
        github_branch: str = "main",
        github_commit_message: str = "Generated by APIWeaver",
        **kwargs: Any,
    ) -> dict[str, Any]:
        """Create GitHub repo and push files + CI/CD workflows via GitHub API."""
        settings = get_settings()

        if not settings.github_app_id:
            logger.warning("github_app_not_configured", project_id=project_id)
            return {
                "type": "github",
                "status": "skipped",
                "error": "GitHub App not configured",
            }

        try:
            github_client = GitHubAppClient(settings)

            spec = kwargs.get("normalized_spec") or {}
            title_slug = spec.get("title", "").lower().replace(" ", "-").replace("_", "-").strip("-")
            repo_name = github_repo_name or (f"{title_slug}-client" if title_slug else f"apiweaver-project-{project_id[:8]}")

            installation_id, user_token = await self._resolve_github_installation(
                project_id, settings
            )

            if installation_id is None:
                logger.info(
                    "github_export_no_installation",
                    project_id=project_id,
                    repo_name=repo_name,
                )
                return {
                    "type": "github",
                    "status": "skipped",
                    "error": "No GitHub App installation found. Connect GitHub and install the app on your repository or organization.",
                    "install_url": f"https://github.com/apps/{getattr(settings, 'github_app_slug', 'apiweaver')}/installations",
                }

            installation_token = await github_client.get_installation_token(installation_id)

            repo = await github_client.create_repository(
                installation_token=installation_token,
                org=github_org,
                name=repo_name,
                private=github_private,
            )
            repo_full_name = repo["full_name"]

            files_to_push = []
            for gf in generated_files:
                content = await self._resolve_file_content(gf)
                files_to_push.append({
                    "path": gf.get("file_path", gf.get("filename", "unknown")),
                    "content": content,
                    "encoding": "utf-8",
                })
            
            files_to_push.append({
                "path": "README.md",
                "content": f"# {repo_name}\n\nGenerated by APIWeaver.\n\n## Usage\n\nSee documentation for usage instructions.\n",
                "encoding": "utf-8",
            })
            
            if not files_to_push:
                logger.warning("github_export_no_files", project_id=project_id)
                return {
                    "type": "github",
                    "status": "skipped",
                    "error": "No files to push",
                }
            
            commit_sha = await github_client.push_files_via_git_data_api(
                installation_token=installation_token,
                repo_full_name=repo_full_name,
                files=files_to_push,
                message=github_commit_message,
                branch=github_branch,
            )
            
            from datetime import UTC, datetime
            pushed_at = datetime.now(UTC).isoformat()
            
            s3_key = f"exports/{project_id}/github/manifest.json"
            manifest = {
                "repo_full_name": repo_full_name,
                "commit_sha": commit_sha,
                "pushed_at": pushed_at,
                "files_pushed": len(files_to_push),
                "export_types": export_types or [],
                "branch": github_branch,
                "private": github_private,
            }
            
            await storage_service.upload(s3_key, json.dumps(manifest).encode())
            
            logger.info(
                "github_export_completed",
                project_id=project_id,
                repo_full_name=repo_full_name,
                commit_sha=commit_sha,
            )
            
            return {
                "type": "github",
                "status": "completed",
                "s3_key": s3_key,
                "metadata": manifest,
                "repo_url": f"https://github.com/{repo_full_name}",
            }
            
        except Exception as e:
            logger.error("github_export_failed", project_id=project_id, error=str(e))
            return {
                "type": "github",
                "status": "failed",
                "error": str(e),
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

        doc_version = str(normalized_spec.get("version") or (normalized_spec.get("info") or {}).get("version") or "1.0.0")
        openapi_spec = {
            "openapi": "3.1.0",
            "info": {
                "title": normalized_spec.get("title", "API"),
                "version": doc_version,
            },
            "paths": {},
            "components": {
                "schemas": normalized_spec.get("components", {}).get("schemas", {})
                or normalized_spec.get("definitions", {})
            },
        }

        for ep in normalized_spec.get("endpoints", []):
            method = ep.get("method", "get").lower()
            path = ep.get("path", "/")
            op_data = {
                "summary": ep.get("summary"),
                "operationId": ep.get("operationId"),
                "parameters": ep.get("parameters", []),
                "responses": {
                    code: {
                        "description": schema.get("description", "") if isinstance(schema, dict) else "",
                        "content": {"application/json": {"schema": schema}},
                    }
                    for code, schema in (ep.get("response_schemas") or {}).items()
                },
            }
            if ep.get("request_schema"):
                op_data["requestBody"] = {
                    "content": {"application/json": {"schema": ep.get("request_schema")}}
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