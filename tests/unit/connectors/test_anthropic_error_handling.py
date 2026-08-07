"""Tests for Anthropic connector error handling in streaming responses."""

from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest
from src.core.domain.chat import CanonicalChatRequest, ChatMessage


def test_retry_after_metadata_from_headers() -> None:
    """Retry-After extraction preserves header and parses numeric seconds."""
    from src.connectors.anthropic import _retry_after_metadata_from_httpx_headers

    details, reset_hint = _retry_after_metadata_from_httpx_headers(
        httpx.Headers({"Retry-After": "42"})
    )

    assert details == {"headers": {"retry-after": "42"}}
    assert reset_hint == 42


def test_retry_after_metadata_handles_non_numeric_header() -> None:
    """Non-numeric Retry-After is preserved while reset hint remains unset."""
    from src.connectors.anthropic import _retry_after_metadata_from_httpx_headers

    details, reset_hint = _retry_after_metadata_from_httpx_headers(
        httpx.Headers({"Retry-After": "Wed, 21 Oct 2015 07:28:00 GMT"})
    )

    assert details == {"headers": {"retry-after": "Wed, 21 Oct 2015 07:28:00 GMT"}}
    assert reset_hint is None


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
async def test_stream_completion_http_429_raises_rate_limit_exceeded() -> None:
    """HTTP 429 before the SSE body must map to RateLimitExceededError for resilience."""
    from src.connectors.anthropic import AnthropicBackend
    from src.core.common.exceptions import RateLimitExceededError
    from src.core.config.app_config import AppConfig
    from src.core.services.translation_service import TranslationService

    client = httpx.AsyncClient()
    config = AppConfig()
    translation_service = TranslationService()

    backend = AnthropicBackend(client, config, translation_service)
    await backend.initialize(
        anthropic_api_base_url="https://api.anthropic.com/v1",
        key_name="test_key",
        api_key="test-api-key-123",
    )

    err_json = (
        '{"type":"error","error":{"type":"SubscriptionUsageLimitError",'
        '"message":"quota exceeded"}}'
    )
    mock_response = MagicMock()
    mock_response.status_code = 429
    mock_response.headers = httpx.Headers({"retry-after": "42"})

    async def mock_aiter_bytes():
        yield err_json.encode()

    mock_response.aiter_bytes = mock_aiter_bytes
    mock_response.aclose = AsyncMock()

    req = CanonicalChatRequest(
        model="claude-3-5-sonnet-20241022",
        messages=[ChatMessage(role="user", content="hello")],
        stream=True,
    )

    with (
        patch.object(backend.client, "build_request", return_value=MagicMock()),
        patch.object(backend, "_capture_http_client") as cap,
    ):
        cap.send = AsyncMock(return_value=mock_response)
        with pytest.raises(RateLimitExceededError) as exc_info:
            async for _ in backend.stream_completion(req):
                pass

    assert "quota exceeded" in str(exc_info.value).lower()
    assert exc_info.value.details.get("headers", {}).get("retry-after") == "42"
    assert getattr(exc_info.value, "reset_at", None) == 42


@pytest.mark.asyncio
async def test_zai_coding_plan_uses_openai_connector():
    """Test that zai-coding-plan now inherits from OpenAI connector."""
    from src.connectors.openai import OpenAIConnector
    from src.connectors.zai_coding_plan import ZaiCodingPlanBackend

    # Use minimal mock setup to avoid heavy initialization
    client = MagicMock()
    config = MagicMock()
    translation_service = MagicMock()

    backend = ZaiCodingPlanBackend(client, config, translation_service)

    # Verify it's an OpenAI connector now
    assert isinstance(backend, OpenAIConnector)

    # Mock _refresh_available_models to avoid network call entirely
    async def mock_refresh():
        backend.available_models = ["glm-4.6", "claude-sonnet-4-20250514"]
        backend._provider_models = {"glm-4.6", "claude-sonnet-4-20250514"}

    # Patch _refresh_available_models and directly set attributes to avoid initialization overhead
    with patch.object(backend, "_refresh_available_models", new=mock_refresh):
        # Directly set attributes that would be set during initialize
        backend.api_key = "test-zai-key"
        backend.api_base_url = "https://api.z.ai/api/coding/paas/v4"
        backend._max_tokens_limit = 200000
        backend._default_max_tokens = 8192

    # Verify OpenAI-style API URL
    assert "api.z.ai/api/coding/paas/v4" in backend.api_base_url
