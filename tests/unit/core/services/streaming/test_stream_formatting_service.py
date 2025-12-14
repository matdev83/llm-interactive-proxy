"""Unit tests for StreamFormattingService.

Tests SSE encoding, [DONE] marker handling, valid token identification,
and equivalence with BackendService helper methods.
"""

from __future__ import annotations

import json

import pytest
from src.core.interfaces.response_processor_interface import ProcessedResponse
from src.core.services.stream_formatting_service import StreamFormattingService


class TestFormatChunkAsSSE:
    """Tests for format_chunk_as_sse method."""

    def test_dict_formatted_as_sse_json(self) -> None:
        """Dict content should be formatted as SSE with JSON payload."""
        service = StreamFormattingService()
        chunk = {
            "id": "chatcmpl-123",
            "object": "chat.completion.chunk",
            "choices": [{"delta": {"content": "Hello"}}],
        }
        result = service.format_chunk_as_sse(chunk)

        assert isinstance(result, bytes)
        decoded = result.decode("utf-8")
        assert decoded.startswith("data: ")
        assert decoded.endswith("\n\n")

        json_part = decoded[6:-2]
        parsed = json.loads(json_part)
        assert parsed == chunk

    def test_string_without_data_prefix_formatted_as_sse(self) -> None:
        """String content without 'data:' prefix should be SSE-framed."""
        service = StreamFormattingService()
        result = service.format_chunk_as_sse("test content")

        assert result == b"data: test content\n\n"

    def test_string_with_data_prefix_passed_through(self) -> None:
        """String content already starting with 'data:' should pass through."""
        service = StreamFormattingService()
        content = "data: already formatted\n\n"
        result = service.format_chunk_as_sse(content)

        assert result == content.encode("utf-8")

    def test_bytes_without_data_prefix_formatted_as_sse(self) -> None:
        """Bytes content without 'data:' prefix should be SSE-framed."""
        service = StreamFormattingService()
        result = service.format_chunk_as_sse(b"raw bytes")

        assert result == b"data: raw bytes\n\n"

    def test_bytes_with_data_prefix_passed_through(self) -> None:
        """Bytes content already starting with 'data:' should pass through."""
        service = StreamFormattingService()
        content = b"data: already formatted\n\n"
        result = service.format_chunk_as_sse(content)

        assert result == content

    def test_done_string_normalized(self) -> None:
        """Raw [DONE] string should be normalized to SSE format."""
        service = StreamFormattingService()
        assert service.format_chunk_as_sse("[DONE]") == b"data: [DONE]\n\n"
        assert service.format_chunk_as_sse('["DONE"]') == b"data: [DONE]\n\n"

    def test_done_bytes_normalized(self) -> None:
        """Raw [DONE] bytes should be normalized to SSE format."""
        service = StreamFormattingService()
        assert service.format_chunk_as_sse(b"[DONE]") == b"data: [DONE]\n\n"
        assert service.format_chunk_as_sse(b'["DONE"]') == b"data: [DONE]\n\n"

    def test_pydantic_model_serialized(self) -> None:
        """Content with model_dump() method should be serialized as JSON."""
        service = StreamFormattingService()

        class MockPydanticModel:
            def model_dump(self) -> dict:
                return {"key": "value", "nested": {"inner": 42}}

        result = service.format_chunk_as_sse(MockPydanticModel())
        decoded = result.decode("utf-8")

        assert decoded.startswith("data: ")
        assert decoded.endswith("\n\n")
        parsed = json.loads(decoded[6:-2])
        assert parsed == {"key": "value", "nested": {"inner": 42}}


