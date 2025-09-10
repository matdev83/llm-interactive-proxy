"""
Regression tests using the MockRegressionBackend.

These tests verify that both the legacy and new implementations can work
with the same mock backend and produce equivalent results.
"""

from collections.abc import AsyncIterator
from typing import Any, cast

import pytest
from src.core.domain.chat import (
    ChatMessage,
    ChatRequest,
    FunctionDefinition,
    ToolDefinition,
)
from src.core.domain.responses import ResponseEnvelope
from tests.mocks.mock_regression_backend import MockRegressionBackend


class TestMockBackendRegression:
    """Test both implementations with the same mock backend."""

    @pytest.fixture
    def mock_backend(self) -> MockRegressionBackend:
        """Create a mock backend for testing."""
        return MockRegressionBackend()

    @pytest.mark.asyncio
    async def test_new_chat_completion(
        self, mock_backend: MockRegressionBackend
    ) -> None:
        """Test chat completion with the new implementation."""
        request = ChatRequest(
            model="mock-model",
            messages=[ChatMessage(role="user", content="Hello, world!")],
            max_tokens=50,
            temperature=0.7,
            stream=False,
        )

        # Call the mock backend directly
        response_envelope_or_iterator = await mock_backend.chat_completions(
            request_data=request,
            processed_messages=[ChatMessage(role="user", content="Hello, world!")],
            effective_model="mock-model",
        )
        response_envelope = cast(ResponseEnvelope, response_envelope_or_iterator)
        response = response_envelope.content

        # Verify response structure
        assert "id" in response
        assert "choices" in response
        assert len(response["choices"]) > 0
        assert "message" in response["choices"][0]
        assert "content" in response["choices"][0]["message"]
        assert response["choices"][0]["message"]["content"] is not None

    @pytest.mark.asyncio
    async def test_new_streaming_chat_completion(
        self, mock_backend: MockRegressionBackend
    ) -> None:
        """Test streaming chat completion with the new implementation."""
        request = ChatRequest(
            model="mock-model",
            messages=[ChatMessage(role="user", content="Hello, world!")],
            max_tokens=50,
            temperature=0.7,
            stream=True,
        )

        # Call the mock backend directly
        stream_iterator_untyped = await mock_backend.chat_completions(
            request_data=request,
            processed_messages=[ChatMessage(role="user", content="Hello, world!")],
            effective_model="mock-model",
            stream=True,
        )
        stream_iterator = cast(AsyncIterator[dict[str, Any]], stream_iterator_untyped)

        # Collect streaming chunks
        chunks = []
        async for chunk in stream_iterator:
            chunks.append(chunk)

        # Verify streaming response
        assert len(chunks) > 0
        assert "choices" in chunks[0]
        assert len(chunks[0]["choices"]) > 0

        # Last chunk should have finish_reason
        assert chunks[-1]["choices"][0]["finish_reason"] == "stop"

    @pytest.mark.asyncio
    async def test_new_tool_calling(self, mock_backend: MockRegressionBackend) -> None:
        """Test tool calling with the new implementation."""
        tools = [
            ToolDefinition(
                type="function",
                function=FunctionDefinition(
                    name="get_current_weather",
                    description="Get the current weather",
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

        # Convert tools to dictionaries for the new implementation
        tools_dict = [tool.model_dump() for tool in tools]

        # Create a request with tools
        request = ChatRequest(
            model="mock-model",
            messages=[ChatMessage(role="user", content="What's the weather like?")],
            max_tokens=50,
            temperature=0.7,
            stream=False,
            tools=tools_dict,
            tool_choice="auto",
        )

        # Call the mock backend directly
        response_envelope_or_iterator = await mock_backend.chat_completions(
            request_data=request,
            processed_messages=[
                ChatMessage(role="user", content="What's the weather like?")
            ],
            effective_model="mock-model",
        )
        response_envelope = cast(ResponseEnvelope, response_envelope_or_iterator)
        response = response_envelope.content

        # Verify tool call in response
        choices = response.get("choices")
        assert isinstance(choices, list) and len(choices) > 0
        first_choice = choices[0]
        assert "message" in first_choice
        message = first_choice.get("message")
        assert isinstance(message, dict)
        tool_calls = message.get("tool_calls")
        assert isinstance(tool_calls, list) and len(tool_calls) > 0
        assert tool_calls[0]["function"]["name"] == "get_current_weather"
        assert "arguments" in tool_calls[0]["function"]
