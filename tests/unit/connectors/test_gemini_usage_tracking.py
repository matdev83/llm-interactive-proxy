"""Tests for Gemini connector usage tracking."""

from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest
from src.connectors.gemini import GeminiBackend
from src.core.config.app_config import AppConfig
from src.core.domain.chat import ChatMessage, ChatRequest
from src.core.domain.responses import ResponseEnvelope
from src.core.domain.usage_summary import UsageSummary
from src.core.services.translation_service import TranslationService


@pytest.mark.asyncio
async def test_gemini_extracts_usage_from_response():
    """Test that Gemini connector extracts usage from usageMetadata."""
    mock_client = AsyncMock(spec=httpx.AsyncClient)
    mock_config = MagicMock(spec=AppConfig)
    mock_config.backends = MagicMock()
    mock_config.backends.gemini = None

    translation_service = TranslationService()

    connector = GeminiBackend(
        client=mock_client,
        config=mock_config,
        translation_service=translation_service,
    )

    connector.api_key = "test_key"
    connector.gemini_api_base_url = "https://generativelanguage.googleapis.com/v1beta"

    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.headers = {"content-type": "application/json"}
    mock_response.json.return_value = {
        "candidates": [
            {
                "content": {
                    "parts": [{"text": "Hello from Gemini!"}],
                    "role": "model",
                },
                "finishReason": "STOP",
            }
        ],
        "usageMetadata": {
            "promptTokenCount": 25,
            "candidatesTokenCount": 10,
            "totalTokenCount": 35,
        },
    }

    mock_client.post = AsyncMock(return_value=mock_response)

    request = ChatRequest(
        model="gemini-pro",
        messages=[ChatMessage(role="user", content="Hello")],
        stream=False,
    )

    result = await connector.chat_completions(
        request_data=request,
        processed_messages=request.messages,
        effective_model="gemini-pro",
        identity=None,
    )

    assert isinstance(result, ResponseEnvelope)
    assert result.usage is not None
    assert isinstance(result.usage, UsageSummary)
    assert result.usage.prompt_tokens == 25
    assert result.usage.completion_tokens == 10
    assert result.usage.total_tokens == 35


@pytest.mark.asyncio
async def test_gemini_calculates_usage_when_missing():
    """Test that Gemini connector calculates usage when usageMetadata is missing."""
    mock_client = AsyncMock(spec=httpx.AsyncClient)
    mock_config = MagicMock(spec=AppConfig)
    mock_config.backends = MagicMock()
    mock_config.backends.gemini = None

    translation_service = TranslationService()

    connector = GeminiBackend(
        client=mock_client,
        config=mock_config,
        translation_service=translation_service,
    )

    connector.api_key = "test_key"
    connector.gemini_api_base_url = "https://generativelanguage.googleapis.com/v1beta"

    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.headers = {"content-type": "application/json"}
    mock_response.json.return_value = {
        "candidates": [
            {
                "content": {
                    "parts": [{"text": "Response without usage"}],
                    "role": "model",
                },
                "finishReason": "STOP",
            }
        ],
    }

    mock_client.post = AsyncMock(return_value=mock_response)

    request = ChatRequest(
        model="gemini-pro",
        messages=[ChatMessage(role="user", content="Test message")],
        stream=False,
    )

    result = await connector.chat_completions(
        request_data=request,
        processed_messages=request.messages,
        effective_model="gemini-pro",
        identity=None,
    )

    assert isinstance(result, ResponseEnvelope)
    assert result.usage is not None
    assert isinstance(result.usage, UsageSummary)
    assert result.usage.prompt_tokens is not None and result.usage.prompt_tokens > 0
    assert (
        result.usage.completion_tokens is not None
        and result.usage.completion_tokens > 0
    )
    assert result.usage.total_tokens is not None and result.usage.total_tokens > 0
    assert (
        result.usage.total_tokens
        == result.usage.prompt_tokens + result.usage.completion_tokens
    )


@pytest.mark.asyncio
async def test_gemini_calculates_usage_when_zero():
    """Test that Gemini connector calculates usage when usageMetadata has zeros."""
    mock_client = AsyncMock(spec=httpx.AsyncClient)
    mock_config = MagicMock(spec=AppConfig)
    mock_config.backends = MagicMock()
    mock_config.backends.gemini = None

    translation_service = TranslationService()

    connector = GeminiBackend(
        client=mock_client,
        config=mock_config,
        translation_service=translation_service,
    )

    connector.api_key = "test_key"
    connector.gemini_api_base_url = "https://generativelanguage.googleapis.com/v1beta"

    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.headers = {"content-type": "application/json"}
    mock_response.json.return_value = {
        "candidates": [
            {
                "content": {
                    "parts": [{"text": "Response with zero usage"}],
                    "role": "model",
                },
                "finishReason": "STOP",
            }
        ],
        "usageMetadata": {
            "promptTokenCount": 0,
            "candidatesTokenCount": 0,
            "totalTokenCount": 0,
        },
    }

    mock_client.post = AsyncMock(return_value=mock_response)

    request = ChatRequest(
        model="gemini-pro",
        messages=[ChatMessage(role="user", content="Another test")],
        stream=False,
    )

    result = await connector.chat_completions(
        request_data=request,
        processed_messages=request.messages,
        effective_model="gemini-pro",
        identity=None,
    )

    assert isinstance(result, ResponseEnvelope)
    assert result.usage is not None
    assert isinstance(result.usage, UsageSummary)
    assert result.usage.prompt_tokens is not None and result.usage.prompt_tokens > 0
    assert (
        result.usage.completion_tokens is not None
        and result.usage.completion_tokens > 0
    )
    assert result.usage.total_tokens is not None and result.usage.total_tokens > 0
