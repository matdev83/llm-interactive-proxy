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

def _assert_headers(request: httpx.Request, expected_api_key: str = "FAKE_KEY"):
    """Helper function to assert request headers."""
    assert request.headers["Authorization"] == f"Bearer {expected_api_key}"
    assert request.headers["Content-Type"] == "application/json"
    assert request.headers["HTTP-Referer"] == "http://localhost:test"
    assert request.headers["X-Title"] == "TestProxy"

def _assert_payload_basic_structure(
    sent_payload: Dict[str, Any],
    effective_model: str,
    request_data: models.ChatCompletionRequest
):
    """Helper function to assert basic payload structure."""
    assert sent_payload["model"] == effective_model
    assert sent_payload["max_tokens"] == request_data.max_tokens
    assert sent_payload["temperature"] == request_data.temperature
    assert sent_payload.get("stream") == request_data.stream # Handles if stream is None or False
    # Ensure only specified fields from request_data are passed (exclude_unset=True behavior)
    assert "n" not in sent_payload
    assert "logit_bias" not in sent_payload

def _assert_payload_messages(sent_payload: Dict[str, Any], expected_messages: List[Dict[str, Any]]):
    """Helper function to assert payload messages structure and content."""
    assert len(sent_payload["messages"]) == len(expected_messages)
    for actual_msg, expected_msg in zip(sent_payload["messages"], expected_messages):
        assert actual_msg["role"] == expected_msg["role"]
        _assert_message_content(actual_msg["content"], expected_msg["content"])
        # Ensure Pydantic models were converted to dicts (for the message itself)
        assert isinstance(actual_msg, dict)

def _assert_message_content(
    actual_content: Union[str, List[Dict[str, Any]]],
    expected_content: Union[str, List[Dict[str, Any]]]
):
    """Helper function to assert individual message content (string or list of parts)."""
    if isinstance(expected_content, list):
        assert isinstance(actual_content, list), "Actual content type mismatch: expected list"
        assert len(actual_content) == len(expected_content), \
            f"Content parts length mismatch: actual {len(actual_content)}, expected {len(expected_content)}"

        for actual_part, expected_part in zip(actual_content, expected_content):
            assert actual_part.get("type") == expected_part.get("type"), \
                f"Part type mismatch: actual {actual_part.get('type')}, expected {expected_part.get('type')}"

            if expected_part.get("type") == "text":
                assert actual_part.get("text") == expected_part.get("text"), \
                    f"Text part content mismatch: actual '{actual_part.get('text')}', expected '{expected_part.get('text')}'"
            elif expected_part.get("type") == "image_url":
                assert isinstance(actual_part.get("image_url"), dict), "Actual image_url part is not a dict"
                assert isinstance(expected_part.get("image_url"), dict), "Expected image_url part is not a dict" # Should always be true
                assert actual_part["image_url"].get("url") == expected_part["image_url"].get("url"), \
                    f"Image URL mismatch: actual '{actual_part['image_url'].get('url')}', expected '{expected_part['image_url'].get('url')}'"

            # Ensure individual parts (if dicts) are indeed dicts (already handled by type hints and Pydantic conversion)
            assert isinstance(actual_part, dict), "Actual message part is not a dictionary"
    else:  # string content
        assert isinstance(actual_content, str), "Actual content type mismatch: expected string"
        assert actual_content == expected_content, \
            f"String content mismatch: actual '{actual_content}', expected '{expected_content}'"


