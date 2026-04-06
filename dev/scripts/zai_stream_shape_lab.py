#!/usr/bin/env python
"""Probe ZAI coding-plan streaming behavior across request shapes.

This is intentionally standalone (no proxy internals) to isolate payload/headers
that may produce empty HTTP 200 streams.
"""

from __future__ import annotations

import argparse
import json
import os
from dataclasses import dataclass
from typing import Any

import httpx


@dataclass(frozen=True)
class ProbeCase:
    name: str
    payload: dict[str, Any]


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
                        "properties": {
                            "query": {"type": "string"},
                        },
                        "required": ["query"],
                    },
                },
            }
        )
    return tools


def _make_cases(model: str) -> list[ProbeCase]:
    base_messages = [
        {"role": "system", "content": "You are a concise coding assistant."},
        {"role": "user", "content": "Reply with exactly: ok"},
    ]
    base = {
        "model": model,
        "messages": base_messages,
        "max_tokens": 128,
        "stream": True,
    }

    proxy_noise = {
        **base,
        "agent": "opencode/1.2.26 ai-sdk/provider-utils/3.0.20 runtime/bun/1.3.10",
        "audio": None,
        "extra_body": {
            "backend_type": "zai-coding-plan",
            "model": model,
            "session_id": "shape-lab-session",
        },
        "frequency_penalty": None,
        "logit_bias": None,
        "logprobs": None,
        "max_completion_tokens": None,
    }

    with_one_tool = {
        **base,
        "tools": _build_tools(1),
        "tool_choice": "auto",
    }

    with_many_tools = {
        **base,
        "tools": _build_tools(16),
        "tool_choice": "auto",
    }

    huge_system_prompt = "OPENCODE_RULES " * 5000
    with_huge_system_and_tools = {
        **with_many_tools,
        "messages": [
            {"role": "system", "content": huge_system_prompt},
            {"role": "user", "content": "Return: ok"},
        ],
        "max_tokens": 32000,
    }

    return [
        ProbeCase("minimal_stream", base),
        ProbeCase("proxy_noise_fields", proxy_noise),
        ProbeCase("with_one_tool", with_one_tool),
        ProbeCase("with_many_tools_16", with_many_tools),
        ProbeCase("huge_system_plus_tools", with_huge_system_and_tools),
    ]


def _run_case(
    client: httpx.Client, url: str, headers: dict[str, str], case: ProbeCase
) -> dict[str, Any]:
    chunks: list[str] = []
    total_bytes = 0
    status_code = 0
    response_headers: dict[str, str | None] = {}
    error_text: str | None = None

    try:
        with client.stream("POST", url, headers=headers, json=case.payload) as response:
            status_code = response.status_code
            response_headers = {
                "content-type": response.headers.get("content-type"),
                "retry-after": response.headers.get("retry-after"),
            }
            for idx, chunk in enumerate(response.iter_bytes()):
                total_bytes += len(chunk)
                if idx < 5:
                    chunks.append(chunk.decode("utf-8", errors="replace")[:300])
    except Exception as exc:
        error_text = str(exc)

    return {
        "case": case.name,
        "status": status_code,
        "response_headers": response_headers,
        "request_bytes": len(json.dumps(case.payload, ensure_ascii=False)),
        "stream_total_bytes": total_bytes,
        "stream_first_chunks": chunks,
        "error": error_text,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="ZAI stream request-shape lab")
    parser.add_argument("--api-key", default=os.getenv("ZAI_API_KEY"))
    parser.add_argument("--model", default="glm-5.1")
    parser.add_argument("--base-url", default="https://api.z.ai/api/coding/paas/v4")
    args = parser.parse_args()

    if not args.api_key:
        raise SystemExit("Missing API key: set --api-key or ZAI_API_KEY env var")

    url = f"{args.base_url.rstrip('/')}/chat/completions"
    headers = _kilo_headers(args.api_key)
    cases = _make_cases(args.model)

    with httpx.Client(timeout=60.0) as client:
        results = [_run_case(client, url, headers, case) for case in cases]

    print(json.dumps({"url": url, "model": args.model, "results": results}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
