"""Authentication configuration routes for target APIs (`API.md §6.3`, `Security.md §7`)."""

from __future__ import annotations

from typing import Any, cast

from fastapi import APIRouter, Depends, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_current_principal, get_db
from app.core.errors import DependencyUnavailableError, NotFoundError
from app.core.logging import get_logger
from app.models.auth_config import AuthConfig, SecretRef
from app.models.project import Project
from app.rbac.enforce import require_project_permission
from app.rbac.policy import Permission, Principal
from app.schemas.auth_config import AuthConfigRequest, AuthConfigResponse
from app.services import audit_service
from app.services.vault_service import VaultClient, create_vault_client

logger = get_logger(__name__)

router = APIRouter(prefix="/projects", tags=["auth_config"])


@router.get("/{id}/auth", response_model=AuthConfigResponse)
async def get_auth_config(
    project: Project = Depends(require_project_permission(Permission.AUTH_CONFIG_READ)),
    session: AsyncSession = Depends(get_db),
) -> AuthConfigResponse:
    """Retrieve the non-secret auth configuration for a project."""
    config = await session.scalar(
        select(AuthConfig).where(AuthConfig.project_id == project.id)
    )
    if config is None:
        raise NotFoundError("No auth configuration found for this project.")
    return AuthConfigResponse(
        scheme=config.scheme,
        config_json=config.config_json,
        verified=config.verified,
    )


@router.put("/{id}/auth", response_model=AuthConfigResponse, status_code=status.HTTP_200_OK)
async def put_auth_config(
    payload: AuthConfigRequest,
    project: Project = Depends(require_project_permission(Permission.AUTH_CONFIG_WRITE)),
    principal: Principal = Depends(get_current_principal),
    session: AsyncSession = Depends(get_db),
    vault: VaultClient = Depends(create_vault_client),
) -> AuthConfigResponse:
    """Create or update auth config; credentials are saved directly to Vault."""
    config = await session.scalar(
        select(AuthConfig).where(AuthConfig.project_id == project.id)
    )
    if config is None:
        config = AuthConfig(
            project_id=project.id,
            scheme=payload.scheme.value,
            config_json=payload.config_json,
            verified=False,
        )
        session.add(config)
        await session.flush()
    else:
        config.scheme = payload.scheme.value
        config.config_json = payload.config_json
        config.verified = False
        await session.flush()

    # If credentials are provided, persist them to Vault
    if payload.credentials:
        vault_path = f"apiweaver/projects/{project.id}/auth"
        # The request model's validator always normalizes credentials to a plain dict.
        await vault.write_secret(vault_path, cast(dict[str, Any], payload.credentials))

        secret_ref = await session.scalar(
            select(SecretRef).where(SecretRef.auth_config_id == config.id)
        )
        if secret_ref is None:
            secret_ref = SecretRef(auth_config_id=config.id, vault_path=vault_path)
            session.add(secret_ref)
            await session.flush()

    await audit_service.record(
        session,
        action="auth_config.updated",
        **audit_service.actor(principal),
        organization_id=project.organization_id,
        resource_type="auth_config",
        resource_id=str(config.id),
        metadata={"scheme": config.scheme, "has_credentials": bool(payload.credentials)},
    )

    return AuthConfigResponse(
        scheme=config.scheme,
        config_json=config.config_json,
        verified=config.verified,
    )


async def delete_auth_config_with_vault(
    session: AsyncSession,
    vault: VaultClient,
    auth_config: AuthConfig,
) -> None:
    """Application-level Vault-deletion hook per Database.md §5 and Security.md §7.

    SecretRef FK is RESTRICT. Deleting an AuthConfig requires first purging all
    associated Vault secrets to avoid leaving orphaned credentials in Vault,
    then deleting the SecretRef rows, and finally deleting the AuthConfig.
    """
    secret_refs = (
        await session.scalars(
            select(SecretRef).where(SecretRef.auth_config_id == auth_config.id)
        )
    ).all()

    for ref in secret_refs:
        try:
            await vault.delete_secret(ref.vault_path)
        except Exception as exc:
            # Keep the SecretRef (the RESTRICT FK exists for exactly this): deleting it
            # would orphan a live credential in Vault with nothing pointing at it.
            logger.warning(
                "failed_to_delete_vault_secret",
                vault_path=ref.vault_path,
                error=str(exc),
            )
            raise DependencyUnavailableError(
                "Could not remove the stored credentials from Vault; nothing was deleted."
            ) from exc
        await session.delete(ref)

    await session.delete(auth_config)
    await session.flush()


@router.delete("/{id}/auth", status_code=status.HTTP_204_NO_CONTENT, response_model=None)
async def delete_auth_config(
    project: Project = Depends(require_project_permission(Permission.AUTH_CONFIG_WRITE)),
    principal: Principal = Depends(get_current_principal),
    session: AsyncSession = Depends(get_db),
    vault: VaultClient = Depends(create_vault_client),
) -> None:
    """Delete project auth configuration and purge all associated secrets from Vault."""
    config = await session.scalar(
        select(AuthConfig).where(AuthConfig.project_id == project.id)
    )
    if config is None:
        raise NotFoundError("No auth configuration found for this project.")

    config_id = str(config.id)
    scheme = config.scheme

    await delete_auth_config_with_vault(session, vault, config)

    await audit_service.record(
        session,
        action="auth_config.deleted",
        **audit_service.actor(principal),
        organization_id=project.organization_id,
        resource_type="auth_config",
        resource_id=config_id,
        metadata={"scheme": scheme},
    )

    await session.commit()

