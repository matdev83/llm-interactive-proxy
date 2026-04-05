#!/usr/bin/env python
"""Verify that the ZAI connector sends correct headers for BOTH client types."""

from __future__ import annotations

import asyncio
import json
from unittest.mock import AsyncMock, MagicMock

import httpx
from src.connectors.zai_coding_plan import ZaiCodingPlanBackend
from src.core.domain.chat import CanonicalChatRequest, ChatMessage
from src.core.domain.responses import ResponseEnvelope


async def test_opencode_request() -> dict:
    """Test OpenCode client gets minimal headers."""
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
            # NO agent field - defaults to Kilo-Code
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


async def main() -> int:
    print("=" * 70)
    print("ZAI CONNECTOR FINGERPRINT VERIFICATION (end-to-end)")
    print("=" * 70)
    print()

    # Test OpenCode
    print("Testing OpenCode request...")
    opencode = await test_opencode_request()
    opencode_headers = {k.lower(): v for k, v in opencode.get("connector_headers", {}).items()}
    print(f"  User-Agent: {opencode_headers.get('user-agent', 'MISSING')}")
    print(f"  Has Referer: {'referer' in opencode_headers}")
    print(f"  Has Origin: {'origin' in opencode_headers}")
    print(f"  Has X-Title: {'x-title' in opencode_headers}")
    print(f"  Has X-KiloCode-Version: {'x-kilocode-version' in opencode_headers}")

    opencode_pass = (
        opencode_headers.get("user-agent") == "opencode"
        and "referer" not in opencode_headers
        and "origin" not in opencode_headers
        and "x-title" not in opencode_headers
        and "x-kilocode-version" not in opencode_headers
    )
    print(f"  Result: {'✅ PASS' if opencode_pass else '❌ FAIL'}")
    print()

    # Test Kilo-Code
    print("Testing Kilo-Code request...")
    kilocode = await test_kilocode_request()
    kilocode_headers = {k.lower(): v for k, v in kilocode.get("connector_headers", {}).items()}
    print(f"  User-Agent: {kilocode_headers.get('user-agent', 'MISSING')}")
    print(f"  Has Referer: {'referer' in kilocode_headers}")
    print(f"  Has Origin: {'origin' in kilocode_headers}")
    print(f"  Has X-Title: {'x-title' in kilocode_headers}")
    print(f"  Has X-KiloCode-Version: {'x-kilocode-version' in kilocode_headers}")

    kilocode_pass = (
        kilocode_headers.get("user-agent") == "Kilo-Code/4.111.0"
        and "referer" in kilocode_headers
        and "origin" in kilocode_headers
        and "x-title" in kilocode_headers
        and "x-kilocode-version" in kilocode_headers
    )
    print(f"  Result: {'✅ PASS' if kilocode_pass else '❌ FAIL'}")
    print()

    print("=" * 70)
    if opencode_pass and kilocode_pass:
        print("ALL TESTS PASSED ✅")
        print("=" * 70)
        return 0
    else:
        print("SOME TESTS FAILED ❌")
        print("=" * 70)
        return 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
