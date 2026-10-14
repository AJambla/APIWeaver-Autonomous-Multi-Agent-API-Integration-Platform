from app.services.safety_service import (
    RiskLevel,
    SafetyBadge,
    classify_safety,
    format_tool_docstring,
)


def test_classify_safety_get_read_only():
    c = classify_safety("GET", "/api/v1/users/123", summary="Get user profile")
    assert c.risk_level == RiskLevel.LOW
    assert c.badge == SafetyBadge.SAFE
    assert c.is_safe is True
    assert c.requires_confirmation is False
    assert c.is_destructive is False


def test_classify_safety_delete_destructive():
    c = classify_safety("DELETE", "/api/v1/users/123", summary="Remove user")
    assert c.risk_level == RiskLevel.HIGH
    assert c.badge == SafetyBadge.DESTRUCTIVE
    assert c.requires_confirmation is True
    assert c.is_destructive is True
    assert c.is_safe is False


def test_classify_safety_post_standard_state_changing():
    c = classify_safety("POST", "/api/v1/orders", summary="Create order")
    assert c.risk_level == RiskLevel.MEDIUM
    assert c.badge == SafetyBadge.STATE_CHANGING
    assert c.is_state_changing is True
    assert c.requires_confirmation is False
    assert c.is_destructive is False


def test_classify_safety_semantic_high_risk_elevation():
    # POST to /refund or /transfer is elevated to HIGH risk and requires confirmation
    c_refund = classify_safety("POST", "/api/v1/payments/refund", summary="Process a customer refund")
    assert c_refund.risk_level == RiskLevel.HIGH
    assert c_refund.badge == SafetyBadge.DESTRUCTIVE
    assert c_refund.requires_confirmation is True
    assert c_refund.is_destructive is True

    c_transfer = classify_safety("POST", "/api/v1/wallets/transfer", summary="Transfer funds between accounts")
    assert c_transfer.risk_level == RiskLevel.HIGH
    assert c_transfer.badge == SafetyBadge.DESTRUCTIVE
    assert c_transfer.requires_confirmation is True

    c_purge = classify_safety("POST", "/api/v1/cache/purge", summary="Purge entire cache")
    assert c_purge.risk_level == RiskLevel.HIGH
    assert c_purge.requires_confirmation is True


def test_format_tool_docstring():
    c = classify_safety("DELETE", "/api/v1/projects/proj-1")
    doc = format_tool_docstring("Permanently delete a project.", c)
    assert "Permanently delete a project." in doc
    assert "Safety Tier: [DESTRUCTIVE ⚠] (HIGH)" in doc
    assert "Requires Confirmation: True" in doc
