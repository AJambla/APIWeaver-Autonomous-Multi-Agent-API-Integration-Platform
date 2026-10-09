"""Dependency Graph API contracts (`API.md §6.5`)."""

from __future__ import annotations

from app.models.enums import DependencyRelationship
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
    # The model's own enum (a StrEnum, so it serializes to the same strings) rather than a
    # duplicated Literal that the stored column's str could not be checked against.
    relationship: DependencyRelationship


class DependencyGraphResponse(ResponseModel):
    nodes: list[DependencyNode]
    edges: list[DependencyEdge]