"""initial schema — Database.md §3 plus ADDENDUM-Phase1.md §A.1-A.3

Creates every table in `Database.md §3` except the two natively-partitioned ones
(`agent_events`, `usage_metrics`), which migration `0002` creates with raw DDL because
SQLAlchemy cannot express `PARTITION BY RANGE`.

Constraint and index names come from the naming convention in `app/db/base.py`, so
`downgrade()` can drop them deterministically by name (`Database.md §6`). Check
constraints are declared with their bare name here — Alembic applies the
`ck_%(table_name)s_%(constraint_name)s` convention on top.

Generated once from the model metadata and checked in as a static artifact. Do not
regenerate it: later schema changes ship as new revisions using the expand/contract
pattern (`Database.md §6`).

Revision ID: 0001
Revises:
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op
from app.db.base import INET, JSONB, UUID, false_, gen_random_uuid, utcnow

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "organizations",
        sa.Column("id", UUID(), server_default=gen_random_uuid(), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("slug", sa.String(100), nullable=False),
        sa.Column("plan_tier", sa.String(50), server_default=sa.text("'free'"), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=utcnow(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=utcnow(), nullable=False
        ),
        sa.CheckConstraint("plan_tier IN ('free', 'pro', 'enterprise')", name="plan_tier_valid"),
        sa.PrimaryKeyConstraint("id", name="pk_organizations"),
        sa.UniqueConstraint("slug", name="uq_organizations_slug"),
    )
    op.create_table(
        "tool_calls",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("agent_event_id", sa.BigInteger(), nullable=False),
        sa.Column("tool_name", sa.String(100), nullable=False),
        sa.Column("arguments", JSONB(), nullable=True),
        sa.Column("result", JSONB(), nullable=True),
        sa.Column("duration_ms", sa.Integer(), nullable=True),
        sa.PrimaryKeyConstraint("id", name="pk_tool_calls"),
    )
    op.create_index("idx_tool_calls_agent_event_id", "tool_calls", ["agent_event_id"])
    op.create_table(
        "users",
        sa.Column("id", UUID(), server_default=gen_random_uuid(), nullable=False),
        sa.Column("email", sa.String(255), nullable=False),
        sa.Column("password_hash", sa.String(255), nullable=True),
        sa.Column("full_name", sa.String(255), nullable=False),
        sa.Column("mfa_enabled", sa.Boolean(), server_default=false_(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=utcnow(), nullable=False
        ),
        sa.PrimaryKeyConstraint("id", name="pk_users"),
        sa.UniqueConstraint("email", name="uq_users_email"),
    )
    op.create_table(
        "audit_logs",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("organization_id", UUID(), nullable=True),
        sa.Column("actor_user_id", UUID(), nullable=True),
        sa.Column("actor_type", sa.String(20), nullable=False),
        sa.Column("action", sa.String(100), nullable=False),
        sa.Column("resource_type", sa.String(50), nullable=True),
        sa.Column("resource_id", sa.String(100), nullable=True),
        sa.Column("ip_address", INET(), nullable=True),
        sa.Column("user_agent", sa.String(500), nullable=True),
        sa.Column("event_metadata", JSONB(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=utcnow(), nullable=False
        ),
        sa.CheckConstraint("actor_type IN ('user', 'agent', 'system')", name="actor_type_valid"),
        sa.ForeignKeyConstraint(
            ["actor_user_id"],
            ["users.id"],
            name="fk_audit_logs_actor_user_id_users",
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["organizations.id"],
            name="fk_audit_logs_organization_id_organizations",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_audit_logs"),
    )
    op.create_index("idx_audit_logs_actor", "audit_logs", ["actor_user_id"])
    op.create_index("idx_audit_logs_org_created", "audit_logs", ["organization_id", "created_at"])
    op.create_table(
        "organization_members",
        sa.Column("organization_id", UUID(), nullable=False),
        sa.Column("user_id", UUID(), nullable=False),
        sa.Column("role", sa.String(50), nullable=False),
        sa.Column("joined_at", sa.DateTime(timezone=True), server_default=utcnow(), nullable=False),
        sa.CheckConstraint("role IN ('owner', 'admin', 'member', 'billing')", name="role_valid"),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["organizations.id"],
            name="fk_organization_members_organization_id_organizations",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name="fk_organization_members_user_id_users",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("organization_id", "user_id", name="pk_organization_members"),
    )
    op.create_table(
        "projects",
        sa.Column("id", UUID(), server_default=gen_random_uuid(), nullable=False),
        sa.Column("organization_id", UUID(), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("status", sa.String(50), server_default=sa.text("'draft'"), nullable=False),
        sa.Column("created_by", UUID(), nullable=True),
        sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=utcnow(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=utcnow(), nullable=False
        ),
        sa.CheckConstraint(
            "status IN ('draft', 'planning', 'building', 'testing', 'ready', 'failed', 'archived')",
            name="status_valid",
        ),
        sa.ForeignKeyConstraint(
            ["created_by"], ["users.id"], name="fk_projects_created_by_users", ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["organizations.id"],
            name="fk_projects_organization_id_organizations",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_projects"),
    )
    op.create_index("idx_projects_org_id", "projects", ["organization_id"])
    op.create_index("idx_projects_status", "projects", ["status"])
    op.create_table(
        "refresh_tokens",
        sa.Column("id", UUID(), server_default=gen_random_uuid(), nullable=False),
        sa.Column("user_id", UUID(), nullable=False),
        sa.Column("family_id", UUID(), nullable=False),
        sa.Column("token_hash", sa.String(64), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=utcnow(), nullable=False
        ),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name="fk_refresh_tokens_user_id_users", ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name="pk_refresh_tokens"),
        sa.UniqueConstraint("token_hash", name="uq_refresh_tokens_token_hash"),
    )
    op.create_index("idx_refresh_tokens_family_id", "refresh_tokens", ["family_id"])
    op.create_index("idx_refresh_tokens_user_id", "refresh_tokens", ["user_id"])
    op.create_table(
        "api_keys",
        sa.Column("id", UUID(), server_default=gen_random_uuid(), nullable=False),
        sa.Column("organization_id", UUID(), nullable=False),
        sa.Column("project_id", UUID(), nullable=True),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("key_prefix", sa.String(20), nullable=False),
        sa.Column("key_hash", sa.String(64), nullable=False),
        sa.Column("created_by", UUID(), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=utcnow(), nullable=False
        ),
        sa.CheckConstraint("key_prefix IN ('apw_live_', 'apw_test_')", name="key_prefix_valid"),
        sa.ForeignKeyConstraint(
            ["created_by"], ["users.id"], name="fk_api_keys_created_by_users", ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["organizations.id"],
            name="fk_api_keys_organization_id_organizations",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["project_id"],
            ["projects.id"],
            name="fk_api_keys_project_id_projects",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_api_keys"),
        sa.UniqueConstraint("key_hash", name="uq_api_keys_key_hash"),
    )
    op.create_index("idx_api_keys_org_id", "api_keys", ["organization_id"])
    op.create_index("idx_api_keys_prefix", "api_keys", ["key_prefix"])
    op.create_table(
        "artifact_versions",
        sa.Column("id", UUID(), server_default=gen_random_uuid(), nullable=False),
        sa.Column("project_id", UUID(), nullable=False),
        sa.Column("artifact_type", sa.String(50), nullable=False),
        sa.Column("version_number", sa.Integer(), nullable=False),
        sa.Column("diff_ref", sa.String(1000), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=utcnow(), nullable=False
        ),
        sa.ForeignKeyConstraint(
            ["project_id"],
            ["projects.id"],
            name="fk_artifact_versions_project_id_projects",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_artifact_versions"),
        sa.UniqueConstraint(
            "project_id",
            "artifact_type",
            "version_number",
            name="uniq_artifact_versions_project_type_number",
        ),
    )
    op.create_index("idx_artifact_versions_project_id", "artifact_versions", ["project_id"])
    op.create_table(
        "auth_configs",
        sa.Column("id", UUID(), server_default=gen_random_uuid(), nullable=False),
        sa.Column("project_id", UUID(), nullable=False),
        sa.Column("scheme", sa.String(50), nullable=False),
        sa.Column("config_json", JSONB(), nullable=False),
        sa.Column("verified", sa.Boolean(), server_default=false_(), nullable=False),
        sa.CheckConstraint(
            "scheme IN ('api_key', 'bearer_jwt', 'oauth2_client_credentials', 'oauth2_auth_code', 'basic', 'hmac', 'none')",
            name="scheme_valid",
        ),
        sa.ForeignKeyConstraint(
            ["project_id"],
            ["projects.id"],
            name="fk_auth_configs_project_id_projects",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_auth_configs"),
        sa.UniqueConstraint("project_id", name="uq_auth_configs_project_id"),
    )
    op.create_table(
        "documents",
        sa.Column("id", UUID(), server_default=gen_random_uuid(), nullable=False),
        sa.Column("project_id", UUID(), nullable=False),
        sa.Column("filename", sa.String(500), nullable=False),
        sa.Column("format", sa.String(50), nullable=False),
        sa.Column("s3_key", sa.String(1000), nullable=False),
        sa.Column("checksum_sha256", sa.String(64), nullable=False),
        sa.Column("uploaded_by", UUID(), nullable=True),
        sa.Column(
            "uploaded_at", sa.DateTime(timezone=True), server_default=utcnow(), nullable=False
        ),
        sa.CheckConstraint(
            "format IN ('openapi', 'swagger', 'postman', 'markdown', 'pdf', 'html')",
            name="format_valid",
        ),
        sa.ForeignKeyConstraint(
            ["project_id"],
            ["projects.id"],
            name="fk_documents_project_id_projects",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["uploaded_by"],
            ["users.id"],
            name="fk_documents_uploaded_by_users",
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_documents"),
        sa.UniqueConstraint("project_id", "checksum_sha256", name="uniq_documents_checksum"),
    )
    op.create_index("idx_documents_project_id", "documents", ["project_id"])
    op.create_table(
        "exports",
        sa.Column("id", UUID(), server_default=gen_random_uuid(), nullable=False),
        sa.Column("project_id", UUID(), nullable=False),
        sa.Column("export_type", sa.String(50), nullable=False),
        sa.Column("status", sa.String(20), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=utcnow(), nullable=False
        ),
        sa.CheckConstraint(
            "export_type IN ('sdk', 'client', 'docker', 'github', 'mcp', 'docs', 'cicd')",
            name="export_type_valid",
        ),
        sa.ForeignKeyConstraint(
            ["project_id"],
            ["projects.id"],
            name="fk_exports_project_id_projects",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_exports"),
    )
    op.create_index("idx_exports_project_id", "exports", ["project_id"])
    op.create_table(
        "mcp_tools",
        sa.Column("id", UUID(), server_default=gen_random_uuid(), nullable=False),
        sa.Column("project_id", UUID(), nullable=False),
        sa.Column("tool_name", sa.String(255), nullable=False),
        sa.Column("input_schema", JSONB(), nullable=False),
        sa.Column("requires_confirmation", sa.Boolean(), server_default=false_(), nullable=False),
        sa.ForeignKeyConstraint(
            ["project_id"],
            ["projects.id"],
            name="fk_mcp_tools_project_id_projects",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_mcp_tools"),
        sa.UniqueConstraint("project_id", "tool_name", name="uniq_mcp_tools_project_tool_name"),
    )
    op.create_table(
        "project_members",
        sa.Column("project_id", UUID(), nullable=False),
        sa.Column("user_id", UUID(), nullable=False),
        sa.Column("role", sa.String(50), nullable=False),
        sa.CheckConstraint("role IN ('owner', 'editor', 'viewer')", name="role_valid"),
        sa.ForeignKeyConstraint(
            ["project_id"],
            ["projects.id"],
            name="fk_project_members_project_id_projects",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name="fk_project_members_user_id_users", ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("project_id", "user_id", name="pk_project_members"),
    )
    op.create_table(
        "sdk_packages",
        sa.Column("id", UUID(), server_default=gen_random_uuid(), nullable=False),
        sa.Column("project_id", UUID(), nullable=False),
        sa.Column("language", sa.String(20), nullable=False),
        sa.Column("package_name", sa.String(255), nullable=False),
        sa.CheckConstraint("language IN ('python', 'node')", name="language_valid"),
        sa.ForeignKeyConstraint(
            ["project_id"],
            ["projects.id"],
            name="fk_sdk_packages_project_id_projects",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_sdk_packages"),
        sa.UniqueConstraint("project_id", "language", name="uniq_sdk_packages_project_language"),
    )
    op.create_table(
        "workflow_runs",
        sa.Column("id", UUID(), server_default=gen_random_uuid(), nullable=False),
        sa.Column("project_id", UUID(), nullable=False),
        sa.Column("triggered_by", UUID(), nullable=True),
        sa.Column("status", sa.String(50), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "total_tokens_used", sa.BigInteger(), server_default=sa.text("0"), nullable=False
        ),
        sa.Column(
            "estimated_cost_usd", sa.Numeric(10, 4), server_default=sa.text("0"), nullable=False
        ),
        sa.CheckConstraint(
            "status IN ('queued', 'running', 'paused_for_approval', 'completed', 'failed', 'cancelled')",
            name="status_valid",
        ),
        sa.ForeignKeyConstraint(
            ["project_id"],
            ["projects.id"],
            name="fk_workflow_runs_project_id_projects",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["triggered_by"],
            ["users.id"],
            name="fk_workflow_runs_triggered_by_users",
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_workflow_runs"),
    )
    op.create_index("idx_workflow_runs_project_id", "workflow_runs", ["project_id"])
    op.create_index("idx_workflow_runs_status", "workflow_runs", ["status"])
    op.create_table(
        "api_specs",
        sa.Column("id", UUID(), server_default=gen_random_uuid(), nullable=False),
        sa.Column("project_id", UUID(), nullable=False),
        sa.Column("source_document_id", UUID(), nullable=True),
        sa.Column("title", sa.String(255), nullable=True),
        sa.Column("base_url", sa.String(1000), nullable=True),
        sa.Column("raw_normalized", JSONB(), nullable=False),
        sa.Column("confidence_score", sa.Numeric(3, 2), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=utcnow(), nullable=False
        ),
        sa.CheckConstraint(
            "confidence_score IS NULL OR (confidence_score >= 0 AND confidence_score <= 1)",
            name="confidence_score_range",
        ),
        sa.ForeignKeyConstraint(
            ["project_id"],
            ["projects.id"],
            name="fk_api_specs_project_id_projects",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["source_document_id"],
            ["documents.id"],
            name="fk_api_specs_source_document_id_documents",
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_api_specs"),
    )
    op.create_index("idx_api_specs_project_id", "api_specs", ["project_id"])
    op.create_table(
        "code_generation_runs",
        sa.Column("id", UUID(), server_default=gen_random_uuid(), nullable=False),
        sa.Column("workflow_run_id", UUID(), nullable=False),
        sa.Column("target_language", sa.String(20), nullable=False),
        sa.Column("status", sa.String(50), nullable=False),
        sa.CheckConstraint("target_language IN ('python', 'node')", name="target_language_valid"),
        sa.ForeignKeyConstraint(
            ["workflow_run_id"],
            ["workflow_runs.id"],
            name="fk_code_generation_runs_workflow_run_id_workflow_runs",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_code_generation_runs"),
    )
    op.create_index(
        "idx_code_generation_runs_workflow_run_id", "code_generation_runs", ["workflow_run_id"]
    )
    op.create_table(
        "document_versions",
        sa.Column("id", UUID(), server_default=gen_random_uuid(), nullable=False),
        sa.Column("document_id", UUID(), nullable=False),
        sa.Column("version_number", sa.Integer(), nullable=False),
        sa.Column("diff_summary", JSONB(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=utcnow(), nullable=False
        ),
        sa.ForeignKeyConstraint(
            ["document_id"],
            ["documents.id"],
            name="fk_document_versions_document_id_documents",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_document_versions"),
    )
    op.create_table(
        "github_exports",
        sa.Column("id", UUID(), server_default=gen_random_uuid(), nullable=False),
        sa.Column("export_id", UUID(), nullable=False),
        sa.Column("repo_full_name", sa.String(255), nullable=False),
        sa.Column("commit_sha", sa.String(40), nullable=True),
        sa.Column("pushed_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["export_id"],
            ["exports.id"],
            name="fk_github_exports_export_id_exports",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_github_exports"),
        sa.UniqueConstraint("export_id", name="uq_github_exports_export_id"),
    )
    op.create_table(
        "sdk_versions",
        sa.Column("id", UUID(), server_default=gen_random_uuid(), nullable=False),
        sa.Column("sdk_package_id", UUID(), nullable=False),
        sa.Column("semver", sa.String(50), nullable=False),
        sa.Column("s3_key", sa.String(1000), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=utcnow(), nullable=False
        ),
        sa.ForeignKeyConstraint(
            ["sdk_package_id"],
            ["sdk_packages.id"],
            name="fk_sdk_versions_sdk_package_id_sdk_packages",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_sdk_versions"),
        sa.UniqueConstraint("sdk_package_id", "semver", name="uniq_sdk_versions_package_semver"),
    )
    op.create_table(
        "secrets_refs",
        sa.Column("id", UUID(), server_default=gen_random_uuid(), nullable=False),
        sa.Column("auth_config_id", UUID(), nullable=False),
        sa.Column("vault_path", sa.String(1000), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=utcnow(), nullable=False
        ),
        sa.ForeignKeyConstraint(
            ["auth_config_id"],
            ["auth_configs.id"],
            name="fk_secrets_refs_auth_config_id_auth_configs",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_secrets_refs"),
    )
    op.create_table(
        "test_runs",
        sa.Column("id", UUID(), server_default=gen_random_uuid(), nullable=False),
        sa.Column("project_id", UUID(), nullable=False),
        sa.Column("workflow_run_id", UUID(), nullable=True),
        sa.Column("environment", sa.String(20), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("environment IN ('sandbox', 'live')", name="environment_valid"),
        sa.ForeignKeyConstraint(
            ["project_id"],
            ["projects.id"],
            name="fk_test_runs_project_id_projects",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["workflow_run_id"],
            ["workflow_runs.id"],
            name="fk_test_runs_workflow_run_id_workflow_runs",
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_test_runs"),
    )
    op.create_index("idx_test_runs_project_id", "test_runs", ["project_id"])
    op.create_table(
        "workflow_checkpoints",
        sa.Column("id", UUID(), server_default=gen_random_uuid(), nullable=False),
        sa.Column("workflow_run_id", UUID(), nullable=False),
        sa.Column("node_name", sa.String(100), nullable=False),
        sa.Column("state_snapshot", JSONB(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=utcnow(), nullable=False
        ),
        sa.ForeignKeyConstraint(
            ["workflow_run_id"],
            ["workflow_runs.id"],
            name="fk_workflow_checkpoints_workflow_run_id_workflow_runs",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_workflow_checkpoints"),
    )
    op.create_index("idx_workflow_checkpoints_run_id", "workflow_checkpoints", ["workflow_run_id"])
    op.create_table(
        "endpoints",
        sa.Column("id", UUID(), server_default=gen_random_uuid(), nullable=False),
        sa.Column("api_spec_id", UUID(), nullable=False),
        sa.Column("method", sa.String(10), nullable=False),
        sa.Column("path", sa.String(1000), nullable=False),
        sa.Column("summary", sa.Text(), nullable=True),
        sa.Column("request_schema", JSONB(), nullable=True),
        sa.Column("response_schemas", JSONB(), nullable=False),
        sa.Column("deprecated", sa.Boolean(), server_default=false_(), nullable=False),
        sa.Column("is_destructive", sa.Boolean(), server_default=false_(), nullable=False),
        sa.Column("confidence_score", sa.Numeric(3, 2), nullable=True),
        sa.CheckConstraint(
            "confidence_score IS NULL OR (confidence_score >= 0 AND confidence_score <= 1)",
            name="confidence_score_range",
        ),
        sa.CheckConstraint(
            "method IN ('GET', 'POST', 'PUT', 'PATCH', 'DELETE')", name="method_valid"
        ),
        sa.ForeignKeyConstraint(
            ["api_spec_id"],
            ["api_specs.id"],
            name="fk_endpoints_api_spec_id_api_specs",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_endpoints"),
        sa.UniqueConstraint("api_spec_id", "method", "path", name="uniq_endpoint_method_path"),
    )
    op.create_index("idx_endpoints_spec_id", "endpoints", ["api_spec_id"])
    op.create_table(
        "generated_files",
        sa.Column("id", UUID(), server_default=gen_random_uuid(), nullable=False),
        sa.Column("code_generation_run_id", UUID(), nullable=False),
        sa.Column("file_path", sa.String(1000), nullable=False),
        sa.Column("content_s3_key", sa.String(1000), nullable=False),
        sa.Column("language", sa.String(20), nullable=True),
        sa.Column("file_type", sa.String(50), nullable=True),
        sa.CheckConstraint(
            "file_type IN ('sdk', 'test', 'dockerfile', 'ci_cd', 'readme', 'mcp_manifest')",
            name="file_type_valid",
        ),
        sa.ForeignKeyConstraint(
            ["code_generation_run_id"],
            ["code_generation_runs.id"],
            name="fk_generated_files_code_generation_run_id_code_generation_runs",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_generated_files"),
    )
    op.create_index("idx_generated_files_run_id", "generated_files", ["code_generation_run_id"])
    op.create_table(
        "endpoint_dependencies",
        sa.Column("id", UUID(), server_default=gen_random_uuid(), nullable=False),
        sa.Column("project_id", UUID(), nullable=False),
        sa.Column("from_endpoint_id", UUID(), nullable=False),
        sa.Column("to_endpoint_id", UUID(), nullable=False),
        sa.Column("relationship", sa.String(50), nullable=True),
        sa.CheckConstraint("from_endpoint_id <> to_endpoint_id", name="no_self_loop"),
        sa.CheckConstraint(
            "relationship IN ('requires_auth', 'requires_created_resource', 'optional_precedes')",
            name="relationship_valid",
        ),
        sa.ForeignKeyConstraint(
            ["from_endpoint_id"],
            ["endpoints.id"],
            name="fk_endpoint_dependencies_from_endpoint_id_endpoints",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["project_id"],
            ["projects.id"],
            name="fk_endpoint_dependencies_project_id_projects",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["to_endpoint_id"],
            ["endpoints.id"],
            name="fk_endpoint_dependencies_to_endpoint_id_endpoints",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_endpoint_dependencies"),
    )
    op.create_index("idx_endpoint_dependencies_from", "endpoint_dependencies", ["from_endpoint_id"])
    op.create_index("idx_endpoint_dependencies_project_id", "endpoint_dependencies", ["project_id"])
    op.create_table(
        "endpoint_parameters",
        sa.Column("id", UUID(), server_default=gen_random_uuid(), nullable=False),
        sa.Column("endpoint_id", UUID(), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("location", sa.String(20), nullable=False),
        sa.Column("type", sa.String(50), nullable=False),
        sa.Column("required", sa.Boolean(), server_default=false_(), nullable=False),
        sa.CheckConstraint(
            "location IN ('path', 'query', 'header', 'body')", name="location_valid"
        ),
        sa.ForeignKeyConstraint(
            ["endpoint_id"],
            ["endpoints.id"],
            name="fk_endpoint_parameters_endpoint_id_endpoints",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_endpoint_parameters"),
    )
    op.create_index("idx_endpoint_parameters_endpoint_id", "endpoint_parameters", ["endpoint_id"])
    op.create_table(
        "test_results",
        sa.Column("id", UUID(), server_default=gen_random_uuid(), nullable=False),
        sa.Column("test_run_id", UUID(), nullable=False),
        sa.Column("endpoint_id", UUID(), nullable=True),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("status_code", sa.Integer(), nullable=True),
        sa.Column("latency_ms", sa.Integer(), nullable=True),
        sa.Column("response_snapshot", JSONB(), nullable=True),
        sa.CheckConstraint("status IN ('passed', 'failed', 'skipped')", name="status_valid"),
        sa.ForeignKeyConstraint(
            ["endpoint_id"],
            ["endpoints.id"],
            name="fk_test_results_endpoint_id_endpoints",
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["test_run_id"],
            ["test_runs.id"],
            name="fk_test_results_test_run_id_test_runs",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_test_results"),
    )
    op.create_index("idx_test_results_endpoint_id", "test_results", ["endpoint_id"])
    op.create_index("idx_test_results_run_id", "test_results", ["test_run_id"])
    op.create_table(
        "repair_attempts",
        sa.Column("id", UUID(), server_default=gen_random_uuid(), nullable=False),
        sa.Column("test_result_id", UUID(), nullable=False),
        sa.Column("attempt_number", sa.Integer(), nullable=False),
        sa.Column("failure_classification", sa.String(50), nullable=True),
        sa.Column("diff_summary", JSONB(), nullable=True),
        sa.Column("outcome", sa.String(20), nullable=True),
        sa.CheckConstraint(
            "outcome IS NULL OR outcome IN ('resolved', 'still_failing', 'escalated')",
            name="outcome_valid",
        ),
        sa.ForeignKeyConstraint(
            ["test_result_id"],
            ["test_results.id"],
            name="fk_repair_attempts_test_result_id_test_results",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_repair_attempts"),
    )
    op.create_index("idx_repair_attempts_test_result_id", "repair_attempts", ["test_result_id"])


def downgrade() -> None:
    # Reverse dependency order. Dropping a table takes its indexes and constraints
    # with it, so they need no separate drop statements.
    op.drop_table("repair_attempts")
    op.drop_table("test_results")
    op.drop_table("endpoint_parameters")
    op.drop_table("endpoint_dependencies")
    op.drop_table("generated_files")
    op.drop_table("endpoints")
    op.drop_table("workflow_checkpoints")
    op.drop_table("test_runs")
    op.drop_table("secrets_refs")
    op.drop_table("sdk_versions")
    op.drop_table("github_exports")
    op.drop_table("document_versions")
    op.drop_table("code_generation_runs")
    op.drop_table("api_specs")
    op.drop_table("workflow_runs")
    op.drop_table("sdk_packages")
    op.drop_table("project_members")
    op.drop_table("mcp_tools")
    op.drop_table("exports")
    op.drop_table("documents")
    op.drop_table("auth_configs")
    op.drop_table("artifact_versions")
    op.drop_table("api_keys")
    op.drop_table("refresh_tokens")
    op.drop_table("projects")
    op.drop_table("organization_members")
    op.drop_table("audit_logs")
    op.drop_table("users")
    op.drop_table("tool_calls")
    op.drop_table("organizations")
