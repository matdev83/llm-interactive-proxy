"""Unit tests for Anthropic front-end converters."""

import json
from unittest.mock import Mock

from src.anthropic_converters import (
    _map_finish_reason,
    anthropic_to_openai_request,
    extract_anthropic_usage,
    get_anthropic_models,
    openai_stream_to_anthropic_stream,
    openai_to_anthropic_response,
)
from src.anthropic_models import AnthropicMessage, AnthropicMessagesRequest
from src.core.domain.chat import ChatRequest


class TestAnthropicConverters:
    """Test suite for Anthropic front-end converters."""

    def test_anthropic_message_model(self) -> None:
        """Test AnthropicMessage model validation."""
        msg = AnthropicMessage(role="user", content="Hello")
        assert msg.role == "user"
        assert msg.content == "Hello"

    def test_anthropic_messages_request_model(self) -> None:
        """Test AnthropicMessagesRequest model validation."""
        req = AnthropicMessagesRequest(
            model="claude-3-sonnet-20240229",
            messages=[AnthropicMessage(role="user", content="Hello")],
            max_tokens=100,
            temperature=0.7,
            top_p=0.9,
            system="You are helpful",
            stream=True,
        )
        assert req.model == "claude-3-sonnet-20240229"
        assert len(req.messages) == 1
        assert req.max_tokens == 100
        assert req.temperature == 0.7
        assert req.top_p == 0.9
        assert req.system == "You are helpful"
        assert req.stream is True

    def test_anthropic_to_openai_request_basic(self) -> None:
        """Test basic Anthropic to OpenAI request conversion."""
        anthropic_req = AnthropicMessagesRequest(
            model="claude-3-sonnet-20240229",
            messages=[AnthropicMessage(role="user", content="Hello")],
            max_tokens=100,
        )

        openai_req = anthropic_to_openai_request(anthropic_req)

        assert openai_req["model"] == "claude-3-sonnet-20240229"
        assert openai_req["max_tokens"] == 100
        assert openai_req["stream"] is False
        assert len(openai_req["messages"]) == 1
        assert openai_req["messages"][0]["role"] == "user"
        assert openai_req["messages"][0]["content"] == "Hello"

    def test_anthropic_to_openai_request_with_system(self) -> None:
        """Test conversion with system message."""
        anthropic_req = AnthropicMessagesRequest(
            model="claude-3-haiku-20240307",
            messages=[AnthropicMessage(role="user", content="Hello")],
            max_tokens=50,
            system="You are a helpful assistant",
        )

        openai_req = anthropic_to_openai_request(anthropic_req)

        assert len(openai_req["messages"]) == 2
        assert openai_req["messages"][0]["role"] == "system"
        assert openai_req["messages"][0]["content"] == "You are a helpful assistant"
        assert openai_req["messages"][1]["role"] == "user"
        assert openai_req["messages"][1]["content"] == "Hello"

    def test_anthropic_to_openai_request_with_parameters(self) -> None:
        """Test conversion with all optional parameters."""
        anthropic_req = AnthropicMessagesRequest(
            model="claude-3-opus-20240229",
            messages=[AnthropicMessage(role="user", content="Test")],
            max_tokens=200,
            temperature=0.8,
            top_p=0.95,
            top_k=40,  # Should be dropped
            stop_sequences=["STOP", "END"],
            stream=True,
        )

        openai_req = anthropic_to_openai_request(anthropic_req)

        assert openai_req["temperature"] == 0.8
        assert openai_req["top_p"] == 0.95
        assert "top_k" not in openai_req  # Should be dropped
        assert openai_req["stop"] == ["STOP", "END"]
        assert openai_req["stream"] is True

    def test_anthropic_to_openai_request_tool_use_and_results(self) -> None:
        """Tool use blocks convert to OpenAI tool calls and tool messages."""

        anthropic_req = AnthropicMessagesRequest(
            model="claude-3-sonnet-20240229",
            messages=[
                AnthropicMessage(role="user", content="Run a lookup"),
                AnthropicMessage(
                    role="assistant",
                    content=[
                        {
                            "type": "tool_use",
                            "id": "toolu_1",
                            "name": "lookup_weather",
                            "input": {"location": "San Francisco"},
                        }
                    ],
                ),
                AnthropicMessage(
                    role="user",
                    content=[
                        {
                            "type": "tool_result",
                            "tool_use_id": "toolu_1",
                            "content": "65F and sunny",
                        }
                    ],
                ),
            ],
        )

        openai_req = anthropic_to_openai_request(anthropic_req)
        assert [m["role"] for m in openai_req["messages"]] == [
            "user",
            "assistant",
            "tool",
        ]

        chat_request = ChatRequest(**openai_req)
        assistant_message = chat_request.messages[1]
        assert assistant_message.tool_calls is not None
        assert len(assistant_message.tool_calls) == 1
        tool_call = assistant_message.tool_calls[0]
        assert tool_call.function.name == "lookup_weather"
        assert json.loads(tool_call.function.arguments) == {
            "location": "San Francisco"
        }

        tool_message = chat_request.messages[2]
        assert tool_message.role == "tool"
        assert tool_message.tool_call_id == "toolu_1"
        assert tool_message.content == "65F and sunny"

    def test_openai_to_anthropic_response_basic(self) -> None:
        """Test basic OpenAI to Anthropic response conversion."""
        openai_response = {
            "id": "chatcmpl-123",
            "object": "chat.completion",
            "model": "claude-3-sonnet-20240229",
            "choices": [
                {
                    "index": 0,
                    "message": {
                        "role": "assistant",
                        "content": "Hello! How can I help you?",
                    },
                    "finish_reason": "stop",
                }
            ],
            "usage": {"prompt_tokens": 10, "completion_tokens": 15, "total_tokens": 25},
        }

        anthropic_response = openai_to_anthropic_response(openai_response)

        assert anthropic_response["id"] == "chatcmpl-123"
        assert anthropic_response["type"] == "message"
        assert anthropic_response["role"] == "assistant"
        assert anthropic_response["model"] == "claude-3-sonnet-20240229"
        assert anthropic_response["stop_reason"] == "end_turn"
        assert len(anthropic_response["content"]) == 1
        assert anthropic_response["content"][0]["type"] == "text"
        assert anthropic_response["content"][0]["text"] == "Hello! How can I help you?"
        assert anthropic_response["usage"]["input_tokens"] == 10
        assert anthropic_response["usage"]["output_tokens"] == 15

    def test_openai_stream_to_anthropic_stream_start(self) -> None:
        """Test OpenAI stream chunk to Anthropic stream conversion - start."""
        openai_chunk = 'data: {"id": "chatcmpl-123", "object": "chat.completion.chunk", "choices": [{"index": 0, "delta": {"role": "assistant"}}]}'

        anthropic_chunk = openai_stream_to_anthropic_stream(openai_chunk)

        assert anthropic_chunk.startswith("data: ")
        assert "message_start" in anthropic_chunk
        assert "assistant" in anthropic_chunk

    def test_openai_stream_to_anthropic_stream_content(self) -> None:
        """Test OpenAI stream chunk to Anthropic stream conversion - content."""
        openai_chunk = 'data: {"id": "chatcmpl-123", "object": "chat.completion.chunk", "choices": [{"index": 0, "delta": {"content": "Hello"}}]}'

        anthropic_chunk = openai_stream_to_anthropic_stream(openai_chunk)

        assert anthropic_chunk.startswith("data: ")
        assert "content_block_delta" in anthropic_chunk
        assert "Hello" in anthropic_chunk

    def test_openai_stream_to_anthropic_stream_finish(self) -> None:
        """Test OpenAI stream chunk to Anthropic stream conversion - finish."""
        openai_chunk = 'data: {"id": "chatcmpl-123", "object": "chat.completion.chunk", "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}]}'

        anthropic_chunk = openai_stream_to_anthropic_stream(openai_chunk)

        assert anthropic_chunk.startswith("data: ")
        assert "message_delta" in anthropic_chunk
        assert "end_turn" in anthropic_chunk

    def test_openai_stream_to_anthropic_stream_invalid(self) -> None:
        """Test handling of invalid OpenAI stream chunks."""
        invalid_chunk = "invalid data"

        anthropic_chunk = openai_stream_to_anthropic_stream(invalid_chunk)

        # Should pass through unchanged
        assert anthropic_chunk == invalid_chunk

    def test_map_finish_reason(self) -> None:
        """Test finish reason mapping."""
        assert _map_finish_reason("stop") == "end_turn"
        assert _map_finish_reason("length") == "max_tokens"
        assert _map_finish_reason("content_filter") == "stop_sequence"
        assert _map_finish_reason("function_call") == "tool_use"
        assert _map_finish_reason(None) is None
        assert _map_finish_reason("unknown") == "end_turn"

    def test_get_anthropic_models(self) -> None:
        """Test Anthropic models endpoint response."""
        models_response = get_anthropic_models()

        assert models_response["object"] == "list"
        assert "data" in models_response
        assert len(models_response["data"]) > 0

        # Check for expected models
        model_ids = [model["id"] for model in models_response["data"]]
        assert "claude-3-5-sonnet-20241022" in model_ids
        assert "claude-3-5-haiku-20241022" in model_ids
        assert "claude-3-opus-20240229" in model_ids

        # Check model structure
        first_model = models_response["data"][0]
        assert "id" in first_model
        assert "object" in first_model
        assert "created" in first_model
        assert "owned_by" in first_model
        assert first_model["owned_by"] == "anthropic"

    def test_extract_anthropic_usage_dict(self) -> None:
        """Test usage extraction from dictionary response."""
        response = {"usage": {"input_tokens": 50, "output_tokens": 75}}

        usage = extract_anthropic_usage(response)

        assert usage["input_tokens"] == 50
        assert usage["output_tokens"] == 75
        assert usage["total_tokens"] == 125

    def test_extract_anthropic_usage_object(self) -> None:
        """Test usage extraction from object response."""
        mock_usage = Mock()
        mock_usage.input_tokens = 30
        mock_usage.output_tokens = 45

        mock_response = Mock()
        mock_response.usage = mock_usage

        usage = extract_anthropic_usage(mock_response)

        assert usage["input_tokens"] == 30
        assert usage["output_tokens"] == 45
        assert usage["total_tokens"] == 75

    def test_extract_anthropic_usage_empty(self) -> None:
        """Test usage extraction with empty/invalid response."""
        usage = extract_anthropic_usage({})

        assert usage["input_tokens"] == 0
        assert usage["output_tokens"] == 0
        assert usage["total_tokens"] == 0

    def test_conversation_flow(self) -> None:
        """Test a complete conversation flow conversion."""
        # Multi-turn conversation
        anthropic_req = AnthropicMessagesRequest(
            model="claude-3-sonnet-20240229",
            messages=[
                AnthropicMessage(role="user", content="What is 2+2?"),
                AnthropicMessage(role="assistant", content="2+2 equals 4."),
                AnthropicMessage(role="user", content="What about 3+3?"),
            ],
            max_tokens=50,
            system="You are a math tutor",
        )

        openai_req = anthropic_to_openai_request(anthropic_req)

        # Should have system + 3 conversation messages
        assert len(openai_req["messages"]) == 4
        assert openai_req["messages"][0]["role"] == "system"
        assert openai_req["messages"][1]["role"] == "user"
        assert openai_req["messages"][1]["content"] == "What is 2+2?"
        assert openai_req["messages"][2]["role"] == "assistant"
        assert openai_req["messages"][2]["content"] == "2+2 equals 4."
        assert openai_req["messages"][3]["role"] == "user"
        assert openai_req["messages"][3]["content"] == "What about 3+3?"
