"""Unit tests for configurable model pricing, token budget, and cost calculations."""

from __future__ import annotations

from decimal import Decimal

import pytest

from app.core.config import Settings
from app.workflows.langgraph_pipeline import (
    calculate_token_cost_usd,
    check_budget,
)


def _base_settings(**kwargs) -> Settings:
    return Settings(
        app_env="development",
        jwt_private_key_path="backend/tests/fixtures/jwt_private.pem",
        jwt_public_key_path="backend/tests/fixtures/jwt_public.pem",
        **kwargs,
    )


def test_settings_default_pricing_table():
    """Settings includes default pricing for major frontier and open models."""
    settings = _base_settings()
    assert settings.default_token_budget == 1_000_000
    assert settings.default_token_price == 0.000003
    assert settings.model_pricing_per_token["gpt-4o-mini"] == 0.0000003
    assert settings.model_pricing_per_token["gpt-4o"] == 0.000005
    assert settings.model_pricing_per_token["gemini-2.0-flash"] == 0.0000001
    assert settings.model_pricing_per_token["claude-3-5-sonnet"] == 0.000003


def test_settings_custom_json_env_pricing():
    """Settings merges custom JSON string pricing with standard models."""
    json_str = '{"gpt-4o": 0.0000025, "custom-deepseek": 0.0000005}'
    settings = _base_settings(model_pricing_per_token=json_str)

    # Overridden model
    assert settings.model_pricing_per_token["gpt-4o"] == 0.0000025
    # New custom model
    assert settings.model_pricing_per_token["custom-deepseek"] == 0.0000005
    # Unchanged default models preserved
    assert settings.model_pricing_per_token["gpt-4o-mini"] == 0.0000003


def test_settings_invalid_json_pricing_fails_fast():
    """Malformed JSON string for model_pricing_per_token raises ValidationError."""
    with pytest.raises(Exception):
        _base_settings(model_pricing_per_token="not-valid-json")

    with pytest.raises(Exception):
        _base_settings(model_pricing_per_token='["not", "a", "dict"]')


def test_calculate_token_cost_usd_default():
    """calculate_token_cost_usd uses configured per-model prices with high precision."""
    # 10,000 tokens of gpt-4o-mini at $0.0000003/token = $0.003
    cost = calculate_token_cost_usd(10_000, "gpt-4o-mini")
    assert cost == Decimal("0.003000")

    # 10,000 tokens of gpt-4o at $0.000005/token = $0.05
    cost_gpt4o = calculate_token_cost_usd(10_000, "gpt-4o")
    assert cost_gpt4o == Decimal("0.050000")


def test_calculate_token_cost_usd_fallback():
    """Unknown model falls back to default_token_price."""
    settings = _base_settings(default_token_price=0.000001)
    # 1,000,000 tokens with default price $0.000001 = $1.00
    cost = calculate_token_cost_usd(1_000_000, "unknown-model-xyz", settings=settings)
    assert cost == Decimal("1.000000")


def test_calculate_token_cost_usd_custom_settings():
    """Passing custom settings overrides model price lookup."""
    settings = _base_settings(
        model_pricing_per_token={"gpt-4o": 0.000001},
        default_token_price=0.000002,
    )
    cost = calculate_token_cost_usd(100_000, "gpt-4o", settings=settings)
    assert cost == Decimal("0.100000")


def test_calculate_token_cost_usd_ad_hoc_overrides():
    """Ad-hoc pricing_overrides dictionary takes precedence."""
    overrides = {"gpt-4o": 0.000009}
    cost = calculate_token_cost_usd(100_000, "gpt-4o", pricing_overrides=overrides)
    assert cost == Decimal("0.900000")


def test_check_budget():
    """check_budget allows runs within budget and halts runs exceeding budget."""
    settings = _base_settings(default_token_budget=50_000)

    # Within budget
    check_budget({"total_tokens_used": 40_000}, settings=settings)

    # Exceeded default budget from settings
    with pytest.raises(RuntimeError, match="token_budget_exceeded"):
        check_budget({"total_tokens_used": 60_000}, settings=settings)

    # Explicit state token_budget overrides settings
    check_budget({"token_budget": 100_000, "total_tokens_used": 60_000}, settings=settings)

    with pytest.raises(RuntimeError, match="token_budget_exceeded"):
        check_budget({"token_budget": 100_000, "total_tokens_used": 100_001}, settings=settings)
