import json

import httpx
import pytest
import pytest_asyncio

# from starlette.responses import StreamingResponse # F401: Removed
import src.models as models

# from fastapi import HTTPException # F401: Removed
from pytest_httpx import HTTPXMock
from src.connectors.openrouter import OpenRouterBackend

# Default OpenRouter settings for tests
TEST_OPENROUTER_API_BASE_URL = (
    "https://openrouter.ai/api/v1"  # Real one for realistic requests
)


def mock_get_openrouter_headers(key_name: str, api_key: str) -> dict[str, str]:
    # Create a mock config dictionary for testing
    mock_config = {
        "app_site_url": "http://localhost:test",
        "app_x_title": "TestProxy",
    }
    return {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "HTTP-Referer": mock_config["app_site_url"],
        "X-Title": mock_config["app_x_title"],
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
        temperature=None,
        top_p=None,
        n=None,
        stream=False,  # Explicitly set stream to False for non-streaming tests
        stop=None,
        max_tokens=None,
        presence_penalty=None,
        frequency_penalty=None,
        logit_bias=None,
        user=None,
        tool_choice=None,
        reasoning_effort=None,
        reasoning=None,
        thinking_budget=None,
        generation_config=None,
        extra_params=None,
    )


@pytest.fixture
def sample_processed_messages() -> list[models.ChatMessage]:
    return [models.ChatMessage(role="user", content="Hello")]


@pytest.mark.asyncio
@pytest.mark.usefixtures("openrouter_backend")
@pytest.mark.httpx_mock()
async def test_chat_completions_non_streaming_success(
    openrouter_backend: OpenRouterBackend,
    httpx_mock: HTTPXMock,
    sample_chat_request_data: models.ChatCompletionRequest,
    sample_processed_messages: list[models.ChatMessage],
):
    sample_chat_request_data.stream = False
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

    response_tuple = await openrouter_backend.chat_completions(
        request_data=sample_chat_request_data,
        processed_messages=sample_processed_messages,
        effective_model=effective_model,
        openrouter_api_base_url=TEST_OPENROUTER_API_BASE_URL,
        openrouter_headers_provider=mock_get_openrouter_headers,
        key_name="test_key",
        api_key="FAKE_KEY",
    )
    # Explicitly cast to Tuple for type checking, as it's a non-streaming test
    response: dict
    if isinstance(response_tuple, tuple):
        response, _ = response_tuple
    else:
        # This case should not happen for non-streaming requests, but for type safety
        raise TypeError("Expected a tuple response for non-streaming request.")

    assert isinstance(response, dict)
    assert response["id"] == "test_completion_id"
    assert response["choices"][0]["message"]["content"] == "Hi there!"

    # Verify request payload
    request = httpx_mock.get_request()
    assert request is not None
    sent_payload = json.loads(request.content)
    assert sent_payload["model"] == effective_model
    assert sent_payload["messages"][0]["content"] == "Hello"
    assert not sent_payload["stream"]
    assert request.headers["Authorization"] == "Bearer FAKE_KEY"
