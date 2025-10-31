"""
Unit tests for Qwen OAuth connector reasoning_effort handling.

Tests that when reasoning_effort is set to "medium" or "high", the connector
appends " /think" to the last client message.
"""

import time
from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest
from src.connectors.qwen_oauth import QwenOAuthConnector
from src.core.config.app_config import AppConfig
from src.core.domain.chat import ChatMessage, ChatRequest
from src.core.domain.responses import ResponseEnvelope


class TestQwenOAuthReasoningEffort:
    """Test reasoning_effort handling in QwenOAuthConnector."""

    @pytest.fixture
    def mock_client(self):
        """Mock httpx.AsyncClient."""
        client = MagicMock(spec=httpx.AsyncClient)
        # Mock the post method to return a successful response
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "id": "test-id",
            "object": "chat.completion",
            "created": int(time.time()),
            "model": "qwen-turbo",
            "choices": [
                {
                    "index": 0,
                    "message": {"role": "assistant", "content": "Test response"},
                    "finish_reason": "stop",
                }
            ],
            "usage": {
                "prompt_tokens": 10,
                "completion_tokens": 5,
                "total_tokens": 15,
            },
        }
        mock_response.headers = {}
        client.post = AsyncMock(return_value=mock_response)
        return client

    @pytest.fixture
    def connector(self, mock_client):
        """QwenOAuthConnector instance with mocked client."""
        config = AppConfig()
        connector = QwenOAuthConnector(mock_client, config=config)
        # Mock credentials to make connector functional
        connector._oauth_credentials = {
            "access_token": "test-access-token",
            "refresh_token": "test-refresh-token",
            "resource_url": "portal.qwen.ai",
            "expiry_date": int(time.time() * 1000) + 3600000,  # 1 hour from now
        }
        connector.is_functional = True
        connector.available_models = ["qwen-turbo", "qwen-plus"]
        return connector

    @pytest.mark.asyncio
    async def test_default_appends_think(self, connector, mock_client):
        """Test that by default (no reasoning_effort) appends ' /think' to last user message."""
        # Create request without reasoning_effort (should default to appending)
        request = ChatRequest(
            model="qwen-turbo",
            messages=[
                ChatMessage(role="user", content="Hello"),
                ChatMessage(role="assistant", content="Hi there"),
                ChatMessage(role="user", content="What is 2+2?"),
            ],
        )

        processed_messages = [
            {"role": "user", "content": "Hello"},
            {"role": "assistant", "content": "Hi there"},
            {"role": "user", "content": "What is 2+2?"},
        ]

        # Call chat_completions
        response = await connector.chat_completions(
            request_data=request,
            processed_messages=processed_messages,
            effective_model="qwen-turbo",
        )

        # Verify that the last user message was modified
        assert processed_messages[-1]["content"] == "What is 2+2? /think"
        assert isinstance(response, ResponseEnvelope)

    @pytest.mark.asyncio
    async def test_reasoning_effort_medium_appends_think(self, connector, mock_client):
        """Test that reasoning_effort='medium' appends ' /think' to last user message."""
        request = ChatRequest(
            model="qwen-turbo",
            messages=[ChatMessage(role="user", content="Solve this puzzle")],
            reasoning_effort="medium",
        )

        processed_messages = [{"role": "user", "content": "Solve this puzzle"}]

        response = await connector.chat_completions(
            request_data=request,
            processed_messages=processed_messages,
            effective_model="qwen-turbo",
        )

        # Verify that the message was modified
        assert processed_messages[0]["content"] == "Solve this puzzle /think"
        assert isinstance(response, ResponseEnvelope)

    @pytest.mark.asyncio
    async def test_reasoning_effort_high_appends_think(self, connector, mock_client):
        """Test that reasoning_effort='high' appends ' /think' to last user message."""
        request = ChatRequest(
            model="qwen-turbo",
            messages=[ChatMessage(role="user", content="Complex problem")],
            reasoning_effort="high",
        )

        processed_messages = [{"role": "user", "content": "Complex problem"}]

        response = await connector.chat_completions(
            request_data=request,
            processed_messages=processed_messages,
            effective_model="qwen-turbo",
        )

        # Verify that the message was modified
        assert processed_messages[0]["content"] == "Complex problem /think"
        assert isinstance(response, ResponseEnvelope)

    @pytest.mark.asyncio
    async def test_reasoning_effort_low_does_not_append(self, connector, mock_client):
        """Test that reasoning_effort='low' does NOT append ' /think'."""
        request = ChatRequest(
            model="qwen-turbo",
            messages=[ChatMessage(role="user", content="Simple question")],
            reasoning_effort="low",
        )

        processed_messages = [{"role": "user", "content": "Simple question"}]

        response = await connector.chat_completions(
            request_data=request,
            processed_messages=processed_messages,
            effective_model="qwen-turbo",
        )

        # Verify that the message was NOT modified
        assert processed_messages[0]["content"] == "Simple question"
        assert isinstance(response, ResponseEnvelope)

    @pytest.mark.asyncio
    async def test_none_reasoning_effort_appends_think(self, connector, mock_client):
        """Test that None reasoning_effort (default) appends ' /think'."""
        request = ChatRequest(
            model="qwen-turbo",
            messages=[ChatMessage(role="user", content="Normal message")],
            reasoning_effort=None,
        )

        processed_messages = [{"role": "user", "content": "Normal message"}]

        response = await connector.chat_completions(
            request_data=request,
            processed_messages=processed_messages,
            effective_model="qwen-turbo",
        )

        # Verify that the message WAS modified (default behavior)
        assert processed_messages[0]["content"] == "Normal message /think"
        assert isinstance(response, ResponseEnvelope)

    @pytest.mark.asyncio
    async def test_empty_string_reasoning_effort_appends_think(
        self, connector, mock_client
    ):
        """Test that empty string reasoning_effort appends ' /think'."""
        request = ChatRequest(
            model="qwen-turbo",
            messages=[ChatMessage(role="user", content="Another message")],
            reasoning_effort="",
        )

        processed_messages = [{"role": "user", "content": "Another message"}]

        response = await connector.chat_completions(
            request_data=request,
            processed_messages=processed_messages,
            effective_model="qwen-turbo",
        )

        # Verify that the message WAS modified (empty string is not "low")
        assert processed_messages[0]["content"] == "Another message /think"
        assert isinstance(response, ResponseEnvelope)

    @pytest.mark.asyncio
    async def test_reasoning_effort_skips_tool_responses(self, connector, mock_client):
        """Test that ' /think' is appended to last user message, not tool responses."""
        request = ChatRequest(
            model="qwen-turbo",
            messages=[
                ChatMessage(role="user", content="Use a tool"),
                ChatMessage(
                    role="assistant",
                    content=None,
                    tool_calls=[
                        {
                            "id": "call_1",
                            "type": "function",
                            "function": {"name": "test_tool", "arguments": "{}"},
                        }
                    ],
                ),
                ChatMessage(role="tool", content="Tool result", tool_call_id="call_1"),
            ],
            reasoning_effort="medium",
        )

        processed_messages = [
            {"role": "user", "content": "Use a tool"},
            {
                "role": "assistant",
                "content": None,
                "tool_calls": [
                    {
                        "id": "call_1",
                        "type": "function",
                        "function": {"name": "test_tool", "arguments": "{}"},
                    }
                ],
            },
            {"role": "tool", "content": "Tool result", "tool_call_id": "call_1"},
        ]

        response = await connector.chat_completions(
            request_data=request,
            processed_messages=processed_messages,
            effective_model="qwen-turbo",
        )

        # Verify that ' /think' was appended to the user message, not the tool message
        assert processed_messages[0]["content"] == "Use a tool /think"
        assert processed_messages[2]["content"] == "Tool result"
        assert isinstance(response, ResponseEnvelope)

    @pytest.mark.asyncio
    async def test_reasoning_effort_with_system_message(self, connector, mock_client):
        """Test that ' /think' can be appended to system messages if they're last."""
        request = ChatRequest(
            model="qwen-turbo",
            messages=[
                ChatMessage(role="system", content="You are a helpful assistant"),
            ],
            reasoning_effort="high",
        )

        processed_messages = [
            {"role": "system", "content": "You are a helpful assistant"}
        ]

        response = await connector.chat_completions(
            request_data=request,
            processed_messages=processed_messages,
            effective_model="qwen-turbo",
        )

        # Verify that the system message was modified
        assert processed_messages[0]["content"] == "You are a helpful assistant /think"
        assert isinstance(response, ResponseEnvelope)

    @pytest.mark.asyncio
    async def test_reasoning_effort_with_multiple_messages(
        self, connector, mock_client
    ):
        """Test that reasoning_effort appends to the last user message in a multi-turn conversation."""
        request = ChatRequest(
            model="qwen-turbo",
            messages=[
                ChatMessage(role="user", content="First question"),
                ChatMessage(role="assistant", content="First answer"),
                ChatMessage(role="user", content="Second question"),
            ],
            reasoning_effort="high",
        )

        processed_messages = [
            {"role": "user", "content": "First question"},
            {"role": "assistant", "content": "First answer"},
            {"role": "user", "content": "Second question"},
        ]

        response = await connector.chat_completions(
            request_data=request,
            processed_messages=processed_messages,
            effective_model="qwen-turbo",
        )

        # Verify that only the last user message was modified
        assert processed_messages[0]["content"] == "First question"
        assert processed_messages[1]["content"] == "First answer"
        assert processed_messages[2]["content"] == "Second question /think"
        assert isinstance(response, ResponseEnvelope)

    @pytest.mark.asyncio
    async def test_reasoning_effort_with_pydantic_message(self, connector, mock_client):
        """Test that reasoning_effort works with Pydantic ChatMessage objects."""
        request = ChatRequest(
            model="qwen-turbo",
            messages=[ChatMessage(role="user", content="Pydantic message")],
            reasoning_effort="high",
        )

        # Use actual ChatMessage objects in processed_messages
        processed_messages = [ChatMessage(role="user", content="Pydantic message")]

        response = await connector.chat_completions(
            request_data=request,
            processed_messages=processed_messages,
            effective_model="qwen-turbo",
        )

        # Verify that the message was modified
        # The message should be replaced with a modified copy
        assert processed_messages[0].content == "Pydantic message /think"
        assert isinstance(response, ResponseEnvelope)
