#!/usr/bin/env python
"""
Minimal OpenAI-compatible client for testing ZAI Coding Plan access.

This script sends a simple non-streaming chat completion request directly
to https://api.z.ai/api/coding/paas/v4 using the provided API key.
"""

from __future__ import annotations

import sys

from openai import OpenAI


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")

    client = OpenAI(
        api_key="your-zai-api-key-here",
        base_url="https://api.z.ai/api/coding/paas/v4",
    )

    response = client.chat.completions.create(
        model="glm-4.6",
        messages=[
            {"role": "system", "content": "You are a concise assistant."},
            {"role": "user", "content": "Return the string `ok` and nothing else."},
        ],
        max_tokens=64,
        stream=False,
    )

    print(response.model_dump_json(indent=2))


if __name__ == "__main__":
    main()
