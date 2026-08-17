"""Smoke client for early-session verbosity bump against a live proxy.

Sends Chat Completions to openai-codex:gpt-5.4-mini with temperature=0.2 and
verbosity=low in both URI and body. Early-session bump should force outbound
temperature=1 and verbosity=high (verified via CBOR after this script runs).
"""

from __future__ import annotations

import json
import sys
import time
import uuid
from typing import Any

import httpx

BASE = "http://127.0.0.1:8791"
MODEL = "openai-codex:gpt-5.4-mini?temperature=0.2&verbosity=low"
SESSION_ID = f"early-bump-smoke-{uuid.uuid4().hex[:12]}"


def wait_ready(timeout: float = 90.0) -> None:
    deadline = time.time() + timeout
    last_err: Exception | None = None
    while time.time() < deadline:
        try:
            r = httpx.get(f"{BASE}/health", timeout=2.0)
            if r.status_code < 500:
                print(f"proxy ready: status={r.status_code}")
                return
        except Exception as exc:  # - smoke wait loop
            last_err = exc
        time.sleep(0.5)
    raise RuntimeError(f"proxy not ready within {timeout}s: {last_err}")


def chat(prompt: str, turn: int) -> dict[str, Any]:
    payload = {
        "model": MODEL,
        "messages": [{"role": "user", "content": prompt}],
        "stream": False,
        "temperature": 0.2,
        "verbosity": "low",
    }
    headers = {
        "Content-Type": "application/json",
        "X-Session-ID": SESSION_ID,
    }
    print(f"\n=== turn {turn} ===")
    print(f"session={SESSION_ID}")
    print(f"model={MODEL}")
    print(f"client body temperature={payload['temperature']} verbosity={payload['verbosity']}")
    with httpx.Client(timeout=180.0) as client:
        resp = client.post(f"{BASE}/v1/chat/completions", headers=headers, json=payload)
    print(f"http_status={resp.status_code}")
    try:
        data = resp.json()
    except Exception:
        print(resp.text[:2000])
        raise
    if resp.status_code >= 400:
        print(json.dumps(data, indent=2)[:3000])
        raise RuntimeError(f"chat failed: {resp.status_code}")
    content = ""
    choices = data.get("choices") or []
    if choices:
        msg = choices[0].get("message") or {}
        content = str(msg.get("content") or "")
    print(f"assistant_preview={content[:240]!r}")
    usage = data.get("usage")
    if usage:
        print(f"usage={usage}")
    return data


def main() -> int:
    wait_ready()
    chat("Reply with exactly one word: ping", turn=1)
    chat("Reply with exactly one word: pong", turn=2)
    print(f"\nSESSION_ID={SESSION_ID}")
    print("Done. Inspect CBOR under var/wire_captures_cbor/early_bump_smoke/")
    return 0


if __name__ == "__main__":
    sys.exit(main())
