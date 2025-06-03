import pytest
import httpx
import json
from typing import List, Dict, Any, Callable, Union

from starlette.responses import StreamingResponse
from fastapi import HTTPException

from src.models import ChatMessage, ChatCompletionRequest, MessageContentPartText
from src.connectors.openrouter import OpenRouterBackend

# Default OpenRouter settings for tests
TEST_OPENROUTER_API_BASE_URL = "https.openrouter.ai/api/v1" # Real one for realistic requests

def mock_get_openrouter_headers() -> Dict[str, str]:
    return {
        "Authorization": "Bearer FAKE_KEY",
        "Content-Type": "application/json",
        "HTTP-Referer": "http://localhost:test",
        "X-Title": "TestProxy",
    }

@pytest.fixture
def openrouter_backend():
    return OpenRouterBackend()

@pytest.fixture
def sample_chat_request_data() -> ChatCompletionRequest:
    return ChatCompletionRequest(
        model="test-model",
        messages=[ChatMessage(role="user", content="Hello")]
    )

@pytest.fixture
def sample_processed_messages() -> List[ChatMessage]:
    return [ChatMessage(role="user", content="Hello")]


@pytest.mark.asyncio
async def test_chat_completions_non_streaming_success(
    openrouter_backend: OpenRouterBackend,
    httpx_mock: httpx.MockTransport,
    sample_chat_request_data: ChatCompletionRequest,
    sample_processed_messages: List[ChatMessage]
):
    sample_chat_request_data.stream = False
    effective_model = "openai/gpt-3.5-turbo"

    # Mock successful response from OpenRouter
    mock_response_payload = {
        "id": "test_completion_id",
        "choices": [{"message": {"role": "assistant", "content": "Hi there!"}}],
        "model": effective_model,
        "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15}
    }
    httpx_mock.add_response(
        url=f"{TEST_OPENROUTER_API_BASE_URL}/chat/completions",
        method="POST",
        json=mock_response_payload,
        status_code=200
    )

    async with httpx.AsyncClient(transport=httpx_mock) as client:
        response = await openrouter_backend.chat_completions(
            request_data=sample_chat_request_data,
            processed_messages=sample_processed_messages,
            effective_model=effective_model,
            client=client,
            openrouter_api_base_url=TEST_OPENROUTER_API_BASE_URL,
            openrouter_headers_provider=mock_get_openrouter_headers
        )

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


@pytest.mark.asyncio
async def test_chat_completions_streaming_success(
    openrouter_backend: OpenRouterBackend,
    httpx_mock: httpx.MockTransport,
    sample_chat_request_data: ChatCompletionRequest,
    sample_processed_messages: List[ChatMessage]
):
    sample_chat_request_data.stream = True
    effective_model = "openai/gpt-4"

    # Mock streaming response chunks
    stream_chunks = [
        b'data: {"id": "chatcmpl-xxxx", "object": "chat.completion.chunk", "created": 123, "model": "',
        bytes(effective_model, 'utf-8'),
        b'", "choices": [{"index": 0, "delta": {"role": "assistant"}, "finish_reason": null}]}\n\n',
        b'data: {"id": "chatcmpl-xxxx", "object": "chat.completion.chunk", "created": 123, "model": "',
        bytes(effective_model, 'utf-8'),
        b'", "choices": [{"index": 0, "delta": {"content": "Hello"}, "finish_reason": null}]}\n\n',
        b'data: {"id": "chatcmpl-xxxx", "object": "chat.completion.chunk", "created": 123, "model": "',
        bytes(effective_model, 'utf-8'),
        b'", "choices": [{"index": 0, "delta": {"content": " world!"}, "finish_reason": null}]}\n\n',
        b'data: [DONE]\n\n'
    ]

    httpx_mock.add_response(
        url=f"{TEST_OPENROUTER_API_BASE_URL}/chat/completions",
        method="POST",
        stream=httpx.ByteStream(stream_chunks), # Use ByteStream for streaming
        status_code=200,
        headers={"Content-Type": "text/event-stream"}
    )

    async with httpx.AsyncClient(transport=httpx_mock) as client:
        response = await openrouter_backend.chat_completions(
            request_data=sample_chat_request_data,
            processed_messages=sample_processed_messages,
            effective_model=effective_model,
            client=client,
            openrouter_api_base_url=TEST_OPENROUTER_API_BASE_URL,
            openrouter_headers_provider=mock_get_openrouter_headers
        )

    assert isinstance(response, StreamingResponse)

    # Consume the stream and check content
    content = b""
    async for chunk in response.body_iterator:
        content += chunk

    expected_content = b"".join(stream_chunks)
    assert content == expected_content

    # Verify request payload
    request = httpx_mock.get_request()
    assert request is not None
    sent_payload = json.loads(request.content)
    assert sent_payload["model"] == effective_model
    assert sent_payload["stream"] is True


@pytest.mark.asyncio
async def test_chat_completions_http_error_non_streaming(
    openrouter_backend: OpenRouterBackend,
    httpx_mock: httpx.MockTransport,
    sample_chat_request_data: ChatCompletionRequest,
    sample_processed_messages: List[ChatMessage]
):
    sample_chat_request_data.stream = False
    error_payload = {"error": {"message": "Insufficient credits", "type": "billing_error"}}

    httpx_mock.add_response(
        url=f"{TEST_OPENROUTER_API_BASE_URL}/chat/completions",
        method="POST",
        json=error_payload,
        status_code=402 # Payment Required
    )

    async with httpx.AsyncClient(transport=httpx_mock) as client:
        with pytest.raises(HTTPException) as exc_info:
            await openrouter_backend.chat_completions(
                request_data=sample_chat_request_data,
                processed_messages=sample_processed_messages,
                effective_model="test-model",
                client=client,
                openrouter_api_base_url=TEST_OPENROUTER_API_BASE_URL,
                openrouter_headers_provider=mock_get_openrouter_headers
            )

    assert exc_info.value.status_code == 402
    assert exc_info.value.detail == error_payload # Connector should pass through OpenRouter's error


