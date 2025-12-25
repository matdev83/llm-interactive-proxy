"""Tests for response adapter protocols.

This module verifies that all protocols are properly defined and can be used
as type hints, and that implementations satisfy protocol contracts.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any

from src.core.domain.responses import ResponseEnvelope, StreamingResponseEnvelope
from src.core.domain.streaming.streaming_content import StreamingContent

# Import all protocols
from src.core.transport.fastapi.adapters.protocols import (
    IHeaderSanitizer,
    IJSONResponseBuilder,
    IJSONSanitizer,
    IOtherResponseBuilder,
    IReasoningInjector,
    ISSEDecoder,
    ISSEFormatter,
    IStreamingContentConverter,
    IStreamingResponseBuilder,
    IToolBlockBuffer,
    IUsageHeaderInjector,
    IUsageNormalizer,
    IWireCaptureCoordinator,
)
from starlette.responses import JSONResponse, Response, StreamingResponse


class TestProtocolTypeHints:
    """Test that protocols can be used as type hints."""

    def test_sse_formatter_protocol_type_hint(self) -> None:
        """Test ISSEFormatter can be used as type hint."""
        formatter: ISSEFormatter | None = None
        assert formatter is None  # Just verify type checking works

    def test_sse_decoder_protocol_type_hint(self) -> None:
        """Test ISSEDecoder can be used as type hint."""
        decoder: ISSEDecoder | None = None
        assert decoder is None

    def test_reasoning_injector_protocol_type_hint(self) -> None:
        """Test IReasoningInjector can be used as type hint."""
        injector: IReasoningInjector | None = None
        assert injector is None

    def test_usage_normalizer_protocol_type_hint(self) -> None:
        """Test IUsageNormalizer can be used as type hint."""
        normalizer: IUsageNormalizer | None = None
        assert normalizer is None

    def test_usage_header_injector_protocol_type_hint(self) -> None:
        """Test IUsageHeaderInjector can be used as type hint."""
        injector: IUsageHeaderInjector | None = None
        assert injector is None

    def test_json_sanitizer_protocol_type_hint(self) -> None:
        """Test IJSONSanitizer can be used as type hint."""
        sanitizer: IJSONSanitizer | None = None
        assert sanitizer is None

    def test_header_sanitizer_protocol_type_hint(self) -> None:
        """Test IHeaderSanitizer can be used as type hint."""
        sanitizer: IHeaderSanitizer | None = None
        assert sanitizer is None

    def test_wire_capture_coordinator_protocol_type_hint(self) -> None:
        """Test IWireCaptureCoordinator can be used as type hint."""
        coordinator: IWireCaptureCoordinator | None = None
        assert coordinator is None

    def test_tool_block_buffer_protocol_type_hint(self) -> None:
        """Test IToolBlockBuffer can be used as type hint."""
        buffer: IToolBlockBuffer | None = None
        assert buffer is None

    def test_streaming_content_converter_protocol_type_hint(self) -> None:
        """Test IStreamingContentConverter can be used as type hint."""
        converter: IStreamingContentConverter | None = None
        assert converter is None

    def test_json_response_builder_protocol_type_hint(self) -> None:
        """Test IJSONResponseBuilder can be used as type hint."""
        builder: IJSONResponseBuilder | None = None
        assert builder is None

    def test_streaming_response_builder_protocol_type_hint(self) -> None:
        """Test IStreamingResponseBuilder can be used as type hint."""
        builder: IStreamingResponseBuilder | None = None
        assert builder is None

    def test_other_response_builder_protocol_type_hint(self) -> None:
        """Test IOtherResponseBuilder can be used as type hint."""
        builder: IOtherResponseBuilder | None = None
        assert builder is None


class TestProtocolContracts:
    """Test that implementations satisfy protocol contracts."""

    def test_sse_formatter_contract(self) -> None:
        """Test ISSEFormatter contract compliance."""

        class MockSSEFormatter:
            def format_chunk(self, content: dict | bytes | str) -> bytes:
                if isinstance(content, dict):
                    return b"data: {}\n\n"
                elif isinstance(content, bytes):
                    return content
                else:
                    return content.encode("utf-8")

        formatter: ISSEFormatter = MockSSEFormatter()
        assert isinstance(formatter.format_chunk({"test": "data"}), bytes)
        assert isinstance(formatter.format_chunk(b"test"), bytes)
        assert isinstance(formatter.format_chunk("test"), bytes)

    def test_sse_decoder_contract(self) -> None:
        """Test ISSEDecoder contract compliance."""
        from src.core.transport.fastapi.adapters.sse.models import DecodedSSE

        class MockSSEDecoder:
            def decode_payload(self, payload: bytes | str) -> DecodedSSE:
                return DecodedSSE(content={}, metadata={}, is_done=False)

        decoder: ISSEDecoder = MockSSEDecoder()
        res = decoder.decode_payload(b"data: {}")
        assert isinstance(res.metadata, dict)
        assert isinstance(res.is_done, bool)

    def test_reasoning_injector_contract(self) -> None:
        """Test IReasoningInjector contract compliance."""

        class MockReasoningInjector:
            def inject_reasoning(self, content: Any, metadata: dict[str, Any]) -> Any:
                return content

            def build_streaming_payload(
                self, content: Any, metadata: dict[str, Any]
            ) -> dict[str, Any]:
                return {"content": content}

        injector: IReasoningInjector = MockReasoningInjector()
        result = injector.inject_reasoning({}, {"reasoning": "test"})
        assert result is not None
        payload = injector.build_streaming_payload("test", {})
        assert isinstance(payload, dict)

    def test_usage_normalizer_contract(self) -> None:
        """Test IUsageNormalizer contract compliance."""

        class MockUsageNormalizer:
            def normalize(self, usage: dict[str, Any] | None) -> dict[str, int]:
                return {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}

            def merge_streaming_usage(
                self, existing: dict[str, int], new: dict[str, Any]
            ) -> dict[str, int]:
                return existing

        normalizer: IUsageNormalizer = MockUsageNormalizer()
        normalized = normalizer.normalize(None)
        assert isinstance(normalized, dict)
        assert all(isinstance(v, int) for v in normalized.values())
        merged = normalizer.merge_streaming_usage({}, {})
        assert isinstance(merged, dict)

    def test_usage_header_injector_contract(self) -> None:
        """Test IUsageHeaderInjector contract compliance."""

        class MockUsageHeaderInjector:
            def inject_headers(
                self, headers: dict[str, str], usage: dict[str, Any]
            ) -> dict[str, str]:
                return headers

        injector: IUsageHeaderInjector = MockUsageHeaderInjector()
        result = injector.inject_headers({}, {"prompt_tokens": 10})
        assert isinstance(result, dict)

    def test_json_sanitizer_contract(self) -> None:
        """Test IJSONSanitizer contract compliance."""

        class MockJSONSanitizer:
            def sanitize(self, content: Any) -> Any:
                return content

        sanitizer: IJSONSanitizer = MockJSONSanitizer()
        result = sanitizer.sanitize({"test": "data"})
        assert result is not None

    def test_header_sanitizer_contract(self) -> None:
        """Test IHeaderSanitizer contract compliance."""

        class MockHeaderSanitizer:
            ALLOWED_PREFIXES: tuple[str, ...] = ("x-",)
            HOP_BY_HOP_HEADERS: frozenset[str] = frozenset({"connection"})

            def sanitize(self, headers: dict[str, str] | None) -> dict[str, str]:
                return headers or {}

        sanitizer: IHeaderSanitizer = MockHeaderSanitizer()
        assert hasattr(sanitizer, "ALLOWED_PREFIXES")
        assert hasattr(sanitizer, "HOP_BY_HOP_HEADERS")
        result = sanitizer.sanitize(None)
        assert isinstance(result, dict)

    def test_wire_capture_coordinator_contract(self) -> None:
        """Test IWireCaptureCoordinator contract compliance."""

        class MockWireCaptureCoordinator:
            def schedule_capture(
                self, envelope: ResponseEnvelope, response_content: Any
            ) -> None:
                pass

            async def wrap_stream(
                self,
                envelope: StreamingResponseEnvelope,
                stream: AsyncIterator[bytes],
            ) -> AsyncIterator[bytes]:
                async for chunk in stream:
                    yield chunk

        coordinator: IWireCaptureCoordinator = MockWireCaptureCoordinator()
        envelope = ResponseEnvelope(content={})
        coordinator.schedule_capture(envelope, {})

    def test_tool_block_buffer_contract(self) -> None:
        """Test IToolBlockBuffer contract compliance."""

        class MockToolBlockBuffer:
            def buffer(self, content: str, stream_id: str | None) -> str:
                return content

            def flush(self) -> str:
                return ""

            def reset(self) -> None:
                pass

        buffer: IToolBlockBuffer = MockToolBlockBuffer()
        result = buffer.buffer("test", None)
        assert isinstance(result, str)
        flushed = buffer.flush()
        assert isinstance(flushed, str)
        buffer.reset()

    def test_streaming_content_converter_contract(self) -> None:
        """Test IStreamingContentConverter contract compliance."""

        class MockStreamingContentConverter:
            async def convert_stream(
                self, raw_stream: AsyncIterator[Any], context: dict[str, Any]
            ) -> AsyncIterator[StreamingContent]:
                yield StreamingContent(content="test")

        MockStreamingContentConverter()

    def test_json_response_builder_contract(self) -> None:
        """Test IJSONResponseBuilder contract compliance."""

        class MockJSONResponseBuilder:
            def build(self, envelope: ResponseEnvelope) -> JSONResponse:
                return JSONResponse(content={})

        builder: IJSONResponseBuilder = MockJSONResponseBuilder()
        envelope = ResponseEnvelope(content={})
        response = builder.build(envelope)
        assert isinstance(response, JSONResponse)

    def test_streaming_response_builder_contract(self) -> None:
        """Test IStreamingResponseBuilder contract compliance."""

        class MockStreamingResponseBuilder:
            def build(self, envelope: StreamingResponseEnvelope) -> StreamingResponse:
                async def empty_stream() -> AsyncIterator[bytes]:
                    return
                    yield  # Make it async generator

                return StreamingResponse(content=empty_stream())

        builder: IStreamingResponseBuilder = MockStreamingResponseBuilder()
        envelope = StreamingResponseEnvelope(content=None)
        response = builder.build(envelope)
        assert isinstance(response, StreamingResponse)

    def test_other_response_builder_contract(self) -> None:
        """Test IOtherResponseBuilder contract compliance."""

        class MockOtherResponseBuilder:
            def build(self, envelope: ResponseEnvelope) -> Response:
                return Response(content=b"test")

        builder: IOtherResponseBuilder = MockOtherResponseBuilder()
        envelope = ResponseEnvelope(content="test", media_type="text/plain")
        response = builder.build(envelope)
        assert isinstance(response, Response)
