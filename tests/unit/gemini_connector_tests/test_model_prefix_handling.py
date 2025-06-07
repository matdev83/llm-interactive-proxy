import pytest
import httpx
import json
from pytest_httpx import HTTPXMock
import pytest_asyncio

import src.models as models
from src.connectors.gemini import GeminiBackend

TEST_GEMINI_API_BASE_URL = "https://generativelanguage.googleapis.com"

@pytest_asyncio.fixture(name="gemini_backend")
async def gemini_backend_fixture():
    async with httpx.AsyncClient() as client:
        yield GeminiBackend(client=client)


@pytest.fixture
def sample_chat_request_data() -> models.ChatCompletionRequest:
    return models.ChatCompletionRequest(
        model="test-model",
        messages=[models.ChatMessage(role="user", content="Hello")],
    )


@pytest.fixture
def sample_processed_messages() -> list[models.ChatMessage]:
    return [models.ChatMessage(role="user", content="Hello")]


@pytest.mark.asyncio
async def test_chat_completions_model_prefix_handled(
    gemini_backend: GeminiBackend,
    httpx_mock: HTTPXMock,
    sample_chat_request_data: models.ChatCompletionRequest,
    sample_processed_messages: list[models.ChatMessage],
):
    sample_chat_request_data.stream = False
    effective_model = "models/gemini-1"

    mock_response_payload = {
        "candidates": [{"content": {"parts": [{"text": "Hi"}]}}],
        "usageMetadata": {"promptTokenCount": 1, "candidatesTokenCount": 1, "totalTokenCount": 2},
    }
    httpx_mock.add_response(
        url=f"{TEST_GEMINI_API_BASE_URL}/v1beta/models/gemini-1:generateContent",
        method="POST",
        json=mock_response_payload,
        status_code=200,
        headers={"Content-Type": "application/json"},
        match_headers={"x-goog-api-key": "FAKE_KEY"},
    )

    response = await gemini_backend.chat_completions(
        request_data=sample_chat_request_data,
        processed_messages=sample_processed_messages,
        effective_model=effective_model,
        openrouter_api_base_url=TEST_GEMINI_API_BASE_URL,
        openrouter_headers_provider=None,
        key_name="GEMINI_API_KEY_1",
        api_key="FAKE_KEY",
    )

    assert isinstance(response, dict)
    request = httpx_mock.get_request()
    assert request is not None
    assert str(request.url) == f"{TEST_GEMINI_API_BASE_URL}/v1beta/models/gemini-1:generateContent"
    assert request.headers.get("x-goog-api-key") == "FAKE_KEY"
