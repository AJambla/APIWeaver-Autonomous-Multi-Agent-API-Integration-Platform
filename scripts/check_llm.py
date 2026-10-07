#!/usr/bin/env python3
"""CLI utility to test LLM connectivity and quota status."""

import asyncio
import os
import sys

# Ensure backend modules can be imported
sys.path.insert(0, os.path.abspath("backend"))

from app.core.config import get_settings
from app.workflows.llm import LLMClient


async def test_llm():
    settings = get_settings()
    print("==========================================")
    print("APIWeaver LLM Diagnostics")
    print("==========================================")
    print(f"Configured Model    : {settings.llm_model}")
    print(f"OpenAI Base URL     : {settings.openai_api_base_url}")
    print(f"OpenAI Key Set      : {'Yes' if settings.openai_api_key else 'No'}")
    print(f"Anthropic Key Set   : {'Yes' if settings.anthropic_api_key else 'No'}")
    print("------------------------------------------")
    print("Sending test request via LLMClient...")

    client = LLMClient(settings=settings)
    try:
        result, token_count = await client.generate_json(
            system_prompt="You are a health probe. Reply with valid JSON only.",
            user_prompt="Return a JSON object: {\"status\": \"ok\", \"message\": \"LLM is working\"}",
        )
        print("\n[SUCCESS] Response received:")
        print(f"  Payload : {result}")
        print(f"  Tokens  : {token_count}")
        print("------------------------------------------")
        print("LLM is operational!")
        return 0
    except Exception as exc:
        print("\n[FAILED] Request failed:")
        print(f"  Error: {exc}")
        print("------------------------------------------")
        return 1


if __name__ == "__main__":
    code = asyncio.run(test_llm())
    sys.exit(code)
