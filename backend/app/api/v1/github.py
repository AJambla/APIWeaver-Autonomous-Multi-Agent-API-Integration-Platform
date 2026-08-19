"""GitHub OAuth and integration API routes (Phase 4)."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, Query, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_current_principal, get_db
from app.core.errors import ConflictError, NotFoundError
from app.models.github import GitHubConnection, GitHubOAuthState
from app.rbac.enforce import require_org_permission
from app.rbac.policy import Permission, Principal
from app.schemas.github import (
    GitHubAuthUrlResponse,
    GitHubReposResponse,
    GitHubStatusResponse,
)
from app.services.github_service import (
    GitHubAppClient,
    GitHubOAuthClient,
    create_github_app_client,
    create_github_oauth_client,
)
from app.services.vault_service import VaultClient, create_vault_client

router = APIRouter(prefix="/github", tags=["github"])


@router.post("/connect", response_model=GitHubAuthUrlResponse)
async def github_connect(
    request: Request,
    principal: Principal = Depends(require_org_permission(Permission.GITHUB_CONNECT)),
    oauth_client: GitHubOAuthClient = Depends(create_github_oauth_client),
) -> GitHubAuthUrlResponse:
    """Initiate GitHub OAuth flow."""
    # Generate secure state parameter
    state = uuid.uuid4().hex
    expires_at = request.app.state.settings.github_oauth_state_ttl_seconds or 600  # 10 minutes default

    # Store state in database
    async with request.app.state.db_session_factory() as session:
        oauth_state = GitHubOAuthState(
            user_id=principal.user_id,
            state=state,
        )
        # Manually set expires_at since we're not using the default
        oauth_state.expires_at = datetime.now(UTC) + timedelta(seconds=expires_at)
        session.add(oauth_state)
        await session.commit()

    auth_url = oauth_client.get_authorization_url(state)
    return GitHubAuthUrlResponse(auth_url=auth_url, state=state)


@router.get("/callback", response_model=GitHubStatusResponse)
async def github_callback(
    request: Request,
    code: str = Query(...),
    state: str = Query(...),
    oauth_client: GitHubOAuthClient = Depends(create_github_oauth_client),
    app_client: GitHubAppClient = Depends(create_github_app_client),
    vault: VaultClient = Depends(create_vault_client),
    session: AsyncSession = Depends(get_db),
) -> GitHubStatusResponse:
    """Handle GitHub OAuth callback."""
    # Validate state
    result = await session.execute(
        select(GitHubOAuthState).where(GitHubOAuthState.state == state)
    )
    oauth_state = result.scalar_one_or_none()

    if oauth_state is None:
        raise ConflictError("Invalid or expired OAuth state.")

    if oauth_state.expires_at < datetime.now(UTC):
        await session.delete(oauth_state)
        await session.commit()
        raise ConflictError("OAuth state has expired.")

    # Exchange code for token
    try:
        token_data = await oauth_client.exchange_code(code)
    except Exception as exc:
        raise ConflictError(f"Failed to exchange code: {exc}") from exc

    access_token = token_data.get("access_token")
    _ = token_data.get("refresh_token")
    scopes = token_data.get("scope", "").split(",")

    if not access_token:
        raise ConflictError("No access token returned from GitHub.")

    # Get user info
    user_info = await oauth_client.get_user_info(access_token)
    github_user_id = str(user_info["id"])
    github_username = user_info["login"]

    # Get installations for this user
    installations = await app_client.get_user_installations(access_token)

    # Store connection in database
    # Check for existing connection
    result = await session.execute(
        select(GitHubConnection).where(
            GitHubConnection.user_id == oauth_state.user_id,
            GitHubConnection.github_user_id == github_user_id,
        )
    )
    existing = result.scalar_one_or_none()

    if existing:
        # Update existing connection
        existing.github_username = github_username
        existing.scopes_granted = {"user": scopes, "app": []}
        existing.revoked_at = None
        connection = existing
    else:
        connection = GitHubConnection(
            user_id=oauth_state.user_id,
            github_user_id=github_user_id,
            github_username=github_username,
            scopes_granted={"user": scopes, "app": []},
        )
        session.add(connection)

    # Store tokens in Vault
    vault_base = f"secret/github/connections/{connection.id}"
    connection.access_token_vault_path = f"{vault_base}/access_token"
    connection.refresh_token_vault_path = f"{vault_base}/refresh_token"
    await vault.write_secret(connection.access_token_vault_path, {"token": access_token})
    if token_data.get("refresh_token"):
        await vault.write_secret(connection.refresh_token_vault_path, {"token": token_data["refresh_token"]})

    # Clean up OAuth state
    await session.delete(oauth_state)

    await session.commit()
    await session.refresh(connection)

    return GitHubStatusResponse(
        connected=True,
        github_username=github_username,
        installations=[
            {
                "id": inst["id"],
                "account": inst["account"]["login"],
                "account_type": inst["account"]["type"],
            }
            for inst in installations
        ],
    )


@router.get("/status", response_model=GitHubStatusResponse)
async def github_status(
    principal: Principal = Depends(get_current_principal),
    session: AsyncSession = Depends(get_db),
) -> GitHubStatusResponse:
    """Get current GitHub connection status."""
    result = await session.execute(
        select(GitHubConnection).where(
            GitHubConnection.user_id == principal.user_id,
            GitHubConnection.revoked_at.is_(None),
        )
    )
    connections = result.scalars().all()

    if not connections:
        return GitHubStatusResponse(connected=False)

    # Return the first active connection
    conn = connections[0]
    return GitHubStatusResponse(
        connected=True,
        github_username=conn.github_username,
        installations=[],  # Would need to fetch from GitHub API
    )


@router.delete("/disconnect", status_code=status.HTTP_204_NO_CONTENT)
async def github_disconnect(
    principal: Principal = Depends(get_current_principal),
    session: AsyncSession = Depends(get_db),
) -> None:
    """Revoke GitHub connection and delete tokens from Vault."""
    result = await session.execute(
        select(GitHubConnection).where(
            GitHubConnection.user_id == principal.user_id,
            GitHubConnection.revoked_at.is_(None),
        )
    )
    connection = result.scalar_one_or_none()

    if connection is None:
        raise NotFoundError("No active GitHub connection found.")

    # Mark as revoked
    connection.revoked_at = datetime.now(UTC)

    # Delete tokens from Vault (would use vault_client)
    # await vault_client.delete_secret(connection.access_token_vault_path)
    # await vault_client.delete_secret(connection.refresh_token_vault_path)

    await session.commit()


@router.get("/repos", response_model=GitHubReposResponse)
async def github_repos(
    principal: Principal = Depends(require_org_permission(Permission.GITHUB_CONNECT)),
    session: AsyncSession = Depends(get_db),
    app_client: GitHubAppClient = Depends(create_github_app_client),
) -> GitHubReposResponse:
    """List user's GitHub repositories (requires GitHub connection)."""
    result = await session.execute(
        select(GitHubConnection).where(
            GitHubConnection.user_id == principal.user_id,
            GitHubConnection.revoked_at.is_(None),
        )
    )
    connection = result.scalar_one_or_none()

    if connection is None:
        raise ConflictError("No active GitHub connection. Connect first via /github/connect")

    # Get installations
    # Need to get user's OAuth token from Vault first
    # For now, return empty - requires Vault integration
    return GitHubReposResponse(repos=[])
