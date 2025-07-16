from unittest.mock import AsyncMock

import httpx
import pytest
from fastapi import HTTPException

# from starlette.responses import StreamingResponse # F401: Removed
import src.models as models
from src.connectors.gemini import GeminiBackend

TEST_GEMINI_API_BASE_URL = "https://generativelanguage.googleapis.com"


@pytest.fixture
def sample_chat_request_data() -> models.ChatCompletionRequest:
    return models.ChatCompletionRequest(
        model="test-model",
        messages=[models.ChatMessage(role="user", content="Hello")],
        temperature=None,
        top_p=None,
        n=None,
        stream=False,
        stop=None,
        max_tokens=None,
        presence_penalty=None,
        frequency_penalty=None,
        logit_bias=None,
        user=None,
    )


@pytest.fixture
def sample_processed_messages() -> list[models.ChatMessage]:
    return [models.ChatMessage(role="user", content="Hello")]


@pytest.mark.asyncio
async def test_chat_completions_http_error_streaming(
    monkeypatch: pytest.MonkeyPatch, sample_chat_request_data, sample_processed_messages
):
    sample_chat_request_data.stream = True
    error_text_response = "Gemini internal server error"

    mock_send = AsyncMock()
    mock_send.return_value = httpx.Response(
        status_code=500,
        request=httpx.Request("POST", "http://test-url"),
        content=error_text_response.encode("utf-8"),
        headers={"Content-Type": "text/plain"},
    )
    mock_send.return_value.aclose = AsyncMock()

    monkeypatch.setattr(httpx.AsyncClient, "send", mock_send)

    async with httpx.AsyncClient() as client:
        gemini_backend = GeminiBackend(client=client)
        with pytest.raises(HTTPException) as exc_info:
            await gemini_backend.chat_completions(
                request_data=sample_chat_request_data,
                processed_messages=sample_processed_messages,
                effective_model="test-model",
                openrouter_api_base_url=TEST_GEMINI_API_BASE_URL,
                openrouter_headers_provider=None,
                key_name="GEMINI_API_KEY_1",
                api_key="FAKE_KEY",
            )

    assert exc_info.value.status_code == 500
    detail = exc_info.value.detail
    assert isinstance(detail, dict)
    assert (
        detail.get("message")
        == "Gemini stream error: 500 - Gemini internal server error"
    )
    assert detail.get("type") == "gemini_error"
    assert detail.get("code") == 500
    assert mock_send.return_value.aclose.await_count == 1
