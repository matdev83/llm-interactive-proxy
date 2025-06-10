import json
from typing import Any, Callable, Dict, List, Union

import httpx
import pytest
import pytest_asyncio
from fastapi import HTTPException
from pytest_httpx import HTTPXMock
from starlette.responses import StreamingResponse

import src.models as models
from src.connectors.openrouter import OpenRouterBackend

# Default OpenRouter settings for tests
TEST_OPENROUTER_API_BASE_URL = (
    "https://openrouter.ai/api/v1"  # Real one for realistic requests
)


def mock_get_openrouter_headers(key_name: str, api_key: str) -> Dict[str, str]:
    return {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "HTTP-Referer": "http://localhost:test",
        "X-Title": "TestProxy",
    }


@pytest_asyncio.fixture(name="openrouter_backend")
async def openrouter_backend_fixture():
    async with httpx.AsyncClient() as client:
        yield OpenRouterBackend(client=client)


@pytest.fixture
def sample_chat_request_data() -> models.ChatCompletionRequest:
    """Return a minimal chat request without optional fields set."""
    return models.ChatCompletionRequest(
        model="test-model",
        messages=[models.ChatMessage(role="user", content="Hello")],
    )


@pytest.fixture
def sample_processed_messages() -> List[models.ChatMessage]:
    return [models.ChatMessage(role="user", content="Hello")]


@pytest.mark.asyncio
async def test_chat_completions_http_error_streaming(
    monkeypatch: pytest.MonkeyPatch,  # Add monkeypatch fixture
    sample_chat_request_data: models.ChatCompletionRequest,
    sample_processed_messages: List[models.ChatMessage],
):
    sample_chat_request_data.stream = True
    error_text_response = "OpenRouter internal server error"

    def mock_stream_method(self, method, url, **kwargs):
        mock_response = httpx.Response(
            status_code=500,
            request=httpx.Request(method, url),
            stream=httpx.ByteStream(error_text_response.encode("utf-8")),
            headers={"Content-Type": "text/plain"},
        )

        class MockAsyncStream:
            async def __aenter__(self):
                return mock_response

            async def __aexit__(self, exc_type, exc_val, exc_tb):
                pass

        return MockAsyncStream()

    monkeypatch.setattr(httpx.AsyncClient, "stream", mock_stream_method)

    async with httpx.AsyncClient() as client:
        openrouter_backend = OpenRouterBackend(client=client)

        response = await openrouter_backend.chat_completions(
            request_data=sample_chat_request_data,
            processed_messages=sample_processed_messages,
            effective_model="test-model",
            openrouter_api_base_url=TEST_OPENROUTER_API_BASE_URL,
            openrouter_headers_provider=mock_get_openrouter_headers,
            key_name="OPENROUTER_API_KEY_1",
            api_key="FAKE_KEY",
        )

        assert isinstance(response, StreamingResponse)

        with pytest.raises(HTTPException) as exc_info:
            async for chunk in response.body_iterator:
                pass  # Consume the stream to trigger the exception

    assert exc_info.value.status_code == 500
    detail = exc_info.value.detail
    assert isinstance(detail, dict)
    assert (
        detail.get("message")
        == "OpenRouter stream error: 500 - OpenRouter internal server error"
    )
    assert detail.get("type") == "openrouter_error"
    assert detail.get("code") == 500