def _assert_original_data_unmodified(
    original_request_data: models.ChatCompletionRequest,
    modified_request_data: models.ChatCompletionRequest,
    original_processed_msgs: List[models.ChatMessage],
    modified_processed_msgs: List[models.ChatMessage]
):
    """Helper function to assert original data passed to function was not mutated."""
    # Check that the objects passed into chat_completions are not the same as the originals
    # if they were copied, or that they are unchanged if passed by reference.
    # Pydantic models are immutable by default unless configured otherwise,
    # but .model_copy(deep=True) ensures we are working with distinct objects.

    assert original_request_data.model == modified_request_data.model
    assert original_request_data.messages == modified_request_data.messages
    assert original_request_data.max_tokens == modified_request_data.max_tokens
    assert original_request_data.temperature == modified_request_data.temperature
    assert original_request_data.stream == modified_request_data.stream

    assert len(original_processed_msgs) == len(modified_processed_msgs)
    for i in range(len(original_processed_msgs)):
        assert original_processed_msgs[i] == modified_processed_msgs[i]

@pytest.mark.asyncio
@pytest.mark.usefixtures("openrouter_backend")
async def test_payload_construction_and_headers(
    openrouter_backend: OpenRouterBackend,
    httpx_mock: HTTPXMock,
    sample_chat_request_data: models.ChatCompletionRequest, # This is the base fixture
):
    # --- Test Data Setup ---
    # Create a deep copy of the fixture to modify for this specific test
    request_data_for_this_test = sample_chat_request_data.model_copy(deep=True)
    request_data_for_this_test.stream = False
    request_data_for_this_test.max_tokens = 100
    request_data_for_this_test.temperature = 0.7

    processed_msgs_for_this_test = [
        models.ChatMessage(role="user", content="Hello"),
        models.ChatMessage(role="assistant", content="Hi there!"),
        models.ChatMessage(role="user", content=[
            models.MessageContentPartText(type="text", text="What is this?"),
            models.MessageContentPartImage(type="image_url", image_url=models.ImageURL(url="data:...", detail=None))
        ])
    ]
    effective_model = "some/model-name"
    api_key_to_use = "FAKE_KEY_FOR_THIS_TEST"

    # Store snapshots of the data *before* it's passed to the function, to check for mutation
    request_data_snapshot = request_data_for_this_test.model_copy(deep=True)
    processed_msgs_snapshot = [m.model_copy(deep=True) for m in processed_msgs_for_this_test]

    httpx_mock.add_response(status_code=200, json={"choices": [{"message": {"content": "ok"}}]})

    # --- API Call ---
    await openrouter_backend.chat_completions(
        request_data=request_data_for_this_test,
        processed_messages=processed_msgs_for_this_test,
        effective_model=effective_model,
        openrouter_api_base_url=TEST_OPENROUTER_API_BASE_URL,
        openrouter_headers_provider=mock_get_openrouter_headers,
        key_name="OPENROUTER_API_KEY_1", # This key_name is used by mock_get_openrouter_headers
        api_key=api_key_to_use
    )

    # --- Assertions ---
    request = httpx_mock.get_request()
    assert request is not None

    _assert_headers(request, expected_api_key=api_key_to_use)

    sent_payload = json.loads(request.content)
    _assert_payload_basic_structure(sent_payload, effective_model, request_data_for_this_test)

    expected_messages_in_payload = [
        {"role": "user", "content": "Hello"},
        {"role": "assistant", "content": "Hi there!"},
        {"role": "user", "content": [
            {"type": "text", "text": "What is this?"},
            {"type": "image_url", "image_url": {"url": "data:..."}}
        ]}
    ]
    _assert_payload_messages(sent_payload, expected_messages_in_payload)

    # Check that the original data objects passed to the function were not mutated
    _assert_original_data_unmodified(
        request_data_snapshot,
        request_data_for_this_test,
        processed_msgs_snapshot,
        processed_msgs_for_this_test
    )

    # Additionally, ensure the original fixture was not modified by any operations above
    assert sample_chat_request_data.model == "test-model"
    assert sample_chat_request_data.messages == [models.ChatMessage(role="user", content="Hello")]
    assert sample_chat_request_data.max_tokens is None # Fixture default
    assert sample_chat_request_data.temperature is None # Fixture default
    assert sample_chat_request_data.stream is False # Fixture default, from Pydantic model
