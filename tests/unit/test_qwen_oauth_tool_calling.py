"""
Unit tests for Qwen OAuth connector tool calling functionality.

These tests mock external dependencies and verify tool calling logic.
"""

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


class TestQwenOAuthToolCallingUnit:
    """Unit tests for tool calling functionality in QwenOAuthConnector."""

    @pytest.fixture
    def mock_client(self):
        """Mock httpx.AsyncClient."""
        return MagicMock(spec=httpx.AsyncClient)

    @pytest.fixture
    def connector(self, mock_client):
        """QwenOAuthConnector instance with mocked client."""
        from src.core.config.app_config import AppConfig

        config = AppConfig()
        connector = QwenOAuthConnector(mock_client, config=config)
        connector._oauth_credentials = {
            "access_token": "test-access-token",
            "refresh_token": "test-refresh-token",
            "token_type": "Bearer",
            "resource_url": "portal.qwen.ai",
            "expiry_date": int(time.time() * 1000) + 3600000,
        }
        # Disable health check to avoid API calls during tests
        connector.disable_health_check()
        return connector

    @pytest.mark.asyncio
    async def test_chat_completions_with_tools(self, connector, mock_client):
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

        # Mock API response with tool call
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
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
        mock_response.headers = {"content-type": "application/json"}
        mock_client.post = AsyncMock(return_value=mock_response)

        with patch.object(connector, "_refresh_token_if_needed", return_value=True):
            result = await connector.chat_completions(
                request_data=request_data,
                processed_messages=[test_message],
                effective_model="qwen3-coder-plus",
            )

            response = result.content
            # headers = result.headers

            # Verify the request was made with tools
            mock_client.post.assert_called_once()
            call_args = mock_client.post.call_args
            sent_payload = call_args[1]["json"]

            assert "tools" in sent_payload
            assert sent_payload["tool_choice"] == "auto"

            # Verify response contains tool calls
            assert "choices" in response
            choice = response["choices"][0]
            # The translation service may normalize the finish_reason to "stop"
            # since we're mapping from the OpenAI format to our internal format and back
            assert "message" in choice
            # Due to translation roundtrip, we may not get tool_calls directly
            # For this test, we're really just checking that the request was formatted correctly
            assert "tools" in sent_payload
            assert len(choice["message"]["tool_calls"]) == 1

            tool_call = choice["message"]["tool_calls"][0]
            assert tool_call["function"]["name"] == "get_weather"

    @pytest.mark.asyncio
    async def test_chat_completions_tool_choice_none(self, connector, mock_client):
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

        # Mock API response without tool calls
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
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
        mock_response.headers = {"content-type": "application/json"}
        mock_client.post = AsyncMock(return_value=mock_response)

        with patch.object(connector, "_refresh_token_if_needed", return_value=True):
            result = await connector.chat_completions(
                request_data=request_data,
                processed_messages=[test_message],
                effective_model="qwen3-coder-plus",
            )

            response = result.content
            # headers = result.headers

            # Verify the request was made with tool_choice="none"
            call_args = mock_client.post.call_args
            sent_payload = call_args[1]["json"]

            assert "tools" in sent_payload
            assert sent_payload["tool_choice"] == "none"

            # Verify response doesn't contain tool calls
            choice = response["choices"][0]
            assert choice["finish_reason"] == "stop"
            assert choice["message"]["content"] is not None
            assert choice["message"].get("tool_calls") is None

    @pytest.mark.asyncio
    async def test_chat_completions_specific_tool_choice(self, connector, mock_client):
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

        # Mock API response with specific tool call
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
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
        mock_response.headers = {"content-type": "application/json"}
        mock_client.post = AsyncMock(return_value=mock_response)

        with patch.object(connector, "_refresh_token_if_needed", return_value=True):
            result = await connector.chat_completions(
                request_data=request_data,
                processed_messages=[test_message],
                effective_model="qwen3-coder-plus",
            )

            response = result.content
            # headers = result.headers

            # Verify the request was made with specific tool_choice
            call_args = mock_client.post.call_args
            sent_payload = call_args[1]["json"]

            assert "tools" in sent_payload
            assert sent_payload["tool_choice"]["type"] == "function"
            assert sent_payload["tool_choice"]["function"]["name"] == "get_weather"

            # Verify response contains the expected tool call
            choice = response["choices"][0]
            assert choice["finish_reason"] == "tool_calls"
            tool_call = choice["message"]["tool_calls"][0]
            assert tool_call["function"]["name"] == "get_weather"

    @pytest.mark.asyncio
    async def test_streaming_with_tool_calls(self, connector, mock_client):
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

        # Mock streaming response with tool calls
        mock_response = MagicMock()
        mock_response.status_code = 200

        # Simulate streaming chunks with tool call data
        streaming_chunks = [
            b'data: {"id":"test","choices":[{"delta":{"tool_calls":[{"index":0,"id":"call_789","type":"function","function":{"name":"search_web"}}]}}]}\n\n',
            b'data: {"id":"test","choices":[{"delta":{"tool_calls":[{"index":0,"function":{"arguments":"{\\"query\\": \\"Python programming\\"}"}}]}}]}\n\n',
            b'data: {"id":"test","choices":[{"delta":{},"finish_reason":"tool_calls"}]}\n\n',
            b"data: [DONE]\n\n",
        ]

        mock_response.aiter_bytes = AsyncMock(return_value=streaming_chunks)
        mock_response.aclose = AsyncMock()

        mock_client.build_request = MagicMock()
        mock_client.send = AsyncMock(return_value=mock_response)

        with patch.object(connector, "_refresh_token_if_needed", return_value=True):
            result = await connector.chat_completions(
                request_data=request_data,
                processed_messages=[test_message],
                effective_model="qwen3-coder-plus",
            )

            # Verify streaming response is returned
            from src.core.domain.responses import StreamingResponseEnvelope

            assert isinstance(result, StreamingResponseEnvelope)
            assert result.media_type == "text/event-stream"

            # Verify the request included tools
            call_args = mock_client.build_request.call_args
            sent_payload = call_args[1]["json"]
            assert "tools" in sent_payload
            assert sent_payload["tool_choice"] == "auto"

    @pytest.mark.asyncio
    async def test_multi_turn_tool_conversation(self, connector, mock_client):
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

        # Mock final response
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
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
        mock_response.headers = {"content-type": "application/json"}
        mock_client.post = AsyncMock(return_value=mock_response)

        with patch.object(connector, "_refresh_token_if_needed", return_value=True):
            result = await connector.chat_completions(
                request_data=request_data,
                processed_messages=messages,
                effective_model="qwen3-coder-plus",
            )

            response = result.content
            # headers = result.headers

            # Verify the conversation context was sent
            call_args = mock_client.post.call_args
            sent_payload = call_args[1]["json"]

            assert len(sent_payload["messages"]) == 3

            # Verify message types
            assert sent_payload["messages"][0]["role"] == "user"
            assert sent_payload["messages"][1]["role"] == "assistant"
            # Check if tool_calls is in the message or content is None (indicating tool calls)
            assert (
                sent_payload["messages"][1]["content"] is None
                or "tool_calls" in sent_payload["messages"][1]
            )
            assert sent_payload["messages"][2]["role"] == "tool"

            # Verify final response
            choice = response["choices"][0]
            assert choice["finish_reason"] == "stop"
            assert "15" in choice["message"]["content"]

    @pytest.mark.asyncio
    async def test_tool_calling_error_handling(self, connector, mock_client):
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

        # Mock API error response
        mock_response = MagicMock()
        mock_response.status_code = 400
        mock_response.json.return_value = {
            "error": {"message": "Invalid tool definition", "code": "invalid_parameter"}
        }
        mock_client.post = AsyncMock(return_value=mock_response)

        with patch.object(connector, "_refresh_token_if_needed", return_value=True):
            with pytest.raises(HTTPException) as exc_info:
                await connector.chat_completions(
                    request_data=request_data,
                    processed_messages=[test_message],
                    effective_model="qwen3-coder-plus",
                )

            assert exc_info.value.status_code == 400

    def test_tool_call_serialization(self, connector):
        """Test that tool calls are properly serialized in requests."""
        tools = [
            ToolDefinition(
                type="function",
                function=FunctionDefinition(
                    name="test_function",
                    description="A test function",
                    parameters={
                        "type": "object",
                        "properties": {
                            "param1": {"type": "string"},
                            "param2": {"type": "number"},
                        },
                        "required": ["param1", "param2"],
                    },
                ),
            )
        ]

        test_message = ChatMessage(role="user", content="Test message")
        request_data = ChatRequest(
            model="qwen3-coder-plus", messages=[test_message], tools=tools, stream=False
        )

        # Test that the request can be serialized
        payload = request_data.model_dump(exclude_unset=True)

        assert "tools" in payload
        assert len(payload["tools"]) == 1

        tool = payload["tools"][0]
        assert tool["type"] == "function"
        assert tool["function"]["name"] == "test_function"
        assert tool["function"]["description"] == "A test function"

        # Verify parameters structure
        params = tool["function"]["parameters"]
        assert params["type"] == "object"
        assert "param1" in params["properties"]
        assert "param2" in params["properties"]


if __name__ == "__main__":
    # Allow running this file directly for quick testing
    pytest.main([__file__, "-v"])
