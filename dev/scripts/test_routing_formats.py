#!/usr/bin/env python3
"""Test routing string formats for qwen-oauth."""

import sys

import requests


def safe_print(msg: str):
    try:
        print(msg)
    except UnicodeEncodeError:
        print(msg.replace("✓", "[OK]").replace("✗", "[FAIL]"))


def test_routing(base_url: str, api_key: str, routing_string: str) -> tuple[bool, str]:
    """Test a specific routing string."""
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {api_key}"
    }
    
    payload = {
        "model": routing_string,
        "messages": [
            {"role": "user", "content": "Say 'OK'"}
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
            return True, "Success"
        else:
            try:
                error = response.json()
                return False, f"HTTP {response.status_code}: {error.get('message', response.text[:100])}"
            except:
                return False, f"HTTP {response.status_code}: {response.text[:100]}"
    except Exception as e:
        return False, str(e)


def main():
    base_url = "http://127.0.0.1:8000"
    api_key = "test-key"
    
    # Test different routing formats
    test_cases = [
        ("qwen-coder:coder-model", "Wrong backend name (expected to fail)"),
        ("qwen-oauth:coder-model", "Backend prefix + model"),
        ("qwen-oauth:qwen/coder-model", "Backend prefix + vendor prefix + model"),
        ("qwen-oauth:alibaba/coder-model", "Backend prefix + alibaba vendor + model"),
        ("qwen-oauth:tongyi/coder-model", "Backend prefix + tongyi vendor + model"),
        ("coder-model", "Just model name (no backend)"),
    ]
    
    safe_print("=" * 70)
    safe_print("Testing qwen-oauth routing string formats")
    safe_print("=" * 70)
    
    for routing, description in test_cases:
        safe_print(f"\nTesting: {routing}")
        safe_print(f"Format: {description}")
        success, result = test_routing(base_url, api_key, routing)
        if success:
            safe_print(f"Result: [OK] {result}")
        else:
            safe_print(f"Result: [FAIL] {result}")
    
    safe_print("\n" + "=" * 70)


if __name__ == "__main__":
    sys.exit(main())
