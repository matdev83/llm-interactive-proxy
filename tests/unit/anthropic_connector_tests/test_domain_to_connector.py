"""
Tests for Anthropic connector domain -> connector behavior.

This module tests that the Anthropic connector correctly processes domain models.
"""

import json

import httpx
import pytest
import pytest_asyncio
from pytest_httpx import HTTPXMock
from src.connectors.anthropic import (
    ANTHROPIC_DEFAULT_BASE_URL,
    ANTHROPIC_VERSION_HEADER,
    AnthropicBackend,
)
from src.core.domain.chat import (
    ChatMessage,
    ChatRequest,
    FunctionDefinition,
    ToolDefinition,
)

TEST_ANTHROPIC_API_BASE_URL = ANTHROPIC_DEFAULT_BASE_URL


@pytest_asyncio.fixture(name="anthropic_backend")
async def anthropic_backend_fixture() -> AnthropicBackend:
    """Create an Anthropic backend instance with a mock client."""
    async with httpx.AsyncClient() as client:
        from src.core.config.app_config import AppConfig
        from src.core.services.translation_service import TranslationService

        config = AppConfig()
        translation_service = TranslationService()
        backend = AnthropicBackend(client, config, translation_service)
        await backend.initialize(key_name="anthropic", api_key="test_key")
        yield backend


@pytest.mark.asyncio
async def test_chat_completions_basic_request(
    anthropic_backend: AnthropicBackend, httpx_mock: HTTPXMock
) -> None:
    """Test that a basic chat completion request is properly formatted for Anthropic."""
    # Setup the mock response
    httpx_mock.add_response(
        url=f"{TEST_ANTHROPIC_API_BASE_URL}/messages",
        method="POST",
        json={
            "id": "msg_123",
            "type": "message",
            "role": "assistant",
            "content": [{"type": "text", "text": "Hello, world!"}],
            "model": "claude-3-haiku-20240307",
            "stop_reason": "end_turn",
            "usage": {"input_tokens": 10, "output_tokens": 5},
        },
        status_code=200,
        headers={"Content-Type": "application/json"},
    )

    # Create a domain request
    request = ChatRequest(
        model="anthropic:claude-3-haiku-20240307",
        messages=[ChatMessage(role="user", content="Hello")],
        temperature=0.7,
        max_tokens=100,
        stream=False,
    )

    # Process the request
    processed_messages = [ChatMessage(role="user", content="Hello")]
    await anthropic_backend.chat_completions(
        request_data=request,
        processed_messages=processed_messages,
        effective_model="claude-3-haiku-20240307",
    )

    # Get the request that was sent
    sent_request = httpx_mock.get_request()
    assert sent_request is not None
    sent_payload = json.loads(sent_request.content)

    # Verify the payload
    assert sent_payload["model"] == "claude-3-haiku-20240307"
    assert sent_payload["temperature"] == 0.7
    assert sent_payload["max_tokens"] == 100
    assert not sent_payload.get("stream", False)
    assert len(sent_payload["messages"]) == 1
    assert sent_payload["messages"][0]["role"] == "user"
    assert sent_payload["messages"][0]["content"] == "Hello"

    # Verify Anthropic-specific headers
    assert sent_request.headers["anthropic-version"] == ANTHROPIC_VERSION_HEADER
    assert sent_request.headers["x-api-key"] == "test_key"


@pytest.mark.asyncio
async def test_chat_completions_with_system_message(
    anthropic_backend: AnthropicBackend, httpx_mock: HTTPXMock
) -> None:
    """Test that a chat completion request with system message is properly formatted."""
    # Setup the mock response
    httpx_mock.add_response(
        url=f"{TEST_ANTHROPIC_API_BASE_URL}/messages",
        method="POST",
        json={
            "id": "msg_123",
            "type": "message",
            "role": "assistant",
            "content": [
                {"type": "text", "text": "I'll help with weather information."}
            ],
            "model": "claude-3-haiku-20240307",
            "stop_reason": "end_turn",
            "usage": {"input_tokens": 15, "output_tokens": 7},
        },
        status_code=200,
        headers={"Content-Type": "application/json"},
    )

    # Create a domain request with system message
    request = ChatRequest(
        model="anthropic:claude-3-haiku-20240307",
        messages=[
            ChatMessage(role="system", content="You are a helpful weather assistant."),
            ChatMessage(role="user", content="What's the weather like?"),
        ],
        temperature=0.7,
        max_tokens=100,
        stream=False,
    )

    # Process the request
    processed_messages = [
        ChatMessage(role="system", content="You are a helpful weather assistant."),
        ChatMessage(role="user", content="What's the weather like?"),
    ]
    await anthropic_backend.chat_completions(
        request_data=request,
        processed_messages=processed_messages,
        effective_model="claude-3-haiku-20240307",
    )

    # Get the request that was sent
    sent_request = httpx_mock.get_request()
    assert sent_request is not None
    sent_payload = json.loads(sent_request.content)

    # Verify the system message is handled correctly
    assert "system" in sent_payload
    assert sent_payload["system"] == "You are a helpful weather assistant."

    # Verify the messages don't include the system message
    assert len(sent_payload["messages"]) == 1
    assert sent_payload["messages"][0]["role"] == "user"
    assert sent_payload["messages"][0]["content"] == "What's the weather like?"


