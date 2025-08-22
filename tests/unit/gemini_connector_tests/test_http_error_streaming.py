from unittest.mock import AsyncMock

import httpx
import pytest
from fastapi import HTTPException
from src.connectors.gemini import GeminiBackend
from src.core.common.exceptions import BackendError

# from starlette.responses import StreamingResponse # F401: Removed
from src.core.domain.chat import ChatMessage, ChatRequest

TEST_GEMINI_API_BASE_URL = "https://generativelanguage.googleapis.com"


@pytest.fixture
def sample_chat_request_data() -> ChatRequest:
    return ChatRequest(
        model="test-model", messages=[ChatMessage(role="user", content="Hello")]
    )


@pytest.fixture
def sample_processed_messages() -> list[ChatMessage]:
    return [ChatMessage(role="user", content="Hello")]


@pytest.mark.asyncio
async def test_chat_completions_http_error_streaming(
    monkeypatch: pytest.MonkeyPatch, sample_chat_request_data, sample_processed_messages
):
    sample_chat_request_data = sample_chat_request_data.model_copy(
        update={"stream": True}
    )
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
        with pytest.raises(BackendError) as exc_info:
            await gemini_backend.chat_completions(
                request_data=sample_chat_request_data,
                processed_messages=sample_processed_messages,
                effective_model="test-model",
                openrouter_api_base_url=TEST_GEMINI_API_BASE_URL,
                openrouter_headers_provider=None,
                key_name="GEMINI_API_KEY_1",
                api_key="FAKE_KEY",
            )

    # Check that the BackendError contains the error information
    assert "500" in str(exc_info.value)
    assert "Gemini internal server error" in str(exc_info.value)
    assert "gemini" in str(exc_info.value).lower()
    assert mock_send.return_value.aclose.await_count == 1
