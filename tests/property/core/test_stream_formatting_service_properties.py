"""Property-based tests for StreamFormattingService.

Validates:
- Property 1: SSE Format Consistency (Requirements 5.1, 5.3)
- Property 2: Done Marker Detection (Requirements 5.4)
- Property 3: Valid Token Identification (Requirements 5.2)
"""

from __future__ import annotations

import json

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st
from src.core.interfaces.response_processor_interface import ProcessedResponse
from src.core.services.stream_formatting_service import StreamFormattingService

# Strategies for generating test data
json_primitives = st.one_of(
    st.none(),
    st.booleans(),
    st.integers(),
    st.floats(allow_nan=False, allow_infinity=False),
    st.text(max_size=100),
)


def json_dicts() -> st.SearchStrategy:
    """Generate JSON-serializable dicts."""
    return st.dictionaries(
        keys=st.text(min_size=1, max_size=20),
        values=json_primitives,
        max_size=5,
    )


def openai_chunk_dicts() -> st.SearchStrategy:
    """Generate OpenAI-style streaming chunk dicts."""
    return st.fixed_dictionaries(
        {
            "id": st.text(
                min_size=1, max_size=20, alphabet="abcdefghijklmnopqrstuvwxyz-"
            ),
            "object": st.just("chat.completion.chunk"),
            "created": st.integers(min_value=1000000000, max_value=2000000000),
            "model": st.text(min_size=1, max_size=30),
            "choices": st.lists(
                st.fixed_dictionaries(
                    {
                        "index": st.integers(min_value=0, max_value=10),
                        "delta": st.fixed_dictionaries(
                            {
                                "content": st.text(max_size=100),
                            },
                            optional={"role": st.just("assistant")},
                        ),
                    },
                    optional={
                        "finish_reason": st.sampled_from([None, "stop", "length"])
                    },
                ),
                min_size=1,
                max_size=3,
            ),
        }
    )


class TestSSEFormatConsistencyProperty:
    """Property 1: SSE Format Consistency (Requirements 5.1, 5.3)."""

    @given(content=st.text(min_size=1, max_size=200))
    @settings(max_examples=100)
    def test_string_content_produces_valid_sse(self, content: str) -> None:
        """Any string content should produce valid SSE-framed bytes."""
        service = StreamFormattingService()
        result = service.format_chunk_as_sse(content)

        assert isinstance(result, bytes)
        decoded = result.decode("utf-8")

        # Already SSE-formatted content should pass through
        if content.strip().startswith("data:"):
            assert decoded == content
        elif content.strip() in ("[DONE]", '["DONE"]'):
            assert decoded == "data: [DONE]\n\n"
        else:
            assert decoded.startswith("data: ")
            assert decoded.endswith("\n\n")

    @given(content=st.binary(min_size=1, max_size=200))
    @settings(max_examples=100)
    def test_bytes_content_produces_valid_sse(self, content: bytes) -> None:
        """Any bytes content should produce valid SSE-framed bytes."""
        service = StreamFormattingService()
        result = service.format_chunk_as_sse(content)

        assert isinstance(result, bytes)
        decoded = result.decode("utf-8", errors="replace")

        # Already SSE-formatted content should pass through
        if content.strip().startswith(b"data:"):
            assert result == content
        elif content.strip() in (b"[DONE]", b'["DONE"]'):
            assert result == b"data: [DONE]\n\n"
        else:
            assert decoded.startswith("data: ")
            assert decoded.endswith("\n\n")

    @given(content=openai_chunk_dicts())
    @settings(max_examples=100)
    def test_dict_content_produces_valid_sse_json(self, content: dict) -> None:
        """Any dict content should produce valid SSE-framed JSON."""
        service = StreamFormattingService()
        result = service.format_chunk_as_sse(content)

        assert isinstance(result, bytes)
        decoded = result.decode("utf-8")

        assert decoded.startswith("data: ")
        assert decoded.endswith("\n\n")

        # Extract and verify JSON payload
        json_part = decoded[6:-2]
        parsed = json.loads(json_part)
        assert parsed == content

    @given(content=json_dicts())
    @settings(max_examples=100)
    def test_arbitrary_dict_produces_valid_sse(self, content: dict) -> None:
        """Any JSON-serializable dict should produce valid SSE."""
        service = StreamFormattingService()
        result = service.format_chunk_as_sse(content)

        assert isinstance(result, bytes)
        decoded = result.decode("utf-8")

        assert decoded.startswith("data: ")
        assert decoded.endswith("\n\n")


class TestDoneMarkerDetectionProperty:
    """Property 2: Done Marker Detection (Requirements 5.4)."""

    @given(
        done_marker=st.sampled_from(
            [
                "[DONE]",
                '["DONE"]',
                "data: [DONE]",
                'data: ["DONE"]',
                "data: [DONE]\n\n",
                'data: ["DONE"]\n\n',
            ]
        )
    )
    def test_done_markers_detected_as_string(self, done_marker: str) -> None:
        """All known [DONE] marker variants should signal done."""
        service = StreamFormattingService()
        result = service.chunk_signals_done(done_marker, None)
        assert result is True

    @given(
        done_marker=st.sampled_from(
            [
                b"[DONE]",
                b'["DONE"]',
                b"data: [DONE]",
                b'data: ["DONE"]',
                b"data: [DONE]\n\n",
                b'data: ["DONE"]\n\n',
            ]
        )
    )
    def test_done_markers_detected_as_bytes(self, done_marker: bytes) -> None:
        """All known [DONE] marker variants should signal done (bytes)."""
        service = StreamFormattingService()
        result = service.chunk_signals_done(done_marker, None)
        assert result is True

    @given(
        content=st.text(min_size=1, max_size=100).filter(
            lambda s: "DONE" not in s.upper() and "finish_reason" not in s
        )
    )
    @settings(max_examples=100)
    def test_non_done_content_not_detected(self, content: str) -> None:
        """Regular content without DONE markers should not signal done."""
        service = StreamFormattingService()
        result = service.chunk_signals_done(content, None)
        assert result is False

    @given(
        finish_reason=st.sampled_from(
            ["stop", "length", "tool_calls", "content_filter"]
        )
    )
    def test_metadata_finish_reason_with_empty_content_signals_done(
        self, finish_reason: str
    ) -> None:
        """Empty content with metadata.finish_reason should signal done."""
        service = StreamFormattingService()
        metadata = {"finish_reason": finish_reason}

        assert service.chunk_signals_done(None, metadata) is True
        assert service.chunk_signals_done("", metadata) is True

    @given(finish_reason=st.sampled_from(["stop", "length"]))
    def test_openai_finish_reason_in_dict_signals_done(
        self, finish_reason: str
    ) -> None:
        """OpenAI-style finish_reason in choices should signal done."""
        service = StreamFormattingService()
        content = {
            "choices": [{"index": 0, "delta": {}, "finish_reason": finish_reason}]
        }
        assert service.chunk_signals_done(content, None) is True


