#!/usr/bin/env python
"""Direct ZAI API probe - bypasses the proxy entirely.

Tests whether the ZAI coding plan API accepts requests with the exact
same fingerprint headers the proxy sends, or if the account itself is
rate-limited / blocked.
"""

import os
import sys
import time

import httpx

API_KEY = os.environ.get("ZAI_API_KEY", "")
API_URL = "https://api.z.ai/api/coding/paas/v4/chat/completions"

KILO_CODE_HEADERS = {
    "Authorization": f"Bearer {API_KEY}",
    "Content-Type": "application/json",
    "User-Agent": "Kilo-Code/4.111.0",
    "Referer": "https://kilocode.ai",
    "Origin": "https://kilocode.ai",
    "HTTP-Referer": "https://kilocode.ai",
    "X-Title": "Kilo Code",
    "X-KiloCode-Version": "4.111.0",
}

MINIMAL_PAYLOAD = {
    "model": "glm-4.7",
    "stream": True,
    "max_tokens": 64,
    "messages": [
        {"role": "user", "content": "Say hello in one word."},
    ],
}


def probe(headers: dict, payload: dict, label: str) -> None:
    print(f"\n{'='*60}")
    print(f"PROBE: {label}")
    print(f"{'='*60}")
    print(f"URL: {API_URL}")
    print(f"Headers (non-auth):")
    for k, v in headers.items():
        if k.lower() != "authorization":
            print(f"  {k}: {v}")
        else:
            print(f"  {k}: Bearer {v[:8]}...{v[-6:]}")
    print(f"Payload: model={payload.get('model')}, messages={len(payload.get('messages', []))}")
    print()

    with httpx.Client(timeout=30.0, http2=False) as client:
        try:
            start = time.time()
            resp = client.post(API_URL, headers=headers, json=payload)
            elapsed = time.time() - start
            print(f"Status: {resp.status_code}")
            print(f"Elapsed: {elapsed:.2f}s")
            print(f"Response headers:")
            for k, v in resp.headers.items():
                print(f"  {k}: {v}")
            print(f"Response body (first 1000 chars):")
            body = resp.text[:1000]
            print(f"  {body}")
        except Exception as e:
            print(f"ERROR: {e}")


def main():
    if not API_KEY:
        print("ERROR: ZAI_API_KEY not set", file=sys.stderr)
        sys.exit(1)

    print(f"API Key: {API_KEY[:8]}...{API_KEY[-6:]}")

    # Test 1: Kilo-Code fingerprint with minimal payload (no tools)
    probe(KILO_CODE_HEADERS, MINIMAL_PAYLOAD, "Kilo-Code fingerprint, minimal payload")

    time.sleep(2)

    # Test 2: Kilo-Code fingerprint with tools payload (like the proxy sends)
    tools_payload = {
        "model": "glm-4.7",
        "stream": True,
        "max_tokens": 1024,
        "messages": [
            {"role": "system", "content": "You are a helpful assistant."},
            {"role": "user", "content": "List files in current directory."},
        ],
        "tools": [
            {
                "type": "function",
                "function": {
                    "name": "bash",
                    "description": "Execute a command",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "command": {"type": "string", "description": "The command"},
                        },
                        "required": ["command"],
                    },
                },
            }
        ],
        "tool_choice": "auto",
    }
    probe(KILO_CODE_HEADERS, tools_payload, "Kilo-Code fingerprint, tools payload")

    time.sleep(2)

    # Test 3: Bare minimum (just auth + content-type)
    bare_headers = {
        "Authorization": f"Bearer {API_KEY}",
        "Content-Type": "application/json",
    }
    probe(bare_headers, MINIMAL_PAYLOAD, "Bare minimum headers")

    time.sleep(2)

    # Test 4: Non-streaming request
    non_stream_payload = dict(MINIMAL_PAYLOAD, stream=False)
    probe(KILO_CODE_HEADERS, non_stream_payload, "Kilo-Code, non-streaming")


if __name__ == "__main__":
    main()
