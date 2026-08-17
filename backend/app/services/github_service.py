"""GitHub service for OAuth and GitHub App integration (Phase 4)."""

from __future__ import annotations

import base64
import time
import uuid
from typing import Any

import httpx
import jwt
from fastapi import Depends, HTTPException, status

from app.core.config import Settings, get_settings
from app.core.logging import get_logger
from app.services.vault_service import VaultClient, create_vault_client

logger = get_logger(__name__)

GITHUB_API_BASE = "https://api.github.com"
GITHUB_OAUTH_AUTHORIZE_URL = "https://github.com/login/oauth/authorize"
GITHUB_OAUTH_TOKEN_URL = "https://github.com/login/oauth/access_token"


class GitHubAppClient:
    """GitHub App client for installation-based API calls.

    Uses JWT authentication with the GitHub App private key to obtain
    installation access tokens, then makes API calls on behalf of the installation.
    """

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.app_id = settings.github_app_id
        self._private_key: str | None = None

    def _load_private_key(self) -> str:
        if self._private_key is not None:
            return self._private_key
        if not self.settings.github_app_private_key_path:
            raise RuntimeError("GitHub App private key path not configured")
        try:
            self._private_key = self.settings.github_app_private_key_path.read_text().strip()
            return self._private_key
        except FileNotFoundError:
            raise RuntimeError(f"GitHub App private key not found at {self.settings.github_app_private_key_path}")

    def _generate_jwt(self) -> str:
        """Generate a GitHub App JWT (RS256, 10 min expiry)."""
        private_key = self._load_private_key()
        now = int(time.time())
        payload = {
            "iat": now - 60,  # issued 60s ago to account for clock skew
            "exp": now + 600,  # 10 minutes
            "iss": self.app_id,
        }
        return jwt.encode(payload, private_key, algorithm="RS256")

    async def get_installation_token(self, installation_id: int) -> str:
        """Get an installation access token for the given installation ID."""
        jwt_token = self._generate_jwt()
        url = f"{GITHUB_API_BASE}/app/installations/{installation_id}/access_tokens"
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(
                url,
                headers={
                    "Authorization": f"Bearer {jwt_token}",
                    "Accept": "application/vnd.github+json",
                },
            )
            response.raise_for_status()
            data = response.json()
            return data["token"]

    async def get_user_installations(self, user_token: str) -> list[dict[str, Any]]:
        """List installations accessible to the user (using their OAuth token)."""
        url = f"{GITHUB_API_BASE}/user/installations"
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.get(
                url,
                headers={
                    "Authorization": f"Bearer {user_token}",
                    "Accept": "application/vnd.github+json",
                },
            )
            response.raise_for_status()
            return response.json().get("installations", [])

    async def create_repository(
        self, installation_token: str, org: str | None, name: str, private: bool = True
    ) -> dict[str, Any]:
        """Create a new repository via GitHub App installation token."""
        url = f"{GITHUB_API_BASE}/user/repos" if org is None else f"{GITHUB_API_BASE}/orgs/{org}/repos"
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(
                url,
                json={"name": name, "private": private, "auto_init": False},
                headers={
                    "Authorization": f"Bearer {installation_token}",
                    "Accept": "application/vnd.github+json",
                },
            )
            if response.status_code == 422:
                # Repo may already exist
                existing = await self.get_repository(installation_token, org, name)
                if existing:
                    return existing
            response.raise_for_status()
            return response.json()

    async def get_repository(
        self, installation_token: str, org: str | None, name: str
    ) -> dict[str, Any] | None:
        """Get repository by name."""
        full_name = f"{org}/{name}" if org else name
        url = f"{GITHUB_API_BASE}/repos/{full_name}"
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.get(
                url,
                headers={
                    "Authorization": f"Bearer {installation_token}",
                    "Accept": "application/vnd.github+json",
                },
            )
            if response.status_code == 404:
                return None
            response.raise_for_status()
            return response.json()

    async def push_files_via_git_data_api(
        self,
        installation_token: str,
        repo_full_name: str,
        files: list[dict[str, Any]],
        message: str,
        branch: str = "main",
    ) -> str:
        """Push multiple files using Git Data API (blob -> tree -> commit -> ref)."""
        # 1. Get the current HEAD commit SHA
        head_sha = await self._get_head_sha(installation_token, repo_full_name, branch)

        # 2. Get the base tree SHA
        base_tree_sha = await self._get_tree_sha(installation_token, repo_full_name, head_sha)

        # 3. Create blobs for each file
        blob_shas = []
        for file_info in files:
            content = file_info.get("content", "")
            encoding = file_info.get("encoding", "utf-8")
            if encoding == "base64":
                blob_content = base64.b64encode(content.encode()).decode()
            else:
                blob_content = content

            blob_sha = await self._create_blob(installation_token, repo_full_name, blob_content, encoding)
            blob_shas.append({"path": file_info["path"], "mode": "100644", "type": "blob", "sha": blob_sha})

        # 4. Create new tree
        new_tree_sha = await self._create_tree(
            installation_token, repo_full_name, base_tree_sha, blob_shas
        )

        # 5. Create commit
        commit_sha = await self._create_commit(
            installation_token, repo_full_name, message, head_sha, new_tree_sha
        )

        # 6. Update ref
        await self._update_ref(installation_token, repo_full_name, branch, commit_sha)

        return commit_sha

    async def _get_head_sha(self, token: str, repo: str, branch: str) -> str:
        url = f"{GITHUB_API_BASE}/repos/{repo}/git/refs/heads/{branch}"
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.get(url, headers=self._auth_headers(token))
            if response.status_code == 404:
                # Empty repo, return empty tree SHA
                return "4b825dc642cb6eb9a060e54bf8d69288fbee4904"
            response.raise_for_status()
            return response.json()["object"]["sha"]

    async def _get_tree_sha(self, token: str, repo: str, commit_sha: str) -> str:
        url = f"{GITHUB_API_BASE}/repos/{repo}/git/commits/{commit_sha}"
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.get(url, headers=self._auth_headers(token))
            response.raise_for_status()
            return response.json()["tree"]["sha"]

    async def _create_blob(
        self, token: str, repo: str, content: str, encoding: str = "utf-8"
    ) -> str:
        url = f"{GITHUB_API_BASE}/repos/{repo}/git/blobs"
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(
                url,
                json={"content": content, "encoding": encoding},
                headers=self._auth_headers(token),
            )
            response.raise_for_status()
            return response.json()["sha"]

    async def _create_tree(
        self, token: str, repo: str, base_tree_sha: str, blobs: list[dict]
    ) -> str:
        url = f"{GITHUB_API_BASE}/repos/{repo}/git/trees"
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(
                url,
                json={"base_tree": base_tree_sha, "tree": blobs},
                headers=self._auth_headers(token),
            )
            response.raise_for_status()
            return response.json()["sha"]

    async def _create_commit(
        self, token: str, repo: str, message: str, parent_sha: str, tree_sha: str
    ) -> str:
        url = f"{GITHUB_API_BASE}/repos/{repo}/git/commits"
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(
                url,
                json={"message": message, "parents": [parent_sha], "tree": tree_sha},
                headers=self._auth_headers(token),
            )
            response.raise_for_status()
            return response.json()["sha"]

    async def _update_ref(self, token: str, repo: str, branch: str, commit_sha: str) -> None:
        url = f"{GITHUB_API_BASE}/repos/{repo}/git/refs/heads/{branch}"
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.patch(
                url,
                json={"sha": commit_sha, "force": True},
                headers=self._auth_headers(token),
            )
            response.raise_for_status()

    def _auth_headers(self, token: str) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
        }


