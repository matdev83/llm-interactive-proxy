#!/usr/bin/env python
"""
Probe the CommandCode gateway for its available model catalog.

Hits ``https://api.commandcode.ai/provider/v1/models`` directly so the slugs we
print are exactly the ones the ``commandcode-openai`` backend will accept.

Usage:

    ./.venv/Scripts/python.exe dev/scripts/probe_commandcode_models.py
    ./.venv/Scripts/python.exe dev/scripts/probe_commandcode_models.py --raw
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os

import httpx

MODELS_ENDPOINT = "https://api.commandcode.ai/provider/v1/models"
API_KEY_ENV = "COMMANDCODE_API_KEY"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Enumerate models exposed by the CommandCode gateway."
    )
    parser.add_argument(
        "--raw",
        action="store_true",
        help="Print the full raw JSON model listing response.",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=30.0,
        help="HTTP timeout in seconds (default: 30.0).",
    )
    return parser.parse_args()


async def async_main(args: argparse.Namespace) -> int:
    api_key = os.getenv(API_KEY_ENV)
    if not api_key:
        print(f"ERROR: {API_KEY_ENV} environment variable is not set.")
        return 2

    headers = {
        "Authorization": f"Bearer {api_key.strip()}",
        "Accept": "application/json",
    }

    async with httpx.AsyncClient(timeout=args.timeout) as client:
        response = await client.get(MODELS_ENDPOINT, headers=headers)
        print(f"GET {MODELS_ENDPOINT}")
        print(f"Status: {response.status_code} {response.reason_phrase}")
        print(
            "Response headers: " + json.dumps(dict(response.headers.items()), indent=2)
        )

        if response.status_code >= 400:
            print("\nError body:")
            print(response.text[:4000])
            return 1
        payload = response.json()

        if args.raw:
            print("\nRaw payload:")
            print(json.dumps(payload, indent=2))
            return 0

        data = payload.get("data", [])
        print(f"\nTotal models reported by gateway: {len(data)}")
        print("\nModel IDs (slugs usable with commandcode-openai):")
        for entry in data:
            if not isinstance(entry, dict):
                continue
            entry_id = entry.get("id")
            if not entry_id:
                continue
            owned_by = entry.get("owned_by") or entry.get("owner") or ""
            suffix = f"  [owner: {owned_by}]" if owned_by else ""
            print(f"- {entry_id}{suffix}")

        return 0


def main() -> None:
    args = parse_args()
    try:
        exit_code = asyncio.run(async_main(args))
    except KeyboardInterrupt:
        exit_code = 130
    raise SystemExit(exit_code)


if __name__ == "__main__":
    main()
