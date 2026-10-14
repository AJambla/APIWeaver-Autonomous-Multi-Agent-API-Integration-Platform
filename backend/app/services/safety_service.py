"""Deterministic Safety Rule Engine for MCP Tools (Blueprint §4).

Classifies endpoints and generated MCP tools by HTTP method and semantic rules into
explicit risk tiers:
- SAFE (read-only queries)
- STATE-CHANGING (creates/updates)
- DESTRUCTIVE (deletions, financial transactions, revocations)
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass
from enum import Enum
from typing import Any


class RiskLevel(str, Enum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"


class SafetyBadge(str, Enum):
    SAFE = "[SAFE]"
    STATE_CHANGING = "[STATE-CHANGING]"
    DESTRUCTIVE = "[DESTRUCTIVE ⚠]"


# Semantic patterns indicating high-impact or destructive side effects
HIGH_RISK_PATTERNS = [
    re.compile(r"\b(refund|chargeback|reversal)\b", re.IGNORECASE),
    re.compile(r"\b(transfer|payout|disburse|withdraw|send_money)\b", re.IGNORECASE),
    re.compile(r"\b(terminate|destroy|purge|drop|wipe|erase|truncate)\b", re.IGNORECASE),
    re.compile(r"\b(revoke|ban|block|suspend|deactivate|disable)\b", re.IGNORECASE),
    re.compile(r"\b(cancel|void|abort)\b", re.IGNORECASE),
    re.compile(r"\b(reset|factory_reset|hard_reset)\b", re.IGNORECASE),
    re.compile(r"\b(delete|remove)\b", re.IGNORECASE),
]


@dataclass(frozen=True)
class SafetyClassification:
    method: str
    path: str
    risk_level: RiskLevel
    badge: SafetyBadge
    requires_confirmation: bool
    is_destructive: bool
    is_state_changing: bool
    is_safe: bool
    reason: str
    tags: list[str]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def classify_safety(
    method: str,
    path: str,
    summary: str | None = None,
    operation_id: str | None = None,
) -> SafetyClassification:
    """Classify API endpoint / MCP tool safety deterministically."""
    clean_method = (method or "GET").strip().upper()
    clean_path = (path or "/").strip()
    full_text = f"{clean_path} {summary or ''} {operation_id or ''}"

    # 1. Check for semantic high-risk keywords in path, summary, or operation_id
    matched_high_risk = []
    for pattern in HIGH_RISK_PATTERNS:
        match = pattern.search(full_text)
        if match:
            matched_high_risk.append(match.group(1).lower())

    # 2. HTTP DELETE is inherently destructive
    if clean_method == "DELETE":
        return SafetyClassification(
            method=clean_method,
            path=clean_path,
            risk_level=RiskLevel.HIGH,
            badge=SafetyBadge.DESTRUCTIVE,
            requires_confirmation=True,
            is_destructive=True,
            is_state_changing=True,
            is_safe=False,
            reason=f"HTTP DELETE on {clean_path} permanently removes resources",
            tags=["destructive", "delete", "requires_confirmation"],
        )

    # 3. High-risk semantic operations (even on POST/PUT/PATCH) require confirmation
    if matched_high_risk and clean_method in ("POST", "PUT", "PATCH"):
        kw_str = ", ".join(sorted(set(matched_high_risk)))
        return SafetyClassification(
            method=clean_method,
            path=clean_path,
            risk_level=RiskLevel.HIGH,
            badge=SafetyBadge.DESTRUCTIVE,
            requires_confirmation=True,
            is_destructive=True,
            is_state_changing=True,
            is_safe=False,
            reason=f"High-impact operation detected ({kw_str}) on {clean_method} {clean_path}",
            tags=["destructive", "high_risk", *matched_high_risk, "requires_confirmation"],
        )

    # 4. Standard mutating methods
    if clean_method in ("POST", "PUT", "PATCH"):
        return SafetyClassification(
            method=clean_method,
            path=clean_path,
            risk_level=RiskLevel.MEDIUM,
            badge=SafetyBadge.STATE_CHANGING,
            requires_confirmation=False,
            is_destructive=False,
            is_state_changing=True,
            is_safe=False,
            reason=f"HTTP {clean_method} creates or updates server state on {clean_path}",
            tags=["state_changing", clean_method.lower()],
        )

    # 5. Read-only queries (GET, HEAD, OPTIONS)
    return SafetyClassification(
        method=clean_method,
        path=clean_path,
        risk_level=RiskLevel.LOW,
        badge=SafetyBadge.SAFE,
        requires_confirmation=False,
        is_destructive=False,
        is_state_changing=False,
        is_safe=True,
        reason=f"HTTP {clean_method} is a read-only idempotent operation",
        tags=["safe", "read_only", clean_method.lower()],
    )


def format_tool_docstring(
    description: str,
    classification: SafetyClassification,
) -> str:
    """Format docstring for FastMCP tool with structured safety metadata."""
    lines = [description.strip(), ""]
    lines.append(f"Safety Tier: {classification.badge.value} ({classification.risk_level.value})")
    lines.append(f"Requires Confirmation: {classification.requires_confirmation}")
    lines.append(f"Details: {classification.reason}")
    return "\n".join(lines)
