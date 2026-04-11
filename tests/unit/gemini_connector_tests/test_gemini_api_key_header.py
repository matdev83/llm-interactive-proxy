"""Regression test: Gemini backend must send x-goog-api-key header, not 'gemini'.

This test proves the fix for the 403 PERMISSION_DENIED error caused by the
GeminiInitializationStrategy setting key_name='gemini' (which was used as
the HTTP header name, sending 'gemini: <api_key>' instead of the correct
'x-goog-api-key: <api_key>' that the Gemini API expects).
"""

from __future__ import annotations

import httpx
import pytest
from src.connectors.contracts import (
    ConnectorChatCompletionsRequest,
    ConnectorRequestContext,
)
from src.connectors.gemini import GeminiBackend
from src.connectors.strategies.gemini import GeminiInitializationStrategy
from src.core.config.app_config import AppConfig
from src.core.domain.chat import CanonicalChatRequest, ChatMessage
from src.core.services.translation_service import TranslationService


def _make_gemini_connector_request(
    canonical_request: CanonicalChatRequest,
    effective_model: str,
) -> ConnectorChatCompletionsRequest:
    return ConnectorChatCompletionsRequest(
        request=canonical_request,
        processed_messages=list(canonical_request.messages),
        effective_model=effective_model,
        identity=None,
        cancellation_token=None,
        cancellation_coordinator=None,
        context=ConnectorRequestContext(
            request_id="req-test",
            session_id="sess-test",
            client_host="127.0.0.1",
            extensions={},
        ),
        options={},
    )


class TestGeminiApiKeyHeaderName:
    """Prove that the Gemini backend sends x-goog-api-key header."""

    def test_strategy_sets_x_goog_api_key_not_gemini(self) -> None:
        """GeminiInitializationStrategy must set key_name='x-goog-api-key'."""
        strategy = GeminiInitializationStrategy()
        config = {"api_key": "test-key"}
        result = strategy.augment_init_config(config)
        assert result["key_name"] == "x-goog-api-key", (
            f"Expected key_name='x-goog-api-key' but got '{result['key_name']}'. "
            "The Gemini API requires the 'x-goog-api-key' header name, not 'gemini'."
        )

    @pytest.mark.asyncio
    async def test_gemini_backend_sends_x_goog_api_key_header(self) -> None:
        """When initialized via strategy config, the backend must send the
        x-goog-api-key header (not a header named 'gemini')."""
        captured_headers: dict[str, str] = {}

        async def handler(request: httpx.Request) -> httpx.Response:
            captured_headers.update({k.lower(): v for k, v in request.headers.items()})
            return httpx.Response(
                status_code=200,
                json={
                    "candidates": [
                        {
                            "content": {
                                "parts": [{"text": "response"}],
                                "role": "model",
                            },
                            "finishReason": "STOP",
                        }
                    ],
                    "usageMetadata": {
                        "promptTokenCount": 1,
                        "candidatesTokenCount": 1,
                        "totalTokenCount": 2,
                    },
                },
            )

        transport = httpx.MockTransport(handler)

        async with httpx.AsyncClient(transport=transport) as client:
            backend = GeminiBackend(
                client=client,
                config=AppConfig(),
                translation_service=TranslationService(),
            )

            strategy = GeminiInitializationStrategy()
            init_config = strategy.augment_init_config(
                {
                    "api_key": "test-api-key-123",
                    "gemini_api_base_url": "https://generativelanguage.googleapis.com",
                }
            )
            await backend.initialize(**init_config)

            canonical_request = CanonicalChatRequest(
                model="gemini-2.0-flash",
                messages=[ChatMessage(role="user", content="hello")],
                stream=False,
            )

            await backend.chat_completions(
                _make_gemini_connector_request(canonical_request, "gemini-2.0-flash")
            )

        assert "x-goog-api-key" in captured_headers, (
            f"Header 'x-goog-api-key' not found in request headers. "
            f"Available headers: {list(captured_headers.keys())}. "
            "The Gemini API requires 'x-goog-api-key' header for authentication."
        )
        assert captured_headers["x-goog-api-key"] == "test-api-key-123", (
            f"Expected API key 'test-api-key-123' under 'x-goog-api-key' header, "
            f"but got '{captured_headers['x-goog-api-key']}'."
        )
        assert "gemini" not in captured_headers, (
            "Found unexpected 'gemini' header in request. "
            "The old key_name='gemini' caused a 403 PERMISSION_DENIED error "
            "because 'gemini' is not a recognized Gemini API authentication header."
        )