@pytest.mark.asyncio
async def test_chat_completions_http_error_streaming(
    openrouter_backend: OpenRouterBackend,
    httpx_mock: httpx.MockTransport,
    sample_chat_request_data: ChatCompletionRequest,
    sample_processed_messages: List[ChatMessage]
):
    sample_chat_request_data.stream = True
    error_text_response = "OpenRouter internal server error"

    httpx_mock.add_response(
        url=f"{TEST_OPENROUTER_API_BASE_URL}/chat/completions",
        method="POST",
        text=error_text_response, # Non-JSON error
        status_code=500
    )

    async with httpx.AsyncClient(transport=httpx_mock) as client:
        response = await openrouter_backend.chat_completions(
            request_data=sample_chat_request_data,
            processed_messages=sample_processed_messages,
            effective_model="test-model",
            client=client,
            openrouter_api_base_url=TEST_OPENROUTER_API_BASE_URL,
            openrouter_headers_provider=mock_get_openrouter_headers
        )

    assert isinstance(response, StreamingResponse)
    # Check if the stream yields the error message in SSE format
    content = b""
    async for chunk in response.body_iterator:
        content += chunk

    # The connector should format this as an SSE error event
    # Example: data: {"error": {"message": "OpenRouter stream error: 500 - OpenRouter internal server error", ...}}\n\n
    assert b"data:" in content
    assert b"OpenRouter stream error: 500" in content
    assert b"OpenRouter internal server error" in content
    assert b'"type": "openrouter_error"' in content

@pytest.mark.asyncio
async def test_chat_completions_request_error(
    openrouter_backend: OpenRouterBackend,
    httpx_mock: httpx.MockTransport,
    sample_chat_request_data: ChatCompletionRequest,
    sample_processed_messages: List[ChatMessage]
):
    httpx_mock.add_exception(httpx.ConnectError("Connection failed"))

    async with httpx.AsyncClient(transport=httpx_mock) as client:
        with pytest.raises(HTTPException) as exc_info:
            await openrouter_backend.chat_completions(
                request_data=sample_chat_request_data,
                processed_messages=sample_processed_messages,
                effective_model="test-model",
                client=client,
                openrouter_api_base_url=TEST_OPENROUTER_API_BASE_URL,
                openrouter_headers_provider=mock_get_openrouter_headers
            )

    assert exc_info.value.status_code == 503 # Service Unavailable
    assert "Could not connect to OpenRouter" in exc_info.value.detail
    assert "Connection failed" in exc_info.value.detail


@pytest.mark.asyncio
async def test_payload_construction_and_headers(
    openrouter_backend: OpenRouterBackend,
    httpx_mock: httpx.MockTransport,
    sample_chat_request_data: ChatCompletionRequest,
):
    sample_chat_request_data.stream = False
    sample_chat_request_data.max_tokens = 100
    sample_chat_request_data.temperature = 0.7

    processed_msgs = [
        ChatMessage(role="user", content="Hello"),
        ChatMessage(role="assistant", content="Hi there!"), # Example of multi-turn
        ChatMessage(role="user", content=[ # Multimodal example
            MessageContentPartText(type="text", text="What is this?"),
            MessageContentPart(type="image_url", image_url={"url": "data:..."})
        ])
    ]
    effective_model = "some/model-name"

    httpx_mock.add_response(status_code=200, json={"choices": [{"message": {"content": "ok"}}]}) # Dummy success

    async with httpx.AsyncClient(transport=httpx_mock) as client:
        await openrouter_backend.chat_completions(
            request_data=sample_chat_request_data,
            processed_messages=processed_msgs,
            effective_model=effective_model,
            client=client,
            openrouter_api_base_url=TEST_OPENROUTER_API_BASE_URL,
            openrouter_headers_provider=mock_get_openrouter_headers
        )

    request = httpx_mock.get_request()
    assert request is not None

    # Check headers
    assert request.headers["Authorization"] == "Bearer FAKE_KEY"
    assert request.headers["Content-Type"] == "application/json"
    assert request.headers["HTTP-Referer"] == "http://localhost:test" # From mock_get_openrouter_headers
    assert request.headers["X-Title"] == "TestProxy"           # From mock_get_openrouter_headers

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
    # e.g., if 'n' was not set in sample_chat_request_data, it shouldn't be in payload
    assert "n" not in sent_payload # Assuming 'n' was not set in fixture
    assert "logit_bias" not in sent_payload # Assuming 'logit_bias' was not set

    # Check if original request_data was not modified (important due to model_dump)
    assert sample_chat_request_data.model == "test-model" # Original model name
    assert sample_chat_request_data.messages[0].content == "Hello" # Original messages
    assert sample_chat_request_data.max_tokens == 100 # Original value

    # The connector receives 'processed_messages' which are already Pydantic models.
    # It then dumps them to dicts for the payload.
    assert isinstance(processed_msgs[0], ChatMessage)
    assert isinstance(processed_msgs[2].content[0], MessageContentPartText)
    assert isinstance(processed_msgs[2].content[1], MessageContentPart) # This is a Pydantic model

    # The `openrouter_payload["messages"]` line in the connector does:
    # `[msg.model_dump(exclude_unset=True) for msg in processed_messages]`
    # So, `msg` here is a `ChatMessage` model. Its `content` can be str or List[MessageContentPartModel].
    # `msg.model_dump()` will convert these appropriately.
    # The test verifies this by checking `sent_payload["messages"]`.
