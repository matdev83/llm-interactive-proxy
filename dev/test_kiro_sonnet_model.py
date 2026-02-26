#!/usr/bin/env python3
"""Test script to verify which Claude Sonnet model names work with kiro-oauth-auto backend."""

import asyncio
import json
import sys
from pathlib import Path

import httpx

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))


PROXY_URL = "http://127.0.0.1:8000/v1/chat/completions"
TEST_MESSAGE = "Say 'Hello' if you can read this."

# Test different model name variations
TEST_MODELS = [
    "kiro-oauth-auto:amazon/claude-sonnet-4.6",
    "kiro-oauth-auto:amazon/claude-sonnet-4.5",
    "kiro-oauth-auto:claude-sonnet-4.6",
    "kiro-oauth-auto:claude-sonnet-4.5",
]


async def test_model(model_name: str) -> tuple[str, bool, str]:
    """Test a single model name.
    
    Returns:
        (model_name, success, response_or_error)
    """
    payload = {
        "model": model_name,
        "messages": [{"role": "user", "content": TEST_MESSAGE}],
        "max_tokens": 50,
        "stream": False,
    }
    
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(PROXY_URL, json=payload)
            
            if response.status_code == 200:
                data = response.json()
                content = data.get("choices", [{}])[0].get("message", {}).get("content", "")
                return (model_name, True, f"SUCCESS: {content[:100]}")
            else:
                error_text = response.text[:200]
                return (model_name, False, f"HTTP {response.status_code}: {error_text}")
    except Exception as e:
        return (model_name, False, f"EXCEPTION: {type(e).__name__}: {str(e)[:100]}")


async def main():
    """Run all model tests."""
    print("Testing Claude Sonnet model names with kiro-oauth-auto backend...")
    print(f"Proxy: {PROXY_URL}")
    print("=" * 80)
    
    results = []
    for model in TEST_MODELS:
        print(f"\nTesting: {model}")
        model_name, success, message = await test_model(model)
        results.append((model_name, success, message))
        print(f"  {message}")
    
    print("\n" + "=" * 80)
    print("SUMMARY:")
    print("=" * 80)
    
    working_models = []
    for model_name, success, message in results:
        status = "[WORKS]" if success else "[FAILS]"
        print(f"{status}: {model_name}")
        if success:
            working_models.append(model_name)
    
    print("\n" + "=" * 80)
    if working_models:
        print(f"Working models: {', '.join(working_models)}")
    else:
        print("WARNING: NO MODELS WORKING!")
    
    return 0 if working_models else 1


if __name__ == "__main__":
    exit_code = asyncio.run(main())
    sys.exit(exit_code)
