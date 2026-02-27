#!/usr/bin/env python3
"""Test qwen-oauth models - ask what model they are."""

import sys

import requests


def safe_print(msg: str):
    try:
        print(msg)
    except UnicodeEncodeError:
        msg = msg.replace("✓", "[OK]").replace("✗", "[FAIL]").replace("⚠", "[WARN]")
        print(msg)


def test_model(base_url: str, api_key: str, model: str) -> tuple[bool, str]:
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {api_key}"
    }
    
    payload = {
        "model": f"qwen-oauth:{model}",
        "messages": [
            {"role": "user", "content": "What model are you? Answer with just the model name and version."}
        ],
        "max_tokens": 50
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
                content = choices[0].get("message", {}).get("content", "")
                return True, content
            return False, "No content in response"
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
    
    models_to_test = [
        "coder-model",
        "qwen-coder",
        "qwen3-coder-plus",
    ]
    
    safe_print("=" * 70)
    safe_print("Testing qwen-oauth models - asking for model identity")
    safe_print("=" * 70)
    
    for model in models_to_test:
        safe_print(f"\nTesting model: {model}")
        safe_print("-" * 40)
        success, response = test_model(base_url, api_key, model)
        if success:
            safe_print(f"[OK] Response: {response}")
        else:
            safe_print(f"[FAIL] {response}")
    
    safe_print("\n" + "=" * 70)


if __name__ == "__main__":
    sys.exit(main())
