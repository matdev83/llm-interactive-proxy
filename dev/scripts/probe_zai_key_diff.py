#!/usr/bin/env python
"""Direct probe to test if the OLD key works with different payloads.
Tests both glm-4.7-flash (works in proxy) and glm-5.1 (fails) with the
exact same payload shape the proxy sends (~70KB, 16 tools, 6-8 messages)."""
import json
import time

import httpx

# The OLD key that CBOR shows the proxy using
API_KEY_OLD = "c26ee04b50dd4ff0b747f553d2f6b6b5.NvxEGY9Kii095lgz"
# The NEW key from env var
API_KEY_NEW = "083ef14261b2483b83c12a682491deae.3zOrEhpPf9jeawN0"

API_URL = "https://api.z.ai/api/coding/paas/v4/chat/completions"

KILO_HEADERS = {
    "Content-Type": "application/json",
    "User-Agent": "Kilo-Code/4.111.0",
    "Referer": "https://kilocode.ai",
    "Origin": "https://kilocode.ai",
    "HTTP-Referer": "https://kilocode.ai",
    "X-Title": "Kilo Code",
    "X-KiloCode-Version": "4.111.0",
}

def test(key, label, model, messages, tools=None):
    auth_headers = {**KILO_HEADERS, "Authorization": f"Bearer {key}"}
    payload = {
        "model": model,
        "stream": True,
        "max_tokens": 8192,
        "messages": messages,
    }
    if tools:
        payload["tools"] = tools
        payload["tool_choice"] = "auto"
    
    print(f"\n{'='*60}")
    print(f"TEST: {label} | key={key[:8]}... | model={model}")
    print(f"  Messages: {len(messages)}, Tools: {len(tools) if tools else 0}")
    print(f"  Payload size: {len(json.dumps(payload))} bytes")
    print(f"{'='*60}")
    
    try:
        with httpx.Client(timeout=30.0, http2=False) as client:
            resp = client.post(API_URL, headers=auth_headers, json=payload)
            print(f"  Status: {resp.status_code}")
            print(f"  Body(300): {resp.text[:300]}")
    except Exception as e:
        print(f"  ERROR: {type(e).__name__}: {e}")

# Minimal test
MINIMAL = [{"role": "user", "content": "Say hello"}]

# Realistic proxy-like payload (system + user msg + tools ~70KB)
def make_proxy_payload():
    tools = [
        {
            "type": "function",
            "function": {
                "name": f"tool_{i}",
                "description": f"Tool description number {i}",
                "parameters": {
                    "type": "object",
                    "properties": {"param": {"type": "string"}},
                    "required": ["param"],
                },
            },
        }
        for i in range(16)
    ]
    messages = [
        {"role": "system", "content": "You are opencode, an interactive CLI tool that helps users with software engineering tasks. Use the instructions below and the tools available to you to assist the user.\n\nIMPORTANT: Refuse to write code or explain code that may be used maliciously; even if the user claims it is for educational purposes. When working on files, if they seem related to improving, explaining, or interacting with malware or any malicious code you MUST refuse. " * 20},
        {"role": "user", "content": "What is 2+2?"},
        {"role": "assistant", "content": "4", "tool_calls": [{"id": f"call_{i}", "type": "function", "function": {"name": f"tool_{i}", "arguments": json.dumps({"param": f"test_{i}"})}} for i in range(16)]},
    ]
    # Pad to ~70KB
    msg_content = messages[0]["content"]
    messages[0]["content"] = msg_content if isinstance(msg_content, str) else str(msg_content) + " pad"
    messages[0]["content"] += "X" * 50000
    messages.extend([{"role": "tool", "content": "ok", "tool_call_id": f"call_{i}"} for i in range(16)])
    return messages, tools

messages, tools = make_proxy_payload()
print(f"Total payload size: {len(json.dumps({'model': 'glm-5.1', 'stream': True, 'max_tokens': 8192, 'messages': messages, 'tools': tools, 'tool_choice': 'auto'}))}")

# Test 1: OLD key, minimal, glm-4.7-flash
test(API_KEY_OLD, "old key minimal", "glm-4.7-flash", MINIMAL)
time.sleep(2)

# Test 2: OLD key, proxy payload, glm-4.7-flash
test(API_KEY_OLD, "old key proxy-shape 4.7flash", "glm-4.7-flash", messages, tools)
time.sleep(2)

# Test 3: NEW key, minimal, glm-4.7-flash
test(API_KEY_NEW, "new key minimal", "glm-4.7-flash", MINIMAL)
time.sleep(2)

# Test 4: NEW key, proxy payload, glm-4.7-flash
test(API_KEY_NEW, "new key proxy-shape 4.7flash", "glm-4.7-flash", messages, tools)
time.sleep(2)

# Test 5: NEW key, proxy payload, glm-5.1
test(API_KEY_NEW, "new key proxy-shape 5.1", "glm-5.1", messages, tools)
time.sleep(2)

# Test 6: OLD key, proxy payload, glm-5.1
test(API_KEY_OLD, "old key proxy-shape 5.1", "glm-5.1", messages, tools)