class GitHubOAuthClient:
    """User OAuth client for GitHub authorization flow."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.client_id = settings.github_app_client_id
        self._client_secret: str | None = None
        self.vault_client: VaultClient | None = None

    async def _get_client_secret(self) -> str:
        if self._client_secret is not None:
            return self._client_secret
        if not self.settings.github_app_client_secret_vault_path:
            raise RuntimeError("GitHub App client secret vault path not configured")
        if self.vault_client is None:
            self.vault_client = create_vault_client(self.settings)
        secret = await self.vault_client.read_secret(self.settings.github_app_client_secret_vault_path)
        if not secret or "client_secret" not in secret:
            raise RuntimeError("GitHub App client secret not found in Vault")
        self._client_secret = secret["client_secret"]
        return self._client_secret

    def get_authorization_url(self, state: str, scopes: list[str] | None = None) -> str:
        """Generate the GitHub OAuth authorization URL."""
        scope_str = " ".join(scopes or ["repo", "read:user", "read:org"])
        params = {
            "client_id": self.client_id,
            "redirect_uri": self.settings.github_oauth_redirect_uri,
            "scope": scope_str,
            "state": state,
            "allow_signup": "false",
        }
        query = "&".join(f"{k}={v}" for k, v in params.items())
        return f"{GITHUB_OAUTH_AUTHORIZE_URL}?{query}"

    async def exchange_code(self, code: str) -> dict[str, Any]:
        """Exchange authorization code for access token."""
        client_secret = await self._get_client_secret()
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(
                GITHUB_OAUTH_TOKEN_URL,
                data={
                    "client_id": self.client_id,
                    "client_secret": client_secret,
                    "code": code,
                    "redirect_uri": self.settings.github_oauth_redirect_uri,
                },
                headers={"Accept": "application/json"},
            )
            response.raise_for_status()
            return response.json()

    async def get_user_info(self, access_token: str) -> dict[str, Any]:
        """Get authenticated user info."""
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.get(
                f"{GITHUB_API_BASE}/user",
                headers={"Authorization": f"Bearer {access_token}", "Accept": "application/vnd.github+json"},
            )
            response.raise_for_status()
            return response.json()

    async def get_user_emails(self, access_token: str) -> list[dict[str, Any]]:
        """Get user's email addresses."""
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.get(
                f"{GITHUB_API_BASE}/user/emails",
                headers={"Authorization": f"Bearer {access_token}", "Accept": "application/vnd.github+json"},
            )
            response.raise_for_status()
            return response.json()


def create_github_app_client(settings: Settings = Depends(get_settings)) -> GitHubAppClient:
    return GitHubAppClient(settings)


def create_github_oauth_client(settings: Settings = Depends(get_settings)) -> GitHubOAuthClient:
    return GitHubOAuthClient(settings)