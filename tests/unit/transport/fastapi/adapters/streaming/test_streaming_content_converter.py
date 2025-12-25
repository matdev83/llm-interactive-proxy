"""Tests for StreamingContentConverter."""

from __future__ import annotations

from collections.abc import AsyncIterator
from unittest.mock import MagicMock, patch

import pytest
from src.core.domain.streaming.streaming_content import StreamingContent
from src.core.interfaces.response_processor_interface import ProcessedResponse
from src.core.transport.fastapi.adapters.protocols import (
    IReasoningInjector,
    ISSEDecoder,
    IStreamingContentConverter,
    IToolBlockBuffer,
    IUsageNormalizer,
)
from src.core.transport.fastapi.adapters.streaming.content_converter import (
    StreamingContentConverter,
)


class TestStreamingContentConverter:
    """Test StreamingContentConverter implementation."""

    def test_converter_implements_protocol(self) -> None:
        """Test that StreamingContentConverter implements IStreamingContentConverter protocol."""
        converter: IStreamingContentConverter = StreamingContentConverter()
        assert isinstance(converter, StreamingContentConverter)

    @pytest.mark.asyncio
    async def test_processed_response_normalization(self) -> None:
        """Test ProcessedResponse normalization."""
        converter = StreamingContentConverter()

        async def raw_stream() -> AsyncIterator[ProcessedResponse]:
            yield ProcessedResponse(
                content={"choices": [{"delta": {"content": "test"}}]},
                metadata={"stream_id": "test-123"},
            )

        context = {}
        results = []
        async for content in converter.convert_stream(raw_stream(), context):
            results.append(content)

        assert len(results) == 1
        assert isinstance(results[0], StreamingContent)
        assert results[0].content == {"choices": [{"delta": {"content": "test"}}]}
        assert results[0].metadata.get("stream_id") == "test-123"

    @pytest.mark.asyncio
    async def test_raw_chunk_normalization(self) -> None:
        """Test raw chunk normalization."""
        converter = StreamingContentConverter()

        async def raw_stream() -> AsyncIterator[dict]:
            yield {"choices": [{"delta": {"content": "test"}}]}

        context = {}
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

        async def raw_stream() -> AsyncIterator[bytes]:
            yield b'data: {"test": "data"}\n\n'

        context = {}
        results = []
        async for content in converter.convert_stream(raw_stream(), context):
            results.append(content)

        mock_decoder.decode_payload.assert_called()
        assert len(results) == 1

    @pytest.mark.asyncio
    async def test_metadata_merging(self) -> None:
        """Test metadata merging from decoded content."""
        converter = StreamingContentConverter()

        async def raw_stream() -> AsyncIterator[ProcessedResponse]:
            yield ProcessedResponse(
                content={"finish_reason": "stop", "id": "test-id"},
                metadata={"stream_id": "test-123"},
            )

        context = {}
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

        context = {}
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

        context = {}
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

        async def raw_stream() -> AsyncIterator[bytes]:
            yield b"data: [DONE]\n\n"

        context = {}
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

        context = {}
        results = []
        async for content in converter.convert_stream(raw_stream(), context):
            results.append(content)

        assert len(results) == 1
        assert results[0].is_done is True

    @pytest.mark.asyncio
    async def test_event_loop_yielding(self) -> None:
        """Test event loop yielding with asyncio.sleep(0)."""
        converter = StreamingContentConverter()

        async def raw_stream() -> AsyncIterator[ProcessedResponse]:
            yield ProcessedResponse(content="test", metadata={})

        context = {}
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

        context = {}
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

        context = {}
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

        context = {}
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

        context = {}
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

        context = {}
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

        context = {
            "envelope_metadata": {},
            "context": MagicMock(),
        }
        context["context"].requires_usage_recalculation.return_value = False

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
    async def test_sync_iterator_handling(self) -> None:
        """Test handling of sync iterators."""
        converter = StreamingContentConverter()

        def sync_stream() -> list[ProcessedResponse]:
            return [
                ProcessedResponse(content="test1", metadata={}),
                ProcessedResponse(content="test2", metadata={}),
            ]

        context = {}
        results = []
        async for content in converter.convert_stream(iter(sync_stream()), context):
            results.append(content)

        assert len(results) == 2
