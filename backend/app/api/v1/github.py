"""GitHub OAuth and integration API routes (Phase 4)."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_current_principal, get_db
from app.core.errors import ConflictError, ForbiddenError, NotFoundError
from app.models.github import GitHubConnection, GitHubOAuthState
from app.rbac.enforce import require_own_org_permission
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

# `/github/callback` is a browser redirect from GitHub's authorization server, so it
# arrives with no `Authorization` header and no API key -- nothing a GitHub user could
# carry in a top-level navigation. The org-tier limiter `router.py` attaches to every
# authenticated router resolves a principal and would answer 401 before the route body
# ran, which is the same reason `auth.router` is excluded there. This router rides that
# reasoning and is covered by the per-IP anonymous limiter instead (`Security.md §8`).
public_router = APIRouter(prefix="/github", tags=["github"])

# `GitHubOAuthState` documents a state that "expires after 10 minutes"; the route used to
# read a `github_oauth_state_ttl_seconds` setting that exists in no `Settings` class.
OAUTH_STATE_TTL_SECONDS = 600


@router.post("/connect", response_model=GitHubAuthUrlResponse)
async def github_connect(
    principal: Principal = Depends(require_own_org_permission(Permission.GITHUB_CONNECT)),
    session: AsyncSession = Depends(get_db),
    oauth_client: GitHubOAuthClient = Depends(create_github_oauth_client),
) -> GitHubAuthUrlResponse:
    """Initiate GitHub OAuth flow."""
    if principal.user_id is None:
        # An API key has no user behind it (`deps.py`), and the state -- and the
        # connection it becomes -- belongs to a user. Consent is an interactive action.
        raise ForbiddenError("GitHub connections require an interactive session.")

    # Generate secure state parameter
    state = uuid.uuid4().hex
    oauth_state = GitHubOAuthState(
        user_id=principal.user_id,
        state=state,
        expires_at=datetime.now(UTC) + timedelta(seconds=OAUTH_STATE_TTL_SECONDS),
    )
    session.add(oauth_state)
    await session.commit()

    auth_url = oauth_client.get_authorization_url(state)
    return GitHubAuthUrlResponse(auth_url=auth_url, state=state)


@public_router.get("/callback", response_model=GitHubStatusResponse)
async def github_callback(
    code: str = Query(...),
    state: str = Query(...),
    oauth_client: GitHubOAuthClient = Depends(create_github_oauth_client),
    app_client: GitHubAppClient = Depends(create_github_app_client),
    vault: VaultClient = Depends(create_vault_client),
    session: AsyncSession = Depends(get_db),
) -> GitHubStatusResponse:
    """Handle GitHub OAuth callback.

    Unauthenticated by necessity -- GitHub drives this navigation, and no bearer token
    travels with it. The `state` row created by `/connect` is the authenticator: a
    `uuid4().hex` (122 bits), unique in the database, ten minutes old at most, and deleted
    on the way out whether the exchange succeeds or the state has expired.
    """
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


@router.delete("/disconnect", status_code=status.HTTP_204_NO_CONTENT, response_model=None)
async def github_disconnect(
    principal: Principal = Depends(get_current_principal),
    session: AsyncSession = Depends(get_db),
    vault: VaultClient = Depends(create_vault_client),
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

    # Delete tokens from Vault
    if connection.access_token_vault_path:
        await vault.delete_secret(connection.access_token_vault_path)
    if connection.refresh_token_vault_path:
        await vault.delete_secret(connection.refresh_token_vault_path)

    await session.commit()


@router.get("/repos", response_model=GitHubReposResponse)
async def github_repos(
    principal: Principal = Depends(require_own_org_permission(Permission.GITHUB_CONNECT)),
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
