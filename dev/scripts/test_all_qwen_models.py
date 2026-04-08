#!/usr/bin/env python3
"""Test all qwen-oauth models for functionality."""

import sys

import requests


def safe_print(msg: str):
    """Print message handling encoding issues on Windows."""
    try:
        print(msg)
    except UnicodeEncodeError:
        msg = msg.replace("✓", "[OK]").replace("✗", "[FAIL]").replace("⚠", "[WARN]")
        print(msg)


def test_model(base_url: str, api_key: str, model: str) -> bool:
    """Test a single model."""
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {api_key}"
    }
    
    payload = {
        "model": f"qwen-oauth:{model}",
        "messages": [
            {"role": "user", "content": "Hi"}
        ],
        "max_tokens": 10
    }
    
    try:
        response = requests.post(
            f"{base_url}/v1/chat/completions",
            headers=headers,
            json=payload,
            timeout=30
        )
        
        if response.status_code == 200:
            data = response.json()
            choices = data.get("choices", [])
            if choices:
                return True
        return False
    except Exception:
        return False


def main():
    base_url = "http://127.0.0.1:8000"
    api_key = "test-key"
    
    # List of models from config
    models = [
        "qwen3.5-plus",
        "qwen3-coder-plus",
        "qwen3-coder-next",
        "qwen3-coder-flash",
        "qwen-turbo",
        "qwen-plus",
        "qwen-max",
        "qwen2.5-72b-instruct",
        "qwen2.5-32b-instruct",
        "qwen2.5-14b-instruct",
        "qwen2.5-7b-instruct",
    ]
    
    safe_print("=" * 70)
    safe_print("Testing all qwen-oauth models for functionality")
    safe_print("=" * 70)
    
    working_models = []
    failed_models = []
    
    for i, model in enumerate(models, 1):
        safe_print(f"\n{i}/{len(models)}. Testing model: {model}")
        if test_model(base_url, api_key, model):
            safe_print("   [OK] Model is functional")
            working_models.append(model)
        else:
            safe_print("   [FAIL] Model failed or not available")
            failed_models.append(model)
    
    safe_print("\n" + "=" * 70)
    safe_print("SUMMARY")
    safe_print("=" * 70)
    safe_print(f"Working models ({len(working_models)}/{len(models)}):")
    for m in working_models:
        safe_print(f"  - {m}")
    
    if failed_models:
        safe_print(f"\nFailed/Unavailable models ({len(failed_models)}/{len(models)}):")
        for m in failed_models:
            safe_print(f"  - {m}")
    
    safe_print("=" * 70)
    
    return 0 if len(working_models) > 0 else 1


if __name__ == "__main__":
    sys.exit(main())
