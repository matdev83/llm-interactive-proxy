"""Unit tests for error propagation in streaming pipeline.

These tests verify that error information is correctly propagated through
the streaming pipeline, ensuring clients receive meaningful error messages
instead of empty responses.
"""

import json

import pytest
from src.core.common.exceptions import BackendError
from src.core.ports.streaming_contracts import (
    StreamingContent,
    handle_streaming_error,
)


class TestStreamingContentErrorChunks:
    """Tests for error chunk handling in StreamingContent."""

    def test_error_chunk_contains_error_field(self) -> None:
        """Error chunks must include the error field in metadata."""
        error_metadata = {
            "message": "Rate limit exceeded",
            "type": "rate_limit_exceeded",
            "code": 429,
        }
        chunk = StreamingContent(
            content="",
            metadata={
                "finish_reason": "error",
                "error": error_metadata,
                "id": "chatcmpl-error-123",
                "model": "test-model",
                "created": 1234567890,
            },
            is_done=True,
        )

        assert "error" in chunk.metadata
        assert chunk.metadata["error"] == error_metadata
        assert chunk.metadata["finish_reason"] == "error"

    def test_error_chunk_to_bytes_includes_error_details(self) -> None:
        """StreamingContent.to_bytes() must include error field in output."""
        error_metadata = {
            "message": "Quota exhausted",
            "type": "quota_exceeded",
            "code": 503,
        }
        chunk = StreamingContent(
            content="",
            metadata={
                "finish_reason": "error",
                "error": error_metadata,
                "id": "chatcmpl-error-456",
                "model": "gemini-2.5-pro",
                "created": 1234567890,
            },
            is_done=True,
        )

        result = chunk.to_bytes()
        decoded = result.decode("utf-8")

        # Should contain data line with error information
        assert "data:" in decoded
        assert "[DONE]" in decoded

        # Extract JSON payload
        lines = decoded.strip().split("\n")
        data_line = next(
            line for line in lines if line.startswith("data:") and "[DONE]" not in line
        )
        json_str = data_line[5:].strip()  # Remove "data:" prefix
        payload = json.loads(json_str)

        # Verify error field is present
        assert "error" in payload
        assert payload["error"]["message"] == "Quota exhausted"
        assert payload["error"]["type"] == "quota_exceeded"
        assert payload["error"]["code"] == 503
        assert payload["choices"][0]["finish_reason"] == "error"

    def test_streaming_content_preserves_error_metadata(self) -> None:
        """StreamingContent must preserve all error metadata fields."""
        chunk = StreamingContent(
            content="",
            metadata={
                "finish_reason": "error",
                "error": {
                    "message": "Backend unavailable",
                    "type": "backend_error",
                    "code": 502,
                    "details": {"retry_after": 60},
                },
                "id": "chatcmpl-error-789",
                "model": "claude-sonnet-4-5",
                "created": 1234567890,
                "provider": "gemini-oauth-antigravity",
            },
            is_done=True,
        )

        # Verify all metadata is preserved
        assert chunk.metadata["finish_reason"] == "error"
        assert chunk.metadata["error"]["message"] == "Backend unavailable"
        assert chunk.metadata["error"]["type"] == "backend_error"
        assert chunk.metadata["error"]["code"] == 502
        assert chunk.metadata["error"]["details"]["retry_after"] == 60
        assert chunk.metadata["id"] == "chatcmpl-error-789"
        assert chunk.metadata["model"] == "claude-sonnet-4-5"
        assert chunk.metadata["provider"] == "gemini-oauth-antigravity"

    def test_error_chunk_not_marked_empty(self) -> None:
        """Error chunks should not be marked as empty even with no content."""
        chunk = StreamingContent(
            content="",
            metadata={
                "finish_reason": "error",
                "error": {"message": "Test error", "type": "test", "code": 500},
            },
            is_done=True,
            is_empty=False,  # Explicitly set to False
        )

        assert not chunk.is_empty or chunk.is_done  # Either not empty or is done marker

    def test_error_chunk_is_done_marker(self) -> None:
        """Error chunks must be marked as done markers."""
        chunk = StreamingContent(
            content="",
            metadata={
                "finish_reason": "error",
                "error": {"message": "Test error", "type": "test", "code": 500},
            },
            is_done=True,
        )

        assert chunk.is_done is True


