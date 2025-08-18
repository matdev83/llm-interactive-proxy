"""
Regression tests for chat completion functionality.

These tests verify the behavior of the SOLID architecture implementation
to ensure it meets functional requirements.
"""

import json
from typing import TypedDict
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import HTTPException
from src.core.domain.chat import (
    ChatCompletionChoice,
    ChatCompletionChoiceMessage,
)
from src.core.domain.chat import (
    ChatResponse as ChatCompletionResponse,
)


class MockCompletionUsageData(TypedDict):
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int


class MockChatCompletionChoiceMessageData(TypedDict):
    role: str
    content: str


class MockChatCompletionChoiceData(TypedDict):
    index: int
    message: MockChatCompletionChoiceMessageData
    finish_reason: str


class MockChatCompletionResponseData(TypedDict):
    id: str
    object: str
    created: int
    model: str
    choices: list[MockChatCompletionChoiceData]
    usage: MockCompletionUsageData


# Mark all tests in this module as regression tests
pytestmark = pytest.mark.regression


class TestChatCompletionRegression:
    """Test chat completion functionality to ensure it meets requirements."""

    @patch("src.connectors.openai.OpenAIConnector.initialize", new_callable=AsyncMock)
    @patch("src.connectors.openai.OpenAIConnector.chat_completions")
    def test_basic_chat_completion(
        self, mock_chat_completions, mock_initialize, test_client
    ):
        """Test basic chat completion functionality."""
        # Define a mock response
        mock_response_data: MockChatCompletionResponseData = {
            "id": "chatcmpl-123",
            "object": "chat.completion",
            "created": 1677652288,
            "model": "mock-model",
            "choices": [
                {
                    "index": 0,
                    "message": {"role": "assistant", "content": "Hello, world!"},
                    "finish_reason": "stop",
                }
            ],
            "usage": {"prompt_tokens": 9, "completion_tokens": 12, "total_tokens": 21},
        }
        # Convert raw dicts to Pydantic models
        choices = [
            ChatCompletionChoice(
                index=choice["index"],
                message=ChatCompletionChoiceMessage(**choice["message"]),
                finish_reason=choice["finish_reason"],
            )
            for choice in mock_response_data["choices"]
        ]
        usage = mock_response_data["usage"]

        mock_chat_completions.return_value = ChatCompletionResponse(
            id=mock_response_data["id"],
            object=mock_response_data["object"],
            created=mock_response_data["created"],
            model=mock_response_data["model"],
            choices=choices,
            usage=usage,
        )
        mock_initialize.return_value = None

        # Define a simple chat completion request
        request_payload = {
            "model": "mock-model",
            "messages": [{"role": "user", "content": "Hello, world!"}],
            "max_tokens": 50,
            "temperature": 0.7,
            "stream": False,
        }

        headers = {"Authorization": "Bearer test_api_key"}

        # Send request to the implementation
        response = test_client.post(
            "/v1/chat/completions", json=request_payload, headers=headers
        )

        # Should succeed
        assert response.status_code == 200

        # Parse response body
        result = response.json()

        # Verify response structure
        assert "id" in result
        assert "choices" in result
        assert len(result["choices"]) > 0
        assert "message" in result["choices"][0]
        assert "content" in result["choices"][0]["message"]
        assert "role" in result["choices"][0]["message"]

    @patch("src.connectors.openai.OpenAIConnector.initialize", new_callable=AsyncMock)
    @patch("src.connectors.openai.OpenAIConnector.chat_completions")
    def test_streaming_chat_completion(
        self, mock_chat_completions, mock_initialize, test_client
    ):
        """Test streaming chat completion functionality."""

        async def mock_stream():
            yield 'data: {"id": "1", "choices": [{"delta": {"content": "Hello"}}]}'
            yield 'data: {"id": "2", "choices": [{"delta": {"content": ", world!"}}]}'
            yield "data: [DONE]"

        mock_chat_completions.return_value = mock_stream()
        mock_initialize.return_value = None

        # Define a streaming chat completion request
        request_payload = {
            "model": "mock-model",
            "messages": [{"role": "user", "content": "Count to 5"}],
            "max_tokens": 50,
            "temperature": 0.7,
            "stream": True,
        }

        headers = {"Authorization": "Bearer test_api_key"}

        # Send request to the implementation
        response = test_client.post(
            "/v1/chat/completions", json=request_payload, headers=headers
        )

        # Should succeed
        assert response.status_code == 200

        # Should have streaming content type
        assert "text/event-stream" in response.headers.get("content-type", "")

        # Collect streaming chunks from the response
        chunks = list(self._parse_streaming_response(response))

        # Verify we got some chunks
        assert len(chunks) > 0

        # Extract content from chunks
        content = self._extract_content_from_chunks(chunks)

        # Verify content
        assert len(content) > 0
        assert "Hello" in content
        assert "world" in content

        # Log the content for manual verification
        print(f"Content: {content}")

    @patch("src.connectors.openai.OpenAIConnector.initialize", new_callable=AsyncMock)
    @patch("src.connectors.openai.OpenAIConnector.chat_completions")
    def test_error_handling(self, mock_chat_completions, mock_initialize, test_client):
        """Test error handling functionality."""
        # Configure the mock to raise an HTTPException
        mock_chat_completions.side_effect = HTTPException(
            status_code=400, detail="Invalid model"
        )
        mock_initialize.return_value = None

        # Define an invalid request (missing required field)
        invalid_request = {
            "model": "",  # Invalid empty model
            "messages": [{"role": "user", "content": "Hello"}],
        }

        # Send request to the implementation
        response = test_client.post("/v1/chat/completions", json=invalid_request)

        # Should return an error
        assert response.status_code >= 400

        # Parse error response
        error = response.json()

        # Should have an error message
        assert "error" in error or "detail" in error

    def test_command_processing(self, test_client):
        """Test command processing functionality."""
        # Define a request with a command
        request_payload = {
            "model": "mock-model",
            "messages": [{"role": "user", "content": "!/hello"}],
            "max_tokens": 50,
            "temperature": 0.7,
            "stream": False,
        }

        # Send request to the implementation
        response = test_client.post("/v1/chat/completions", json=request_payload)

        # Should succeed
        assert response.status_code == 200

        # Parse response body
        result = response.json()

        # Extract content from the response
        content = result["choices"][0]["message"]["content"]

        # Command output should contain expected text
        assert "hello" in content.lower()

    def _validate_response_structure(self, response):
        """Validate the structure of a response."""
        # Check basic structure
        assert "id" in response
        assert "choices" in response
        assert len(response["choices"]) > 0

        # Check first choice structure
        choice = response["choices"][0]
        assert "message" in choice
        assert "content" in choice["message"]
        assert "role" in choice["message"]

        # Check usage information if present
        if "usage" in response:
            assert "prompt_tokens" in response["usage"]
            assert "completion_tokens" in response["usage"]
            assert "total_tokens" in response["usage"]

    def _parse_streaming_response(self, response):
        """Parse a streaming response into individual chunks."""
        for line in response.iter_lines():
            if not line:
                continue
            line_str = line if isinstance(line, str) else line.decode("utf-8")
            if line_str.startswith("data: "):
                data_part = line_str[6:]
                if data_part.strip() == "[DONE]":
                    break
                try:
                    chunk_data = json.loads(data_part)
                    yield chunk_data
                except json.JSONDecodeError:
                    continue

    def _extract_content_from_chunks(self, chunks):
        """Extract content from streaming response chunks."""
        content = ""
        for chunk in chunks:
            if "choices" in chunk and len(chunk["choices"]) > 0:
                delta = chunk["choices"][0].get("delta", {})
                if "content" in delta:
                    content += delta["content"]
        return content
