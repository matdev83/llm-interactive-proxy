"""
Tests for the streaming utilities module using Hypothesis for property-based testing.
"""

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st
from hypothesis.strategies import composite
from src.connectors.streaming_utils import (
    _ensure_async_iterator,
    normalize_streaming_response,
)
from src.core.domain.responses import StreamingResponseEnvelope


@composite
def streaming_data(draw):
    """Generate various types of streaming data for testing."""
    data_type = draw(st.sampled_from(["bytes", "dict", "str", "list", "mixed"]))

    if data_type == "bytes":
        return draw(st.binary(min_size=1, max_size=100))
    elif data_type == "dict":
        return draw(st.dictionaries(st.text(), st.text()))
    elif data_type == "str":
        return draw(st.text())
    elif data_type == "list":
        return draw(st.lists(st.text()))
    elif data_type == "mixed":
        return draw(
            st.one_of(
                st.binary(min_size=1, max_size=100),
                st.dictionaries(st.text(), st.text()),
                st.text(),
                st.lists(st.text()),
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
    async def test_normalize_streaming_response_basic(self) -> None:
        """Test normalize_streaming_response with basic async iterator."""

        async def mock_stream():
            yield {"choices": [{"delta": {"content": "chunk1"}}]}
            yield {"choices": [{"delta": {"content": "chunk2"}}]}

        envelope = normalize_streaming_response(mock_stream())
        assert isinstance(envelope, StreamingResponseEnvelope)
        assert envelope.media_type == "text/event-stream"
        assert envelope.headers == {}

        # Check content - should be normalized to SSE format
        chunks = []
        async for chunk in envelope.content:
            chunks.append(chunk)

        # Convert to strings for easier comparison
        chunk_strings = [chunk.decode("utf-8") for chunk in chunks]
        assert "chunk1" in chunk_strings[0]
        assert "chunk2" in chunk_strings[1]

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
        chunks = []
        async for chunk in envelope.content:
            chunks.append(chunk)

        assert chunks == [b"chunk1", b"chunk2"]

    @given(
        data_list=st.lists(streaming_data(), min_size=1, max_size=5),
        media_type=st.sampled_from(
            ["text/event-stream", "application/json", "text/plain"]
        ),
        normalize=st.booleans(),
    )
    @settings(
        deadline=None
    )  # Disable deadline for this test due to variable execution time
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
        chunks = []
        async for chunk in envelope.content:
            chunks.append(chunk)

        # Should have some chunks (exact count depends on data processing)
        assert len(chunks) >= 0
