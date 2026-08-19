"""Dependency Graph API contracts (`API.md §6.5`)."""

from __future__ import annotations

from typing import Literal

from app.schemas.common import ResponseModel, StrictModel


class DependencyNode(StrictModel):
    id: str
    label: str
    method: str
    path: str
    is_destructive: bool


class DependencyEdge(StrictModel):
    from_id: str
    to_id: str
    relationship: Literal[
        "requires_auth",
        "requires_created_resource",
        "optional_precedes",
    ]


class DependencyGraphResponse(ResponseModel):
    nodes: list[DependencyNode]
    edges: list[DependencyEdge]