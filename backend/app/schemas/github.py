"""GitHub-related schemas (Phase 4)."""

from __future__ import annotations

from pydantic import BaseModel


class GitHubAuthUrlResponse(BaseModel):
    auth_url: str
    state: str


class GitHubInstallation(BaseModel):
    id: int
    account: str
    account_type: str


class GitHubStatusResponse(BaseModel):
    connected: bool
    github_username: str | None = None
    installations: list[GitHubInstallation] = []


class GitHubRepo(BaseModel):
    id: int
    name: str
    full_name: str
    private: bool
    owner: str
    default_branch: str = "main"


class GitHubReposResponse(BaseModel):
    repos: list[GitHubRepo]
