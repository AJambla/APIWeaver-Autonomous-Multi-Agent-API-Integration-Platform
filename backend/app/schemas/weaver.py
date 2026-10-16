"""Weaver AI Engineering Agent schemas."""

from __future__ import annotations

from typing import Any
from pydantic import ConfigDict
from app.schemas.common import ResponseModel, StrictModel


class WeaverContext(StrictModel):
    current_stage: str | None = None
    selected_node: str | None = None
    selected_file: str | None = None
    selected_endpoint: str | None = None
    selected_tool: str | None = None
    active_code_snippet: str | None = None
    error_message: str | None = None


class ChatMessage(StrictModel):
    role: str
    content: str


class WeaverChatRequest(StrictModel):
    message: str
    workspace_context: WeaverContext | None = None
    conversation_history: list[ChatMessage] | None = None


class WeaverChangeProposal(ResponseModel):
    file_path: str
    description: str
    original_snippet: str | None = None
    replacement_snippet: str | None = None
    full_content: str | None = None
    diff: str | None = None


class WeaverChatResponse(ResponseModel):
    reply: str
    intent: str  # "explain" | "investigate" | "propose" | "modify" | "verify" | "analyze"
    context_used: dict[str, Any]
    safety_reasoning: list[str] | None = None
    proposal: WeaverChangeProposal | None = None


class WeaverApplyRequest(StrictModel):
    file_path: str
    content: str


class WeaverApplyResponse(ResponseModel):
    success: bool
    file_path: str
    verification_status: str  # "PASS" | "FAIL" | "NOT_RUN"
    details: str
