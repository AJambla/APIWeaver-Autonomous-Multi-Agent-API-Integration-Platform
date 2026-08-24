"""SQLAlchemy models for the full `Database.md §3` schema.

Every model is imported here so `Base.metadata` is complete by the time Alembic
autogenerate inspects it — a model that isn't imported is silently invisible to
autogenerate, which would produce a migration that drops the table.
"""

from sqlalchemy import Table

from app.db.base import Base
from app.models.audit import AuditAction, AuditLog
from app.models.auth_config import AuthConfig, SecretRef
from app.models.codegen import CodeGenerationRun, GeneratedFile
from app.models.document import Document, DocumentVersion
from app.models.export import Export, GitHubExport, MCPTool, SDKPackage, SDKVersion
from app.models.github import GitHubConnection, GitHubOAuthState
from app.models.metrics import UsageMetric
from app.models.organization import Organization, OrganizationMember
from app.models.project import Project, ProjectMember
from app.models.retry import RetryConfig
from app.models.spec import APISpec, Endpoint, EndpointDependency, EndpointParameter
from app.models.testing import RepairAttempt, TestResult, TestRun
from app.models.user import APIKey, RefreshToken, User
from app.models.versioning import ArtifactVersion
from app.models.workflow import AgentEvent, ToolCall, WorkflowCheckpoint, WorkflowRun


def non_partitioned_tables() -> list[Table]:
    """Tables that `metadata.create_all` can build directly.

    `agent_events` and `usage_metrics` are natively partitioned with composite
    `(id, <partition key>)` primary keys, which `create_all` cannot express — they exist
    only via the raw DDL in migration `0002`. Tests that build a schema from metadata
    pass this list so they don't trip over Postgres-only DDL.
    """
    return [
        table for table in Base.metadata.sorted_tables if not table.info.get("managed_by_migration")
    ]


__all__ = [
    "APIKey",
    "APISpec",
    "AgentEvent",
    "ArtifactVersion",
    "AuditAction",
    "AuditLog",
    "AuthConfig",
    "Base",
    "CodeGenerationRun",
    "Document",
    "DocumentVersion",
    "Endpoint",
    "EndpointDependency",
    "EndpointParameter",
    "Export",
    "GeneratedFile",
    "GitHubConnection",
    "GitHubExport",
    "GitHubOAuthState",
    "MCPTool",
    "Organization",
    "OrganizationMember",
    "Project",
    "ProjectMember",
    "RefreshToken",
    "RepairAttempt",
    "RetryConfig",
    "SDKPackage",
    "SDKVersion",
    "SecretRef",
    "TestResult",
    "TestRun",
    "ToolCall",
    "UsageMetric",
    "User",
    "WorkflowCheckpoint",
    "WorkflowRun",
    "non_partitioned_tables",
]
