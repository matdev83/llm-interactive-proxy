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


def mock_get_openrouter_headers(api_key: str) -> dict[str, str]:
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
def sample_processed_messages() -> (
    list[models.ChatMessage]
):  # This is unused in this specific file though
    return [models.ChatMessage(role="user", content="Hello")]


@pytest_asyncio.fixture(name="api_request_and_data")
async def fixture_api_request_and_data(
    openrouter_backend: OpenRouterBackend,
    httpx_mock: HTTPXMock,
    sample_chat_request_data: models.ChatCompletionRequest,
):
    """
    Calls chat_completions and returns a dictionary containing the sent request,
    parsed payload, original request data, processed messages, and effective model.
    """
    sample_chat_request_data.stream = False
    sample_chat_request_data.max_tokens = 100
    sample_chat_request_data.temperature = 0.7

    processed_msgs = [
        models.ChatMessage(role="user", content="Hello"),
        models.ChatMessage(role="assistant", content="Hi there!"),
        models.ChatMessage(
            role="user",
            content=[
                models.MessageContentPartText(type="text", text="What is this?"),
                models.MessageContentPartImage(
                    type="image_url",
                    image_url=models.ImageURL(url="data:...", detail=None),
                ),
            ],
        ),
    ]
    effective_model = "some/model-name"

    httpx_mock.add_response(
        status_code=200, json={"choices": [{"message": {"content": "ok"}}]}
    )

    await openrouter_backend.chat_completions(
        request_data=sample_chat_request_data,
        processed_messages=processed_msgs,
        effective_model=effective_model,
        openrouter_api_base_url=TEST_OPENROUTER_API_BASE_URL,
        openrouter_headers_provider=mock_get_openrouter_headers,
        api_key="FAKE_KEY",
    )

    sent_request = httpx_mock.get_request()
    assert sent_request is not None  # Ensure request was made

    return {
        "sent_request": sent_request,
        "sent_payload": json.loads(sent_request.content),
        "original_request_data": sample_chat_request_data,
        "processed_messages_fixture": processed_msgs,  # Renamed to avoid clash
        "effective_model": effective_model,
    }


@pytest.mark.asyncio
async def test_openrouter_headers_are_correct(api_request_and_data: dict):
    request = api_request_and_data["sent_request"]
    assert request.headers["Authorization"] == "Bearer FAKE_KEY"
    assert request.headers["Content-Type"] == "application/json"
    assert request.headers["HTTP-Referer"] == "http://localhost:test"
    assert request.headers["X-Title"] == "TestProxy"


@pytest.mark.asyncio
async def test_openrouter_payload_basic_fields_and_model(api_request_and_data: dict):
    sent_payload = api_request_and_data["sent_payload"]
    effective_model = api_request_and_data["effective_model"]
    assert sent_payload["model"] == effective_model
    assert sent_payload["max_tokens"] == 100
    assert sent_payload["temperature"] == 0.7
    assert not sent_payload["stream"]


@pytest.mark.asyncio
async def test_openrouter_payload_message_count(api_request_and_data: dict):
    sent_payload = api_request_and_data["sent_payload"]
    assert len(sent_payload["messages"]) == 3


@pytest.mark.asyncio
async def test_openrouter_payload_first_message_structure(api_request_and_data: dict):
    message_one_payload = api_request_and_data["sent_payload"]["messages"][0]
    assert message_one_payload["role"] == "user"
    assert message_one_payload["content"] == "Hello"
    assert isinstance(message_one_payload, dict)


@pytest.mark.asyncio
async def test_openrouter_payload_second_message_structure(api_request_and_data: dict):
    message_two_payload = api_request_and_data["sent_payload"]["messages"][1]
    assert message_two_payload["role"] == "assistant"
    assert message_two_payload["content"] == "Hi there!"
    assert isinstance(message_two_payload, dict)


@pytest.mark.asyncio
async def test_openrouter_payload_third_message_multipart_structure(
    api_request_and_data: dict,
):
    message_three_payload = api_request_and_data["sent_payload"]["messages"][2]
    assert message_three_payload["role"] == "user"
    assert isinstance(message_three_payload["content"], list)

    content_part_one = message_three_payload["content"][0]
    assert content_part_one["type"] == "text"
    assert content_part_one["text"] == "What is this?"
    assert isinstance(content_part_one, dict)

    content_part_two = message_three_payload["content"][1]
    assert content_part_two["type"] == "image_url"
    assert content_part_two["image_url"]["url"] == "data:..."
    assert isinstance(content_part_two, dict)
    assert isinstance(content_part_two["image_url"], dict)


@pytest.mark.asyncio
async def test_openrouter_payload_unset_fields_are_excluded(api_request_and_data: dict):
    sent_payload = api_request_and_data["sent_payload"]
    assert "n" not in sent_payload  # Example of a field that wasn't set
    assert "logit_bias" not in sent_payload  # Another example


@pytest.mark.asyncio
async def test_openrouter_original_request_data_unmodified(api_request_and_data: dict):
    original_request = api_request_and_data["original_request_data"]
    # Check if original request_data was not modified (important due to model_dump)
    assert (
        original_request.model == "test-model"
    )  # Was not overridden by effective_model
    assert original_request.messages[0].content == "Hello"
    assert original_request.max_tokens == 100  # Value was set on original object


@pytest.mark.asyncio
async def test_openrouter_processed_messages_remain_pydantic(
    api_request_and_data: dict,
):
    # The connector receives 'processed_messages' which are already Pydantic models.
    # It then dumps them to dicts for the payload, but original list should be of Pydantic objects.
    processed_msgs_fixture = api_request_and_data["processed_messages_fixture"]
    assert isinstance(processed_msgs_fixture[0], models.ChatMessage)
    assert isinstance(
        processed_msgs_fixture[2].content[0], models.MessageContentPartText
    )
    assert isinstance(
        processed_msgs_fixture[2].content[1], models.MessageContentPartImage
    )  # Specific type
