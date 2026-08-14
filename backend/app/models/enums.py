"""Enum-like value sets from `Database.md §3`.

`Database.md §5` wants CHECK constraints as "a second line of defense beyond application
validation", so each of these is paired with a `CheckConstraint` on its column rather
than a Postgres `ENUM` type. That keeps adding a new value a one-line CHECK change
instead of an `ALTER TYPE` migration, and keeps the constraint visible in the model.
"""

from __future__ import annotations

from enum import StrEnum


class PlanTier(StrEnum):
    FREE = "free"
    PRO = "pro"
    ENTERPRISE = "enterprise"


class OrgRole(StrEnum):
    OWNER = "owner"
    ADMIN = "admin"
    MEMBER = "member"
    BILLING = "billing"


class ProjectRole(StrEnum):
    OWNER = "owner"
    EDITOR = "editor"
    VIEWER = "viewer"


class ProjectStatus(StrEnum):
    DRAFT = "draft"
    PLANNING = "planning"
    BUILDING = "building"
    TESTING = "testing"
    READY = "ready"
    FAILED = "failed"
    ARCHIVED = "archived"


class DocumentFormat(StrEnum):
    OPENAPI = "openapi"
    SWAGGER = "swagger"
    POSTMAN = "postman"
    MARKDOWN = "markdown"
    PDF = "pdf"
    HTML = "html"


class HTTPMethod(StrEnum):
    GET = "GET"
    POST = "POST"
    PUT = "PUT"
    PATCH = "PATCH"
    DELETE = "DELETE"


class ParameterLocation(StrEnum):
    PATH = "path"
    QUERY = "query"
    HEADER = "header"
    BODY = "body"


class DependencyRelationship(StrEnum):
    REQUIRES_AUTH = "requires_auth"
    REQUIRES_CREATED_RESOURCE = "requires_created_resource"
    OPTIONAL_PRECEDES = "optional_precedes"


class AuthScheme(StrEnum):
    API_KEY = "api_key"
    BEARER_JWT = "bearer_jwt"
    OAUTH2_CLIENT_CREDENTIALS = "oauth2_client_credentials"
    OAUTH2_AUTH_CODE = "oauth2_auth_code"
    BASIC = "basic"
    HMAC = "hmac"
    NONE = "none"


class WorkflowStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    PAUSED_FOR_APPROVAL = "paused_for_approval"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class TargetLanguage(StrEnum):
    PYTHON = "python"
    NODE = "node"


class GeneratedFileType(StrEnum):
    SDK = "sdk"
    TEST = "test"
    DOCKERFILE = "dockerfile"
    CI_CD = "ci_cd"
    README = "readme"
    MCP_MANIFEST = "mcp_manifest"


class TestEnvironment(StrEnum):
    SANDBOX = "sandbox"
    LIVE = "live"


class TestResultStatus(StrEnum):
    PASSED = "passed"
    FAILED = "failed"
    SKIPPED = "skipped"


class RepairOutcome(StrEnum):
    RESOLVED = "resolved"
    STILL_FAILING = "still_failing"
    ESCALATED = "escalated"


class ExportType(StrEnum):
    SDK = "sdk"
    CLIENT = "client"
    DOCKER = "docker"
    GITHUB = "github"
    MCP = "mcp"
    DOCS = "docs"
    CICD = "cicd"


class ActorType(StrEnum):
    """Audit-log actor kind (addendum §A.3)."""

    USER = "user"
    AGENT = "agent"
    SYSTEM = "system"


def check_in(column: str, values: type[StrEnum]) -> str:
    """Render a CHECK expression restricting `column` to `values`.

    Values come from a Python enum defined in this module — never from request data —
    so this is a static DDL fragment, not dynamic SQL (`Security.md §11`).
    """
    rendered = ", ".join(f"'{member.value}'" for member in values)
    return f"{column} IN ({rendered})"
