"""The authorization policy — one source of truth.

`Security.md §2` requires authorization checks to be "centralized in a policy layer (not
scattered per-route)". This module owns the role hierarchy and the permission matrix;
`enforce.py` owns applying them. A route never compares roles itself.

Deny by default: a permission with no entry in `PERMISSIONS`, or a principal with no
membership row for the resource, is denied. There is no fallthrough to allow.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from enum import StrEnum

from app.models.enums import OrgRole, ProjectRole

# --- Role hierarchies ---------------------------------------------------------------
# Higher rank implies every capability of the lower ranks.
#
# `billing` is deliberately NOT in this ladder. Per Security.md §2 it is a side role for
# invoice access, so ranking it would silently grant it `member` capabilities over
# project data. It is rank 0 and only satisfies a requirement for `billing` exactly.
ORG_ROLE_RANK: dict[str, int] = {
    OrgRole.OWNER: 30,
    OrgRole.ADMIN: 20,
    OrgRole.MEMBER: 10,
    OrgRole.BILLING: 0,
}

PROJECT_ROLE_RANK: dict[str, int] = {
    ProjectRole.OWNER: 30,
    ProjectRole.EDITOR: 20,
    ProjectRole.VIEWER: 10,
}


def org_role_satisfies(actual: str | None, required: str) -> bool:
    """True when `actual` meets or exceeds `required` in the org hierarchy."""
    if actual is None:
        return False
    if required == OrgRole.BILLING:
        # Not implied by seniority — an owner is not automatically a billing contact.
        return actual in (OrgRole.BILLING, OrgRole.OWNER)
    if actual == OrgRole.BILLING:
        return False
    return ORG_ROLE_RANK.get(actual, -1) >= ORG_ROLE_RANK.get(required, 99)


def project_role_satisfies(actual: str | None, required: str) -> bool:
    """True when `actual` meets or exceeds `required` in the project hierarchy."""
    if actual is None:
        return False
    return PROJECT_ROLE_RANK.get(actual, -1) >= PROJECT_ROLE_RANK.get(required, 99)


# --- Permissions --------------------------------------------------------------------


class Permission(StrEnum):
    """Named capabilities. Routes reference these, never raw role strings."""

    # Organization scope
    ORG_READ = "org:read"
    ORG_UPDATE = "org:update"
    ORG_MANAGE_MEMBERS = "org:manage_members"
    ORG_MANAGE_API_KEYS = "org:manage_api_keys"
    ORG_VIEW_BILLING = "org:view_billing"
    ORG_VIEW_AUDIT_LOG = "org:view_audit_log"

    # Project scope
    PROJECT_CREATE = "project:create"
    PROJECT_READ = "project:read"
    PROJECT_UPDATE = "project:update"
    PROJECT_ARCHIVE = "project:archive"
    PROJECT_MANAGE_MEMBERS = "project:manage_members"

    # Documents and specs
    DOCUMENT_UPLOAD = "document:upload"
    SPEC_READ = "spec:read"
    SPEC_UPDATE = "spec:update"

    # Auth config / secrets
    AUTH_CONFIG_READ = "auth_config:read"
    AUTH_CONFIG_WRITE = "auth_config:write"

    # Workflows, generation, testing, export
    WORKFLOW_TRIGGER = "workflow:trigger"
    WORKFLOW_READ = "workflow:read"
    WORKFLOW_APPROVE = "workflow:approve"
    WORKFLOW_CANCEL = "workflow:cancel"
    CODE_GENERATE = "code:generate"
    CODE_READ = "code:read"
    TEST_RUN = "test:run"
    TEST_READ = "test:read"
    EXPORT_CREATE = "export:create"
    EXPORT_READ = "export:read"
    GITHUB_CONNECT = "github:connect"
    GITHUB_EXPORT = "github:export"


@dataclass(frozen=True, slots=True)
class RoleRequirement:
    """What a principal must hold to exercise a permission.

    `org_role` and `project_role` are both optional, but at least one is always set —
    a requirement with neither would be unconditionally satisfiable, which is exactly
    the deny-by-default violation this layer exists to prevent (enforced by
    `_validate_matrix` at import time).
    """

    org_role: str | None = None
    project_role: str | None = None


PERMISSIONS: dict[Permission, RoleRequirement] = {
    # --- Organization ---------------------------------------------------------------
    Permission.ORG_READ: RoleRequirement(org_role=OrgRole.MEMBER),
    Permission.ORG_UPDATE: RoleRequirement(org_role=OrgRole.ADMIN),
    Permission.ORG_MANAGE_MEMBERS: RoleRequirement(org_role=OrgRole.ADMIN),
    # API keys are org-wide credentials (Security.md §5) — admin and above only.
    Permission.ORG_MANAGE_API_KEYS: RoleRequirement(org_role=OrgRole.ADMIN),
    Permission.ORG_VIEW_BILLING: RoleRequirement(org_role=OrgRole.BILLING),
    Permission.ORG_VIEW_AUDIT_LOG: RoleRequirement(org_role=OrgRole.ADMIN),
    # --- Project --------------------------------------------------------------------
    Permission.PROJECT_CREATE: RoleRequirement(org_role=OrgRole.MEMBER),
    Permission.PROJECT_READ: RoleRequirement(project_role=ProjectRole.VIEWER),
    Permission.PROJECT_UPDATE: RoleRequirement(project_role=ProjectRole.EDITOR),
    # API.md §6.1 — DELETE (archive) requires org owner or admin.
    Permission.PROJECT_ARCHIVE: RoleRequirement(org_role=OrgRole.ADMIN),
    Permission.PROJECT_MANAGE_MEMBERS: RoleRequirement(project_role=ProjectRole.OWNER),
    # --- Documents and specs --------------------------------------------------------
    Permission.DOCUMENT_UPLOAD: RoleRequirement(project_role=ProjectRole.EDITOR),
    Permission.SPEC_READ: RoleRequirement(project_role=ProjectRole.VIEWER),
    Permission.SPEC_UPDATE: RoleRequirement(project_role=ProjectRole.EDITOR),
    # --- Auth config ----------------------------------------------------------------
    Permission.AUTH_CONFIG_READ: RoleRequirement(project_role=ProjectRole.EDITOR),
    # Writing credentials reaches Vault (Security.md §7) — project owner only.
    Permission.AUTH_CONFIG_WRITE: RoleRequirement(project_role=ProjectRole.OWNER),
    # --- Workflows ------------------------------------------------------------------
    # Triggering spends LLM budget (Security.md §15), so viewers cannot.
    Permission.WORKFLOW_TRIGGER: RoleRequirement(project_role=ProjectRole.EDITOR),
    Permission.WORKFLOW_READ: RoleRequirement(project_role=ProjectRole.VIEWER),
    # The human approval gate in Security.md §12 — the last checkpoint before generated
    # code runs, so it is owner-only rather than delegable to an editor.
    Permission.WORKFLOW_APPROVE: RoleRequirement(project_role=ProjectRole.OWNER),
    Permission.WORKFLOW_CANCEL: RoleRequirement(project_role=ProjectRole.EDITOR),
    Permission.CODE_GENERATE: RoleRequirement(project_role=ProjectRole.EDITOR),
    Permission.CODE_READ: RoleRequirement(project_role=ProjectRole.VIEWER),
    # Live-environment tests hit the user's real target API — editor and above.
    Permission.TEST_RUN: RoleRequirement(project_role=ProjectRole.EDITOR),
    Permission.TEST_READ: RoleRequirement(project_role=ProjectRole.VIEWER),
    # Exporting publishes outward (GitHub push, Docker image) — owner only.
    Permission.EXPORT_CREATE: RoleRequirement(project_role=ProjectRole.OWNER),
    Permission.EXPORT_READ: RoleRequirement(project_role=ProjectRole.VIEWER),

    # GitHub integration
    Permission.GITHUB_CONNECT: RoleRequirement(project_role=ProjectRole.MEMBER),
    Permission.GITHUB_EXPORT: RoleRequirement(project_role=ProjectRole.OWNER),
}


def _validate_matrix() -> None:
    """Fail at import if the matrix is incomplete or trivially satisfiable.

    A missing permission would be denied at runtime (correct but silent); catching it
    here turns a latent 403 into a startup error.
    """
    missing = set(Permission) - set(PERMISSIONS)
    if missing:
        raise RuntimeError(f"permissions with no policy entry: {sorted(missing)}")
    for permission, requirement in PERMISSIONS.items():
        if requirement.org_role is None and requirement.project_role is None:
            raise RuntimeError(f"{permission} has an empty requirement (deny-by-default breach)")


_validate_matrix()


# --- Principal ----------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Principal:
    """The authenticated caller.

    Covers both auth modes in `API.md §1`. A JWT principal acts as a user; an API-key
    principal acts as the organization, optionally narrowed to one project
    (`Security.md §5`).
    """

    user_id: uuid.UUID | None
    organization_id: uuid.UUID | None
    org_role: str | None = None
    # Set when authenticated by an API key restricted to a single project. Any request
    # touching a different project is refused regardless of role.
    restricted_to_project_id: uuid.UUID | None = None
    auth_method: str = "jwt"
    api_key_id: uuid.UUID | None = None
    jti: str | None = None
    # Per-project roles resolved lazily by the enforcement layer and cached per request.
    _project_roles: dict[uuid.UUID, str | None] = field(default_factory=dict, compare=False)

    @property
    def is_api_key(self) -> bool:
        return self.auth_method == "api_key"

    def may_touch_project(self, project_id: uuid.UUID) -> bool:
        """False when an API key is scoped to a different project."""
        if self.restricted_to_project_id is None:
            return True
        return self.restricted_to_project_id == project_id
