#!/usr/bin/env python
"""Replay exact proxy request shape against ZAI to find what triggers 429.

Usage:
  ./.venv/Scripts/python.exe dev/scripts/zai_proxy_replay_probe.py --api-key <key>
"""

from __future__ import annotations

import argparse
import json
import os
from typing import Any

import httpx


def _kilo_headers(api_key: str) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "Accept": "text/event-stream",
        "User-Agent": "Kilo-Code/4.111.0",
        "Referer": "https://kilocode.ai",
        "Origin": "https://kilocode.ai",
        "HTTP-Referer": "https://kilocode.ai",
        "X-Title": "Kilo Code",
        "X-KiloCode-Version": "4.111.0",
    }


def _build_tools(count: int) -> list[dict[str, Any]]:
    tools: list[dict[str, Any]] = []
    for idx in range(count):
        tools.append(
            {
                "type": "function",
                "function": {
                    "name": f"tool_{idx}",
                    "description": f"Synthetic probe tool #{idx}",
                    "parameters": {
                        "type": "object",
                        "properties": {"query": {"type": "string"}},
                        "required": ["query"],
                    },
                },
            }
        )
    return tools


def _make_cases(api_key: str, model: str) -> list[tuple[str, dict[str, Any]]]:
    """Build request shapes that progressively add proxy-specific fields."""
    base_messages = [
        {"role": "system", "content": "You are a concise coding assistant."},
        {"role": "user", "content": "Reply with: ok"},
    ]

    # Case 0: Minimal (known good)
    minimal = {
        "model": model,
        "messages": base_messages,
        "max_tokens": 128,
        "stream": True,
    }

    # Case 1: Add null fields the proxy injects
    with_null_fields = {
        "model": model,
        "messages": base_messages,
        "max_tokens": 128,
        "stream": True,
        "audio": None,
        "frequency_penalty": None,
        "generation_config": None,
        "logit_bias": None,
        "logprobs": None,
        "max_completion_tokens": None,
    }

    # Case 2: Add agent field
    with_agent = {
        **with_null_fields,
        "agent": "opencode/1.2.26 ai-sdk/provider-utils/3.0.20 runtime/bun/1.3.10",
    }

    # Case 3: Add extra_body
    with_extra_body = {
        **with_agent,
        "extra_body": {
            "backend_type": "zai-coding-plan",
            "model": model,
            "session_id": "replay-probe-session",
        },
    }

    # Case 4: Full proxy shape with 16 tools (70KB-ish)
    full_proxy = {
        **with_extra_body,
        "messages": [
            {"role": "system", "content": "OPENCODE_RULES " * 5000},
            {"role": "user", "content": "Return: ok"},
        ],
        "max_tokens": 32000,
        "tools": _build_tools(16),
        "tool_choice": "auto",
    }

    # Case 5: Full proxy shape but WITHOUT extra_body
    full_no_extra = {k: v for k, v in full_proxy.items() if k != "extra_body"}

    # Case 6: Full proxy shape but WITHOUT agent
    full_no_agent = {k: v for k, v in full_proxy.items() if k != "agent"}

    # Case 7: Full proxy shape but WITHOUT null fields
    full_no_nulls = {
        "model": model,
        "messages": full_proxy["messages"],
        "max_tokens": 32000,
        "stream": True,
        "tools": full_proxy["tools"],
        "tool_choice": "auto",
        "agent": full_proxy["agent"],
        "extra_body": full_proxy["extra_body"],
    }

    return [
        ("0_minimal", minimal),
        ("1_null_fields", with_null_fields),
        ("2_with_agent", with_agent),
        ("3_with_extra_body", with_extra_body),
        ("4_full_proxy", full_proxy),
        ("5_full_no_extra_body", full_no_extra),
        ("6_full_no_agent", full_no_agent),
        ("7_full_no_nulls", full_no_nulls),
    ]


def _run_case(
    client: httpx.Client, url: str, headers: dict[str, str], name: str, payload: dict
) -> dict[str, Any]:
    chunks: list[str] = []
    total_bytes = 0
    status_code = 0
    response_headers: dict[str, str | None] = {}
    error_text: str | None = None

    try:
        with client.stream("POST", url, headers=headers, json=payload) as response:
            status_code = response.status_code
            response_headers = {
                "content-type": response.headers.get("content-type"),
                "retry-after": response.headers.get("retry-after"),
            }
            for idx, chunk in enumerate(response.iter_bytes()):
                total_bytes += len(chunk)
                if idx < 3:
                    chunks.append(chunk.decode("utf-8", errors="replace")[:200])
    except Exception as exc:
        error_text = str(exc)

    return {
        "case": name,
        "status": status_code,
        "response_headers": response_headers,
        "request_bytes": len(json.dumps(payload, ensure_ascii=False)),
        "stream_total_bytes": total_bytes,
        "stream_first_chunks": chunks,
        "error": error_text,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Replay proxy request shape to ZAI")
    parser.add_argument("--api-key", default=os.getenv("ZAI_API_KEY"))
    parser.add_argument("--model", default="glm-4.7")
    parser.add_argument("--base-url", default="https://api.z.ai/api/coding/paas/v4")
    args = parser.parse_args()

    if not args.api_key:
        raise SystemExit("Missing API key: set --api-key or ZAI_API_KEY env var")

    url = f"{args.base_url.rstrip('/')}/chat/completions"
    headers = _kilo_headers(args.api_key)
    cases = _make_cases(args.api_key, args.model)

    with httpx.Client(timeout=60.0) as client:
        results = [
            _run_case(client, url, headers, name, payload) for name, payload in cases
        ]

    print(json.dumps({"url": url, "model": args.model, "results": results}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
