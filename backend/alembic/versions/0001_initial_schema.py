"""initial schema — consolidated clean schema

Creates every table in the API Weaver schema with standard relational tables,
b-tree indexes, foreign keys, and dialect-aware constraints.

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

_GUARD_FUNCTION = """
CREATE OR REPLACE FUNCTION audit_logs_append_only() RETURNS trigger
LANGUAGE plpgsql
AS $fn$
BEGIN
    IF pg_trigger_depth() > 1 THEN
        RETURN COALESCE(NEW, OLD);
    END IF;
    RAISE EXCEPTION USING
        MESSAGE = 'audit_logs is append-only: ' || TG_OP || ' is withheld at the database level',
        ERRCODE = 'insufficient_privilege';
END
$fn$
"""


def upgrade() -> None:
    # 1. Organizations
    op.create_table(
        "organizations",
        sa.Column("id", UUID(), server_default=gen_random_uuid(), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("slug", sa.String(100), nullable=False),
        sa.Column("plan_tier", sa.String(50), server_default=sa.text("'free'"), nullable=False),
        sa.Column("rate_limit_override", sa.Integer(), nullable=True),
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

    # 2. Usage Metrics (standard relational table)
    op.create_table(
        "usage_metrics",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column(
            "recorded_at", sa.DateTime(timezone=True), server_default=utcnow(), nullable=False
        ),
        sa.Column("organization_id", UUID(), nullable=False),
        sa.Column("metric_name", sa.String(100), nullable=False),
        sa.Column("value", sa.Numeric(18, 4), nullable=False),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["organizations.id"],
            name="fk_usage_metrics_organization_id_organizations",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_usage_metrics"),
    )
    op.create_index("idx_usage_metrics_org_id", "usage_metrics", ["organization_id"])
    op.create_index("idx_usage_metrics_metric_name", "usage_metrics", ["metric_name"])

    # 3. Users
    op.create_table(
        "users",
        sa.Column("id", UUID(), server_default=gen_random_uuid(), nullable=False),
        sa.Column("email", sa.String(255), nullable=False),
        sa.Column("password_hash", sa.String(255), nullable=True),
        sa.Column("full_name", sa.String(255), nullable=False),
        sa.Column("mfa_enabled", sa.Boolean(), server_default=false_(), nullable=False),
        sa.Column("failed_login_count", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("locked_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=utcnow(), nullable=False
        ),
        sa.PrimaryKeyConstraint("id", name="pk_users"),
        sa.UniqueConstraint("email", name="uq_users_email"),
    )

    # 4. GitHub OAuth States & Connections
    op.create_table(
        "github_oauth_states",
        sa.Column("id", UUID(), server_default=gen_random_uuid(), nullable=False),
        sa.Column("user_id", UUID(), nullable=False),
        sa.Column("state", sa.String(64), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=utcnow(), nullable=False
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name="fk_github_oauth_states_user_id_users",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_github_oauth_states"),
        sa.UniqueConstraint("state", name="uq_github_oauth_states_state"),
    )
    op.create_index("idx_github_oauth_states_user_id", "github_oauth_states", ["user_id"])
    op.create_index("idx_github_oauth_states_expires_at", "github_oauth_states", ["expires_at"])

    op.create_table(
        "github_connections",
        sa.Column("id", UUID(), server_default=gen_random_uuid(), nullable=False),
        sa.Column("user_id", UUID(), nullable=False),
        sa.Column("github_user_id", sa.String(64), nullable=False),
        sa.Column("github_username", sa.String(255), nullable=False),
        sa.Column("access_token_vault_path", sa.String(500), nullable=True),
        sa.Column("refresh_token_vault_path", sa.String(500), nullable=True),
        sa.Column("scopes_granted", JSONB(), server_default=sa.text("'{}'::jsonb"), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=utcnow(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=utcnow(), nullable=False
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name="fk_github_connections_user_id_users",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_github_connections"),
        sa.UniqueConstraint("user_id", "github_user_id", name="uniq_github_conn_user_github"),
    )
    op.create_index("idx_github_connections_user_id", "github_connections", ["user_id"])

    # 5. Audit Logs
    op.create_table(
        "audit_logs",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("organization_id", UUID(), nullable=True),
        sa.Column("user_id", UUID(), nullable=True),
        sa.Column("action", sa.String(100), nullable=False),
        sa.Column("resource_type", sa.String(50), nullable=False),
        sa.Column("resource_id", UUID(), nullable=True),
        sa.Column("ip_address", INET(), nullable=True),
        sa.Column("user_agent", sa.String(500), nullable=True),
        sa.Column("details", JSONB(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=utcnow(), nullable=False
        ),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["organizations.id"],
            name="fk_audit_logs_organization_id_organizations",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name="fk_audit_logs_user_id_users", ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id", name="pk_audit_logs"),
    )
    op.create_index("idx_audit_logs_action", "audit_logs", ["action"])
    op.create_index("idx_audit_logs_created_at", "audit_logs", ["created_at"])
    op.create_index("idx_audit_logs_org_created", "audit_logs", ["organization_id", "created_at"])
    op.create_index("idx_audit_logs_org_id", "audit_logs", ["organization_id"])
    op.create_index("idx_audit_logs_resource", "audit_logs", ["resource_type", "resource_id"])
    op.create_index("idx_audit_logs_user_id", "audit_logs", ["user_id"])

    # Apply immutability trigger for postgres
    bind = op.get_bind()
    if bind and bind.dialect.name == "postgresql":
        op.execute(_GUARD_FUNCTION)
        op.execute(
            "CREATE TRIGGER audit_logs_no_update BEFORE UPDATE ON audit_logs "
            "FOR EACH ROW EXECUTE FUNCTION audit_logs_append_only()"
        )
        op.execute(
            "CREATE TRIGGER audit_logs_no_delete BEFORE DELETE ON audit_logs "
            "FOR EACH ROW EXECUTE FUNCTION audit_logs_append_only()"
        )

    # 6. Organization Members
    op.create_table(
        "organization_members",
        sa.Column("id", UUID(), server_default=gen_random_uuid(), nullable=False),
        sa.Column("organization_id", UUID(), nullable=False),
        sa.Column("user_id", UUID(), nullable=False),
        sa.Column("role", sa.String(50), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=utcnow(), nullable=False
        ),
        sa.CheckConstraint("role IN ('owner', 'admin', 'member')", name="org_role_valid"),
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
        sa.PrimaryKeyConstraint("id", name="pk_organization_members"),
        sa.UniqueConstraint("organization_id", "user_id", name="uniq_org_members_org_user"),
    )
    op.create_index(
        "idx_organization_members_org_id", "organization_members", ["organization_id"]
    )
    op.create_index("idx_organization_members_user_id", "organization_members", ["user_id"])

    # 7. Projects
    op.create_table(
        "projects",
        sa.Column("id", UUID(), server_default=gen_random_uuid(), nullable=False),
        sa.Column("organization_id", UUID(), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=utcnow(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=utcnow(), nullable=False
        ),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["organizations.id"],
            name="fk_projects_organization_id_organizations",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_projects"),
        sa.UniqueConstraint("organization_id", "name", name="uniq_projects_org_name"),
    )
    op.create_index("idx_projects_organization_id", "projects", ["organization_id"])

    # 8. Retry Configs
    op.create_table(
        "retry_configs",
        sa.Column("id", UUID(), server_default=gen_random_uuid(), nullable=False),
        sa.Column("project_id", UUID(), nullable=False),
        sa.Column("max_attempts", sa.Integer(), nullable=False, server_default=sa.text("3")),
        sa.Column("backoff_base_seconds", sa.Integer(), nullable=False, server_default=sa.text("2")),
        sa.Column(
            "retryable_status_codes",
            JSONB(),
            nullable=False,
            server_default=sa.text("'[429, 500, 502, 503, 504]'::jsonb"),
        ),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=utcnow(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=utcnow(), nullable=False
        ),
        sa.ForeignKeyConstraint(
            ["project_id"],
            ["projects.id"],
            name="fk_retry_configs_project_id_projects",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_retry_configs"),
        sa.UniqueConstraint("project_id", name="uq_retry_configs_project_id"),
    )

    # 9. Refresh Tokens
    op.create_table(
        "refresh_tokens",
        sa.Column("id", UUID(), server_default=gen_random_uuid(), nullable=False),
        sa.Column("user_id", UUID(), nullable=False),
        sa.Column("token_family", UUID(), nullable=False),
        sa.Column("token_hash", sa.String(255), nullable=False),
        sa.Column("is_revoked", sa.Boolean(), server_default=false_(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=utcnow(), nullable=False
        ),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name="fk_refresh_tokens_user_id_users", ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name="pk_refresh_tokens"),
        sa.UniqueConstraint("token_hash", name="uq_refresh_tokens_token_hash"),
    )
    op.create_index("idx_refresh_tokens_family", "refresh_tokens", ["token_family"])
    op.create_index("idx_refresh_tokens_user_id", "refresh_tokens", ["user_id"])

    # 10. API Keys
    op.create_table(
        "api_keys",
        sa.Column("id", UUID(), server_default=gen_random_uuid(), nullable=False),
        sa.Column("organization_id", UUID(), nullable=False),
        sa.Column("user_id", UUID(), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("key_prefix", sa.String(12), nullable=False),
        sa.Column("key_hash", sa.String(255), nullable=False),
        sa.Column("scopes", JSONB(), nullable=False),
        sa.Column("revoked", sa.Boolean(), server_default=false_(), nullable=False),
        sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=utcnow(), nullable=False
        ),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["organizations.id"],
            name="fk_api_keys_organization_id_organizations",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name="fk_api_keys_user_id_users", ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name="pk_api_keys"),
        sa.UniqueConstraint("key_hash", name="uq_api_keys_key_hash"),
    )
    op.create_index("idx_api_keys_organization_id", "api_keys", ["organization_id"])
    op.create_index("idx_api_keys_prefix", "api_keys", ["key_prefix"])
    op.create_index("idx_api_keys_user_id", "api_keys", ["user_id"])

    # 11. Artifact Versions
    op.create_table(
        "artifact_versions",
        sa.Column("id", UUID(), server_default=gen_random_uuid(), nullable=False),
        sa.Column("project_id", UUID(), nullable=False),
        sa.Column("artifact_type", sa.String(50), nullable=False),
        sa.Column("version_number", sa.Integer(), nullable=False),
        sa.Column("diff_ref", sa.String(1000), nullable=True),
        sa.Column("is_active", sa.Boolean(), server_default=sa.text("FALSE"), nullable=False),
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
    op.create_index(
        "idx_artifact_versions_active", "artifact_versions", ["project_id", "artifact_type"]
    )

    # 12. Auth Configs
    op.create_table(
        "auth_configs",
        sa.Column("id", UUID(), server_default=gen_random_uuid(), nullable=False),
        sa.Column("project_id", UUID(), nullable=False),
        sa.Column("scheme", sa.String(50), nullable=False),
        sa.Column("config_json", JSONB(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=utcnow(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=utcnow(), nullable=False
        ),
        sa.CheckConstraint(
            "scheme IN ('none', 'api_key', 'bearer_jwt', 'oauth2_client_credentials', 'oauth2_auth_code', 'basic', 'hmac')",
            name="auth_scheme_valid",
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

    # 13. Documents
    op.create_table(
        "documents",
        sa.Column("id", UUID(), server_default=gen_random_uuid(), nullable=False),
        sa.Column("project_id", UUID(), nullable=False),
        sa.Column("title", sa.String(255), nullable=False),
        sa.Column("doc_type", sa.String(50), nullable=False),
        sa.Column("s3_key", sa.String(1000), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=utcnow(), nullable=False
        ),
        sa.CheckConstraint(
            "doc_type IN ('openapi', 'markdown', 'html', 'pdf')", name="doc_type_valid"
        ),
        sa.ForeignKeyConstraint(
            ["project_id"],
            ["projects.id"],
            name="fk_documents_project_id_projects",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_documents"),
    )
    op.create_index("idx_documents_project_id", "documents", ["project_id"])

    # 14. Exports
    op.create_table(
        "exports",
        sa.Column("id", UUID(), server_default=gen_random_uuid(), nullable=False),
        sa.Column("project_id", UUID(), nullable=False),
        sa.Column("export_type", sa.String(50), nullable=False),
        sa.Column("status", sa.String(20), nullable=True),
        sa.Column("s3_key", sa.String(1000), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=utcnow(), nullable=False
        ),
        sa.CheckConstraint(
            "export_type IN ('sdk', 'client', 'docker', 'github', 'mcp', 'docs', 'cicd', 'fastapi')",
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

    # 15. MCP Tools
    op.create_table(
        "mcp_tools",
        sa.Column("id", UUID(), server_default=gen_random_uuid(), nullable=False),
        sa.Column("project_id", UUID(), nullable=False),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("input_schema", JSONB(), nullable=False),
        sa.Column("endpoint_ref", sa.String(255), nullable=True),
        sa.ForeignKeyConstraint(
            ["project_id"],
            ["projects.id"],
            name="fk_mcp_tools_project_id_projects",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_mcp_tools"),
        sa.UniqueConstraint("project_id", "name", name="uniq_mcp_tools_project_name"),
    )
    op.create_index("idx_mcp_tools_project_id", "mcp_tools", ["project_id"])

    # 16. Project Members
    op.create_table(
        "project_members",
        sa.Column("id", UUID(), server_default=gen_random_uuid(), nullable=False),
        sa.Column("project_id", UUID(), nullable=False),
        sa.Column("user_id", UUID(), nullable=False),
        sa.Column("role", sa.String(50), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=utcnow(), nullable=False
        ),
        sa.CheckConstraint("role IN ('admin', 'editor', 'viewer')", name="project_role_valid"),
        sa.ForeignKeyConstraint(
            ["project_id"],
            ["projects.id"],
            name="fk_project_members_project_id_projects",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name="fk_project_members_user_id_users", ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name="pk_project_members"),
        sa.UniqueConstraint("project_id", "user_id", name="uniq_project_members_project_user"),
    )
    op.create_index("idx_project_members_project_id", "project_members", ["project_id"])
    op.create_index("idx_project_members_user_id", "project_members", ["user_id"])

    # 17. SDK Packages
    op.create_table(
        "sdk_packages",
        sa.Column("id", UUID(), server_default=gen_random_uuid(), nullable=False),
        sa.Column("project_id", UUID(), nullable=False),
        sa.Column("language", sa.String(50), nullable=False),
        sa.Column("package_name", sa.String(255), nullable=False),
        sa.Column("repository_url", sa.String(1000), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=utcnow(), nullable=False
        ),
        sa.ForeignKeyConstraint(
            ["project_id"],
            ["projects.id"],
            name="fk_sdk_packages_project_id_projects",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_sdk_packages"),
        sa.UniqueConstraint("project_id", "language", name="uniq_sdk_packages_project_language"),
    )
    op.create_index("idx_sdk_packages_project_id", "sdk_packages", ["project_id"])

    # 18. Workflow Runs
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
        sa.Column("current_node", sa.String(100), nullable=True),
        sa.Column(
            "progress_percent", sa.Integer(), server_default=sa.text("0"), nullable=True
        ),
        sa.Column("heartbeat_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=utcnow(), nullable=False
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
    op.create_index(
        "idx_workflow_runs_status_heartbeat", "workflow_runs", ["status", "heartbeat_at"]
    )

    # 19. Agent Events (Standard Table)
    op.create_table(
        "agent_events",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=utcnow(), nullable=False
        ),
        sa.Column("workflow_run_id", UUID(), nullable=False),
        sa.Column("agent_name", sa.String(100), nullable=False),
        sa.Column("event_type", sa.String(50), nullable=False),
        sa.Column("payload", JSONB(), nullable=True),
        sa.ForeignKeyConstraint(
            ["workflow_run_id"],
            ["workflow_runs.id"],
            name="fk_agent_events_workflow_run_id_workflow_runs",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_agent_events"),
    )
    op.create_index("idx_agent_events_run_id", "agent_events", ["workflow_run_id"])
    op.create_index("idx_agent_events_created_at", "agent_events", ["created_at"])

    # 20. Tool Calls
    op.create_table(
        "tool_calls",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("agent_event_id", sa.BigInteger(), nullable=False),
        sa.Column("tool_name", sa.String(100), nullable=False),
        sa.Column("arguments", JSONB(), nullable=True),
        sa.Column("result", JSONB(), nullable=True),
        sa.Column("duration_ms", sa.Integer(), nullable=True),
        sa.ForeignKeyConstraint(
            ["agent_event_id"],
            ["agent_events.id"],
            name="fk_tool_calls_agent_event_id_agent_events",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_tool_calls"),
    )
    op.create_index("idx_tool_calls_agent_event_id", "tool_calls", ["agent_event_id"])

    # 21. API Specs
    op.create_table(
        "api_specs",
        sa.Column("id", UUID(), server_default=gen_random_uuid(), nullable=False),
        sa.Column("project_id", UUID(), nullable=False),
        sa.Column("version", sa.String(50), nullable=False),
        sa.Column("title", sa.String(255), nullable=False),
        sa.Column("spec_format", sa.String(20), nullable=False),
        sa.Column("content_s3_key", sa.String(1000), nullable=False),
        sa.Column("checksum_sha256", sa.CHAR(64), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=utcnow(), nullable=False
        ),
        sa.CheckConstraint("spec_format IN ('openapi_3_0', 'openapi_3_1')", name="spec_format_valid"),
        sa.ForeignKeyConstraint(
            ["project_id"],
            ["projects.id"],
            name="fk_api_specs_project_id_projects",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_api_specs"),
        sa.UniqueConstraint("project_id", "version", name="uniq_api_specs_project_version"),
    )
    op.create_index("idx_api_specs_project_id", "api_specs", ["project_id"])

    # 22. Code Generation Runs
    op.create_table(
        "code_generation_runs",
        sa.Column("id", UUID(), server_default=gen_random_uuid(), nullable=False),
        sa.Column("workflow_run_id", UUID(), nullable=False),
        sa.Column("target_language", sa.String(20), nullable=False),
        sa.Column("output_s3_prefix", sa.String(1000), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=utcnow(), nullable=False
        ),
        sa.CheckConstraint(
            "status IN ('queued', 'running', 'completed', 'failed')",
            name="codegen_status_valid",
        ),
        sa.ForeignKeyConstraint(
            ["workflow_run_id"],
            ["workflow_runs.id"],
            name="fk_code_generation_runs_workflow_run_id_workflow_runs",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_code_generation_runs"),
    )
    op.create_index(
        "idx_code_generation_runs_workflow_run_id",
        "code_generation_runs",
        ["workflow_run_id"],
    )

    # 23. Document Versions
    op.create_table(
        "document_versions",
        sa.Column("id", UUID(), server_default=gen_random_uuid(), nullable=False),
        sa.Column("document_id", UUID(), nullable=False),
        sa.Column("version_number", sa.Integer(), nullable=False),
        sa.Column("content_s3_key", sa.String(1000), nullable=False),
        sa.Column("checksum_sha256", sa.CHAR(64), nullable=False),
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
        sa.UniqueConstraint(
            "document_id", "version_number", name="uniq_doc_versions_document_version"
        ),
    )
    op.create_index("idx_document_versions_doc_id", "document_versions", ["document_id"])

    # 24. GitHub Exports
    op.create_table(
        "github_exports",
        sa.Column("id", UUID(), server_default=gen_random_uuid(), nullable=False),
        sa.Column("export_id", UUID(), nullable=False),
        sa.Column("repository_full_name", sa.String(255), nullable=False),
        sa.Column("branch_name", sa.String(255), nullable=False),
        sa.Column("commit_sha", sa.CHAR(40), nullable=True),
        sa.Column("pr_number", sa.Integer(), nullable=True),
        sa.Column("status", sa.String(20), nullable=False),
        sa.CheckConstraint(
            "status IN ('queued', 'pushing', 'pr_created', 'failed')",
            name="github_export_status_valid",
        ),
        sa.ForeignKeyConstraint(
            ["export_id"],
            ["exports.id"],
            name="fk_github_exports_export_id_exports",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_github_exports"),
        sa.UniqueConstraint("export_id", name="uq_github_exports_export_id"),
    )

    # 25. SDK Versions
    op.create_table(
        "sdk_versions",
        sa.Column("id", UUID(), server_default=gen_random_uuid(), nullable=False),
        sa.Column("package_id", UUID(), nullable=False),
        sa.Column("version_string", sa.String(50), nullable=False),
        sa.Column("artifact_s3_key", sa.String(1000), nullable=False),
        sa.Column(
            "published_at", sa.DateTime(timezone=True), server_default=utcnow(), nullable=False
        ),
        sa.ForeignKeyConstraint(
            ["package_id"],
            ["sdk_packages.id"],
            name="fk_sdk_versions_package_id_sdk_packages",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_sdk_versions"),
        sa.UniqueConstraint("package_id", "version_string", name="uniq_sdk_versions_pkg_version"),
    )
    op.create_index("idx_sdk_versions_package_id", "sdk_versions", ["package_id"])

    # 26. Secrets Refs
    op.create_table(
        "secrets_refs",
        sa.Column("id", UUID(), server_default=gen_random_uuid(), nullable=False),
        sa.Column("auth_config_id", UUID(), nullable=False),
        sa.Column("vault_path", sa.String(1000), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=utcnow(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=utcnow(), nullable=False
        ),
        sa.ForeignKeyConstraint(
            ["auth_config_id"],
            ["auth_configs.id"],
            name="fk_secrets_refs_auth_config_id_auth_configs",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_secrets_refs"),
        sa.UniqueConstraint("auth_config_id", name="uq_secrets_refs_auth_config_id"),
    )

    # 27. Test Runs
    op.create_table(
        "test_runs",
        sa.Column("id", UUID(), server_default=gen_random_uuid(), nullable=False),
        sa.Column("project_id", UUID(), nullable=False),
        sa.Column("workflow_run_id", UUID(), nullable=True),
        sa.Column("environment", sa.String(20), nullable=False),
        sa.Column("status", sa.String(50), nullable=False, server_default=sa.text("'pending'")),
        sa.Column("summary", JSONB(), nullable=True),
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

    # 28. Workflow Checkpoints
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
    op.create_index(
        "idx_workflow_checkpoints_run_id", "workflow_checkpoints", ["workflow_run_id"]
    )

    # 29. Endpoints
    op.create_table(
        "endpoints",
        sa.Column("id", UUID(), server_default=gen_random_uuid(), nullable=False),
        sa.Column("api_spec_id", UUID(), nullable=False),
        sa.Column("operation_id", sa.String(255), nullable=True),
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

    # 30. Generated Files
    op.create_table(
        "generated_files",
        sa.Column("id", UUID(), server_default=gen_random_uuid(), nullable=False),
        sa.Column("code_generation_run_id", UUID(), nullable=False),
        sa.Column("file_path", sa.String(1000), nullable=False),
        sa.Column("content_s3_key", sa.String(1000), nullable=False),
        sa.Column("size_bytes", sa.Integer(), nullable=True, server_default=sa.text("0")),
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

    # 31. Endpoint Dependencies
    op.create_table(
        "endpoint_dependencies",
        sa.Column("id", UUID(), server_default=gen_random_uuid(), nullable=False),
        sa.Column("source_endpoint_id", UUID(), nullable=False),
        sa.Column("target_endpoint_id", UUID(), nullable=False),
        sa.Column("dependency_type", sa.String(50), nullable=False),
        sa.Column("field_mappings", JSONB(), nullable=False),
        sa.CheckConstraint(
            "dependency_type IN ('data_flow', 'auth_prerequisite', 'temporal_ordering')",
            name="dep_type_valid",
        ),
        sa.ForeignKeyConstraint(
            ["source_endpoint_id"],
            ["endpoints.id"],
            name="fk_endpoint_dependencies_source_endpoint_id_endpoints",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["target_endpoint_id"],
            ["endpoints.id"],
            name="fk_endpoint_dependencies_target_endpoint_id_endpoints",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_endpoint_dependencies"),
        sa.UniqueConstraint(
            "source_endpoint_id",
            "target_endpoint_id",
            name="uniq_endpoint_deps_source_target",
        ),
    )
    op.create_index(
        "idx_endpoint_dependencies_source", "endpoint_dependencies", ["source_endpoint_id"]
    )
    op.create_index(
        "idx_endpoint_dependencies_target", "endpoint_dependencies", ["target_endpoint_id"]
    )

    # 32. Endpoint Parameters
    op.create_table(
        "endpoint_parameters",
        sa.Column("id", UUID(), server_default=gen_random_uuid(), nullable=False),
        sa.Column("endpoint_id", UUID(), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("location", sa.String(20), nullable=False),
        sa.Column("required", sa.Boolean(), nullable=False),
        sa.Column("schema_definition", JSONB(), nullable=False),
        sa.CheckConstraint(
            "location IN ('path', 'query', 'header', 'cookie')", name="param_location_valid"
        ),
        sa.ForeignKeyConstraint(
            ["endpoint_id"],
            ["endpoints.id"],
            name="fk_endpoint_parameters_endpoint_id_endpoints",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_endpoint_parameters"),
        sa.UniqueConstraint(
            "endpoint_id", "name", "location", name="uniq_endpoint_params_name_location"
        ),
    )
    op.create_index("idx_endpoint_parameters_endpoint_id", "endpoint_parameters", ["endpoint_id"])

    # 33. Test Results
    op.create_table(
        "test_results",
        sa.Column("id", UUID(), server_default=gen_random_uuid(), nullable=False),
        sa.Column("test_run_id", UUID(), nullable=False),
        sa.Column("endpoint_id", UUID(), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("http_status_code", sa.Integer(), nullable=True),
        sa.Column("latency_ms", sa.Integer(), nullable=True),
        sa.Column("request_payload", JSONB(), nullable=True),
        sa.Column("response_payload", JSONB(), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.CheckConstraint(
            "status IN ('passed', 'failed', 'error', 'skipped')", name="test_result_status_valid"
        ),
        sa.ForeignKeyConstraint(
            ["endpoint_id"],
            ["endpoints.id"],
            name="fk_test_results_endpoint_id_endpoints",
            ondelete="CASCADE",
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
    op.create_index("idx_test_results_test_run_id", "test_results", ["test_run_id"])

    # 34. Repair Attempts
    op.create_table(
        "repair_attempts",
        sa.Column("id", UUID(), server_default=gen_random_uuid(), nullable=False),
        sa.Column("test_result_id", UUID(), nullable=False),
        sa.Column("attempt_number", sa.Integer(), nullable=False),
        sa.Column("root_cause_analysis", sa.Text(), nullable=True),
        sa.Column("proposed_diff", sa.Text(), nullable=True),
        sa.Column("applied", sa.Boolean(), server_default=false_(), nullable=False),
        sa.Column("success", sa.Boolean(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=utcnow(), nullable=False
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
    op.drop_table("repair_attempts")
    op.drop_table("test_results")
    op.drop_table("endpoint_parameters")
    op.drop_table("endpoint_dependencies")
    op.drop_table("generated_files")
    op.drop_table("endpoints")
    op.drop_table("workflow_checkpoints")
    op.drop_table("tool_calls")
    op.drop_table("agent_events")
    op.drop_table("test_runs")
    op.drop_table("secrets_refs")
    op.drop_table("sdk_versions")
    op.drop_table("github_exports")
    op.drop_table("document_versions")
    op.drop_table("code_generation_runs")
    op.drop_table("api_specs")
    op.drop_table("workflow_runs")
    op.drop_table("retry_configs")
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
    op.drop_table("github_connections")
    op.drop_table("github_oauth_states")
    op.drop_table("users")
    op.drop_table("usage_metrics")
    op.drop_table("organizations")
