#!/usr/bin/env python3
"""Test coder-model alias for qwen-oauth."""

import sys

import requests


def safe_print(msg: str):
    """Print message handling encoding issues on Windows."""
    try:
        print(msg)
    except UnicodeEncodeError:
        msg = msg.replace("✓", "[OK]").replace("✗", "[FAIL]").replace("⚠", "[WARN]")
        print(msg)


def test_model(base_url: str, api_key: str, model: str) -> tuple[bool, str]:
    """Test a single model and return status with response info."""
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
            return True, "OK"
        else:
            try:
                error = response.json()
                return False, f"HTTP {response.status_code}: {error.get('detail', response.text[:100])}"
            except:
                return False, f"HTTP {response.status_code}: {response.text[:100]}"
    except Exception as e:
        return False, str(e)


def main():
    base_url = "http://127.0.0.1:8000"
    api_key = "test-key"
    
    # Test various model aliases
    models_to_test = [
        ("coder-model", "Potential alias for latest coder model"),
        ("qwen3.5-plus", "Latest Qwen3.5 model"),
        ("qwen3-coder-plus", "Known working model"),
        ("default", "Default model alias"),
        ("latest", "Latest model alias"),
        ("qwen-coder", "Generic coder alias"),
    ]
    
    safe_print("=" * 70)
    safe_print("Testing qwen-oauth model aliases")
    safe_print("=" * 70)
    
    for model, description in models_to_test:
        safe_print(f"\nTesting: {model}")
        safe_print(f"Description: {description}")
        success, info = test_model(base_url, api_key, model)
        if success:
            safe_print("Result: [OK] Functional")
        else:
            safe_print(f"Result: [FAIL] {info}")
    
    safe_print("\n" + "=" * 70)


if __name__ == "__main__":
    sys.exit(main())
