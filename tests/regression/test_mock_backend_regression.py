"""
Regression tests using the MockRegressionBackend.

These tests verify that both the legacy and new implementations can work
with the same mock backend and produce equivalent results.
"""

import pytest
from tests.mocks.mock_regression_backend import MockRegressionBackend


class TestMockBackendRegression:
    """Test both implementations with the same mock backend."""

    @pytest.fixture
    def mock_backend(self):
        """Create a mock backend for testing."""
        return MockRegressionBackend()

    @pytest.mark.asyncio
    async def test_legacy_chat_completion(self, mock_backend):
        """Test chat completion with the legacy implementation."""
        # Import legacy request model
        from src.models import ChatCompletionRequest

        # Create a request
        request = ChatCompletionRequest(
            model="mock-model",
            messages=[{"role": "user", "content": "Hello, world!"}],
            max_tokens=50,
            temperature=0.7,
            stream=False,
        )

        # Call the mock backend directly
        response, headers = await mock_backend.chat_completions(
            request_data=request,
            processed_messages=[{"role": "user", "content": "Hello, world!"}],
            effective_model="mock-model",
        )

        # Verify response structure
        assert "id" in response
        assert "choices" in response
        assert len(response["choices"]) > 0
        assert "message" in response["choices"][0]
        assert "content" in response["choices"][0]["message"]
        assert response["choices"][0]["message"]["content"] is not None

    @pytest.mark.asyncio
    async def test_new_chat_completion(self, mock_backend):
        """Test chat completion with the new implementation."""
        # Import new request model
        from src.core.domain.chat import ChatMessage, ChatRequest

        # Create a request
        request = ChatRequest(
            model="mock-model",
            messages=[ChatMessage(role="user", content="Hello, world!")],
            max_tokens=50,
            temperature=0.7,
            stream=False,
        )

        # Call the mock backend directly
        response, headers = await mock_backend.chat_completions(
            request_data=request,
            processed_messages=[{"role": "user", "content": "Hello, world!"}],
            effective_model="mock-model",
        )

        # Verify response structure
        assert "id" in response
        assert "choices" in response
        assert len(response["choices"]) > 0
        assert "message" in response["choices"][0]
        assert "content" in response["choices"][0]["message"]
        assert response["choices"][0]["message"]["content"] is not None

    @pytest.mark.asyncio
    async def test_legacy_streaming_chat_completion(self, mock_backend):
        """Test streaming chat completion with the legacy implementation."""
        # Import legacy request model
        from src.models import ChatCompletionRequest

        # Create a request
        request = ChatCompletionRequest(
            model="mock-model",
            messages=[{"role": "user", "content": "Hello, world!"}],
            max_tokens=50,
            temperature=0.7,
            stream=True,
        )

        # Call the mock backend directly
        stream_iterator = await mock_backend.chat_completions(
            request_data=request,
            processed_messages=[{"role": "user", "content": "Hello, world!"}],
            effective_model="mock-model",
        )

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
    async def test_new_streaming_chat_completion(self, mock_backend):
        """Test streaming chat completion with the new implementation."""
        # Import new request model
        from src.core.domain.chat import ChatMessage, ChatRequest

        # Create a request
        request = ChatRequest(
            model="mock-model",
            messages=[ChatMessage(role="user", content="Hello, world!")],
            max_tokens=50,
            temperature=0.7,
            stream=True,
        )

        # Call the mock backend directly
        stream_iterator = await mock_backend.chat_completions(
            request_data=request,
            processed_messages=[{"role": "user", "content": "Hello, world!"}],
            effective_model="mock-model",
            stream=True,
        )

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
    async def test_legacy_tool_calling(self, mock_backend):
        """Test tool calling with the legacy implementation."""
        # Import legacy request model
        from src.models import ChatCompletionRequest, FunctionDefinition, ToolDefinition

        # Create a tool definition
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

        # Create a request with tools
        request = ChatCompletionRequest(
            model="mock-model",
            messages=[{"role": "user", "content": "What's the weather like?"}],
            max_tokens=50,
            temperature=0.7,
            stream=False,
            tools=tools,
            tool_choice="auto",
        )

        # Call the mock backend directly
        response, headers = await mock_backend.chat_completions(
            request_data=request,
            processed_messages=[
                {"role": "user", "content": "What's the weather like?"}
            ],
            effective_model="mock-model",
        )

        # Verify tool call in response
        assert "choices" in response
        assert len(response["choices"]) > 0
        assert "message" in response["choices"][0]
        assert "tool_calls" in response["choices"][0]["message"]
        assert len(response["choices"][0]["message"]["tool_calls"]) > 0
        assert (
            response["choices"][0]["message"]["tool_calls"][0]["function"]["name"]
            == "get_current_weather"
        )
        assert (
            "arguments"
            in response["choices"][0]["message"]["tool_calls"][0]["function"]
        )

    @pytest.mark.asyncio
    async def test_new_tool_calling(self, mock_backend):
        """Test tool calling with the new implementation."""
        # Import new request model
        from src.core.domain.chat import ChatMessage, ChatRequest
        from src.models import FunctionDefinition, ToolDefinition

        # Create a tool definition
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
        response, headers = await mock_backend.chat_completions(
            request_data=request,
            processed_messages=[
                {"role": "user", "content": "What's the weather like?"}
            ],
            effective_model="mock-model",
        )

        # Verify tool call in response
        assert "choices" in response
        assert len(response["choices"]) > 0
        assert "message" in response["choices"][0]
        assert "tool_calls" in response["choices"][0]["message"]
        assert len(response["choices"][0]["message"]["tool_calls"]) > 0
        assert (
            response["choices"][0]["message"]["tool_calls"][0]["function"]["name"]
            == "get_current_weather"
        )
        assert (
            "arguments"
            in response["choices"][0]["message"]["tool_calls"][0]["function"]
        )
