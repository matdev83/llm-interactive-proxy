import pytest
import httpx
import json
from typing import List, Dict, Any, Callable, Union

from starlette.responses import StreamingResponse
from fastapi import HTTPException
from pytest_httpx import HTTPXMock
import pytest_asyncio

import src.models as models
from src.connectors.openrouter import OpenRouterBackend

# Default OpenRouter settings for tests
TEST_OPENROUTER_API_BASE_URL = "https://openrouter.ai/api/v1" # Real one for realistic requests

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
@pytest.mark.usefixtures("openrouter_backend")
async def test_payload_construction_and_headers(
    openrouter_backend: OpenRouterBackend,
    httpx_mock: HTTPXMock,
    sample_chat_request_data: models.ChatCompletionRequest,
):
    sample_chat_request_data.stream = False
    sample_chat_request_data.max_tokens = 100
    sample_chat_request_data.temperature = 0.7

    processed_msgs = [
        models.ChatMessage(role="user", content="Hello"),
        models.ChatMessage(role="assistant", content="Hi there!"),
        models.ChatMessage(role="user", content=[
            models.MessageContentPartText(type="text", text="What is this?"),
            models.MessageContentPartImage(type="image_url", image_url=models.ImageURL(url="data:...", detail=None))
        ])
    ]
    effective_model = "some/model-name"

    httpx_mock.add_response(status_code=200, json={"choices": [{"message": {"content": "ok"}}]})

    await openrouter_backend.chat_completions(
        request_data=sample_chat_request_data,
        processed_messages=processed_msgs,
        effective_model=effective_model,
        openrouter_api_base_url=TEST_OPENROUTER_API_BASE_URL,
        openrouter_headers_provider=mock_get_openrouter_headers,
        key_name="OPENROUTER_API_KEY_1",
        api_key="FAKE_KEY"
    )

    request = httpx_mock.get_request()
    assert request is not None

    # Check headers
    assert request.headers["Authorization"] == "Bearer FAKE_KEY"
    assert request.headers["Content-Type"] == "application/json"
    assert request.headers["HTTP-Referer"] == "http://localhost:test"
    assert request.headers["X-Title"] == "TestProxy"

    # Check payload
    sent_payload = json.loads(request.content)
    assert sent_payload["model"] == effective_model
    assert sent_payload["max_tokens"] == 100
    assert sent_payload["temperature"] == 0.7
    assert not sent_payload["stream"]

    # Check messages format
    assert len(sent_payload["messages"]) == 3
    assert sent_payload["messages"][0]["role"] == "user"
    assert sent_payload["messages"][0]["content"] == "Hello"
    assert sent_payload["messages"][1]["role"] == "assistant"
    assert sent_payload["messages"][1]["content"] == "Hi there!"
    assert sent_payload["messages"][2]["role"] == "user"
    assert isinstance(sent_payload["messages"][2]["content"], list)
    assert sent_payload["messages"][2]["content"][0]["type"] == "text"
    assert sent_payload["messages"][2]["content"][0]["text"] == "What is this?"
    assert sent_payload["messages"][2]["content"][1]["type"] == "image_url"
    assert sent_payload["messages"][2]["content"][1]["image_url"]["url"] == "data:..."

    # Ensure Pydantic models were converted to dicts
    assert isinstance(sent_payload["messages"][0], dict)
    assert isinstance(sent_payload["messages"][2]["content"][0], dict)
    assert isinstance(sent_payload["messages"][2]["content"][1], dict)
    assert isinstance(sent_payload["messages"][2]["content"][1]["image_url"], dict)

    # Ensure only specified fields from request_data are passed (exclude_unset=True)
    assert "n" not in sent_payload
    assert "logit_bias" not in sent_payload

    # Check if original request_data was not modified (important due to model_dump)
    assert sample_chat_request_data.model == "test-model"
    assert sample_chat_request_data.messages[0].content == "Hello"
    assert sample_chat_request_data.max_tokens == 100

    # The connector receives 'processed_messages' which are already Pydantic models.
    # It then dumps them to dicts for the payload.
    assert isinstance(processed_msgs[0], models.ChatMessage)
    assert isinstance(processed_msgs[2].content[0], models.MessageContentPartText)
    assert isinstance(processed_msgs[2].content[1], models.MessageContentPart)
