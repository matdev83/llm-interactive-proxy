import json

from typing import Any

import httpx
import pytest
import pytest_asyncio

# from fastapi import HTTPException # F401: Removed
from pytest_httpx import HTTPXMock
from src.connectors.openrouter import OpenRouterBackend
from src.core.domain.chat import ChatMessage, ChatRequest
from src.core.domain.responses import ResponseEnvelope

# Default OpenRouter settings for tests
TEST_OPENROUTER_API_BASE_URL = (
    "https://openrouter.ai/api/v1"  # Real one for realistic requests
)


def mock_get_openrouter_headers(
    config_payload: dict[str, Any], api_key: str
) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "HTTP-Referer": config_payload["app_site_url"],
        "X-Title": config_payload["app_x_title"],
    }


@pytest_asyncio.fixture(name="openrouter_backend")
async def openrouter_backend_fixture():
    async with httpx.AsyncClient() as client:
        from src.core.config.app_config import AppConfig

        config = AppConfig()
        backend = OpenRouterBackend(client=client, config=config)
        # Call initialize with required arguments
        await backend.initialize(
            api_key="test_key",  # A dummy API key for initialization
            key_name="openrouter",
            openrouter_headers_provider=mock_get_openrouter_headers,
        )
        yield backend


@pytest.fixture
def sample_chat_request_data() -> ChatRequest:
    """Return a minimal chat request without optional fields set."""
    return ChatRequest(
        model="test-model",
        messages=[ChatMessage(role="user", content="Hello")],
        stream=False,
    )


@pytest.fixture
def sample_processed_messages() -> list[ChatMessage]:
    return [ChatMessage(role="user", content="Hello")]


@pytest.mark.asyncio
@pytest.mark.usefixtures("openrouter_backend")
@pytest.mark.httpx_mock()
async def test_chat_completions_non_streaming_success(
    openrouter_backend: OpenRouterBackend,
    httpx_mock: HTTPXMock,
    sample_chat_request_data: ChatRequest,
    sample_processed_messages: list[ChatMessage],
):
    sample_chat_request_data = sample_chat_request_data.model_copy(
        update={"stream": False}
    )
    effective_model = "openai/gpt-3.5-turbo"

    # Mock successful response from OpenRouter
    mock_response_payload = {
        "id": "test_completion_id",
        "choices": [{"message": {"role": "assistant", "content": "Hi there!"}}],
        "model": effective_model,
        "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
    }
    httpx_mock.add_response(
        url=f"{TEST_OPENROUTER_API_BASE_URL}/chat/completions",
        method="POST",
        json=mock_response_payload,
        status_code=200,
    )

    response_envelope = await openrouter_backend.chat_completions(
        request_data=sample_chat_request_data,
        processed_messages=sample_processed_messages,
        effective_model=effective_model,
        openrouter_api_base_url=TEST_OPENROUTER_API_BASE_URL,
        openrouter_headers_provider=mock_get_openrouter_headers,
        key_name="test_key",
        api_key="FAKE_KEY",
    )
    assert isinstance(response_envelope, ResponseEnvelope)
    response_content = response_envelope.content
    assert response_content["id"] == "test_completion_id"
    assert response_content["choices"][0]["message"]["content"] == "Hi there!"

    # Verify request payload
    request = httpx_mock.get_request()
    assert request is not None
    sent_payload = json.loads(request.content)
    assert sent_payload["model"] == effective_model
    assert sent_payload["messages"][0]["content"] == "Hello"
    assert not sent_payload["stream"]
    assert request.headers["Authorization"] == "Bearer FAKE_KEY"
