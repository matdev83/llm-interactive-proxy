#!/usr/bin/env python
"""
Quick check of the local proxy with OpenAI-compatible client.
"""

from __future__ import annotations


def main() -> None:
    import httpx

    request_payload = {
        "model": "glm-4.6",
        "messages": [
            {"role": "system", "content": "You are a concise assistant."},
            {"role": "user", "content": "Return the string `ok` and nothing else."},
        ],
        "stream": False,
    }
    with httpx.Client(base_url="http://127.0.0.1:8000") as client_raw:
        resp = client_raw.post(
            "/v1/chat/completions",
            json=request_payload,
            headers={"Authorization": "Bearer test-placeholder"},
        )
        print("status", resp.status_code)
        print("headers", resp.headers)
        print("body bytes", resp.content[:200])


if __name__ == "__main__":
    main()
