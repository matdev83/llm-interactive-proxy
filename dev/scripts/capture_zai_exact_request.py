#!/usr/bin/env python
"""Capture the exact HTTP request the ZAI connector sends vs raw httpx.

This script runs a side-by-side comparison:
1. Raw httpx request (known to work)
2. ZAI connector request (gets 429)

Both use the SAME headers and payload to isolate the difference.

Usage:
    ./.venv/Scripts/python.exe dev/scripts/capture_zai_exact_request.py --api-key <key>
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
from collections.abc import Awaitable, Callable
from typing import Any
from unittest.mock import MagicMock

import httpx
from src.connectors.zai_coding_plan import ZaiCodingPlanBackend
from src.core.domain.chat import CanonicalChatRequest, ChatMessage

CapturedRequest = dict[str, Any]


async def _capture_connector_request(
    api_key: str, model: str, base_url: str
) -> CapturedRequest:
    """Run the ZAI connector and capture the exact request it would send."""
    captured: CapturedRequest = {}

    class CapturingTransport(httpx.AsyncBaseTransport):
        async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
            captured["url"] = str(request.url)
            captured["method"] = request.method
            captured["headers"] = dict(request.headers)
            captured["body"] = json.loads(request.content)
            return httpx.Response(
                200,
                headers={"content-type": "application/json"},
                content=json.dumps({
                    "id": "test",
                    "object": "chat.completion",
                    "created": 0,
                    "model": model,
                    "choices": [{
                        "index": 0,
                        "message": {"role": "assistant", "content": "ok"},
                        "finish_reason": "stop",
                    }],
                    "usage": {"prompt_tokens": 10, "completion_tokens": 2, "total_tokens": 12},
                }).encode(),
                request=request,
            )

    transport = CapturingTransport()
    async with httpx.AsyncClient(transport=transport) as client:
        backend = ZaiCodingPlanBackend(
            client=client,
            config=MagicMock(),
            translation_service=MagicMock(),
        )
        backend.api_key = api_key
        backend.api_base_url = base_url
        backend.available_models = [model]
        backend._provider_models = {model}
        backend._model_discovery_succeeded = True
        backend._max_tokens_limit = 200000
        backend._default_max_tokens = 8192

        # Test with OpenCode agent (the problematic case)
        request = CanonicalChatRequest(
            model=model,
            messages=[
                ChatMessage(role="system", content="You are a concise assistant."),
                ChatMessage(role="user", content="Reply with: ok"),
            ],
            max_tokens=64,
            stream=False,
            agent="opencode/1.2.26 ai-sdk/provider-utils/3.0.20",
        )

        # Mock the parent's chat_completions to avoid actual network call
        # but still go through _prepare_payload and get_headers
        original_handle = backend._handle_non_streaming_response

        async def mock_handle(url, payload, headers, session_id, context=None):
            captured["connector_url"] = url
            captured["connector_payload"] = payload
            captured["connector_headers"] = dict(headers) if headers else {}
            # Return a fake response envelope
            from src.core.domain.responses import ResponseEnvelope
            return ResponseEnvelope(
                content={"choices": [{"message": {"content": "ok", "role": "assistant"}}]},
                status_code=200,
                headers={},
                usage=None,
            )

        backend._handle_non_streaming_response = mock_handle

        # This will go through the full connector pipeline
        await backend.chat_completions(request, [], model)

    return captured


def _raw_httpx_request(api_key: str, model: str, base_url: str) -> CapturedRequest:
    """Make a raw httpx request with the same shape as the connector would produce."""
    # Minimal payload (what ZAI expects)
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": "You are a concise assistant."},
            {"role": "user", "content": "Reply with: ok"},
        ],
        "max_tokens": 64,
        "stream": False,
    }

    # Minimal headers (known to work)
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "Accept": "application/json",
    }

    url = f"{base_url.rstrip('/')}/chat/completions"

    return {
        "url": url,
        "headers": headers,
        "payload": payload,
    }


def _normalize_headers_for_comparison(headers: dict[str, str]) -> dict[str, str]:
    """Normalize headers to lowercase keys for comparison."""
    return {k.lower(): v for k, v in headers.items()}


def _compare_requests(raw: CapturedRequest, connector: CapturedRequest) -> list[str]:
    """Find differences between raw and connector requests."""
    diffs: list[str] = []

    # Compare payload keys
    raw_payload_keys = set(raw.get("payload", {}).keys())
    connector_payload_keys = set(connector.get("connector_payload", {}).keys())

    extra_in_connector = connector_payload_keys - raw_payload_keys
    missing_in_connector = raw_payload_keys - connector_payload_keys

    if extra_in_connector:
        diffs.append(f"Connector has extra payload keys: {sorted(extra_in_connector)}")
    if missing_in_connector:
        diffs.append(f"Connector missing payload keys: {sorted(missing_in_connector)}")

    # Compare payload values for common keys
    common_keys = raw_payload_keys & connector_payload_keys
    for key in sorted(common_keys):
        raw_val = raw["payload"][key]
        connector_val = connector["connector_payload"][key]
        if raw_val != connector_val:
            diffs.append(f"Payload key '{key}': raw={raw_val!r} vs connector={connector_val!r}")

    # Compare headers
    raw_headers = _normalize_headers_for_comparison(raw.get("headers", {}))
    connector_headers = _normalize_headers_for_comparison(connector.get("connector_headers", {}))

    extra_hdrs = set(connector_headers.keys()) - set(raw_headers.keys())
    missing_hdrs = set(raw_headers.keys()) - set(connector_headers.keys())

    if extra_hdrs:
        diffs.append(f"Connector has extra headers: {sorted(extra_hdrs)}")
    if missing_hdrs:
        diffs.append(f"Connector missing headers: {sorted(missing_hdrs)}")

    # Compare header values
    for key in sorted(set(raw_headers.keys()) & set(connector_headers.keys())):
        if raw_headers[key] != connector_headers[key]:
            # Redact auth headers
            if "auth" in key:
                raw_val = raw_headers[key][:15] + "..."
                conn_val = connector_headers[key][:15] + "..."
            else:
                raw_val = raw_headers[key]
                conn_val = connector_headers[key]
            diffs.append(f"Header '{key}': raw={raw_val!r} vs connector={conn_val!r}")

    return diffs


async def main() -> int:
    api_key = os.environ.get("ZAI_API_KEY")
    if not api_key:
        print("ERROR: Set ZAI_API_KEY env var or pass --api-key", file=sys.stderr)
        return 1

    model = "glm-4.7"
    base_url = "https://api.z.ai/api/coding/paas/v4"

    print("=" * 70)
    print("ZAI CONNECTOR EXACT REQUEST CAPTURE")
    print("=" * 70)
    print()

    # Capture connector request
    print("Capturing connector request...")
    connector = await _capture_connector_request(api_key, model, base_url)

    # Raw httpx request (known working shape)
    print("Building raw httpx request...")
    raw = _raw_httpx_request(api_key, model, base_url)

    print()
    print("-" * 70)
    print("RAW HTTPX REQUEST (known working shape)")
    print("-" * 70)
    print(f"URL: {raw['url']}")
    print(f"Payload keys: {sorted(raw['payload'].keys())}")
    print(f"Headers: {sorted(raw['headers'].keys())}")

    print()
    print("-" * 70)
    print("CONNECTOR REQUEST")
    print("-" * 70)
    print(f"URL: {connector.get('connector_url', 'N/A')}")
    print(f"Payload keys: {sorted(connector.get('connector_payload', {}).keys())}")
    print(f"Payload: {json.dumps(connector.get('connector_payload', {}), indent=2)}")
    print(f"Headers: {sorted(connector.get('connector_headers', {}).keys())}")

    print()
    print("-" * 70)
    print("DIFFERENCES")
    print("-" * 70)
    diffs = _compare_requests(raw, connector)
    if diffs:
        for diff in diffs:
            print(f"  ⚠️  {diff}")
    else:
        print("  ✅ No differences found - requests are identical!")

    print()
    print("=" * 70)
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