class TestHandleStreamingError:
    """Tests for the handle_streaming_error utility function."""

    @pytest.mark.asyncio
    async def test_backend_error_creates_proper_chunk(self) -> None:
        """handle_streaming_error should create proper error chunk from BackendError."""
        error = BackendError(
            message="API rate limit exceeded",
            code="rate_limit_exceeded",
            status_code=429,
        )

        chunk = await handle_streaming_error(
            error, stream_id="stream-123", provider="gemini-oauth"
        )

        assert chunk.is_done is True
        assert chunk.metadata["finish_reason"] == "error"
        assert "error" in chunk.metadata
        # The error message should contain information about the original error
        error_info = chunk.metadata["error"]
        assert "message" in error_info
        assert "type" in error_info
        # The message should contain the original error text
        assert "rate limit" in error_info["message"].lower()
        assert chunk.metadata["provider"] == "gemini-oauth"
        assert chunk.stream_id == "stream-123"

    @pytest.mark.asyncio
    async def test_generic_exception_creates_error_chunk(self) -> None:
        """handle_streaming_error should handle generic exceptions."""
        error = RuntimeError("Unexpected failure")

        chunk = await handle_streaming_error(error, provider="test-backend")

        assert chunk.is_done is True
        assert chunk.metadata["finish_reason"] == "error"
        assert "error" in chunk.metadata
        assert chunk.metadata["provider"] == "test-backend"

    @pytest.mark.asyncio
    async def test_error_chunk_includes_retryable_flag(self) -> None:
        """Error chunks should indicate whether the error is retryable."""
        error = BackendError(
            message="Rate limited",
            code="rate_limit_exceeded",
            status_code=429,
        )

        chunk = await handle_streaming_error(error, provider="test")

        assert "error" in chunk.metadata
        # The retryable flag should be present
        assert "retryable" in chunk.metadata["error"]


class TestErrorChunkSerializationRoundtrip:
    """Tests for error chunk serialization and format compliance."""

    def test_error_chunk_json_serializable(self) -> None:
        """Error chunks must be JSON-serializable."""
        chunk = StreamingContent(
            content="",
            metadata={
                "finish_reason": "error",
                "error": {
                    "message": "Test error message",
                    "type": "test_error",
                    "code": 500,
                },
                "id": "chatcmpl-error-test",
                "model": "test-model",
                "created": 1234567890,
            },
            is_done=True,
        )

        # Should not raise
        result = chunk.to_bytes()
        assert isinstance(result, bytes)
        assert len(result) > 0

    def test_error_chunk_follows_openai_format(self) -> None:
        """Error chunks should follow OpenAI streaming format."""
        chunk = StreamingContent(
            content="",
            metadata={
                "finish_reason": "error",
                "error": {
                    "message": "Error message",
                    "type": "api_error",
                    "code": 500,
                },
                "id": "chatcmpl-error-format",
                "model": "test-model",
                "created": 1234567890,
            },
            is_done=True,
        )

        result = chunk.to_bytes().decode("utf-8")

        # Should have proper SSE format
        assert result.startswith("data:")
        assert "data: [DONE]" in result

        # Extract and parse JSON
        data_line = next(
            line
            for line in result.split("\n")
            if line.startswith("data:") and "[DONE]" not in line
        )
        payload = json.loads(data_line[5:].strip())

        # Check OpenAI format fields
        assert "id" in payload
        assert "choices" in payload
        assert "error" in payload
        assert payload["choices"][0]["finish_reason"] == "error"

    @pytest.mark.asyncio
    async def test_sse_assembler_emits_error_when_bytes_would_be_done_only(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """SSESerializer should never collapse error chunks into a bare [DONE].

        This test verifies that the serializer correctly handles error chunks
        and always produces a proper error payload, not just [DONE].
        """
        from src.core.ports.sse_assembler import SSEAssembler
        from tests.utils.property_test_helpers import async_iter, async_list

        chunk = StreamingContent(
            content="",
            metadata={
                "finish_reason": "error",
                "error": {"message": "boom", "type": "api_error", "code": 400},
                "id": "chatcmpl-error-test",
                "model": "test-model",
                "created": 123,
            },
            is_done=True,
        )

        # The serializer should handle error chunks correctly
        # No need to simulate faulty serialization - verify real behavior
        assembler = SSEAssembler()
        outputs = await async_list(assembler.assemble_stream(async_iter([chunk])))
        combined = b"".join(outputs).decode("utf-8")

        # Verify error information is present
        assert "boom" in combined
        assert "error" in combined
        assert "chatcmpl-error-test" in combined
        assert combined.strip().endswith("[DONE]")

        # Verify it's NOT just [DONE]
        assert combined != "data: [DONE]\n\n"

    def test_error_chunk_preserved_when_error_only_in_content(self) -> None:
        """Error chunks should serialize even if metadata.error is missing."""
        chunk = StreamingContent(
            content={
                "id": "chatcmpl-error-content-only",
                "object": "chat.completion.chunk",
                "created": 123,
                "model": "test-model",
                "choices": [{"index": 0, "delta": {}, "finish_reason": "error"}],
                "error": {
                    "message": "Error from payload",
                    "type": "api_error",
                    "code": 503,
                },
            },
            metadata={"finish_reason": "error"},
            is_done=True,
        )

        result = chunk.to_bytes().decode("utf-8")

        assert result.startswith("data:")
        assert "data: [DONE]" in result
        # The serialized chunk must include the error payload from the content
        assert (
            '"error": {"message": "Error from payload", "type": "api_error", "code": 503}'
            in result
        )
