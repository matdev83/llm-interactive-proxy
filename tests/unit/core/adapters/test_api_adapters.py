"""
Tests for API Adapters module.

This module tests the conversion functions between different API formats
and the internal domain models.
"""

from typing import Any

import pytest
from src.core.adapters.api_adapters import (
    _convert_tool_calls,
    _convert_tools,
    anthropic_to_domain_chat_request,
    dict_to_domain_chat_request,
    gemini_to_domain_chat_request,
    openai_to_domain_chat_request,
)
from src.core.common.exceptions import InvalidRequestError
from src.core.domain.chat import (
    ChatMessage,
    ChatRequest,
    FunctionCall,
    ToolCall,
    ToolDefinition,
)


class TestDictToDomainChatRequest:
    """Tests for dict_to_domain_chat_request function."""

    def test_basic_conversion(self) -> None:
        """Test basic dict to domain conversion."""
        request_dict = {
            "model": "gpt-4",
            "messages": [{"role": "user", "content": "Hello"}],
            "temperature": 0.7,
        }

        result = dict_to_domain_chat_request(request_dict)

        assert isinstance(result, ChatRequest)
        assert result.model == "gpt-4"
        assert len(result.messages) == 1
        assert result.messages[0].role == "user"
        assert result.temperature == 0.7

    def test_empty_messages_raises_error(self) -> None:
        """Test that empty messages raises a domain InvalidRequestError."""
        request_dict = {
            "model": "gpt-4",
            "messages": [],
        }

        with pytest.raises(InvalidRequestError) as exc_info:
            dict_to_domain_chat_request(request_dict)
        # Validate domain error properties
        assert exc_info.value.status_code == 400
        assert getattr(exc_info.value, "param", None) == "messages"

    def test_convert_existing_chat_messages(self) -> None:
        """Test conversion with existing ChatMessage objects."""
        existing_message = ChatMessage(role="user", content="Hello")
        request_dict = {
            "model": "gpt-4",
            "messages": [existing_message],
        }

        result = dict_to_domain_chat_request(request_dict)

        assert isinstance(result, ChatRequest)
        assert len(result.messages) == 1
        assert result.messages[0] is existing_message  # Should be the same object

    def test_convert_legacy_message_objects(self) -> None:
        """Test conversion with legacy message objects."""

        class MockMessage:
            def __init__(self) -> None:
                self.role = "user"
                self.content = "Hello"
                self.name = "test_user"

            def model_dump(self) -> dict[str, Any]:
                return {"role": self.role, "content": self.content, "name": self.name}

        mock_message = MockMessage()
        request_dict = {
            "model": "gpt-4",
            "messages": [mock_message],
        }

        result = dict_to_domain_chat_request(request_dict)

        assert isinstance(result, ChatRequest)
        assert len(result.messages) == 1
        assert result.messages[0].role == "user"
        assert result.messages[0].content == "Hello"
        assert result.messages[0].name == "test_user"


class TestOpenAIToDomainChatRequest:
    """Tests for openai_to_domain_chat_request function."""

    def test_basic_openai_conversion(self) -> None:
        """Test basic OpenAI format conversion."""
        openai_request = {
            "model": "gpt-4",
            "messages": [{"role": "user", "content": "Hello"}],
            "temperature": 0.7,
            "max_tokens": 100,
        }

        result = openai_to_domain_chat_request(openai_request)

        assert isinstance(result, ChatRequest)
        assert result.model == "gpt-4"
        assert len(result.messages) == 1
        assert result.messages[0].role == "user"
        assert result.temperature == 0.7
        assert result.max_tokens == 100


class TestAnthropicToDomainChatRequest:
    """Tests for anthropic_to_domain_chat_request function."""

    def test_basic_anthropic_conversion(self) -> None:
        """Test basic Anthropic format conversion."""
        anthropic_request = {
            "model": "claude-3-haiku-20240307",
            "system": "You are a helpful assistant.",
            "messages": [{"role": "user", "content": "Hello"}],
            "temperature": 0.7,
            "max_tokens": 100,
            "stream": False,
        }

        result = anthropic_to_domain_chat_request(anthropic_request)

        assert isinstance(result, ChatRequest)
        assert result.model == "claude-3-haiku-20240307"
        assert len(result.messages) == 2  # system + user message
        assert result.messages[0].role == "system"
        assert result.messages[0].content == "You are a helpful assistant."
        assert result.messages[1].role == "user"
        assert result.messages[1].content == "Hello"
        assert result.temperature == 0.7
        assert result.max_tokens == 100

    def test_anthropic_without_system(self) -> None:
        """Test Anthropic conversion without system message."""
        anthropic_request = {
            "model": "claude-3-haiku-20240307",
            "messages": [{"role": "user", "content": "Hello"}],
            "temperature": 0.7,
        }

        result = anthropic_to_domain_chat_request(anthropic_request)

        assert isinstance(result, ChatRequest)
        assert len(result.messages) == 1
        assert result.messages[0].role == "user"
        assert result.messages[0].content == "Hello"


