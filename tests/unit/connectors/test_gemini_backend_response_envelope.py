from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest

from src.connectors.gemini import GeminiBackend
from src.core.config.app_config import AppConfig
from src.core.domain.responses import ResponseEnvelope
from src.core.services.translation_service import TranslationService


@pytest.mark.asyncio
async def test_handle_non_streaming_response_serializes_domain_response() -> None:
    """Ensure GeminiBackend returns JSON-serializable content with usage metadata."""

    mock_client = AsyncMock(spec=httpx.AsyncClient)
    connector = GeminiBackend(
        client=mock_client,
        config=AppConfig(),
        translation_service=TranslationService(),
    )

    gemini_response = {
        "candidates": [
            {
                "content": {"parts": [{"text": "Hello, world!"}]},
                "finishReason": "STOP",
            }
        ],
        "usageMetadata": {
            "promptTokenCount": 3,
            "candidatesTokenCount": 5,
            "totalTokenCount": 8,
        },
    }

    mock_http_response = MagicMock()
    mock_http_response.status_code = 200
    mock_http_response.json.return_value = gemini_response
    mock_http_response.headers = {"content-type": "application/json"}

    mock_client.post.return_value = mock_http_response

    envelope = await connector._handle_gemini_non_streaming_response(
        "https://example.googleapis.com/v1beta/models/gemini-pro",
        {"contents": []},
        {"x-goog-api-key": "test"},
        "gemini-pro",
    )

    assert isinstance(envelope, ResponseEnvelope)
    assert isinstance(envelope.content, dict)
    assert envelope.content["choices"][0]["message"]["content"] == "Hello, world!"
    assert envelope.usage == {
        "prompt_tokens": 3,
        "completion_tokens": 5,
        "total_tokens": 8,
    }