@pytest.mark.asyncio
async def test_chat_completions_merges_metadata(
    anthropic_backend: AnthropicBackend, httpx_mock: HTTPXMock
) -> None:
    """Ensure metadata from project/user merges with extra_body metadata."""

    httpx_mock.add_response(
        url=f"{TEST_ANTHROPIC_API_BASE_URL}/messages",
        method="POST",
        json={
            "id": "msg_123",
            "type": "message",
            "role": "assistant",
            "content": [{"type": "text", "text": "Hello"}],
            "model": "claude-3-haiku-20240307",
            "stop_reason": "end_turn",
            "usage": {"input_tokens": 5, "output_tokens": 2},
        },
        status_code=200,
        headers={"Content-Type": "application/json"},
    )

    request = ChatRequest(
        model="anthropic:claude-3-haiku-20240307",
        messages=[ChatMessage(role="user", content="Hello")],
        stream=False,
        user="domain-user",
        extra_body={
            "metadata": {"source": "cli", "user_id": "override-user"},
            "custom_flag": True,
        },
    )

    await anthropic_backend.chat_completions(
        request_data=request,
        processed_messages=[ChatMessage(role="user", content="Hello")],
        effective_model="claude-3-haiku-20240307",
        project="project-123",
    )

    sent_request = httpx_mock.get_request()
    assert sent_request is not None
    sent_payload = json.loads(sent_request.content)

    assert sent_payload["metadata"] == {
        "project": "project-123",
        "source": "cli",
        "user_id": "override-user",
    }
    assert sent_payload["custom_flag"] is True


@pytest.mark.asyncio
async def test_chat_completions_with_tools(
    anthropic_backend: AnthropicBackend, httpx_mock: HTTPXMock
) -> None:
    """Test that a chat completion request with tools is properly formatted."""
    # Setup the mock response
    httpx_mock.add_response(
        url=f"{TEST_ANTHROPIC_API_BASE_URL}/messages",
        method="POST",
        json={
            "id": "msg_123",
            "type": "message",
            "role": "assistant",
            "content": [{"type": "text", "text": "I'll check the weather for you."}],
            "model": "claude-3-haiku-20240307",
            "stop_reason": "end_turn",
            "usage": {"input_tokens": 20, "output_tokens": 8},
        },
        status_code=200,
        headers={"Content-Type": "application/json"},
    )

    # Create tools
    tools = [
        ToolDefinition(
            type="function",
            function=FunctionDefinition(
                name="get_weather",
                description="Get the weather for a location",
                parameters={
                    "type": "object",
                    "properties": {
                        "location": {
                            "type": "string",
                            "description": "The location to get weather for",
                        }
                    },
                    "required": ["location"],
                },
            ),
        )
    ]

    # Create a domain request with tools
    request = ChatRequest(
        model="anthropic:claude-3-haiku-20240307",
        messages=[ChatMessage(role="user", content="What's the weather like?")],
        temperature=0.7,
        max_tokens=100,
        stream=False,
        tools=[t.model_dump() for t in tools],
        tool_choice="auto",
    )

    # Process the request
    processed_messages = [ChatMessage(role="user", content="What's the weather like?")]
    await anthropic_backend.chat_completions(
        request_data=request,
        processed_messages=processed_messages,
        effective_model="claude-3-haiku-20240307",
    )

    # Get the request that was sent
    sent_request = httpx_mock.get_request()
    assert sent_request is not None
    sent_payload = json.loads(sent_request.content)

    # Verify the tools in the payload
    assert "tools" in sent_payload
    assert len(sent_payload["tools"]) == 1
    assert sent_payload["tools"][0]["function"]["name"] == "get_weather"

    # Anthropic doesn't have a direct tool_choice parameter like OpenAI
    assert "tool_choice" not in sent_payload


