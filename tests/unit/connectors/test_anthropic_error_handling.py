"""Tests for Anthropic connector error handling in streaming responses."""

from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest


@pytest.mark.asyncio
async def test_anthropic_streaming_handles_error_events():
    """Test that Anthropic connector properly handles error events in streaming."""
    from src.connectors.anthropic import AnthropicBackend
    from src.core.common.exceptions import BackendError
    from src.core.config.app_config import AppConfig
    from src.core.services.translation_service import TranslationService

    # Setup
    client = httpx.AsyncClient()
    config = AppConfig()
    translation_service = TranslationService()

    backend = AnthropicBackend(client, config, translation_service)
    await backend.initialize(
        anthropic_api_base_url="https://api.anthropic.com/v1",
        key_name="test_key",
        api_key="test-api-key-123",
    )

    # Mock the HTTP response with error event
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.headers = {}

    # Simulate error event from backend
    error_chunks = [
        'event: error\ndata: {"type": "error", "error": {"type": "1113", "message": "Insufficient balance or no resource package. Please recharge."}, "request_id": "test123"}\n\n',
    ]

    async def mock_aiter_text():
        for chunk in error_chunks:
            yield chunk

    mock_response.aiter_text = mock_aiter_text
    mock_response.aclose = AsyncMock()

    with (
        patch.object(backend.client, "build_request", return_value=MagicMock()),
        patch.object(backend.client, "send", return_value=mock_response),
    ):
        # Call the streaming handler
        stream_handle = await backend._handle_streaming_response(
            url="https://api.anthropic.com/v1/messages",
            payload={"model": "claude-3-opus-20240229", "messages": []},
            headers={"x-api-key": "test-api-key-123"},
            model="claude-3-opus-20240229",
        )

    # Verify that iterating raises BackendError
    with pytest.raises(BackendError) as exc_info:
        async for _ in stream_handle.iterator:

            # Verify error details
            assert "Insufficient balance" in str(exc_info.value)
            assert exc_info.value.code == "anthropic_error_1113"


@pytest.mark.asyncio
async def test_anthropic_streaming_handles_generic_error():
    """Test that Anthropic connector handles generic error events."""
    from src.connectors.anthropic import AnthropicBackend
    from src.core.common.exceptions import BackendError
    from src.core.config.app_config import AppConfig
    from src.core.services.translation_service import TranslationService

    # Setup
    client = httpx.AsyncClient()
    config = AppConfig()
    translation_service = TranslationService()

    backend = AnthropicBackend(client, config, translation_service)
    await backend.initialize(
        anthropic_api_base_url="https://api.anthropic.com/v1",
        key_name="test_key",
        api_key="test-api-key-123",
    )

    # Mock the HTTP response with generic error
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.headers = {}

    error_chunks = [
        'event: error\ndata: {"type": "error", "error": {"type": "rate_limit", "message": "Rate limit exceeded"}}\n\n',
    ]

    async def mock_aiter_text():
        for chunk in error_chunks:
            yield chunk

    mock_response.aiter_text = mock_aiter_text
    mock_response.aclose = AsyncMock()

    with (
        patch.object(backend.client, "build_request", return_value=MagicMock()),
        patch.object(backend.client, "send", return_value=mock_response),
    ):
        stream_handle = await backend._handle_streaming_response(
            url="https://api.anthropic.com/v1/messages",
            payload={"model": "claude-3-opus-20240229", "messages": []},
            headers={"x-api-key": "test-api-key-123"},
            model="claude-3-opus-20240229",
        )

        with pytest.raises(BackendError) as exc_info:
            async for _ in stream_handle.iterator:
                pass

        assert "Rate limit exceeded" in str(exc_info.value)
        assert exc_info.value.code == "anthropic_error_rate_limit"


@pytest.mark.asyncio
async def test_zai_coding_plan_uses_openai_connector():
    """Test that zai-coding-plan now inherits from OpenAI connector."""
    import os

    from src.connectors.openai import OpenAIConnector
    from src.connectors.zai_coding_plan import ZaiCodingPlanBackend
    from src.core.config.app_config import AppConfig
    from src.core.services.translation_service import TranslationService

    # Setup
    client = httpx.AsyncClient()
    config = AppConfig()
    translation_service = TranslationService()

    backend = ZaiCodingPlanBackend(client, config, translation_service)

    # Verify it's an OpenAI connector now
    assert isinstance(backend, OpenAIConnector)

    with patch.dict(os.environ, {"ZAI_API_KEY": "test-zai-key"}):
        await backend.initialize()

    # Verify OpenAI-style API URL
    assert "api.z.ai/api/coding/paas/v4" in backend.api_base_url
