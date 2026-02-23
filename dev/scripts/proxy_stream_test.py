#!/usr/bin/env python
"""Stream a chat.completions request against the local proxy.

Intended for reproducing client-visible streaming issues (tool calls, early
disconnect, status codes) while capturing traffic via the proxy's CBOR capture.
"""

from __future__ import annotations

import argparse
import time
from typing import Any

import httpx


def _iter_sse_lines(resp: httpx.Response) -> Any:
    """Yield decoded SSE lines (best-effort).

    httpx exposes bytes via iter_bytes(); we decode as UTF-8 with replacement.
    """
    buf = ""
    for b in resp.iter_bytes():
        if not b:
            continue
        buf += b.decode("utf-8", errors="replace")
        while "\n" in buf:
            line, buf = buf.split("\n", 1)
            yield line
    if buf:
        yield buf


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--base-url",
        default="http://127.0.0.1:8000",
        help="Proxy base URL (default: http://127.0.0.1:8000)",
    )
    parser.add_argument(
        "--model",
        default="nvidia/nemotron-3-nano-30b-a3b:free",
        help="Model name to request",
    )
    parser.add_argument(
        "--prompt",
        default="Say 'hello' in one sentence.",
        help="User prompt",
    )
    parser.add_argument(
        "--with-tools",
        action="store_true",
        help="Include a simple function tool and request a tool call.",
    )
    parser.add_argument(
        "--stop-after-lines",
        type=int,
        default=0,
        help="If >0, stop reading after N SSE lines (simulates client disconnect).",
    )
    args = parser.parse_args()

    messages: list[dict[str, Any]] = [
        {"role": "system", "content": "You are a concise assistant."},
        {"role": "user", "content": args.prompt},
    ]

    payload: dict[str, Any] = {
        "model": args.model,
        "messages": messages,
        "stream": True,
    }

    if args.with_tools:
        payload["tools"] = [
            {
                "type": "function",
                "function": {
                    "name": "echo",
                    "description": "Echo back the provided text.",
                    "parameters": {
                        "type": "object",
                        "properties": {"text": {"type": "string"}},
                        "required": ["text"],
                        "additionalProperties": False,
                    },
                },
            }
        ]
        payload["tool_choice"] = "auto"
        # Nudge the model to actually emit a tool call.
        payload["messages"][1][
            "content"
        ] = "Call the tool echo with text='ping' and do not answer directly."

    headers = {"Authorization": "Bearer test-placeholder"}
    t0 = time.time()
    line_count = 0

    with (
        httpx.Client(base_url=args.base_url, timeout=None) as client,
        client.stream(
            "POST",
            "/v1/chat/completions",
            json=payload,
            headers=headers,
        ) as resp,
    ):
        print("status", resp.status_code)
        print("x-request-id", resp.headers.get("x-request-id"))
        if resp.status_code != 200:
            body = resp.read()
            print("non-200 body (first 500 bytes)")
            print(body[:500])
            return 1

        for line in _iter_sse_lines(resp):
            if not line:
                continue
            line_count += 1
            print(line)
            if "data: [DONE]" in line:
                break
            if args.stop_after_lines and line_count >= args.stop_after_lines:
                break

    dt = time.time() - t0
    print(f"done after {dt:.2f}s, lines={line_count}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