class TestChunkSignalsDone:
    """Tests for chunk_signals_done method."""

    def test_done_string_detected(self) -> None:
        """[DONE] string variants should signal done."""
        service = StreamFormattingService()

        assert service.chunk_signals_done("[DONE]", None) is True
        assert service.chunk_signals_done('["DONE"]', None) is True
        assert service.chunk_signals_done("data: [DONE]", None) is True
        assert service.chunk_signals_done('data: ["DONE"]', None) is True
        assert service.chunk_signals_done("data: [DONE]\n\n", None) is True

    def test_done_bytes_detected(self) -> None:
        """[DONE] bytes variants should signal done."""
        service = StreamFormattingService()

        assert service.chunk_signals_done(b"[DONE]", None) is True
        assert service.chunk_signals_done(b'["DONE"]', None) is True
        assert service.chunk_signals_done(b"data: [DONE]", None) is True
        assert service.chunk_signals_done(b'data: ["DONE"]', None) is True

    def test_regular_content_not_done(self) -> None:
        """Regular content should not signal done."""
        service = StreamFormattingService()

        assert service.chunk_signals_done("hello world", None) is False
        assert service.chunk_signals_done(b"hello world", None) is False
        assert service.chunk_signals_done({"content": "test"}, None) is False

    def test_metadata_finish_reason_with_empty_content(self) -> None:
        """Empty content with metadata.finish_reason should signal done."""
        service = StreamFormattingService()

        assert service.chunk_signals_done(None, {"finish_reason": "stop"}) is True
        assert service.chunk_signals_done("", {"finish_reason": "stop"}) is True

    def test_metadata_finish_reason_with_content_delta(self) -> None:
        """Content with actual delta should not signal done even with finish_reason."""
        service = StreamFormattingService()

        content = {"choices": [{"delta": {"content": "still typing..."}}]}
        assert service.chunk_signals_done(content, {"finish_reason": "stop"}) is False

    def test_metadata_finish_reason_with_empty_delta(self) -> None:
        """Empty delta with finish_reason should signal done."""
        service = StreamFormattingService()

        content = {"choices": [{"delta": {}}]}
        assert service.chunk_signals_done(content, {"finish_reason": "stop"}) is True

    def test_openai_finish_reason_in_choices(self) -> None:
        """OpenAI-style finish_reason in choices should signal done."""
        service = StreamFormattingService()

        content = {"choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}]}
        assert service.chunk_signals_done(content, None) is True

    def test_dict_with_metadata_finish_reason(self) -> None:
        """Dict with embedded metadata.finish_reason should signal done."""
        service = StreamFormattingService()

        content = {"metadata": {"finish_reason": "stop"}}
        assert service.chunk_signals_done(content, None) is True


class TestIsValidCompletionToken:
    """Tests for is_valid_completion_token method."""

    def test_non_empty_string_is_valid(self) -> None:
        """Non-empty strings should be valid tokens."""
        service = StreamFormattingService()

        assert service.is_valid_completion_token("hello") is True
        assert service.is_valid_completion_token("some content") is True

    def test_empty_string_is_not_valid(self) -> None:
        """Empty or whitespace-only strings should not be valid."""
        service = StreamFormattingService()

        assert service.is_valid_completion_token("") is False
        assert service.is_valid_completion_token("   ") is False
        assert service.is_valid_completion_token("\n") is False

    def test_done_markers_not_valid(self) -> None:
        """[DONE] markers should not be valid tokens."""
        service = StreamFormattingService()

        assert service.is_valid_completion_token("[DONE]") is False
        assert service.is_valid_completion_token('["DONE"]') is False
        assert service.is_valid_completion_token("data: [DONE]") is False
        assert service.is_valid_completion_token('data: ["DONE"]') is False

    def test_sse_comments_not_valid(self) -> None:
        """SSE comments (starting with :) should not be valid tokens."""
        service = StreamFormattingService()

        assert service.is_valid_completion_token(":keepalive") is False
        assert service.is_valid_completion_token(": heartbeat") is False

    def test_dict_with_content_is_valid(self) -> None:
        """Dict with delta.content should be valid."""
        service = StreamFormattingService()

        chunk = {"choices": [{"delta": {"content": "hello"}}]}
        assert service.is_valid_completion_token(chunk) is True

    def test_dict_with_tool_calls_is_valid(self) -> None:
        """Dict with delta.tool_calls should be valid."""
        service = StreamFormattingService()

        chunk = {"choices": [{"delta": {"tool_calls": [{"id": "call_123"}]}}]}
        assert service.is_valid_completion_token(chunk) is True

    def test_dict_with_function_call_is_valid(self) -> None:
        """Dict with delta.function_call should be valid."""
        service = StreamFormattingService()

        chunk = {"choices": [{"delta": {"function_call": {"name": "test"}}}]}
        assert service.is_valid_completion_token(chunk) is True

    def test_dict_with_empty_delta_not_valid(self) -> None:
        """Dict with empty delta should not be valid."""
        service = StreamFormattingService()

        chunk = {"choices": [{"delta": {}}]}
        assert service.is_valid_completion_token(chunk) is False

    def test_processed_response_extracts_content(self) -> None:
        """ProcessedResponse should have content extracted correctly."""
        service = StreamFormattingService()

        response = ProcessedResponse(
            content={"choices": [{"delta": {"content": "test"}}]}
        )
        assert service.is_valid_completion_token(response) is True

        empty_response = ProcessedResponse(content={"choices": [{"delta": {}}]})
        assert service.is_valid_completion_token(empty_response) is False

    def test_bytes_with_content_is_valid(self) -> None:
        """Bytes with actual content should be valid."""
        service = StreamFormattingService()

        assert service.is_valid_completion_token(b"hello world") is True
        assert service.is_valid_completion_token(b'data: {"content": "test"}') is True

    def test_bytes_done_markers_not_valid(self) -> None:
        """Bytes with [DONE] markers should not be valid."""
        service = StreamFormattingService()

        assert service.is_valid_completion_token(b"[DONE]") is False
        assert service.is_valid_completion_token(b"data: [DONE]") is False

    def test_bytes_keepalive_not_valid(self) -> None:
        """Bytes with SSE comments should not be valid."""
        service = StreamFormattingService()

        assert service.is_valid_completion_token(b":keepalive") is False
        assert service.is_valid_completion_token(b"") is False


class TestStreamAsSSEBytes:
    """Tests for stream_as_sse_bytes method."""

    @pytest.mark.asyncio
    async def test_appends_done_when_missing(self) -> None:
        """Stream should append [DONE] marker when not present."""
        service = StreamFormattingService()

        async def gen():
            yield ProcessedResponse(content={"choices": [{"delta": {"content": "hi"}}]})

        result = [chunk async for chunk in service.stream_as_sse_bytes(gen())]

        assert result[-1] == b"data: [DONE]\n\n"
        assert len(result) == 2

    @pytest.mark.asyncio
    async def test_does_not_duplicate_done(self) -> None:
        """Stream should not duplicate [DONE] marker when already present."""
        service = StreamFormattingService()

        async def gen():
            yield ProcessedResponse(content="data: [DONE]\n\n")

        result = [chunk async for chunk in service.stream_as_sse_bytes(gen())]

        full_output = b"".join(result)
        done_count = full_output.count(b"data: [DONE]\n\n")
        assert done_count == 1

    @pytest.mark.asyncio
    async def test_formats_dict_chunks(self) -> None:
        """Dict chunks should be formatted as SSE JSON."""
        service = StreamFormattingService()

        chunk = {"id": "test", "choices": [{"delta": {"content": "hello"}}]}

        async def gen():
            yield ProcessedResponse(content=chunk)

        result = [chunk async for chunk in service.stream_as_sse_bytes(gen())]

        assert len(result) == 2
        decoded = result[0].decode("utf-8")
        assert decoded.startswith("data: ")
        assert decoded.endswith("\n\n")
        assert '"hello"' in decoded

    @pytest.mark.asyncio
    async def test_handles_finish_reason_in_metadata(self) -> None:
        """Finish reason in metadata should trigger done."""
        service = StreamFormattingService()

        async def gen():
            yield ProcessedResponse(
                content={"choices": [{"delta": {"content": "hi"}}]},
                metadata={},
            )
            yield ProcessedResponse(
                content={"choices": [{"delta": {}}]},
                metadata={"finish_reason": "stop"},
            )

        result = [chunk async for chunk in service.stream_as_sse_bytes(gen())]

        # Should have: data chunk, empty delta chunk, and [DONE]
        full_output = b"".join(result)
        assert b"data: [DONE]\n\n" in full_output

    @pytest.mark.asyncio
    async def test_normalizes_bracket_done_marker(self) -> None:
        """["DONE"] variant should be normalized to [DONE]."""
        service = StreamFormattingService()

        async def gen():
            yield ProcessedResponse(content='["DONE"]')

        result = [chunk async for chunk in service.stream_as_sse_bytes(gen())]

        assert result == [b"data: [DONE]\n\n"]


class TestEquivalenceWithBackendService:
    """Ensure StreamFormattingService matches BackendService behavior."""

    @pytest.mark.asyncio
    async def test_stream_output_matches_backend_service(self) -> None:
        """StreamFormattingService output should match BackendService."""
        from src.core.services.backend_service import BackendService

        service = StreamFormattingService()

        chunk = {"id": "test", "choices": [{"delta": {"content": "hello world"}}]}

        async def gen_for_service():
            yield ProcessedResponse(content=chunk)

        async def gen_for_backend():
            yield ProcessedResponse(content=chunk)

        service_result = [
            c async for c in service.stream_as_sse_bytes(gen_for_service())
        ]
        backend_result = [
            c async for c in BackendService._stream_as_sse_bytes(gen_for_backend())
        ]

        assert service_result == backend_result

    @pytest.mark.asyncio
    async def test_done_handling_matches_backend_service(self) -> None:
        """Done marker handling should match BackendService."""
        from src.core.services.backend_service import BackendService

        service = StreamFormattingService()

        async def gen_for_service():
            yield ProcessedResponse(content="data: [DONE]\n\n")

        async def gen_for_backend():
            yield ProcessedResponse(content="data: [DONE]\n\n")

        service_result = [
            c async for c in service.stream_as_sse_bytes(gen_for_service())
        ]
        backend_result = [
            c async for c in BackendService._stream_as_sse_bytes(gen_for_backend())
        ]

        assert service_result == backend_result

    @pytest.mark.asyncio
    async def test_error_chunk_handling_matches_backend_service(self) -> None:
        """Error chunk handling should match BackendService."""
        from src.core.services.backend_service import BackendService

        service = StreamFormattingService()

        error_chunk = {
            "id": "chatcmpl-error",
            "object": "chat.completion.chunk",
            "choices": [{"index": 0, "delta": {}, "finish_reason": "error"}],
            "error": {"message": "test error", "type": "api_error"},
        }

        async def gen_for_service():
            yield ProcessedResponse(content=error_chunk)

        async def gen_for_backend():
            yield ProcessedResponse(content=error_chunk)

        service_result = [
            c async for c in service.stream_as_sse_bytes(gen_for_service())
        ]
        backend_result = [
            c async for c in BackendService._stream_as_sse_bytes(gen_for_backend())
        ]

        assert service_result == backend_result
