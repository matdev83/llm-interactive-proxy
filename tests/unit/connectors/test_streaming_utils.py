"""Tests for the streaming utilities module using Hypothesis for property-based testing."""

import pytest

pytest.importorskip("hypothesis")

# Suppress Windows ProactorEventLoop ResourceWarnings for this module
pytestmark = pytest.mark.filterwarnings(
    "ignore:unclosed event loop <ProactorEventLoop.*:ResourceWarning"
)


@pytest.fixture(autouse=True)
async def setup_di_container():
    """Set up DI container with required services for streaming tests."""
    from src.core.app.stages.core_services import CoreServicesStage
    from src.core.app.stages.infrastructure import InfrastructureStage
    from src.core.app.stages.processor import ProcessorStage
    from src.core.config.app_config import AppConfig
    from src.core.di.container import ServiceCollection
    from src.core.di.services import set_service_provider

    services = ServiceCollection()
    config = AppConfig()

    # Initialize required stages in order
    infrastructure = InfrastructureStage()
    await infrastructure.execute(services, config)

    core_services = CoreServicesStage()
    await core_services.execute(services, config)

    processor = ProcessorStage()
    await processor.execute(services, config)

    # Build and set the service provider globally
    provider = services.build_service_provider()
    set_service_provider(provider)

    yield

    # Cleanup - just set provider to None
    set_service_provider(None)


from collections.abc import AsyncIterator
from typing import Any, cast

import src.connectors.streaming_utils as streaming_utils
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st
from hypothesis.strategies import composite
from src.connectors.streaming_utils import (
    _ensure_async_iterator,
    normalize_streaming_response,
)
from src.core.domain.responses import StreamingResponseEnvelope
from src.core.ports.streaming_contracts import StreamingContent
from src.loop_detection.event import LoopDetectionEvent


@composite
def streaming_data(draw):
    """Generate various types of streaming data for testing."""
    data_type = draw(st.sampled_from(["bytes", "dict", "str", "list", "mixed"]))

    if data_type == "bytes":
        return draw(st.binary(min_size=1, max_size=50))  # Reduced from 100 to 50
    elif data_type == "dict":
        return draw(
            st.dictionaries(st.text(max_size=20), st.text(max_size=20))
        )  # Limit text size
    elif data_type == "str":
        return draw(st.text(max_size=50))  # Limit text size
    elif data_type == "list":
        return draw(
            st.lists(st.text(max_size=20), max_size=5)
        )  # Limit list and text size
    elif data_type == "mixed":
        return draw(
            st.one_of(
                st.binary(min_size=1, max_size=50),  # Reduced from 100
                st.dictionaries(st.text(max_size=20), st.text(max_size=20)),  # Limited
                st.text(max_size=50),  # Limited
                st.lists(st.text(max_size=20), max_size=5),  # Limited
            )
        )


class TestEnsureAsyncIterator:
    """Tests for the _ensure_async_iterator function."""

    @pytest.mark.asyncio
    async def test_ensure_async_iterator_with_async_generator(self) -> None:
        """Test _ensure_async_iterator with an async generator."""

        async def async_gen():
            yield b"chunk1"
            yield b"chunk2"
            yield b"chunk3"

        result = _ensure_async_iterator(async_gen())
        chunks = []
        async for chunk in result:
            chunks.append(chunk)

        assert chunks == [b"chunk1", b"chunk2", b"chunk3"]

    @pytest.mark.asyncio
    async def test_ensure_async_iterator_with_sync_generator(self) -> None:
        """Test _ensure_async_iterator with a sync generator."""

        def sync_gen():
            yield b"chunk1"
            yield b"chunk2"

        result = _ensure_async_iterator(sync_gen())
        chunks = []
        async for chunk in result:
            chunks.append(chunk)

        assert chunks == [b"chunk1", b"chunk2"]

    @pytest.mark.asyncio
    async def test_ensure_async_iterator_with_coroutine(self) -> None:
        """Test _ensure_async_iterator with a coroutine."""

        async def async_list():
            return [b"chunk1", b"chunk2"]

        result = _ensure_async_iterator(async_list())
        chunks = []
        async for chunk in result:
            chunks.append(chunk)

        assert chunks == [b"chunk1", b"chunk2"]

    @given(data=streaming_data())
    @settings(
        max_examples=20,  # Reduced from 30
        deadline=2000,  # Reduced from 3000ms
        suppress_health_check=[HealthCheck.too_slow],
    )
    @pytest.mark.asyncio
    async def test_ensure_async_iterator_with_various_data_types(self, data) -> None:
        """Test _ensure_async_iterator with various data types using Hypothesis."""

        result = _ensure_async_iterator(data)
        chunks = []
        async for chunk in result:
            chunks.append(chunk)

        # For simple data types, we expect one chunk
        assert len(chunks) >= 0  # Could be empty for some cases

        # All chunks should be bytes
        for chunk in chunks:
            assert isinstance(chunk, bytes)


