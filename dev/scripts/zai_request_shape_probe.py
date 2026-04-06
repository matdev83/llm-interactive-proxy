#!/usr/bin/env python
"""Probe ZAI coding-plan endpoint with multiple request header shapes.

Usage:
  ./.venv/Scripts/python.exe dev/scripts/zai_request_shape_probe.py --api-key <key>

Optional:
  --model glm-4.7
  --base-url https://api.z.ai/api/coding/paas/v4
"""

from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from typing import Any

import httpx


@dataclass(frozen=True)
class Case:
    name: str
    headers: dict[str, str]
    payload: dict[str, Any]


def _base_payload(model: str) -> dict[str, Any]:
    return {
        "model": model,
        "messages": [
            {"role": "system", "content": "You are a concise assistant."},
            {"role": "user", "content": "Reply with: ok"},
        ],
        "max_tokens": 64,
        "stream": False,
    }


def _make_cases(api_key: str, model: str) -> list[Case]:
    minimal_headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "Accept": "application/json",
    }
    kilo_headers = {
        **minimal_headers,
        "User-Agent": "Kilo-Code/4.111.0",
        "Referer": "https://kilocode.ai",
        "Origin": "https://kilocode.ai",
        "HTTP-Referer": "https://kilocode.ai",
        "X-Title": "Kilo Code",
        "X-KiloCode-Version": "4.111.0",
    }
    proxy_like_extra_headers = {
        **kilo_headers,
        "x-llmproxy-loop-guard": "1",
        "X-Session-ID": "shape-probe-session",
        "X-Request-ID": "shape-probe-request",
    }

    base_payload = _base_payload(model)
    low_token_payload = dict(base_payload)
    low_token_payload["max_tokens"] = 16

    return [
        Case(name="minimal", headers=minimal_headers, payload=base_payload),
        Case(name="kilo_fingerprint", headers=kilo_headers, payload=base_payload),
        Case(
            name="kilo_plus_proxy_headers",
            headers=proxy_like_extra_headers,
            payload=base_payload,
        ),
        Case(name="kilo_low_tokens", headers=kilo_headers, payload=low_token_payload),
    ]


def _run_case(client: httpx.Client, url: str, case: Case) -> dict[str, Any]:
    response = client.post(url, headers=case.headers, json=case.payload)
    result: dict[str, Any] = {
        "case": case.name,
        "status": response.status_code,
        "headers": {
            "retry-after": response.headers.get("retry-after"),
            "content-type": response.headers.get("content-type"),
        },
    }
    try:
        body = response.json()
    except Exception:
        body = response.text
    if isinstance(body, dict):
        error = body.get("error")
        if isinstance(error, dict):
            result["error"] = {
                "message": error.get("message"),
                "type": error.get("type"),
                "code": error.get("code"),
            }
        else:
            result["body"] = body
    else:
        result["body"] = str(body)[:500]
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description="Probe ZAI request-shape acceptance")
    parser.add_argument("--api-key", required=True, help="ZAI API key")
    parser.add_argument("--model", default="glm-4.7", help="Model name")
    parser.add_argument(
        "--base-url",
        default="https://api.z.ai/api/coding/paas/v4",
        help="ZAI coding-plan base URL",
    )
    args = parser.parse_args()

    url = f"{args.base_url.rstrip('/')}/chat/completions"
    cases = _make_cases(args.api_key, args.model)

    with httpx.Client(timeout=45.0) as client:
        results = [_run_case(client, url, case) for case in cases]

    print(json.dumps({"url": url, "results": results}, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
