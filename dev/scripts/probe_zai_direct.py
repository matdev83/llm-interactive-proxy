#!/usr/bin/env python
"""Direct ZAI API probe - bypasses the proxy entirely.

Tests whether the ZAI coding plan API accepts requests with the exact
same fingerprint headers the proxy sends, or if the account itself is
rate-limited / blocked.
"""

import argparse
import json
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


def build_minimal_payload(model: str, *, stream: bool = True) -> dict:
    return {
        "model": model,
        "stream": stream,
        "max_tokens": 64,
        "messages": [
            {"role": "user", "content": "Say hello in one word."},
        ],
    }


def build_proxy_shape_payload(model: str, *, stream: bool = True) -> dict:
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
    system_prompt = (
        "You are opencode, an interactive CLI tool that helps users with software "
        "engineering tasks. Use the instructions below and the tools available "
        "to you to assist the user. "
    ) * 20
    system_prompt += "X" * 50000
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": "What is 2+2?"},
        {
            "role": "assistant",
            "content": "4",
            "tool_calls": [
                {
                    "id": f"call_{i}",
                    "type": "function",
                    "function": {
                        "name": f"tool_{i}",
                        "arguments": json.dumps({"param": f"test_{i}"}),
                    },
                }
                for i in range(16)
            ],
        },
    ]
    messages.extend(
        [
            {"role": "tool", "content": "ok", "tool_call_id": f"call_{i}"}
            for i in range(16)
        ]
    )
    return {
        "model": model,
        "stream": stream,
        "max_tokens": 8192,
        "messages": messages,
        "tools": tools,
        "tool_choice": "auto",
    }


def probe(headers: dict, payload: dict, label: str) -> None:
    print(f"\n{'='*60}")
    print(f"PROBE: {label}")
    print(f"{'='*60}")
    print(f"URL: {API_URL}")
    print("Headers (non-auth):")
    for k, v in headers.items():
        if k.lower() != "authorization":
            print(f"  {k}: {v}")
        else:
            print(f"  {k}: Bearer {v[:8]}...{v[-6:]}")
    print(
        f"Payload: model={payload.get('model')}, messages={len(payload.get('messages', []))}"
    )
    print()

    with httpx.Client(timeout=30.0, http2=False) as client:
        try:
            start = time.time()
            resp = client.post(API_URL, headers=headers, json=payload)
            elapsed = time.time() - start
            print(f"Status: {resp.status_code}")
            print(f"Elapsed: {elapsed:.2f}s")
            print("Response headers:")
            for k, v in resp.headers.items():
                print(f"  {k}: {v}")
            print("Response body (first 1000 chars):")
            body = resp.text[:1000]
            print(f"  {body}")
        except Exception as e:
            print(f"ERROR: {e}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", default="glm-4.7")
    parser.add_argument(
        "--payload-shape",
        choices=("minimal", "proxy-shape"),
        default="minimal",
    )
    parser.add_argument("--stream", action="store_true")
    parser.add_argument("--non-stream", action="store_true")
    return parser.parse_args()


def main():
    args = parse_args()
    if not API_KEY:
        print("ERROR: ZAI_API_KEY not set", file=sys.stderr)
        sys.exit(1)

    print(f"API Key: {API_KEY[:8]}...{API_KEY[-6:]}")

    stream = True
    if args.non_stream:
        stream = False
    elif args.stream:
        stream = True

    if args.payload_shape == "proxy-shape":
        payload = build_proxy_shape_payload(args.model, stream=stream)
    else:
        payload = build_minimal_payload(args.model, stream=stream)

    probe(
        KILO_CODE_HEADERS,
        payload,
        f"Kilo-Code fingerprint, {args.payload_shape}, model={args.model}, stream={stream}",
    )


if __name__ == "__main__":
    main()
