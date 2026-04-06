#!/usr/bin/env python
"""Verify that the ZAI connector always sends Kilo-Code fingerprint headers.

The ZAI coding plan gateway requires specific client identification headers
(Referer, Origin, X-Title, X-KiloCode-Version) to validate the subscription.
All requests, regardless of the actual client (OpenCode, Kilo-Code, etc.), must
use the Kilo-Code fingerprint to avoid 429 errors from unrecognized clients.
"""

from __future__ import annotations

import asyncio
import json
from unittest.mock import MagicMock

import httpx
from src.connectors.zai_coding_plan import ZaiCodingPlanBackend
from src.core.domain.chat import CanonicalChatRequest, ChatMessage
from src.core.domain.responses import ResponseEnvelope


async def test_opencode_request() -> dict:
    """Test OpenCode client gets Kilo-Code fingerprint (not minimal headers)."""
    captured: dict = {}

    class CapturingTransport(httpx.AsyncBaseTransport):
        async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
            captured["url"] = str(request.url)
            captured["headers"] = dict(request.headers)
            captured["body"] = json.loads(request.content)
            return httpx.Response(200, content=b'{"id":"test"}', request=request)

    transport = CapturingTransport()
    async with httpx.AsyncClient(transport=transport) as client:
        backend = ZaiCodingPlanBackend(
            client=client,
            config=MagicMock(),
            translation_service=MagicMock(),
        )
        backend.api_key = "test-key"
        backend.api_base_url = "https://api.z.ai/api/coding/paas/v4"
        backend.available_models = ["glm-4.7"]
        backend._provider_models = {"glm-4.7"}
        backend._model_discovery_succeeded = True
        backend._max_tokens_limit = 200000
        backend._default_max_tokens = 8192

        request = CanonicalChatRequest(
            model="glm-4.7",
            messages=[
                ChatMessage(role="system", content="test"),
                ChatMessage(role="user", content="hi"),
            ],
            max_tokens=64,
            stream=False,
            agent="opencode/1.2.26 ai-sdk/provider-utils/3.0.20",
        )

        # Mock _handle_non_streaming_response to avoid real network call
        async def mock_handle(url, payload, headers, session_id, context=None):
            captured["connector_url"] = url
            captured["connector_payload"] = payload
            captured["connector_headers"] = dict(headers) if headers else {}
            return ResponseEnvelope(
                content={"choices": [{"message": {"content": "ok", "role": "assistant"}}]},
                status_code=200, headers={}, usage=None,
            )

        backend._handle_non_streaming_response = mock_handle

        # Create ConnectorChatCompletionsRequest
        from src.connectors.contracts import ConnectorChatCompletionsRequest
        connector_request = ConnectorChatCompletionsRequest(
            request=request,
            processed_messages=request.messages,
            effective_model="glm-4.7",
            identity=None,
            cancellation_coordinator=None,
            cancellation_token=None,
            context=None,
            options={},
        )

        await backend.chat_completions(connector_request)

    return captured


async def test_kilocode_request() -> dict:
    """Test Kilo-Code client (no agent) gets full fingerprint."""
    captured: dict = {}

    class CapturingTransport(httpx.AsyncBaseTransport):
        async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
            captured["url"] = str(request.url)
            captured["headers"] = dict(request.headers)
            captured["body"] = json.loads(request.content)
            return httpx.Response(200, content=b'{"id":"test"}', request=request)

    transport = CapturingTransport()
    async with httpx.AsyncClient(transport=transport) as client:
        backend = ZaiCodingPlanBackend(
            client=client,
            config=MagicMock(),
            translation_service=MagicMock(),
        )
        backend.api_key = "test-key"
        backend.api_base_url = "https://api.z.ai/api/coding/paas/v4"
        backend.available_models = ["glm-4.7"]
        backend._provider_models = {"glm-4.7"}
        backend._model_discovery_succeeded = True
        backend._max_tokens_limit = 200000
        backend._default_max_tokens = 8192

        request = CanonicalChatRequest(
            model="glm-4.7",
            messages=[
                ChatMessage(role="system", content="test"),
                ChatMessage(role="user", content="hi"),
            ],
            max_tokens=64,
            stream=False,
            # NO agent field
        )

        async def mock_handle(url, payload, headers, session_id, context=None):
            captured["connector_url"] = url
            captured["connector_payload"] = payload
            captured["connector_headers"] = dict(headers) if headers else {}
            return ResponseEnvelope(
                content={"choices": [{"message": {"content": "ok", "role": "assistant"}}]},
                status_code=200, headers={}, usage=None,
            )

        backend._handle_non_streaming_response = mock_handle

        from src.connectors.contracts import ConnectorChatCompletionsRequest
        connector_request = ConnectorChatCompletionsRequest(
            request=request,
            processed_messages=request.messages,
            effective_model="glm-4.7",
            identity=None,
            cancellation_coordinator=None,
            cancellation_token=None,
            context=None,
            options={},
        )

        await backend.chat_completions(connector_request)

    return captured


def _check_kilo_headers(headers: dict[str, str], client_name: str) -> tuple[bool, list[str]]:
    """Verify full Kilo-Code fingerprint is present regardless of actual client."""
    issues: list[str] = []
    if headers.get("user-agent") != "Kilo-Code/4.111.0":
        issues.append(f"{client_name}: User-Agent should be 'Kilo-Code/4.111.0', got '{headers.get('user-agent', 'MISSING')}'")
    if "referer" not in headers:
        issues.append(f"{client_name}: Missing Referer header")
    if "origin" not in headers:
        issues.append(f"{client_name}: Missing Origin header")
    if "x-title" not in headers:
        issues.append(f"{client_name}: Missing X-Title header")
    if "x-kilocode-version" not in headers:
        issues.append(f"{client_name}: Missing X-KiloCode-Version header")
    if "x-llmproxy-loop-guard" in headers:
        issues.append(f"{client_name}: Unexpected x-llmproxy-loop-guard header")
    return (len(issues) == 0, issues)


async def main() -> int:
    print("=" * 70)
    print("ZAI CONNECTOR FINGERPRINT VERIFICATION (end-to-end)")
    print("=" * 70)
    print()

    all_pass = True

    for label, test_fn in [
        ("OpenCode client", test_opencode_request),
        ("Kilo-Code client", test_kilocode_request),
    ]:
        print(f"Testing {label}...")
        captured = await test_fn()
        headers = {k.lower(): v for k, v in captured.get("connector_headers", {}).items()}

        print(f"  User-Agent: {headers.get('user-agent', 'MISSING')}")
        print(f"  Has Referer: {'referer' in headers}")
        print(f"  Has Origin: {'origin' in headers}")
        print(f"  Has X-Title: {'x-title' in headers}")
        print(f"  Has X-KiloCode-Version: {'x-kilocode-version' in headers}")

        passed, issues = _check_kilo_headers(headers, label)
        if passed:
            print(f"  Result: PASS")
        else:
            all_pass = False
            for issue in issues:
                print(f"  Issue: {issue}")
            print(f"  Result: FAIL")
        print()

    print("=" * 70)
    if all_pass:
        print("ALL TESTS PASSED")
    else:
        print("SOME TESTS FAILED")
    print("=" * 70)
    return 0 if all_pass else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