@pytest.mark.asyncio
async def test_chat_completions_streaming(
    anthropic_backend: AnthropicBackend, httpx_mock: HTTPXMock
) -> None:
    """Test that a streaming chat completion request is properly formatted."""
    # Setup the mock response for streaming
    httpx_mock.add_response(
        url=f"{TEST_ANTHROPIC_API_BASE_URL}/messages",
        method="POST",
        content=b'data: {"type": "message_start", "message": {"id": "msg_123", "type": "message", "role": "assistant", "model": "claude-3-haiku-20240307"}}\n\n'
        b'data: {"type": "content_block_start", "index": 0, "content_block": {"type": "text"}}\n\n'
        b'data: {"type": "content_block_delta", "index": 0, "delta": {"type": "text_delta", "text": "Hello"}}\n\n'
        b'data: {"type": "content_block_delta", "index": 0, "delta": {"type": "text_delta", "text": ", world!"}}\n\n'
        b'data: {"type": "content_block_stop", "index": 0}\n\n'
        b'data: {"type": "message_delta", "delta": {"stop_reason": "end_turn", "usage": {"input_tokens": 10, "output_tokens": 5}}}\n\n'
        b'data: {"type": "message_stop"}\n\n',
        status_code=200,
        headers={"Content-Type": "text/event-stream"},
    )

    # Create a domain request with streaming
    request = ChatRequest(
        model="anthropic:claude-3-haiku-20240307",
        messages=[ChatMessage(role="user", content="Hello")],
        temperature=0.7,
        max_tokens=100,
        stream=True,
    )

    # Process the request
    processed_messages = [ChatMessage(role="user", content="Hello")]
    response = await anthropic_backend.chat_completions(
        request_data=request,
        processed_messages=processed_messages,
        effective_model="claude-3-haiku-20240307",
    )

    # Get the request that was sent
    sent_request = httpx_mock.get_request()
    assert sent_request is not None
    sent_payload = json.loads(sent_request.content)

    # Verify the payload for streaming
    assert sent_payload["stream"] is True

    # Verify the response is a StreamingResponseEnvelope (not StreamingResponse)
    from src.core.domain.responses import StreamingResponseEnvelope

    assert isinstance(response, StreamingResponseEnvelope)
    assert response.media_type == "text/event-stream"


@pytest.mark.asyncio
async def test_list_models(
    anthropic_backend: AnthropicBackend, httpx_mock: HTTPXMock
) -> None:
    """Test that the list_models method works correctly."""
    # Setup the mock response for models
    mock_models = [
        {"name": "claude-3-opus-20240229", "id": "claude-3-opus-20240229"},
        {"name": "claude-3-sonnet-20240229", "id": "claude-3-sonnet-20240229"},
        {"name": "claude-3-haiku-20240307", "id": "claude-3-haiku-20240307"},
    ]

    httpx_mock.add_response(
        url=f"{TEST_ANTHROPIC_API_BASE_URL}/models",
        method="GET",
        json={"models": mock_models},
        status_code=200,
        headers={"Content-Type": "application/json"},
    )

    # Call list_models
    models_data = await anthropic_backend.list_models()

    # Verify the models data
    assert isinstance(models_data, list)
    assert len(models_data) == 3
    assert models_data[0]["name"] == "claude-3-opus-20240229"

    # Verify that available_models is populated
    await anthropic_backend._ensure_models_loaded()
    available_models = anthropic_backend.get_available_models()
    assert "claude-3-opus-20240229" in available_models
    assert "claude-3-sonnet-20240229" in available_models
    assert "claude-3-haiku-20240307" in available_models
    assert len(available_models) == 3


@pytest.mark.asyncio
async def test_anthropic_error_handling(
    anthropic_backend: AnthropicBackend, httpx_mock: HTTPXMock
) -> None:
    """Test that errors from the Anthropic API are properly handled."""
    # Setup the mock error response
    httpx_mock.add_response(
        url=f"{TEST_ANTHROPIC_API_BASE_URL}/messages",
        method="POST",
        json={
            "error": {
                "type": "invalid_request_error",
                "message": "Invalid model specified",
            }
        },
        status_code=400,
        headers={"Content-Type": "application/json"},
    )

    # Create a domain request
    request = ChatRequest(
        model="anthropic:invalid-model",
        messages=[ChatMessage(role="user", content="Hello")],
        temperature=0.7,
        max_tokens=100,
        stream=False,
    )

    # Process the request and expect an exception
    processed_messages = [ChatMessage(role="user", content="Hello")]

    with pytest.raises(httpx.HTTPStatusError) as excinfo:
        await anthropic_backend.chat_completions(
            request_data=request,
            processed_messages=processed_messages,
            effective_model="invalid-model",
        )

    # Verify the exception contains the error message
    assert excinfo.value.response.status_code == 400
    error_content = json.loads(excinfo.value.response.content)
    assert "Invalid model specified" in error_content["error"]["message"]
