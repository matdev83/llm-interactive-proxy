"""
Test error handling in _accumulate_streaming_response.

This test ensures that when an error chunk is received during the accumulation
of a streaming response for a non-streaming client request, the error is
properly propagated as an error ResponseEnvelope instead of being silently
ignored.
"""

from unittest.mock import patch

import pytest
from src.connectors.gemini_base.connector import GeminiOAuthBaseConnector
from src.core.domain.responses import StreamingResponseEnvelope
from src.core.interfaces.response_processor_interface import ProcessedResponse


class TestAccumulateStreamingResponseErrorHandling:
    """Test suite for error handling in _accumulate_streaming_response."""

    @pytest.fixture
    def mock_connector(self):
        """Create a mock connector for testing."""
        with patch.object(GeminiOAuthBaseConnector, "__abstractmethods__", set()):
            connector = GeminiOAuthBaseConnector.__new__(GeminiOAuthBaseConnector)
            connector.backend_type = "test-gemini"
            connector._oauth_credentials = {"access_token": "test-token"}
            return connector

    @pytest.mark.asyncio
    async def test_error_chunk_propagated_to_response(self, mock_connector):
        """
        Test that when an error chunk is yielded during streaming,
        the error is propagated to the final ResponseEnvelope.
        """
        # Create a streaming response that yields an error chunk
        error_chunk = {
            "id": "chatcmpl-error-123",
            "object": "chat.completion.chunk",
            "created": 1234567890,
            "model": "test-model",
            "choices": [{"index": 0, "delta": {}, "finish_reason": "error"}],
            "error": {
                "message": "Gateway timeout reaching Code Assist streaming endpoint.",
                "type": "api_error",
                "code": 504,
            },
        }

        async def error_stream():
            yield ProcessedResponse(content=error_chunk, metadata={})

        streaming_response = StreamingResponseEnvelope(
            content=error_stream(),
            headers={},
            status_code=200,
        )

        # Call _accumulate_streaming_response
        result = await mock_connector._accumulate_streaming_response(streaming_response)

        # Verify the error is in the response
        assert result.status_code == 504, "Error status code should be propagated"
        assert "error" in result.content, "Error should be in response content"
        assert result.content["error"]["message"] == error_chunk["error"]["message"]
        assert (
            result.content["choices"] == []
        ), "Choices should be empty for error response"

    @pytest.mark.asyncio
    async def test_successful_stream_accumulates_content(self, mock_connector):
        """
        Test that successful streaming chunks are properly accumulated.
        """
        chunks = [
            {
                "id": "chatcmpl-123",
                "object": "chat.completion.chunk",
                "created": 1234567890,
                "model": "test-model",
                "choices": [
                    {"index": 0, "delta": {"role": "assistant"}, "finish_reason": None}
                ],
            },
            {
                "id": "chatcmpl-123",
                "object": "chat.completion.chunk",
                "created": 1234567890,
                "model": "test-model",
                "choices": [
                    {"index": 0, "delta": {"content": "Hello, "}, "finish_reason": None}
                ],
            },
            {
                "id": "chatcmpl-123",
                "object": "chat.completion.chunk",
                "created": 1234567890,
                "model": "test-model",
                "choices": [
                    {
                        "index": 0,
                        "delta": {"content": "world!"},
                        "finish_reason": "stop",
                    }
                ],
            },
        ]

        async def success_stream():
            for chunk in chunks:
                yield ProcessedResponse(content=chunk, metadata={})

        streaming_response = StreamingResponseEnvelope(
            content=success_stream(),
            headers={},
            status_code=200,
        )

        result = await mock_connector._accumulate_streaming_response(streaming_response)

        # Verify content is accumulated
        assert result.status_code == 200
        assert "error" not in result.content
        assert len(result.content["choices"]) == 1
        assert result.content["choices"][0]["message"]["content"] == "Hello, world!"
        assert result.content["choices"][0]["finish_reason"] == "stop"

    @pytest.mark.asyncio
    async def test_exception_during_accumulation_creates_error_response(
        self, mock_connector
    ):
        """
        Test that exceptions during stream accumulation are captured
        and converted to error responses.
        """

        async def failing_stream():
            yield ProcessedResponse(
                content={"choices": [{"delta": {"content": "partial"}}]}, metadata={}
            )
            raise RuntimeError("Simulated stream failure")

        streaming_response = StreamingResponseEnvelope(
            content=failing_stream(),
            headers={},
            status_code=200,
        )

        result = await mock_connector._accumulate_streaming_response(streaming_response)

        # The exception should be captured and converted to an error response
        assert "error" in result.content
        assert "Simulated stream failure" in result.content["error"]["message"]

    @pytest.mark.asyncio
    async def test_error_code_as_string_is_handled(self, mock_connector):
        """
        Test that error codes provided as strings are properly converted.
        """
        error_chunk = {
            "id": "chatcmpl-error-123",
            "object": "chat.completion.chunk",
            "created": 1234567890,
            "model": "test-model",
            "choices": [{"index": 0, "delta": {}, "finish_reason": "error"}],
            "error": {
                "message": "Rate limited",
                "type": "rate_limit_error",
                "code": "429",  # String instead of int
            },
        }

        async def error_stream():
            yield ProcessedResponse(content=error_chunk, metadata={})

        streaming_response = StreamingResponseEnvelope(
            content=error_stream(),
            headers={},
            status_code=200,
        )

        result = await mock_connector._accumulate_streaming_response(streaming_response)

        # String code should be converted to int
        assert result.status_code == 429
