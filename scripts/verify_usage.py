"""
Quick sanity check to confirm usage tokens are delivered to clients.

This script uses the official OpenAI client pointed at the local proxy and
streams a simple request to the gemini-oauth-plan backend/model. It prints any
usage blocks observed in the stream so regressions in usage propagation are easy
to spot.
"""

from __future__ import annotations

import json
import os

from openai import OpenAI


def _get_env(var_name: str, default: str) -> str:
    value = os.getenv(var_name, default).strip()
    return value or default


def stream_and_print_usage() -> None:
    base_url = _get_env("LLM_PROXY_URL", "http://127.0.0.1:8000/v1")
    api_key = _get_env("LLM_PROXY_KEY", "dev-key")

    client = OpenAI(base_url=base_url, api_key=api_key, max_retries=0)

    print(f"Streaming from {base_url} using model gemini-oauth-plan:gemini-2.5-pro")
    usage_seen = False

    # Stream the completion and inspect chunks for usage data.
    stream = client.chat.completions.create(
        model="gemini-oauth-plan:gemini-2.5-pro",
        messages=[
            {"role": "system", "content": "Return a short greeting."},
            {"role": "user", "content": "Hello!"},
        ],
        temperature=0,
        stream=True,
    )

    for chunk in stream:
        # The SDK chunk is a Pydantic model; use model_dump to inspect its contents.
        payload = chunk.model_dump() if hasattr(chunk, "model_dump") else {}
        usage = payload.get("usage")
        if isinstance(usage, dict):
            usage_seen = True
            print("Usage chunk received:")
            print(json.dumps(usage, indent=2))
        else:
            choices = payload.get("choices") or []
            if choices:
                finish = choices[0].get("finish_reason")
                if finish:
                    print(f"Finish chunk received (finish_reason={finish})")
                print(f"Finish chunk received (finish_reason={finish})")

    if not usage_seen:
        raise SystemExit("No usage data observed in stream (regression suspected)")


if __name__ == "__main__":
    stream_and_print_usage()
