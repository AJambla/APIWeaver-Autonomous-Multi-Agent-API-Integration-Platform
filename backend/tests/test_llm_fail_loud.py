"""Production fail-loud behavior for LLM/embedding mock fallbacks (Track B3)."""

from __future__ import annotations

import pytest

from app.core.config import Settings
from app.core.errors import DependencyUnavailableError
from app.workflows.llm import LLMClient


def _make_settings(**overrides) -> Settings:
    values = dict(
        database_url="sqlite+aiosqlite:///:memory:",
        redis_url="redis://localhost:6379/0",
        jwt_private_key_path="test-jwt-key.pem",
        jwt_public_key_path="test-jwt-key.pub",
        # Production Settings refuse the in-process sandbox (audit M1), which conftest
        # exports into the environment; these tests only vary app_env and provider keys.
        sandbox_backend="docker",
    )
    values.update(overrides)
    return Settings(**values)


async def test_generate_json_raises_in_production_without_keys():
    client = LLMClient(_make_settings(app_env="production"))

    with pytest.raises(DependencyUnavailableError, match="No LLM provider configured"):
        await client.generate_json(
            system_prompt="system",
            user_prompt="user",
            fallback_json={"answer": "mock"},
        )


async def test_generate_embedding_raises_in_production_without_key():
    client = LLMClient(_make_settings(app_env="production"))

    with pytest.raises(DependencyUnavailableError, match="No embedding provider configured"):
        await client.generate_embedding("hello")


async def test_generate_json_still_falls_back_in_development():
    client = LLMClient(_make_settings(app_env="development"))

    parsed, tokens = await client.generate_json(
        system_prompt="system",
        user_prompt="user",
        fallback_json={"answer": "mock"},
    )

    assert parsed == {"answer": "mock"}
    assert tokens == 50


async def test_generate_embedding_still_zero_vector_in_development():
    client = LLMClient(_make_settings(app_env="development"))

    embedding = await client.generate_embedding("hello")

    assert embedding == [0.0] * 1536


async def test_generate_json_uses_provider_when_key_set(monkeypatch):
    client = LLMClient(_make_settings(app_env="production", openai_api_key="sk-test"))

    async def fake_call_openai(system: str, user: str):
        return {"routed": "openai"}, 12

    monkeypatch.setattr(client, "_call_openai", fake_call_openai)

    parsed, tokens = await client.generate_json(system_prompt="s", user_prompt="u")

    assert parsed == {"routed": "openai"}
    assert tokens == 12
