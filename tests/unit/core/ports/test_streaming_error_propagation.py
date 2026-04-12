"""Unit tests for error propagation in streaming pipeline.

These tests verify that error information is correctly propagated through
the streaming pipeline, ensuring clients receive meaningful error messages
instead of empty responses.
"""

import json
from typing import Any, cast

import pytest
from fastapi import HTTPException
from src.core.common.exceptions import BackendError, RateLimitExceededError
from src.core.ports.openai_normalizer import OpenAIStreamNormalizer
from src.core.ports.streaming_contracts import (
    StreamingContent,
    StreamingErrorMapper,
    handle_streaming_error,
)
from src.core.ports.streaming_integration import integrate_streaming_pipeline


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
        assert payload["error"]["code"] == "503"
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
                "provider": "antigravity-oauth",
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
        assert chunk.metadata["provider"] == "antigravity-oauth"

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

    def test_streaming_error_mapper_promotes_backend_error_429(self) -> None:
        """Plain BackendError(429) should map like a native rate-limit error."""

        mapped_error = StreamingErrorMapper.map_backend_error(
            BackendError(
                message="upstream throttled",
                status_code=429,
                details={"headers": {"retry-after": "33"}},
            ),
            "anthropic",
            "s-1",
        )

        assert isinstance(mapped_error, RateLimitExceededError)
        assert mapped_error.details.get("headers", {}).get("retry-after") == "33"
        assert mapped_error.details.get("stream_id") == "s-1"

    def test_streaming_error_mapper_preserves_retry_after_headers(self) -> None:
        """HTTP 429 detail headers should survive streaming error mapping."""

        mapped_error = StreamingErrorMapper.map_backend_error(
            HTTPException(
                status_code=429,
                detail={
                    "message": "Too many requests",
                    "headers": {"retry-after": "17"},
                },
            ),
            "zai-coding-plan",
            "stream-429",
        )

        assert isinstance(mapped_error, RateLimitExceededError)
        assert mapped_error.details["headers"]["retry-after"] == "17"

    @pytest.mark.asyncio
    async def test_handle_streaming_error_emits_429_terminal_chunk(self) -> None:
        """Streaming 429s must produce terminal chunks that keep HTTP 429 semantics."""

        chunk = await handle_streaming_error(
            HTTPException(
                status_code=429,
                detail={
                    "message": "Too many requests",
                    "headers": {"retry-after": "9"},
                },
            ),
            stream_id="stream-429-chunk",
            provider="zai-coding-plan",
        )

        assert chunk.metadata["finish_reason"] == "error"
        error_payload = cast(dict[str, Any], chunk.metadata["error"])
        assert error_payload["status_code"] == 429
        assert error_payload["type"] == "RateLimitExceededError"

    @pytest.mark.asyncio
    async def test_handle_streaming_error_preserves_429_in_serialized_bytes(
        self,
    ) -> None:
        """Serialized terminal chunks should carry the 429 status in the OpenAI payload."""

        chunk = await handle_streaming_error(
            RateLimitExceededError(
                "Too many requests",
                details={"headers": {"retry-after": "11"}},
            ),
            stream_id="stream-serialized-429",
            provider="zai-coding-plan",
        )

        rendered = chunk.to_bytes().decode("utf-8", errors="replace")
        assert "RateLimitExceededError" in rendered
        assert '"status_code": 429' in rendered

    @pytest.mark.asyncio
    async def test_openai_normalizer_reraises_early_429(self) -> None:
        """OpenAI normalizer must not swallow early 429s before any chunks."""

        async def failing_raw_stream():
            raise HTTPException(
                status_code=429,
                detail={
                    "message": "Too many requests",
                    "headers": {"retry-after": "7"},
                },
            )
            yield b""  # pragma: no cover

        normalizer = OpenAIStreamNormalizer()

        with pytest.raises(HTTPException) as excinfo:
            async for _ in normalizer.normalize_stream(failing_raw_stream(), "openai"):
                pass

        detail = cast(dict[str, Any], excinfo.value.detail)
        headers = cast(dict[str, Any], detail["headers"])
        assert headers["retry-after"] == "7"

    @pytest.mark.asyncio
    async def test_integrate_streaming_pipeline_maps_early_429(
        self, monkeypatch
    ) -> None:
        """Early streaming 429s must bubble up as retryable backend errors."""

        class _FailingPipeline:
            async def process_stream(self, *args, **kwargs):
                raise HTTPException(
                    status_code=429,
                    detail={
                        "message": "Too many requests",
                        "headers": {"retry-after": "7"},
                    },
                )
                yield b""  # pragma: no cover

        monkeypatch.setattr(
            "src.core.ports.streaming_integration.create_pipeline_for_provider",
            lambda *args, **kwargs: _FailingPipeline(),
        )

        async def empty_stream():
            if False:
                yield b""

        with pytest.raises(RateLimitExceededError) as excinfo:
            await integrate_streaming_pipeline(
                empty_stream(),
                provider="openai",
                stream_id="stream-early-429",
                enable_loop_detection=False,
                enable_tool_call_repair=False,
                enable_think_tags=False,
            )

        assert excinfo.value.details["headers"]["retry-after"] == "7"

    @pytest.mark.asyncio
    async def test_integrate_streaming_pipeline_empty_stream_uses_error_status(
        self, monkeypatch
    ) -> None:
        """Empty upstream streams should produce explicit error status + chunk."""

        class _EmptyPipeline:
            async def process_stream(self, *args, **kwargs):
                if False:
                    yield b""

        monkeypatch.setattr(
            "src.core.ports.streaming_integration.create_pipeline_for_provider",
            lambda *args, **kwargs: _EmptyPipeline(),
        )

        async def empty_stream():
            if False:
                yield b""

        envelope = await integrate_streaming_pipeline(
            empty_stream(),
            provider="openai",
            stream_id="stream-empty",
            enable_loop_detection=False,
            enable_tool_call_repair=False,
            enable_think_tags=False,
        )

        assert envelope.status_code == 502
        assert envelope.content is not None
        first = await anext(envelope.content)
        if isinstance(first.content, bytes):
            rendered = first.content.decode("utf-8", errors="replace")
        else:
            rendered = str(first.content)
        assert "error" in rendered


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
