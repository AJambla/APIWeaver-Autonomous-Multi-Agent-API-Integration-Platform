"""GitHub service for OAuth and GitHub App integration (Phase 4)."""

from __future__ import annotations

import base64
import time
from typing import Any
from urllib.parse import urlencode

import httpx
import jwt
from fastapi import Depends

from app.core.config import Settings, get_settings
from app.core.logging import get_logger
from app.services.vault_service import VaultClient, create_vault_client

logger = get_logger(__name__)

GITHUB_API_BASE = "https://api.github.com"
GITHUB_OAUTH_AUTHORIZE_URL = "https://github.com/login/oauth/authorize"
GITHUB_OAUTH_TOKEN_URL = "https://github.com/login/oauth/access_token"


def sanitize_github_path(path: str) -> str:
    """Validate and sanitize file path for GitHub commit to prevent directory traversal."""
    if not isinstance(path, str):
        raise ValueError("GitHub file path must be a string")
    cleaned = path.strip().replace("\\", "/").lstrip("/")
    parts = cleaned.split("/")
    if any(part in ("..", ".") for part in parts) or not cleaned:
        raise ValueError(f"Path traversal or invalid path not permitted: {path}")
    return cleaned


class GitHubAppClient:
    """GitHub App client for installation-based API calls.

    Uses JWT authentication with the GitHub App private key to obtain
    installation access tokens, then makes API calls on behalf of the installation.
    """

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.app_id = settings.github_app_id
        self._private_key: str | None = None
        self.timeout = getattr(settings, "github_timeout_seconds", 30.0)
        self.api_base_url = (getattr(settings, "github_api_base_url", None) or GITHUB_API_BASE).rstrip("/")

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
        url = f"{self.api_base_url}/app/installations/{installation_id}/access_tokens"
        async with httpx.AsyncClient(timeout=self.timeout) as client:
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
        url = f"{self.api_base_url}/user/installations"
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            response = await client.get(
                url,
                headers={
                    "Authorization": f"Bearer {user_token}",
                    "Accept": "application/vnd.github+json",
                },
            )
            response.raise_for_status()
            return response.json().get("installations", [])

    async def get_user_repositories(self, user_token: str) -> list[dict[str, Any]]:
        """List repositories accessible to the user (using their OAuth token)."""
        url = f"{self.api_base_url}/user/repos"
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            response = await client.get(
                url,
                params={"sort": "updated", "per_page": 100},
                headers={
                    "Authorization": f"Bearer {user_token}",
                    "Accept": "application/vnd.github+json",
                },
            )
            response.raise_for_status()
            data = response.json()
            return data if isinstance(data, list) else []

    async def create_repository(
        self, installation_token: str, org: str | None, name: str, private: bool = True
    ) -> dict[str, Any]:
        """Create a new repository via GitHub App installation token."""
        url = f"{self.api_base_url}/user/repos" if org is None else f"{self.api_base_url}/orgs/{org}/repos"
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            response = await client.post(
                url,
                # auto_init gives the repo a first commit on its default branch. An
                # empty repository has no ref to build on, and the Git Data API refuses
                # blobs in it (409), so every push into a repo created here failed.
                json={"name": name, "private": private, "auto_init": True},
                headers={
                    "Authorization": f"Bearer {installation_token}",
                    "Accept": "application/vnd.github+json",
                },
            )
            if response.status_code == 422:
                # Repo may already exist. For a user repo the owner is the token's user:
                # `/repos/{name}` without an owner is always a 404.
                owner = org or await self._token_login(installation_token)
                existing = (
                    await self.get_repository(installation_token, owner, name) if owner else None
                )
                if existing:
                    return existing
            response.raise_for_status()
            return response.json()

    async def get_repository(
        self, installation_token: str, org: str | None, name: str
    ) -> dict[str, Any] | None:
        """Get repository by name."""
        full_name = f"{org}/{name}" if org else name
        url = f"{self.api_base_url}/repos/{full_name}"
        async with httpx.AsyncClient(timeout=self.timeout) as client:
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

    async def _token_login(self, token: str) -> str | None:
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            response = await client.get(f"{self.api_base_url}/user", headers=self._auth_headers(token))
            if response.status_code != 200:
                return None
            login = response.json().get("login")
            return str(login) if login else None

    async def push_files_via_git_data_api(
        self,
        installation_token: str,
        repo_full_name: str,
        files: list[dict[str, Any]],
        message: str,
        branch: str = "main",
    ) -> str:
        """Push multiple files as one commit (blob -> tree -> commit -> ref).

        Works on a branch that exists (fast-forward), a branch that does not (created from
        the default branch) and an empty repository (initialized first). The ref update is
        never forced: a branch that moved meanwhile fails loudly instead of having the
        user's history overwritten.
        """
        token, repo = installation_token, repo_full_name
        head_sha = await self._get_branch_sha(token, repo, branch)
        create_branch = head_sha is None
        if head_sha is None:
            head_sha = await self._get_default_branch_sha(token, repo)
        if head_sha is None:
            # Empty repository: the contents API is the one call that can create the first
            # commit (and with it the branch).
            head_sha = await self._initialize_empty_repo(token, repo, branch)
            create_branch = False

        base_tree_sha = await self._get_tree_sha(token, repo, head_sha)

        # 3. Create blobs for each file
        blob_shas = []
        for file_info in files:
            content = file_info.get("content", "")
            encoding = file_info.get("encoding", "utf-8")
            if encoding == "base64":
                blob_content = base64.b64encode(content.encode()).decode()
            else:
                blob_content = content

            clean_path = sanitize_github_path(str(file_info.get("path", "")))
            blob_sha = await self._create_blob(installation_token, repo_full_name, blob_content, encoding)
            blob_shas.append({"path": clean_path, "mode": "100644", "type": "blob", "sha": blob_sha})

        # 4. Create new tree
        new_tree_sha = await self._create_tree(
            installation_token, repo_full_name, base_tree_sha, blob_shas
        )

        # 5. Create commit
        commit_sha = await self._create_commit(
            installation_token, repo_full_name, message, head_sha, new_tree_sha
        )

        # 6. Point the branch at the new commit
        if create_branch:
            await self._create_ref(installation_token, repo_full_name, branch, commit_sha)
        else:
            await self._update_ref(installation_token, repo_full_name, branch, commit_sha)

        return commit_sha

    async def _get_branch_sha(self, token: str, repo: str, branch: str) -> str | None:
        """The branch's head commit, or None if the branch (or any commit) is missing.

        The old version returned the empty *tree* SHA here, which the next call then
        looked up as a commit: a 404/422 on every new repository.
        """
        url = f"{self.api_base_url}/repos/{repo}/git/refs/heads/{branch}"
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            response = await client.get(url, headers=self._auth_headers(token))
            if response.status_code in (404, 409):  # 409: "Git Repository is empty"
                return None
            response.raise_for_status()
            return str(response.json()["object"]["sha"])

    async def _get_default_branch_sha(self, token: str, repo: str) -> str | None:
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            response = await client.get(
                f"{self.api_base_url}/repos/{repo}", headers=self._auth_headers(token)
            )
            response.raise_for_status()
            default_branch = response.json().get("default_branch")
        if not default_branch:
            return None
        return await self._get_branch_sha(token, repo, str(default_branch))

    async def _initialize_empty_repo(self, token: str, repo: str, branch: str) -> str:
        url = f"{self.api_base_url}/repos/{repo}/contents/README.md"
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            response = await client.put(
                url,
                json={
                    "message": "Initialize repository",
                    "content": base64.b64encode(b"# Generated by APIWeaver\n").decode(),
                    "branch": branch,
                },
                headers=self._auth_headers(token),
            )
            response.raise_for_status()
            return str(response.json()["commit"]["sha"])

    async def _create_ref(self, token: str, repo: str, branch: str, commit_sha: str) -> None:
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            response = await client.post(
                f"{self.api_base_url}/repos/{repo}/git/refs",
                json={"ref": f"refs/heads/{branch}", "sha": commit_sha},
                headers=self._auth_headers(token),
            )
            response.raise_for_status()

    async def _get_tree_sha(self, token: str, repo: str, commit_sha: str) -> str:
        url = f"{self.api_base_url}/repos/{repo}/git/commits/{commit_sha}"
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            response = await client.get(url, headers=self._auth_headers(token))
            response.raise_for_status()
            return response.json()["tree"]["sha"]

    async def _create_blob(
        self, token: str, repo: str, content: str, encoding: str = "utf-8"
    ) -> str:
        url = f"{self.api_base_url}/repos/{repo}/git/blobs"
        async with httpx.AsyncClient(timeout=self.timeout) as client:
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
        url = f"{self.api_base_url}/repos/{repo}/git/trees"
        async with httpx.AsyncClient(timeout=self.timeout) as client:
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
        url = f"{self.api_base_url}/repos/{repo}/git/commits"
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            response = await client.post(
                url,
                json={"message": message, "parents": [parent_sha], "tree": tree_sha},
                headers=self._auth_headers(token),
            )
            response.raise_for_status()
            return response.json()["sha"]

    async def _update_ref(self, token: str, repo: str, branch: str, commit_sha: str) -> None:
        url = f"{self.api_base_url}/repos/{repo}/git/refs/heads/{branch}"
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            response = await client.patch(
                url,
                # Fast-forward only: never overwrite history someone else pushed.
                json={"sha": commit_sha, "force": False},
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
        self.api_base_url = (getattr(settings, "github_api_base_url", None) or GITHUB_API_BASE).rstrip("/")
        self.authorize_url = getattr(settings, "github_oauth_authorize_url", None) or GITHUB_OAUTH_AUTHORIZE_URL
        self.token_url = getattr(settings, "github_oauth_token_url", None) or GITHUB_OAUTH_TOKEN_URL
        self.timeout = getattr(settings, "github_timeout_seconds", 30.0)

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
        # urlencode: the redirect URI and the space-separated scopes must be escaped.
        return f"{self.authorize_url}?{urlencode(params)}"

    async def exchange_code(self, code: str) -> dict[str, Any]:
        """Exchange authorization code for access token."""
        client_secret = await self._get_client_secret()
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            response = await client.post(
                self.token_url,
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
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            response = await client.get(
                f"{self.api_base_url}/user",
                headers={"Authorization": f"Bearer {access_token}", "Accept": "application/vnd.github+json"},
            )
            response.raise_for_status()
            return response.json()



def create_github_app_client(settings: Settings = Depends(get_settings)) -> GitHubAppClient:
    return GitHubAppClient(settings)


def create_github_oauth_client(settings: Settings = Depends(get_settings)) -> GitHubOAuthClient:
    return GitHubOAuthClient(settings)