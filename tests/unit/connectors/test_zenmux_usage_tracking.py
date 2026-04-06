"""Test that ZenMux connector properly handles token usage tracking."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest
from src.connectors.contracts import ConnectorChatCompletionsRequest
from src.connectors.zenmux import ZenmuxConnector
from src.core.config.app_config import AppConfig
from src.core.domain.chat import CanonicalChatRequest, ChatMessage, ChatRequest
from src.core.domain.responses import ResponseEnvelope
from src.core.services.translation_service import TranslationService
from src.core.transport.fastapi.response_adapters import to_fastapi_response


def _zenmux_connector_req(request: ChatRequest) -> ConnectorChatCompletionsRequest:
    domain = CanonicalChatRequest.model_validate(request.model_dump())
    return ConnectorChatCompletionsRequest(
        request=domain,
        processed_messages=list(request.messages),
        effective_model=request.model,
        identity=None,
        cancellation_token=None,
        cancellation_coordinator=None,
        context=None,
        options={},
    )


@pytest.mark.asyncio
async def test_zenmux_non_streaming_response_includes_headers():
    """Test that ZenMux connector includes response headers in ResponseEnvelope."""
    # Arrange
    mock_client = AsyncMock(spec=httpx.AsyncClient)
    mock_config = MagicMock(spec=AppConfig)
    mock_config.backends = MagicMock()
    mock_config.backends.zenmux = None

    translation_service = TranslationService()

    connector = ZenmuxConnector(
        client=mock_client,
        config=mock_config,
        translation_service=translation_service,
    )

    # Set up connector state
    connector.api_key = "test_zenmux_key"
    connector.api_base_url = "https://zenmux.ai/api/v1"
    connector.disable_health_check()

    # Mock response with usage headers
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.headers = {
        "content-type": "application/json",
        "x-request-id": "zenmux-req-123",
        "x-ratelimit-remaining": "999",
        "zenmux-model-version": "v1.0",
    }
    mock_response.json.return_value = {
        "id": "chatcmpl-zenmux-123",
        "object": "chat.completion",
        "created": 1234567890,
        "model": "gpt-4",
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": "Hello from ZenMux!"},
                "finish_reason": "stop",
            }
        ],
        "usage": {
            "prompt_tokens": 15,
            "completion_tokens": 8,
            "total_tokens": 23,
        },
    }

    mock_response.aread = AsyncMock()
    mock_client.build_request = MagicMock(return_value=MagicMock())
    mock_client.send = AsyncMock(return_value=mock_response)

    request = ChatRequest(
        model="gpt-4",
        messages=[ChatMessage(role="user", content="Hello")],
        stream=False,
    )

    result = await connector.chat_completions(_zenmux_connector_req(request))

    assert isinstance(result, ResponseEnvelope)
    assert result.headers is not None
    assert "x-request-id" in result.headers
    assert result.headers["x-request-id"] == "zenmux-req-123"
    assert "zenmux-model-version" in result.headers

    # Verify usage is also included
    assert result.usage is not None
    assert result.usage["prompt_tokens"] == 15
    assert result.usage["completion_tokens"] == 8
    assert result.usage["total_tokens"] == 23


@pytest.mark.asyncio
async def test_zenmux_usage_data_in_client_response():
    """Test that usage data from ZenMux backend appears in the final client response."""
    # Arrange
    mock_client = AsyncMock(spec=httpx.AsyncClient)
    mock_config = MagicMock(spec=AppConfig)
    mock_config.backends = MagicMock()
    mock_config.backends.zenmux = None

    translation_service = TranslationService()

    connector = ZenmuxConnector(
        client=mock_client,
        config=mock_config,
        translation_service=translation_service,
    )

    # Set up connector state
    connector.api_key = "test_key"
    connector.api_base_url = "https://zenmux.ai/api/v1"
    connector.disable_health_check()

    # Mock backend response with usage data
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.headers = {
        "content-type": "application/json",
        "x-request-id": "req-456",
        "zenmux-processing-time": "123ms",
    }
    mock_response.json.return_value = {
        "id": "chatcmpl-zenmux-456",
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
            "prompt_tokens": 30,
            "completion_tokens": 20,
            "total_tokens": 50,
        },
    }

    mock_response.aread = AsyncMock()
    mock_client.build_request = MagicMock(return_value=MagicMock())
    mock_client.send = AsyncMock(return_value=mock_response)

    request = ChatRequest(
        model="gpt-4",
        messages=[ChatMessage(role="user", content="Test message")],
        stream=False,
    )

    envelope = await connector.chat_completions(_zenmux_connector_req(request))

    # Convert to FastAPI response (simulating what happens in the controller)
    fastapi_response = to_fastapi_response(envelope)

    # Assert - Usage data should be in the response body
    response_body = json.loads(fastapi_response.body)

    assert "usage" in response_body
    assert response_body["usage"]["prompt_tokens"] == 30  # Preserved
    # completion_tokens will be recalculated based on actual content ("Test response" = ~2 tokens)
    assert response_body["usage"]["completion_tokens"] > 0
    assert (
        response_body["usage"]["total_tokens"]
        == response_body["usage"]["prompt_tokens"]
        + response_body["usage"]["completion_tokens"]
    )

    # Assert - ZenMux-specific headers should be forwarded
    assert "x-request-id" in fastapi_response.headers
    assert fastapi_response.headers["x-request-id"] == "req-456"
    assert "zenmux-processing-time" in fastapi_response.headers
    assert fastapi_response.headers["zenmux-processing-time"] == "123ms"


@pytest.mark.asyncio
async def test_zenmux_response_with_custom_headers():
    """Test that ZenMux custom headers are properly forwarded."""
    # Arrange
    mock_client = AsyncMock(spec=httpx.AsyncClient)
    mock_config = MagicMock(spec=AppConfig)
    mock_config.backends = MagicMock()
    mock_config.backends.zenmux = None

    translation_service = TranslationService()

    connector = ZenmuxConnector(
        client=mock_client,
        config=mock_config,
        translation_service=translation_service,
    )

    connector.api_key = "test_key"
    connector.api_base_url = "https://zenmux.ai/api/v1"
    connector.disable_health_check()

    # Mock response with ZenMux-specific headers
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.headers = {
        "content-type": "application/json",
        "x-request-id": "req-789",
        "zenmux-model-id": "gpt-4-turbo",
        "zenmux-region": "us-east-1",
        "zenmux-cost": "0.0025",
    }
    mock_response.json.return_value = {
        "id": "chatcmpl-789",
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
            "prompt_tokens": 10,
            "completion_tokens": 5,
            "total_tokens": 15,
        },
    }

    mock_response.aread = AsyncMock()
    mock_client.build_request = MagicMock(return_value=MagicMock())
    mock_client.send = AsyncMock(return_value=mock_response)

    request = ChatRequest(
        model="gpt-4",
        messages=[ChatMessage(role="user", content="Test")],
        stream=False,
    )

    result = await connector.chat_completions(_zenmux_connector_req(request))

    # Assert - ZenMux headers should be preserved for usage tracking
    assert isinstance(result, ResponseEnvelope)
    assert result.headers is not None
    assert "zenmux-model-id" in result.headers
    assert result.headers["zenmux-model-id"] == "gpt-4-turbo"
    assert "zenmux-cost" in result.headers
    assert result.headers["zenmux-cost"] == "0.0025"
    assert "zenmux-region" in result.headers
