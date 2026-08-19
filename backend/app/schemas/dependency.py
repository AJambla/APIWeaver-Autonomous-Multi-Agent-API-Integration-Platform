"""Dependency graph API contracts."""

from __future__ import annotations

import uuid

from pydantic import Field

from app.schemas.common import ResponseModel


class DependencyNode(ResponseModel):
    """A node in the dependency graph (an endpoint)."""
    id: uuid.UUID
    label: str
    method: str
    path: str


class DependencyEdge(ResponseModel):
    """An edge in the dependency graph."""
    from_: uuid.UUID = Field(alias="from")
    to: uuid.UUID
    relationship: str | None = None


class DependencyGraphResponse(ResponseModel):
    """Full dependency graph for a project."""
    nodes: list[DependencyNode]
    edges: list[DependencyEdge]
