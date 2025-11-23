"""Test that usage data flows correctly from Cline backend to client response."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest
from src.connectors.cline import ClineConnector
from src.core.config.app_config import AppConfig
from src.core.domain.chat import ChatMessage, ChatRequest
from src.core.services.translation_service import TranslationService
from src.core.transport.fastapi.response_adapters import to_fastapi_response


@pytest.mark.asyncio
async def test_cline_usage_data_in_client_response():
    """Test that usage data from Cline backend appears in the final client response."""
    # Arrange
    mock_client = AsyncMock(spec=httpx.AsyncClient)
    mock_config = MagicMock(spec=AppConfig)
    mock_config.backends = MagicMock()
    mock_config.backends.cline = None

    translation_service = TranslationService()

    connector = ClineConnector(
        client=mock_client,
        config=mock_config,
        translation_service=translation_service,
        name="cline",
    )

    # Set up connector state
    connector.api_key = "test_key"
    connector.api_base_url = "https://api.cline.bot/api/v1"
    connector._token_cache = {"idToken": "test_token", "expiresAt": 9999999999}
    connector._enable_cline_backend_debugging_override = True  # Bypass validation

    # Mock backend response with usage data
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.headers = {
        "content-type": "application/json",
        "x-request-id": "req-123",
    }
    mock_response.json.return_value = {
        "id": "chatcmpl-789",
        "object": "chat.completion",
        "created": 1234567890,
        "model": "gpt-4",
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": "Test response"},
                "finish_reason": "stop",
            }
        ],
        "usage": {
            "prompt_tokens": 25,
            "completion_tokens": 15,
            "total_tokens": 40,
        },
    }

    mock_client.post = AsyncMock(return_value=mock_response)

    request = ChatRequest(
        model="gpt-4",
        messages=[ChatMessage(role="user", content="Test message")],
        stream=False,
    )

    # Act - Get response from connector
    envelope = await connector.chat_completions(
        request_data=request,
        processed_messages=request.messages,
        effective_model="gpt-4",
        identity=None,
        incoming_headers={"User-Agent": "Cline VSCode Extension"},
    )

    # Convert to FastAPI response (simulating what happens in the controller)
    fastapi_response = to_fastapi_response(envelope)

    # Assert - Usage data should be in the response body
    import json

    response_body = json.loads(fastapi_response.body)

    assert "usage" in response_body
    assert response_body["usage"]["prompt_tokens"] == 25  # Preserved
    # completion_tokens will be recalculated based on actual content ("Test response" = ~2 tokens)
    assert response_body["usage"]["completion_tokens"] > 0
    assert (
        response_body["usage"]["total_tokens"]
        == response_body["usage"]["prompt_tokens"]
        + response_body["usage"]["completion_tokens"]
    )


@pytest.mark.asyncio
async def test_cline_usage_calculated_after_transformations():
    """Test that usage reflects the actual tokens sent/received, not pre-transformation counts."""
    # This test verifies that if the proxy modifies content, the usage should reflect
    # the actual content that was processed by the backend

    # Arrange
    mock_client = AsyncMock(spec=httpx.AsyncClient)
    mock_config = MagicMock(spec=AppConfig)
    mock_config.backends = MagicMock()
    mock_config.backends.cline = None

    translation_service = TranslationService()

    connector = ClineConnector(
        client=mock_client,
        config=mock_config,
        translation_service=translation_service,
        name="cline",
    )

    connector.api_key = "test_key"
    connector.api_base_url = "https://api.cline.bot/api/v1"
    connector._token_cache = {"idToken": "test_token", "expiresAt": 9999999999}

    # Mock response - the backend returns usage based on what IT processed
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.headers = {"content-type": "application/json"}
    mock_response.json.return_value = {
        "id": "chatcmpl-999",
        "object": "chat.completion",
        "created": 1234567890,
        "model": "gpt-4",
        "choices": [
            {
                "index": 0,
                "message": {
                    "role": "assistant",
                    "content": "Backend processed response",
                },
                "finish_reason": "stop",
            }
        ],
        # These usage numbers reflect what the backend actually processed
        "usage": {
            "prompt_tokens": 100,
            "completion_tokens": 50,
            "total_tokens": 150,
        },
    }

    mock_client.post = AsyncMock(return_value=mock_response)

    request = ChatRequest(
        model="gpt-4",
        messages=[ChatMessage(role="user", content="Original message")],
        stream=False,
    )

    # Act
    envelope = await connector.chat_completions(
        request_data=request,
        processed_messages=request.messages,
        effective_model="gpt-4",
        identity=None,
        incoming_headers={"User-Agent": "Cline VSCode Extension"},
    )

    # Assert - Usage should match what the backend reported (post-transformation)
    assert envelope.usage is not None
    assert envelope.usage["prompt_tokens"] == 100
    assert envelope.usage["completion_tokens"] == 50
    assert envelope.usage["total_tokens"] == 150

    # Verify it flows through to the client response
    # Note: Usage will be recalculated based on actual content
    fastapi_response = to_fastapi_response(envelope)
    import json

    response_body = json.loads(fastapi_response.body)

    assert response_body["usage"]["prompt_tokens"] == 100  # Preserved
    # completion_tokens will be recalculated based on actual content ("Backend processed response" = ~3 tokens)
    assert response_body["usage"]["completion_tokens"] > 0
    assert (
        response_body["usage"]["total_tokens"]
        == response_body["usage"]["prompt_tokens"]
        + response_body["usage"]["completion_tokens"]
    )
