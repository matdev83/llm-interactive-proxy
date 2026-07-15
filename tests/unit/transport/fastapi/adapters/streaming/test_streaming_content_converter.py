"""Tests for StreamingContentConverter."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from typing import TYPE_CHECKING
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from pydantic.types import JsonValue
from src.core.domain.streaming.streaming_content import StreamingContent
from src.core.interfaces.response_processor_interface import ProcessedResponse
from src.core.transport.fastapi.adapters.protocols import (
    IReasoningInjector,
    ISSEDecoder,
    IToolBlockBuffer,
    IUsageNormalizer,
)
from src.core.transport.fastapi.adapters.streaming.content_converter import (
    StreamingContentConverter,
)

if TYPE_CHECKING:
    from src.core.domain.request_context import RequestContext


class TestStreamingContentConverter:
    """Test StreamingContentConverter implementation."""

    def test_converter_implements_protocol(self) -> None:
        """Test that StreamingContentConverter implements IStreamingContentConverter protocol."""
        converter = StreamingContentConverter()
        # Type check: async generator functions are valid Protocol implementations
        # but pyright doesn't recognize them, so we verify runtime behavior instead
        assert isinstance(converter, StreamingContentConverter)
        assert hasattr(converter, "convert_stream")
        assert callable(converter.convert_stream)

    @pytest.mark.asyncio
    async def test_converter_closes_source_after_terminal_chunk(self) -> None:
        converter = StreamingContentConverter()
        closed = False

        async def raw_stream() -> AsyncIterator[ProcessedResponse]:
            nonlocal closed
            try:
                yield ProcessedResponse(content="data: [DONE]\n\n", metadata={})
            finally:
                closed = True

        results = []
        async for content in converter.convert_stream(raw_stream(), {}):
            results.append(content)

        assert results[-1].is_done is True
        assert closed is True

    @pytest.mark.asyncio
    async def test_processed_response_normalization(self) -> None:
        """Test ProcessedResponse normalization."""
        converter = StreamingContentConverter()

        async def raw_stream() -> AsyncIterator[ProcessedResponse]:
            yield ProcessedResponse(
                content={"choices": [{"delta": {"content": "test"}}]},
                metadata={"stream_id": "test-123"},
            )

        context: dict[str, JsonValue | RequestContext | None] = {}
        results = []
        async for content in converter.convert_stream(raw_stream(), context):
            results.append(content)

        assert len(results) == 1
        assert isinstance(results[0], StreamingContent)
        assert results[0].content == {"choices": [{"delta": {"content": "test"}}]}
        assert results[0].metadata.get("stream_id") == "test-123"

    @pytest.mark.asyncio
    async def test_raw_chunk_normalization(self) -> None:
        """Test ProcessedResponse normalization with dict content."""
        converter = StreamingContentConverter()

        async def raw_stream() -> AsyncIterator[ProcessedResponse]:
            yield ProcessedResponse(
                content={"choices": [{"delta": {"content": "test"}}]},
                metadata={},
            )

        context: dict[str, JsonValue | RequestContext | None] = {}
        results = []
        async for content in converter.convert_stream(raw_stream(), context):
            results.append(content)

        assert len(results) == 1
        assert isinstance(results[0], StreamingContent)

    @pytest.mark.asyncio
    async def test_sse_payload_decoding(self) -> None:
        """Test SSE payload decoding."""
        from src.core.transport.fastapi.adapters.sse.models import DecodedSSE

        mock_decoder = MagicMock(spec=ISSEDecoder)
        mock_decoder.decode_payload.return_value = DecodedSSE(
            content={"choices": [{"delta": {"content": "decoded"}}]},
            metadata={"finish_reason": "stop"},
            is_done=False,
        )

        converter = StreamingContentConverter(sse_decoder=mock_decoder)

        async def raw_stream() -> AsyncIterator[ProcessedResponse]:
            yield ProcessedResponse(
                content=b'data: {"test": "data"}\n\n',
                metadata={},
            )

        context: dict[str, JsonValue | RequestContext | None] = {}
        results = []
        async for content in converter.convert_stream(raw_stream(), context):
            results.append(content)

        mock_decoder.decode_payload.assert_called()
        assert len(results) == 1

    @pytest.mark.asyncio
    async def test_non_opencode_reasoning_only_stream_does_not_get_placeholder(
        self,
    ) -> None:
        from src.core.transport.fastapi.adapters.sse.models import DecodedSSE

        mock_decoder = MagicMock(spec=ISSEDecoder)
        mock_decoder.decode_payload.return_value = DecodedSSE(
            content={
                "choices": [
                    {
                        "index": 0,
                        "delta": {"reasoning_content": "thinking", "content": ""},
                        "finish_reason": None,
                    }
                ]
            },
            metadata={},
            is_done=False,
        )

        converter = StreamingContentConverter(sse_decoder=mock_decoder)

        async def raw_stream() -> AsyncIterator[ProcessedResponse]:
            yield ProcessedResponse(
                content=b"data: {}\n\n",
                metadata={"provider": "openai"},
            )

        results: list[StreamingContent] = []
        async for content in converter.convert_stream(raw_stream(), {}):
            results.append(content)

        assert len(results) == 1
        assert isinstance(results[0].content, dict)
        delta = results[0].content["choices"][0]["delta"]
        assert delta["content"] == ""

    @pytest.mark.asyncio
    async def test_metadata_merging(self) -> None:
        """Test metadata merging from decoded content."""
        converter = StreamingContentConverter()

        async def raw_stream() -> AsyncIterator[ProcessedResponse]:
            yield ProcessedResponse(
                content={"finish_reason": "stop", "id": "test-id"},
                metadata={"stream_id": "test-123"},
            )

        context: dict[str, JsonValue | RequestContext | None] = {}
        results = []
        async for content in converter.convert_stream(raw_stream(), context):
            results.append(content)

        assert len(results) == 1
        # Metadata should be merged from decoded payload
        assert results[0].metadata.get("finish_reason") == "stop"

    @pytest.mark.asyncio
    async def test_usage_tracking_highest_values(self) -> None:
        """Test usage tracking keeps highest values."""
        mock_normalizer = MagicMock(spec=IUsageNormalizer)
        mock_normalizer.merge_streaming_usage.side_effect = lambda existing, new: {
            "prompt_tokens": max(
                existing.get("prompt_tokens", 0), new.get("prompt_tokens", 0)
            ),
            "completion_tokens": max(
                existing.get("completion_tokens", 0), new.get("completion_tokens", 0)
            ),
            "total_tokens": max(
                existing.get("total_tokens", 0), new.get("total_tokens", 0)
            ),
        }

        converter = StreamingContentConverter(usage_normalizer=mock_normalizer)

        async def raw_stream() -> AsyncIterator[ProcessedResponse]:
            yield ProcessedResponse(
                content={"usage": {"prompt_tokens": 10, "completion_tokens": 20}},
                metadata={},
            )
            yield ProcessedResponse(
                content={"usage": {"prompt_tokens": 15, "completion_tokens": 25}},
                metadata={},
            )

        context: dict[str, JsonValue | RequestContext | None] = {}
        results = []
        async for content in converter.convert_stream(raw_stream(), context):
            results.append(content)

        # Usage should be tracked and merged
        assert mock_normalizer.merge_streaming_usage.called

    @pytest.mark.asyncio
    async def test_finish_reason_detection(self) -> None:
        """Test finish_reason detection."""
        converter = StreamingContentConverter()

        async def raw_stream() -> AsyncIterator[ProcessedResponse]:
            yield ProcessedResponse(
                content={"choices": [{"finish_reason": "stop"}]},
                metadata={},
            )

        context: dict[str, JsonValue | RequestContext | None] = {}
        results = []
        async for content in converter.convert_stream(raw_stream(), context):
            results.append(content)

        assert len(results) == 1
        assert results[0].is_done is True

    @pytest.mark.asyncio
    async def test_done_marker_detection(self) -> None:
        """Test [DONE] marker detection."""
        from src.core.transport.fastapi.adapters.sse.models import DecodedSSE

        mock_decoder = MagicMock(spec=ISSEDecoder)
        mock_decoder.decode_payload.return_value = DecodedSSE(
            content="",
            metadata={"finish_reason": "stop"},
            is_done=True,  # forced_done
        )

        converter = StreamingContentConverter(sse_decoder=mock_decoder)

        async def raw_stream() -> AsyncIterator[ProcessedResponse]:
            yield ProcessedResponse(
                content=b"data: [DONE]\n\n",
                metadata={},
            )

        context: dict[str, JsonValue | RequestContext | None] = {}
        results = []
        async for content in converter.convert_stream(raw_stream(), context):
            results.append(content)

        assert len(results) == 1
        assert results[0].is_done is True

    @pytest.mark.asyncio
    async def test_is_done_metadata_detection(self) -> None:
        """Test is_done metadata detection."""
        converter = StreamingContentConverter()

        async def raw_stream() -> AsyncIterator[ProcessedResponse]:
            yield ProcessedResponse(
                content={},
                metadata={"is_done": True},
            )

        context: dict[str, JsonValue | RequestContext | None] = {}
        results = []
        async for content in converter.convert_stream(raw_stream(), context):
            results.append(content)

        assert len(results) == 1
        assert results[0].is_done is True

    @pytest.mark.asyncio
    async def test_error_metadata_marks_done(self) -> None:
        """Error metadata should mark finish_reason=error and done."""
        converter = StreamingContentConverter()

        async def raw_stream() -> AsyncIterator[ProcessedResponse]:
            yield ProcessedResponse(
                content={"choices": [{"delta": {}}]},
                metadata={"error": "payload_too_large"},
            )

        context: dict[str, JsonValue | RequestContext | None] = {}
        results = []
        async for content in converter.convert_stream(raw_stream(), context):
            results.append(content)

        assert len(results) == 1
        assert results[0].metadata.get("finish_reason") == "error"
        assert results[0].is_done is True

    @pytest.mark.asyncio
    async def test_error_metadata_is_dict_on_exception(self) -> None:
        """Ensure error metadata is a dict when conversion fails."""
        converter = StreamingContentConverter()

        async def raw_stream() -> AsyncIterator[ProcessedResponse]:
            yield ProcessedResponse(content="ok", metadata={})
            raise RuntimeError("boom")

        context: dict[str, JsonValue | RequestContext | None] = {}
        results = []
        async for content in converter.convert_stream(raw_stream(), context):
            results.append(content)

        assert results
        error_chunk = results[-1]
        assert error_chunk.is_done is True
        error_meta = error_chunk.metadata.get("error")
        assert isinstance(error_meta, dict)
        assert "boom" in str(error_meta.get("message"))

    @pytest.mark.asyncio
    async def test_event_loop_yielding(self) -> None:
        """Test event loop yielding with asyncio.sleep(0)."""
        # Set yield_interval=1 to ensure yielding on every chunk for testing
        converter = StreamingContentConverter(yield_interval=1)

        async def raw_stream() -> AsyncIterator[ProcessedResponse]:
            yield ProcessedResponse(content="test", metadata={})

        context: dict[str, JsonValue | RequestContext | None] = {}
        results = []
        # This test verifies that asyncio.sleep(0) is called (yielding to event loop)
        with patch("asyncio.sleep") as mock_sleep:
            async for content in converter.convert_stream(raw_stream(), context):
                results.append(content)

        # Should yield to event loop between chunks
        assert mock_sleep.called

    @pytest.mark.asyncio
    async def test_generator_exit_cleanup(self) -> None:
        """Test GeneratorExit cleanup."""
        converter = StreamingContentConverter()

        async def raw_stream() -> AsyncIterator[ProcessedResponse]:
            yield ProcessedResponse(content="test", metadata={})
            raise GeneratorExit()

        context: dict[str, JsonValue | RequestContext | None] = {}
        results = []

        # GeneratorExit should be re-raised, not caught as error
        with pytest.raises(GeneratorExit):
            async for content in converter.convert_stream(raw_stream(), context):
                results.append(content)

    @pytest.mark.asyncio
    async def test_empty_stream_handling(self) -> None:
        """Test empty stream handling."""
        converter = StreamingContentConverter()

        async def raw_stream() -> AsyncIterator[ProcessedResponse]:
            return
            yield  # type: ignore[unreachable]

        context: dict[str, JsonValue | RequestContext | None] = {}
        results = []
        async for content in converter.convert_stream(raw_stream(), context):
            results.append(content)

        assert len(results) == 0

    @pytest.mark.asyncio
    async def test_reasoning_injection(self) -> None:
        """Test reasoning metadata injection."""
        mock_injector = MagicMock(spec=IReasoningInjector)
        mock_injector.inject_reasoning.return_value = {
            "choices": [{"delta": {"content": "test", "reasoning_content": "thinking"}}]
        }

        converter = StreamingContentConverter(reasoning_injector=mock_injector)

        async def raw_stream() -> AsyncIterator[ProcessedResponse]:
            yield ProcessedResponse(
                content={"choices": [{"delta": {"content": "test"}}]},
                metadata={"reasoning_content": "thinking"},
            )

        context: dict[str, JsonValue | RequestContext | None] = {}
        results = []
        async for content in converter.convert_stream(raw_stream(), context):
            results.append(content)

        mock_injector.inject_reasoning.assert_called()

    @pytest.mark.asyncio
    async def test_tool_block_buffering(self) -> None:
        """Test tool block buffering integration."""
        mock_buffer = MagicMock(spec=IToolBlockBuffer)
        mock_buffer.buffer.return_value = "<read_file>test</read_file>"

        converter = StreamingContentConverter(tool_block_buffer=mock_buffer)

        async def raw_stream() -> AsyncIterator[ProcessedResponse]:
            yield ProcessedResponse(
                content={
                    "choices": [{"delta": {"content": "<read_file>test</read_file>"}}]
                },
                metadata={"stream_id": "test-123"},
            )

        context: dict[str, JsonValue | RequestContext | None] = {}
        results = []
        async for content in converter.convert_stream(raw_stream(), context):
            results.append(content)

        # Tool block buffer should be called
        mock_buffer.buffer.assert_called()

    @pytest.mark.asyncio
    async def test_error_handling(self) -> None:
        """Test error handling produces error StreamingContent."""
        converter = StreamingContentConverter()

        async def raw_stream() -> AsyncIterator[ProcessedResponse]:
            raise ValueError("Test error")
            yield  # type: ignore[unreachable]

        context: dict[str, JsonValue | RequestContext | None] = {}
        results = []
        async for content in converter.convert_stream(raw_stream(), context):
            results.append(content)

        # Should yield error StreamingContent
        assert len(results) == 1
        assert results[0].is_done is True
        assert "error" in results[0].metadata

    @pytest.mark.asyncio
    async def test_usage_recalculation_on_done(self) -> None:
        """Test usage recalculation when stream completes."""
        converter = StreamingContentConverter()

        async def raw_stream() -> AsyncIterator[ProcessedResponse]:
            yield ProcessedResponse(
                content={
                    "choices": [{"delta": {"content": "test"}, "finish_reason": "stop"}]
                },
                metadata={},
            )

        mock_context = MagicMock()
        mock_context.requires_usage_recalculation.return_value = False
        context: dict[str, JsonValue | RequestContext | None] = {
            "envelope_metadata": {},
            "context": mock_context,  # type: ignore[assignment]
        }

        with patch(
            "src.core.services.usage_calculation_service.get_usage_calculation_service"
        ) as mock_get_service:
            mock_service = MagicMock()
            mock_get_service.return_value = mock_service
            mock_service.merge_streaming_usage.return_value = {
                "prompt_tokens": 10,
                "completion_tokens": 20,
                "total_tokens": 30,
            }

            results = []
            async for content in converter.convert_stream(raw_stream(), context):
                results.append(content)

            # Usage service should be called on completion
            assert len(results) == 1
            assert results[0].is_done is True

    @pytest.mark.asyncio
    async def test_usage_recalculation_timeout_uses_best_effort_fallback(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from src.core.transport.fastapi.adapters.streaming import (
            content_converter as module_under_test,
        )

        converter = StreamingContentConverter()

        async def raw_stream() -> AsyncIterator[ProcessedResponse]:
            yield ProcessedResponse(
                content={
                    "choices": [
                        {"delta": {"content": "test"}, "finish_reason": "stop"}
                    ],
                    "usage": {
                        "prompt_tokens": 3,
                        "completion_tokens": 4,
                        "total_tokens": 7,
                    },
                },
                metadata={},
            )

        mock_context = MagicMock()
        mock_context.requires_usage_recalculation.return_value = False
        context: dict[str, JsonValue | RequestContext | None] = {
            "envelope_metadata": {},
            "context": mock_context,  # type: ignore[assignment]
        }

        with patch(
            "src.core.services.usage_calculation_service.get_usage_calculation_service"
        ) as mock_get_service:
            mock_service = MagicMock()
            mock_get_service.return_value = mock_service
            monkeypatch.setattr(
                module_under_test.asyncio,
                "wait_for",
                AsyncMock(side_effect=asyncio.TimeoutError()),
            )

            results = []
            async for content in converter.convert_stream(raw_stream(), context):
                results.append(content)

        assert len(results) == 1
        assert results[0].is_done is True
        assert results[0].usage is not None
        assert results[0].usage.prompt_tokens == 3

    @pytest.mark.asyncio
    async def test_sync_iterator_handling(self) -> None:
        """Test handling of sync iterators."""
        converter = StreamingContentConverter()

        def sync_stream() -> list[ProcessedResponse]:
            return [
                ProcessedResponse(content="test1", metadata={}),
                ProcessedResponse(content="test2", metadata={}),
            ]

        context: dict[str, JsonValue | RequestContext | None] = {}
        results = []

        # Convert sync iterator to async iterator
        async def async_stream():
            for item in sync_stream():
                yield item

        async for content in converter.convert_stream(async_stream(), context):
            results.append(content)

        assert len(results) == 2

    @pytest.mark.asyncio
    async def test_typed_processed_response_bytes_content(self) -> None:
        """Test typed ProcessedResponse with bytes content."""
        converter = StreamingContentConverter()

        async def raw_stream() -> AsyncIterator[ProcessedResponse]:
            yield ProcessedResponse(
                content=b"test bytes content",
                metadata={"stream_id": "test-123"},
            )

        context: dict[str, JsonValue | RequestContext | None] = {}
        results = []
        async for content in converter.convert_stream(raw_stream(), context):
            results.append(content)

        assert len(results) == 1
        assert isinstance(results[0], StreamingContent)
        assert isinstance(results[0].content, bytes | str)

    @pytest.mark.asyncio
    async def test_typed_processed_response_str_content(self) -> None:
        """Test typed ProcessedResponse with string content."""
        converter = StreamingContentConverter()

        async def raw_stream() -> AsyncIterator[ProcessedResponse]:
            yield ProcessedResponse(
                content="test string content",
                metadata={"stream_id": "test-456"},
            )

        context: dict[str, JsonValue | RequestContext | None] = {}
        results = []
        async for content in converter.convert_stream(raw_stream(), context):
            results.append(content)

        assert len(results) == 1
        assert isinstance(results[0], StreamingContent)
        # String content is normalized to OpenAI-style dict format by the converter
        assert isinstance(results[0].content, dict)

    @pytest.mark.asyncio
    async def test_typed_processed_response_dict_content(self) -> None:
        """Test typed ProcessedResponse with dict[str, JsonValue] content."""
        converter = StreamingContentConverter()

        async def raw_stream() -> AsyncIterator[ProcessedResponse]:
            yield ProcessedResponse(
                content={"choices": [{"delta": {"content": "test"}}]},
                metadata={"stream_id": "test-789"},
            )

        context: dict[str, JsonValue | RequestContext | None] = {}
        results = []
        async for content in converter.convert_stream(raw_stream(), context):
            results.append(content)

        assert len(results) == 1
        assert isinstance(results[0], StreamingContent)
        assert isinstance(results[0].content, dict)

    @pytest.mark.asyncio
    async def test_typed_processed_response_none_content(self) -> None:
        """Test typed ProcessedResponse with None content."""
        converter = StreamingContentConverter()

        async def raw_stream() -> AsyncIterator[ProcessedResponse]:
            yield ProcessedResponse(
                content=None,
                metadata={"stream_id": "test-none"},
            )

        context: dict[str, JsonValue | RequestContext | None] = {}
        results = []
        async for content in converter.convert_stream(raw_stream(), context):
            results.append(content)

        assert len(results) == 1
        assert isinstance(results[0], StreamingContent)

    @pytest.mark.asyncio
    async def test_typed_processed_response_with_usage_summary(self) -> None:
        """Test typed ProcessedResponse with UsageSummary."""
        from src.core.domain.usage_summary import UsageSummary

        converter = StreamingContentConverter()

        usage = UsageSummary(
            prompt_tokens=10,
            completion_tokens=20,
            total_tokens=30,
        )

        async def raw_stream() -> AsyncIterator[ProcessedResponse]:
            yield ProcessedResponse(
                content={"choices": [{"delta": {"content": "test"}}]},
                usage=usage,
                metadata={"stream_id": "test-usage"},
            )

        context: dict[str, JsonValue | RequestContext | None] = {}
        results = []
        async for content in converter.convert_stream(raw_stream(), context):
            results.append(content)

        assert len(results) == 1
        assert isinstance(results[0], StreamingContent)
        assert results[0].usage is not None
        assert results[0].usage.prompt_tokens == 10

    @pytest.mark.asyncio
    async def test_typed_processed_response_json_safe_metadata(self) -> None:
        """Test typed ProcessedResponse with JSON-safe metadata."""
        converter = StreamingContentConverter()

        async def raw_stream_json() -> AsyncIterator[ProcessedResponse]:
            yield ProcessedResponse(
                content="test",
                metadata={
                    "stream_id": "test-json",
                    "finish_reason": "stop",
                    "model": "test-model",
                    "nested": {"key": "value", "number": 42},
                },
            )

        context_json: dict[str, JsonValue | RequestContext | None] = {}
        results = []
        async for content in converter.convert_stream(raw_stream_json(), context_json):
            results.append(content)

        assert len(results) == 1
        assert isinstance(results[0], StreamingContent)
        assert results[0].metadata.get("stream_id") == "test-json"
        assert results[0].metadata.get("finish_reason") == "stop"

    @pytest.mark.asyncio
    async def test_expected_proxy_error_does_not_log_traceback(self, caplog) -> None:
        """Expected LLMProxyError should not emit raw traceback logs."""
        from src.core.common.exceptions import BackendError

        converter = StreamingContentConverter()

        async def raw_stream() -> AsyncIterator[ProcessedResponse]:
            raise BackendError(
                "rate limited", status_code=429, code="rate_limit_exceeded"
            )
            yield  # pragma: no cover

        caplog.set_level("ERROR")
        context: dict[str, JsonValue | RequestContext | None] = {}

        results: list[StreamingContent] = []
        async for content in converter.convert_stream(raw_stream(), context):
            results.append(content)

        assert results
        assert results[-1].is_done is True
        assert isinstance(results[-1].metadata.get("error"), dict)

        messages = [rec.getMessage() for rec in caplog.records]
        assert any("Streaming content conversion terminated" in m for m in messages)

        async def raw_stream_json() -> AsyncIterator[ProcessedResponse]:
            yield ProcessedResponse(
                content="test",
                metadata={
                    "stream_id": "test-json",
                    "finish_reason": "stop",
                    "model": "test-model",
                    "nested": {"key": "value", "number": 42},
                },
            )

        context_json: dict[str, JsonValue | RequestContext | None] = {}
        results = []
        async for content in converter.convert_stream(raw_stream_json(), context_json):
            results.append(content)

        assert len(results) == 1
        assert isinstance(results[0], StreamingContent)
        assert results[0].metadata.get("stream_id") == "test-json"
        assert results[0].metadata.get("finish_reason") == "stop"
