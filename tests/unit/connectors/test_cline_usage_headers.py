"""Test that Cline connector properly forwards usage headers for token tracking."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest
from src.connectors.cline import ClineConnector
from src.core.config.app_config import AppConfig
from src.core.domain.chat import ChatMessage, ChatRequest
from src.core.domain.responses import ResponseEnvelope
from src.core.services.translation_service import TranslationService


@pytest.mark.asyncio
async def test_cline_non_streaming_response_includes_headers():
    """Test that Cline connector includes response headers in ResponseEnvelope."""
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

    # Set up connector state to bypass auth
    connector.api_key = "test_key"
    connector.api_base_url = "https://api.cline.bot/api/v1"
    connector._token_cache = {"idToken": "test_token", "expiresAt": 9999999999}

    # Mock response with usage headers
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.headers = {
        "content-type": "application/json",
        "x-request-id": "req-123",
        "x-ratelimit-remaining": "99",
    }
    mock_response.json.return_value = {
        "id": "chatcmpl-123",
        "object": "chat.completion",
        "created": 1234567890,
        "model": "gpt-4",
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": "Hello!"},
                "finish_reason": "stop",
            }
        ],
        "usage": {
            "prompt_tokens": 10,
            "completion_tokens": 5,
            "total_tokens": 15,
        },
    }

    mock_client.post = AsyncMock(return_value=mock_response)

    # Create a test request
    request = ChatRequest(
        model="gpt-4",
        messages=[ChatMessage(role="user", content="Hello")],
        stream=False,
    )

    # Act
    result = await connector.chat_completions(
        request_data=request,
        processed_messages=request.messages,
        effective_model="gpt-4",
        identity=None,
    )

    # Assert
    assert isinstance(result, ResponseEnvelope)
    assert result.headers is not None
    assert "x-request-id" in result.headers
    assert result.headers["x-request-id"] == "req-123"
    assert result.headers["content-type"] == "application/json"

    # Verify usage is also included
    assert result.usage is not None
    assert result.usage["prompt_tokens"] == 10
    assert result.usage["completion_tokens"] == 5
    assert result.usage["total_tokens"] == 15


@pytest.mark.asyncio
async def test_cline_response_headers_available_for_usage_tracking():
    """Test that response headers from Cline are available for usage tracking extraction."""
    # This test verifies that the headers flow through properly so that
    # usage tracking can extract billing information from them

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

    # Mock response with custom usage headers (simulating provider-specific headers)
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.headers = {
        "content-type": "application/json",
        "x-custom-usage-header": "some-value",
        "x-provider-cost": "0.0015",
    }
    mock_response.json.return_value = {
        "id": "chatcmpl-456",
        "object": "chat.completion",
        "created": 1234567890,
        "model": "gpt-4",
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": "Response"},
                "finish_reason": "stop",
            }
        ],
        "usage": {
            "prompt_tokens": 20,
            "completion_tokens": 10,
            "total_tokens": 30,
        },
    }

    mock_client.post = AsyncMock(return_value=mock_response)

    request = ChatRequest(
        model="gpt-4",
        messages=[ChatMessage(role="user", content="Test")],
        stream=False,
    )

    # Act
    result = await connector.chat_completions(
        request_data=request,
        processed_messages=request.messages,
        effective_model="gpt-4",
        identity=None,
    )

    # Assert - headers should be preserved for usage tracking
    assert isinstance(result, ResponseEnvelope)
    assert result.headers is not None
    assert "x-custom-usage-header" in result.headers
    assert "x-provider-cost" in result.headers
    assert result.headers["x-provider-cost"] == "0.0015"