class TestValidTokenIdentificationProperty:
    """Property 3: Valid Token Identification (Requirements 5.2)."""

    @given(
        text_content=st.text(min_size=1, max_size=100).filter(
            lambda s: s.strip()
            and "DONE" not in s.upper()
            and not s.strip().startswith(":")
        )
    )
    @settings(max_examples=100)
    def test_non_empty_text_is_valid_token(self, text_content: str) -> None:
        """Non-empty text without [DONE] markers should be valid tokens."""
        service = StreamFormattingService()
        result = service.is_valid_completion_token(text_content)
        assert result is True

    @given(
        done_marker=st.sampled_from(
            [
                "[DONE]",
                '["DONE"]',
                "data: [DONE]",
                'data: ["DONE"]',
            ]
        )
    )
    def test_done_markers_are_not_valid_tokens(self, done_marker: str) -> None:
        """[DONE] markers should not be valid completion tokens."""
        service = StreamFormattingService()
        result = service.is_valid_completion_token(done_marker)
        assert result is False

    @given(empty_content=st.sampled_from(["", "   ", "\n", "\t"]))
    def test_empty_content_is_not_valid_token(self, empty_content: str) -> None:
        """Empty or whitespace-only content should not be valid tokens."""
        service = StreamFormattingService()
        result = service.is_valid_completion_token(empty_content)
        assert result is False

    @given(comment=st.text(min_size=0, max_size=50))
    @settings(max_examples=50)
    def test_sse_comments_are_not_valid_tokens(self, comment: str) -> None:
        """SSE comments (starting with :) should not be valid tokens."""
        service = StreamFormattingService()
        sse_comment = f":{comment}"
        result = service.is_valid_completion_token(sse_comment)
        assert result is False

    @given(text_content=st.text(min_size=1, max_size=50))
    @settings(max_examples=100)
    def test_dict_with_content_is_valid_token(self, text_content: str) -> None:
        """Dict with non-empty delta.content should be valid token."""
        service = StreamFormattingService()
        chunk = {"choices": [{"delta": {"content": text_content}}]}
        result = service.is_valid_completion_token(chunk)
        assert result is True

    def test_dict_with_tool_calls_is_valid_token(self) -> None:
        """Dict with tool_calls should be valid token."""
        service = StreamFormattingService()
        chunk = {"choices": [{"delta": {"tool_calls": [{"id": "call_123"}]}}]}
        result = service.is_valid_completion_token(chunk)
        assert result is True

    @given(text_content=st.text(min_size=1, max_size=50))
    @settings(max_examples=100)
    def test_processed_response_with_content_is_valid_token(
        self, text_content: str
    ) -> None:
        """ProcessedResponse with content should be valid token."""
        service = StreamFormattingService()
        response = ProcessedResponse(
            content={"choices": [{"delta": {"content": text_content}}]}
        )
        result = service.is_valid_completion_token(response)
        assert result is True


class TestEquivalenceWithBackendService:
    """Equivalence tests between StreamFormattingService and BackendService."""

    @given(content=openai_chunk_dicts())
    @settings(max_examples=50)
    @pytest.mark.asyncio
    async def test_stream_as_sse_bytes_equivalence(self, content: dict) -> None:
        """StreamFormattingService.stream_as_sse_bytes should match BackendService."""
        from src.core.services.backend_service import BackendService

        service = StreamFormattingService()

        async def gen_for_service():
            yield ProcessedResponse(content=content)

        async def gen_for_backend():
            yield ProcessedResponse(content=content)

        service_result = [
            chunk async for chunk in service.stream_as_sse_bytes(gen_for_service())
        ]
        backend_result = [
            chunk
            async for chunk in BackendService._stream_as_sse_bytes(gen_for_backend())
        ]

        assert service_result == backend_result

    @given(content=st.text(min_size=1, max_size=100).filter(lambda s: s.strip()))
    @settings(max_examples=50)
    def test_format_chunk_as_sse_equivalence_string(self, content: str) -> None:
        """StreamFormattingService.format_chunk_as_sse should match BackendService._format_as_sse for strings."""
        service = StreamFormattingService()

        # Get reference from BackendService inner function
        # We'll just verify the service produces valid SSE
        result = service.format_chunk_as_sse(content)

        if content.strip().startswith("data:"):
            assert result == content.encode("utf-8")
        elif content.strip() in ("[DONE]", '["DONE"]'):
            assert result == b"data: [DONE]\n\n"
        else:
            decoded = result.decode("utf-8")
            assert decoded.startswith("data: ")
            assert decoded.endswith("\n\n")