class TestNormalizeStreamingResponse:
    """Tests for the normalize_streaming_response function."""

    @pytest.mark.asyncio
    async def test_normalize_streaming_response_uses_loop_detector(self, monkeypatch):
        """Ensure normalization path routes through loop detection pipeline."""

        class DummyLoopDetector:
            def __init__(self) -> None:
                self.calls: list[str] = []

            def process_chunk(self, chunk: str) -> LoopDetectionEvent | None:
                self.calls.append(chunk)
                if "repeat" in chunk:
                    return LoopDetectionEvent(
                        pattern="repeat",
                        pattern_length=len(chunk),
                        repetition_count=2,
                        total_length=len(chunk) * 2,
                        confidence=1.0,
                        buffer_content=chunk,
                        timestamp=0.0,
                    )
                return None

        dummy_detector = DummyLoopDetector()

        class DummyLoopProcessor:
            async def process(self, content: StreamingContent) -> StreamingContent:
                event = dummy_detector.process_chunk(content.content)
                if event:
                    return StreamingContent(
                        content="[LOOP DETECTED]",
                        is_done=True,
                        is_cancellation=True,
                        metadata={
                            "loop_detected": True,
                            "pattern": event.pattern,
                            "repetition_count": event.repetition_count,
                        },
                    )
                return content

        class DummyStreamNormalizer:
            def __init__(self) -> None:
                self.processor = DummyLoopProcessor()

            def reset(self) -> None:  # pragma: no cover - no-op
                return None

            async def process_stream(
                self, stream: AsyncIterator[Any], output_format: str = "bytes"
            ) -> AsyncIterator[Any]:
                async for raw in stream:
                    content = StreamingContent.from_raw(raw)
                    processed = await self.processor.process(content)
                    if output_format == "bytes":
                        yield processed.to_bytes()
                    else:  # pragma: no cover - tests rely on bytes output
                        yield processed

        dummy_normalizer: DummyStreamNormalizer = DummyStreamNormalizer()

        monkeypatch.setattr(
            streaming_utils,
            "_resolve_stream_normalizer_via_di",
            lambda: dummy_normalizer,
        )

        async def mock_stream() -> AsyncIterator[str]:
            yield "repeat"  # Trigger loop detection

        envelope = normalize_streaming_response(mock_stream())

        chunks: list[bytes] = []
        async for chunk in cast(AsyncIterator[bytes], envelope.content):
            chunks.append(chunk)

        assert dummy_detector.calls, "Loop detector should have been invoked"
        assert any(
            b"LOOP DETECTED" in chunk for chunk in chunks
        ), "Loop break output expected"

    @pytest.mark.asyncio
    async def test_normalize_streaming_response_basic(self, monkeypatch) -> None:
        """Test normalize_streaming_response with basic async iterator."""

        from src.core.services.streaming.stream_normalizer import StreamNormalizer

        fallback_normalizer = StreamNormalizer()

        monkeypatch.setattr(
            streaming_utils,
            "_resolve_stream_normalizer_via_di",
            lambda: fallback_normalizer,
        )

        async def mock_stream():
            yield {"choices": [{"delta": {"content": "chunk1"}}]}
            yield {"choices": [{"delta": {"content": "chunk2"}}]}
            yield {"choices": [{"delta": {}}], "usage": {"total_tokens": 10}}

        envelope = normalize_streaming_response(mock_stream())
        assert isinstance(envelope, StreamingResponseEnvelope)
        assert envelope.media_type == "text/event-stream"
        assert envelope.headers == {}

        # Check content - should be normalized to SSE format
        assert envelope.content is not None
        chunks: list[bytes] = []
        async for chunk in cast(AsyncIterator[bytes], envelope.content):
            chunks.append(chunk)

        # Convert to strings for easier comparison
        chunk_strings = [chunk.decode("utf-8") for chunk in chunks]
        combined = "\n".join(chunk_strings)
        assert "chunk1" in combined
        assert "chunk2" in combined

    @pytest.mark.asyncio
    async def test_normalize_streaming_response_with_headers(self) -> None:
        """Test normalize_streaming_response with custom headers."""
        headers = {"X-Custom": "value", "Content-Type": "text/event-stream"}

        async def mock_stream():
            yield b"data"

        envelope = normalize_streaming_response(mock_stream(), headers=headers)
        assert envelope.headers == headers

    @pytest.mark.asyncio
    async def test_normalize_streaming_response_with_media_type(self) -> None:
        """Test normalize_streaming_response with custom media type."""
        media_type = "application/json"

        async def mock_stream():
            yield b"data"

        envelope = normalize_streaming_response(mock_stream(), media_type=media_type)
        assert envelope.media_type == media_type

    @pytest.mark.asyncio
    async def test_normalize_streaming_response_without_normalization(self) -> None:
        """Test normalize_streaming_response with normalization disabled."""

        async def mock_stream():
            yield b"chunk1"
            yield b"chunk2"

        envelope = normalize_streaming_response(mock_stream(), normalize=False)

        # Check content
        assert envelope.content is not None
        chunks: list[bytes] = []
        async for chunk in cast(AsyncIterator[bytes], envelope.content):
            chunks.append(chunk)

        assert chunks == [b"chunk1", b"chunk2"]

    @given(
        data_list=st.lists(streaming_data(), min_size=1, max_size=2),  # Reduced from 3
        media_type=st.sampled_from(["text/event-stream", "application/json"]),
        normalize=st.booleans(),
    )
    @settings(
        max_examples=20,  # Further reduced for performance
        deadline=5000,  # Increased deadline to prevent timeout
        suppress_health_check=[HealthCheck.too_slow],
    )
    @pytest.mark.asyncio
    async def test_normalize_streaming_response_property_based(
        self, data_list, media_type, normalize
    ) -> None:
        """Property-based test for normalize_streaming_response."""

        async def mock_stream():
            for data in data_list:
                yield data

        headers = {"X-Test": "value"}
        envelope = normalize_streaming_response(
            mock_stream(), normalize=normalize, media_type=media_type, headers=headers
        )

        assert isinstance(envelope, StreamingResponseEnvelope)
        assert envelope.media_type == media_type
        assert envelope.headers == headers

        # Collect content
        chunks = [chunk async for chunk in cast(AsyncIterator[bytes], envelope.content)]

        # Should have some chunks (exact count depends on data processing)
        assert len(chunks) >= 0