class TestGeminiToDomainChatRequest:
    """Tests for gemini_to_domain_chat_request function."""

    def test_basic_gemini_conversion(self) -> None:
        """Test basic Gemini format conversion."""
        gemini_request = {
            "model": "gemini-pro",
            "contents": [
                {
                    "role": "user",
                    "parts": [{"text": "Hello"}],
                }
            ],
            "generationConfig": {
                "temperature": 0.7,
                "maxOutputTokens": 100,
            },
            "stream": False,
        }

        result = gemini_to_domain_chat_request(gemini_request)

        assert isinstance(result, ChatRequest)
        assert result.model == "gemini-pro"
        assert len(result.messages) == 1
        assert result.messages[0].role == "user"
        assert result.messages[0].content == "Hello"
        assert result.temperature == 0.7
        assert result.max_tokens == 100

    def test_gemini_multiple_parts(self) -> None:
        """Test Gemini conversion with multiple text parts."""
        gemini_request = {
            "model": "gemini-pro",
            "contents": [
                {
                    "role": "user",
                    "parts": [
                        {"text": "Hello "},
                        {"text": "world!"},
                    ],
                }
            ],
        }

        result = gemini_to_domain_chat_request(gemini_request)

        assert isinstance(result, ChatRequest)
        assert result.messages[0].content == "Hello world!"

    def test_gemini_without_generation_config(self) -> None:
        """Test Gemini conversion without generation config."""
        gemini_request = {
            "model": "gemini-pro",
            "contents": [{"role": "user", "parts": [{"text": "Hello"}]}],
        }

        result = gemini_to_domain_chat_request(gemini_request)

        assert isinstance(result, ChatRequest)
        assert result.temperature is None
        assert result.max_tokens is None


class TestConvertToolCalls:
    """Tests for _convert_tool_calls function."""

    def test_none_input(self) -> None:
        """Test conversion with None input."""
        result = _convert_tool_calls(None)
        assert result is None

    def test_empty_list(self) -> None:
        """Test conversion with empty list."""
        result = _convert_tool_calls([])
        assert result is None

    def test_convert_dict_tool_calls(self) -> None:
        """Test conversion from dict format."""
        tool_calls = [
            {
                "id": "call_123",
                "type": "function",
                "function": {"name": "get_weather", "arguments": '{"location": "NYC"}'},
            }
        ]

        result = _convert_tool_calls(tool_calls)

        assert result is not None
        assert len(result) == 1
        assert isinstance(result[0], ToolCall)
        assert result[0].id == "call_123"
        assert result[0].type == "function"
        assert result[0].function.name == "get_weather"
        assert result[0].function.arguments == '{"location": "NYC"}'

    def test_convert_existing_tool_calls(self) -> None:
        """Test conversion with existing ToolCall objects."""
        existing_tool_call = ToolCall(
            id="call_123",
            type="function",
            function=FunctionCall(name="get_weather", arguments='{"location": "NYC"}'),
        )

        result = _convert_tool_calls([existing_tool_call])

        assert result is not None
        assert len(result) == 1
        assert result[0] is existing_tool_call  # Should be the same object

    def test_convert_legacy_model_tool_calls(self) -> None:
        """Test conversion from legacy model objects."""

        class MockToolCall:
            def __init__(self) -> None:
                self.id = "call_123"
                self.type = "function"
                self.function = {
                    "name": "get_weather",
                    "arguments": '{"location": "NYC"}',
                }

            def model_dump(self) -> dict[str, Any]:
                return {
                    "id": self.id,
                    "type": self.type,
                    "function": self.function,
                }

        mock_tool_call = MockToolCall()
        result = _convert_tool_calls([mock_tool_call])

        assert result is not None
        assert len(result) == 1
        assert isinstance(result[0], ToolCall)
        assert result[0].id == "call_123"
        assert result[0].function.name == "get_weather"


class TestConvertTools:
    """Tests for _convert_tools function."""

    def test_none_input(self) -> None:
        """Test conversion with None input."""
        result = _convert_tools(None)
        assert result is None

    def test_empty_list(self) -> None:
        """Test conversion with empty list."""
        result = _convert_tools([])
        assert result is None

    def test_convert_dict_tools(self) -> None:
        """Test conversion from dict format."""
        tools = [
            {
                "type": "function",
                "function": {
                    "name": "get_weather",
                    "description": "Get weather info",
                    "parameters": {"type": "object", "properties": {}},
                },
            }
        ]

        result = _convert_tools(tools)

        assert result is not None
        assert len(result) == 1
        assert isinstance(result, list)
        assert result[0]["type"] == "function"
        assert result[0]["function"]["name"] == "get_weather"

    def test_convert_existing_tool_definitions(self) -> None:
        """Test conversion with existing ToolDefinition objects."""
        tool_def = ToolDefinition(
            type="function",
            function={
                "name": "get_weather",
                "description": "Get weather info",
                "parameters": {"type": "object", "properties": {}},
            },
        )

        result = _convert_tools([tool_def])

        assert result is not None
        assert len(result) == 1
        assert isinstance(result, list)
        assert result[0]["type"] == "function"
        assert result[0]["function"]["name"] == "get_weather"

    def test_convert_legacy_model_tools(self) -> None:
        """Test conversion from legacy model objects."""

        class MockTool:
            def __init__(self) -> None:
                self.type = "function"
                self.function = {
                    "name": "get_weather",
                    "description": "Get weather info",
                    "parameters": {"type": "object", "properties": {}},
                }

            def model_dump(self) -> dict[str, Any]:
                return {"type": self.type, "function": self.function}

        mock_tool = MockTool()
        result = _convert_tools([mock_tool])

        assert result is not None
        assert len(result) == 1
        assert isinstance(result, list)
        assert result[0]["type"] == "function"
        assert result[0]["function"]["name"] == "get_weather"
