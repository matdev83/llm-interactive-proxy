from __future__ import annotations

import json
import time
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest
from fastapi import HTTPException
from src.connectors.qwen_oauth import QwenOAuthConnector
from src.core.domain.chat import (
    ChatMessage,
    ChatRequest,
    FunctionCall,
    FunctionDefinition,
    ToolCall,
    ToolDefinition,
)
from src.core.domain.responses import ResponseEnvelope, StreamingResponseEnvelope
from starlette.responses import StreamingResponse


class TestQwenOAuthToolCallingEnhanced:
    """Enhanced tests for tool calling functionality in QwenOAuthConnector."""

    @pytest.fixture
    def mock_client(self):
        """Mock httpx.AsyncClient."""
        return MagicMock(spec=httpx.AsyncClient)

    @pytest.fixture
    def connector(self, mock_client):
        """QwenOAuthConnector instance with mocked client."""
        connector = QwenOAuthConnector(mock_client)
        connector._oauth_credentials = {
            "access_token": "test-access-token",
            "refresh_token": "test-refresh-token",
            "token_type": "Bearer",
            "resource_url": "portal.qwen.ai",
            "expiry_date": int(time.time() * 1000) + 3600000,  # 1 hour from now
        }
        return connector

    @pytest.mark.asyncio
    async def test_chat_completions_with_tools(self, connector):
        """Test chat completion request with tools parameter."""
        # Define tools
        tools = [
            ToolDefinition(
                type="function",
                function=FunctionDefinition(
                    name="get_weather",
                    description="Get the current weather for a location",
                    parameters={
                        "type": "object",
                        "properties": {
                            "location": {
                                "type": "string",
                                "description": "The city and state",
                            }
                        },
                        "required": ["location"],
                    },
                ),
            )
        ]

        test_message = ChatMessage(role="user", content="What's the weather?")
        request_data = ChatRequest(
            model="qwen3-coder-plus",
            messages=[test_message],
            tools=tools,
            tool_choice="auto",
            stream=False,
        )

        # Mock response data
        mock_response_data = {
            "id": "test-id",
            "choices": [
                {
                    "message": {
                        "role": "assistant",
                        "content": None,
                        "tool_calls": [
                            {
                                "id": "call_123",
                                "type": "function",
                                "function": {
                                    "name": "get_weather",
                                    "arguments": '{"location": "San Francisco"}',
                                },
                            }
                        ],
                    },
                    "finish_reason": "tool_calls",
                }
            ],
            "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
        }
        mock_headers = {"content-type": "application/json"}

        # Directly mock the parent class's chat_completions method
        from src.core.domain.responses import ResponseEnvelope

        with (
            patch.object(
                connector, "_refresh_token_if_needed", AsyncMock(return_value=True)
            ),
            patch(
                "src.connectors.openai.OpenAIConnector.chat_completions",
                AsyncMock(
                    return_value=ResponseEnvelope(
                        content=mock_response_data, headers=mock_headers
                    )
                ),
            ),
        ):
            # Act
            result = await connector.chat_completions(
                request_data=request_data,
                processed_messages=[test_message],
                effective_model="qwen3-coder-plus",
            )

            # Assert
            response_data = result.content
            # headers = result.headers

            # Verify response contains tool calls
            assert "choices" in response_data
            choice = response_data["choices"][0]
            assert choice["finish_reason"] == "tool_calls"
            assert choice["message"]["tool_calls"] is not None
            assert len(choice["message"]["tool_calls"]) == 1

            tool_call = choice["message"]["tool_calls"][0]
            assert tool_call["function"]["name"] == "get_weather"
            assert json.loads(tool_call["function"]["arguments"]) == {
                "location": "San Francisco"
            }

    @pytest.mark.asyncio
    async def test_chat_completions_tool_choice_none(self, connector):
        """Test chat completion with tool_choice set to 'none'."""
        tools = [
            ToolDefinition(
                type="function",
                function=FunctionDefinition(
                    name="get_time",
                    description="Get the current time",
                    parameters={"type": "object", "properties": {}},
                ),
            )
        ]

        test_message = ChatMessage(role="user", content="What time is it?")
        request_data = ChatRequest(
            model="qwen3-coder-plus",
            messages=[test_message],
            tools=tools,
            tool_choice="none",  # Explicitly disable tool calling
            stream=False,
        )

        # Mock response data
        mock_response_data = {
            "id": "test-id",
            "choices": [
                {
                    "message": {
                        "role": "assistant",
                        "content": "I cannot access the current time directly.",
                    },
                    "finish_reason": "stop",
                }
            ],
            "usage": {"prompt_tokens": 8, "completion_tokens": 10, "total_tokens": 18},
        }
        mock_headers = {"content-type": "application/json"}

        # Create a wrapper around chat_completions to capture payload
        payload_capture = {}

        async def mock_chat_completions(*args, **kwargs):
            # Capture the payload for verification
            payload_capture["payload"] = kwargs.get("request_data")
            return ResponseEnvelope(content=mock_response_data, headers=mock_headers)

        # Create the mock for the parent class's chat_completions method
        parent_chat_completions_mock = AsyncMock(side_effect=mock_chat_completions)

        # Directly mock the parent class's chat_completions method
        with (
            patch.object(
                connector, "_refresh_token_if_needed", AsyncMock(return_value=True)
            ),
            patch(
                "src.connectors.openai.OpenAIConnector.chat_completions",
                parent_chat_completions_mock,
            ),
        ):
            # Act
            result = await connector.chat_completions(
                request_data=request_data,
                processed_messages=[test_message],
                effective_model="qwen3-coder-plus",
            )

            # Verify the parent class's chat_completions method was called
            parent_chat_completions_mock.assert_called_once()

            # Assert
            response_data = result.content
            # headers = result.headers

            # Verify request contained the expected tool_choice
            assert payload_capture["payload"] is not None
            assert payload_capture["payload"].tool_choice == "none"

            # Verify response doesn't contain tool calls
            assert "choices" in response_data
            choice = response_data["choices"][0]
            assert choice["finish_reason"] == "stop"
            assert choice["message"]["content"] is not None
            assert (
                "tool_calls" not in choice["message"]
                or choice["message"]["tool_calls"] is None
            )

    @pytest.mark.asyncio
    async def test_chat_completions_specific_tool_choice(self, connector):
        """Test chat completion with specific function tool_choice."""
        tools = [
            ToolDefinition(
                type="function",
                function=FunctionDefinition(
                    name="get_weather",
                    description="Get weather information",
                    parameters={
                        "type": "object",
                        "properties": {"location": {"type": "string"}},
                        "required": ["location"],
                    },
                ),
            ),
            ToolDefinition(
                type="function",
                function=FunctionDefinition(
                    name="get_news",
                    description="Get news information",
                    parameters={
                        "type": "object",
                        "properties": {"topic": {"type": "string"}},
                        "required": ["topic"],
                    },
                ),
            ),
        ]

        test_message = ChatMessage(role="user", content="Get me information")
        request_data = ChatRequest(
            model="qwen3-coder-plus",
            messages=[test_message],
            tools=tools,
            tool_choice={"type": "function", "function": {"name": "get_weather"}},
            stream=False,
        )

        # Mock response data
        mock_response_data = {
            "id": "test-id",
            "choices": [
                {
                    "message": {
                        "role": "assistant",
                        "content": None,
                        "tool_calls": [
                            {
                                "id": "call_456",
                                "type": "function",
                                "function": {
                                    "name": "get_weather",
                                    "arguments": '{"location": "New York"}',
                                },
                            }
                        ],
                    },
                    "finish_reason": "tool_calls",
                }
            ],
            "usage": {"prompt_tokens": 12, "completion_tokens": 8, "total_tokens": 20},
        }
        mock_headers = {"content-type": "application/json"}

        # Create a wrapper around chat_completions to capture payload
        payload_capture = {}

        async def mock_chat_completions(*args, **kwargs):
            # Capture the payload for verification
            payload_capture["request_data"] = kwargs.get("request_data")
            return ResponseEnvelope(content=mock_response_data, headers=mock_headers)

        # Directly mock the parent class's chat_completions method
        with (
            patch.object(
                connector, "_refresh_token_if_needed", AsyncMock(return_value=True)
            ),
            patch(
                "src.connectors.openai.OpenAIConnector.chat_completions",
                AsyncMock(side_effect=mock_chat_completions),
            ),
        ):
            # Act
            result = await connector.chat_completions(
                request_data=request_data,
                processed_messages=[test_message],
                effective_model="qwen3-coder-plus",
            )

            # Assert
            response_data = result.content
            # headers = result.headers

            # Verify request contained the expected tool_choice
            assert payload_capture["request_data"] is not None
            assert payload_capture["request_data"].tool_choice["type"] == "function"
            assert (
                payload_capture["request_data"].tool_choice["function"]["name"]
                == "get_weather"
            )

            # Verify response contains the expected tool call
            assert "choices" in response_data
            choice = response_data["choices"][0]
            assert choice["finish_reason"] == "tool_calls"
            tool_call = choice["message"]["tool_calls"][0]
            assert tool_call["function"]["name"] == "get_weather"

    @pytest.mark.asyncio
    async def test_streaming_with_tool_calls(self, connector):
        """Test streaming response with tool calls."""
        tools = [
            ToolDefinition(
                type="function",
                function=FunctionDefinition(
                    name="search_web",
                    description="Search the web for information",
                    parameters={
                        "type": "object",
                        "properties": {"query": {"type": "string"}},
                        "required": ["query"],
                    },
                ),
            )
        ]

        test_message = ChatMessage(role="user", content="Search for Python info")
        request_data = ChatRequest(
            model="qwen3-coder-plus",
            messages=[test_message],
            tools=tools,
            tool_choice="auto",
            stream=True,
        )

        # Create streaming chunks
        streaming_chunks = [
            b'data: {"id":"test","choices":[{"delta":{"tool_calls":[{"index":0,"id":"call_789","type":"function","function":{"name":"search_web"}}]}}]}\n\n',
            b'data: {"id":"test","choices":[{"delta":{"tool_calls":[{"index":0,"function":{"arguments":"{\\"query\\": \\"Python programming\\"}"}}]}}]}\n\n',
            b'data: {"id":"test","choices":[{"delta":{},"finish_reason":"tool_calls"}]}\n\n',
            b"data: [DONE]\n\n",
        ]

        # Create a mock streaming response
        mock_stream_response = StreamingResponse(
            content=AsyncMock(return_value=streaming_chunks),
            media_type="text/event-stream",
        )

        # Create a StreamingResponseEnvelope to match what the Qwen connector expects

        mock_stream_envelope = StreamingResponseEnvelope(
            content=mock_stream_response.body_iterator,
            media_type="text/event-stream",
            headers=mock_stream_response.headers,
        )

        # Directly mock the parent class's chat_completions method for streaming
        with (
            patch.object(
                connector, "_refresh_token_if_needed", AsyncMock(return_value=True)
            ),
            patch(
                "src.connectors.openai.OpenAIConnector.chat_completions",
                AsyncMock(return_value=mock_stream_envelope),
            ),
        ):
            # Act
            result = await connector.chat_completions(
                request_data=request_data,
                processed_messages=[test_message],
                effective_model="qwen3-coder-plus",
            )

            # Assert
            assert isinstance(result, StreamingResponseEnvelope)
            assert result.media_type == "text/event-stream"

    @pytest.mark.asyncio
    async def test_multi_turn_tool_conversation(self, connector):
        """Test multi-turn conversation with tool calls and responses."""
        # First turn: User message
        user_message = ChatMessage(role="user", content="Calculate 10 + 5")

        # Second turn: Assistant tool call
        assistant_message = ChatMessage(
            role="assistant",
            tool_calls=[
                ToolCall(
                    id="call_calc_123",
                    type="function",
                    function=FunctionCall(
                        name="calculate", arguments='{"expression": "10 + 5"}'
                    ),
                )
            ],
        )

        # Third turn: Tool response
        tool_message = ChatMessage(
            role="tool", content="15", tool_call_id="call_calc_123"
        )

        messages = [user_message, assistant_message, tool_message]

        request_data = ChatRequest(
            model="qwen3-coder-plus",
            messages=messages,
            tools=[
                ToolDefinition(
                    type="function",
                    function=FunctionDefinition(
                        name="calculate",
                        description="Perform calculations",
                        parameters={
                            "type": "object",
                            "properties": {"expression": {"type": "string"}},
                            "required": ["expression"],
                        },
                    ),
                )
            ],
            stream=False,
        )

        # Mock response for the multi-turn conversation
        mock_response_data = {
            "id": "test-id",
            "choices": [
                {
                    "message": {
                        "role": "assistant",
                        "content": "The result of 10 + 5 is 15.",
                    },
                    "finish_reason": "stop",
                }
            ],
            "usage": {"prompt_tokens": 25, "completion_tokens": 12, "total_tokens": 37},
        }
        mock_headers = {"content-type": "application/json"}

        # Create a wrapper around chat_completions to capture payload
        payload_capture = {}

        async def mock_chat_completions(*args, **kwargs):
            # Capture the payload for verification
            payload_capture["request_data"] = kwargs.get("request_data")
            payload_capture["messages"] = kwargs.get("processed_messages")
            return ResponseEnvelope(content=mock_response_data, headers=mock_headers)

        # Directly mock the parent class's chat_completions method
        with (
            patch.object(
                connector, "_refresh_token_if_needed", AsyncMock(return_value=True)
            ),
            patch(
                "src.connectors.openai.OpenAIConnector.chat_completions",
                AsyncMock(side_effect=mock_chat_completions),
            ),
        ):
            # Act
            result = await connector.chat_completions(
                request_data=request_data,
                processed_messages=messages,
                effective_model="qwen3-coder-plus",
            )

            # Assert
            response_data = result.content
            # headers = result.headers

            # Verify the conversation context was properly passed
            assert payload_capture["messages"] == messages

            # Verify message types in the captured request
            messages_data = payload_capture["request_data"].model_dump()["messages"]
            assert len(messages_data) == 3
            assert messages_data[0]["role"] == "user"
            assert messages_data[1]["role"] == "assistant"
            assert messages_data[1]["tool_calls"] is not None
            assert messages_data[2]["role"] == "tool"
            assert messages_data[2]["tool_call_id"] == "call_calc_123"

            # Verify response contains expected content
            assert "choices" in response_data
            choice = response_data["choices"][0]
            assert choice["finish_reason"] == "stop"
            assert "15" in choice["message"]["content"]

    @pytest.mark.asyncio
    async def test_tool_calling_error_handling(self, connector):
        """Test error handling when tool calling fails."""
        tools = [
            ToolDefinition(
                type="function",
                function=FunctionDefinition(
                    name="failing_tool",
                    description="A tool that fails",
                    parameters={
                        "type": "object",
                        "properties": {"param": {"type": "string"}},
                        "required": ["param"],
                    },
                ),
            )
        ]

        test_message = ChatMessage(role="user", content="Use the failing tool")
        request_data = ChatRequest(
            model="qwen3-coder-plus",
            messages=[test_message],
            tools=tools,
            tool_choice="auto",
            stream=False,
        )

        # Directly mock the parent class's chat_completions method to raise an exception
        error_detail = {
            "error": {"message": "Invalid tool definition", "code": "invalid_parameter"}
        }

        with (
            patch.object(
                connector, "_refresh_token_if_needed", AsyncMock(return_value=True)
            ),
            patch(
                "src.connectors.openai.OpenAIConnector.chat_completions",
                AsyncMock(
                    side_effect=HTTPException(status_code=400, detail=error_detail)
                ),
            ),
        ):
            # Act & Assert
            with pytest.raises(HTTPException) as exc_info:
                await connector.chat_completions(
                    request_data=request_data,
                    processed_messages=[test_message],
                    effective_model="qwen3-coder-plus",
                )

            # Verify the exception was passed through with the correct status code
            assert exc_info.value.status_code == 400
            assert exc_info.value.detail == error_detail

    @pytest.mark.asyncio
    async def test_model_prefix_stripping(self, connector):
        """Test that qwen-oauth: prefix is properly stripped from model names."""
        test_message = ChatMessage(role="user", content="Test message")
        request_data = ChatRequest(
            model="qwen-oauth:qwen3-coder-plus",
            messages=[test_message],
            stream=False,
        )

        # Mock response data
        mock_response_data = {
            "id": "test-id",
            "choices": [
                {
                    "message": {
                        "role": "assistant",
                        "content": "Test response",
                    },
                    "finish_reason": "stop",
                }
            ],
            "usage": {"prompt_tokens": 5, "completion_tokens": 5, "total_tokens": 10},
        }
        mock_headers = {"content-type": "application/json"}

        # Create a wrapper around chat_completions to capture the effective model
        model_capture = {}

        async def mock_chat_completions(*args, **kwargs):
            # Capture the effective model for verification
            model_capture["effective_model"] = kwargs.get("effective_model")
            return ResponseEnvelope(content=mock_response_data, headers=mock_headers)

        # Directly mock the parent class's chat_completions method
        with (
            patch.object(
                connector, "_refresh_token_if_needed", AsyncMock(return_value=True)
            ),
            patch(
                "src.connectors.openai.OpenAIConnector.chat_completions",
                AsyncMock(side_effect=mock_chat_completions),
            ),
        ):
            # Act
            result = await connector.chat_completions(
                request_data=request_data,
                processed_messages=[test_message],
                effective_model="qwen-oauth:qwen3-coder-plus",
            )

            # Assert the prefix was stripped
            assert model_capture["effective_model"] == "qwen3-coder-plus"

            # Verify the response was passed through correctly
            response_data = result.content
            assert response_data["id"] == "test-id"


if __name__ == "__main__":
    # Allow running this file directly for quick testing
    pytest.main([__file__, "-v"])
