"""
Tests for Response Adapters module.

This module tests the response conversion functions between domain models and FastAPI responses.
"""


import pytest
from src.core.adapters.response_adapters import (
    adapt_response,
    to_fastapi_response,
    to_fastapi_streaming_response,
    wrap_async_iterator,
)
from src.core.domain.responses import ResponseEnvelope, StreamingResponseEnvelope
from starlette.responses import JSONResponse, StreamingResponse


class TestToFastapiResponse:
    """Tests for to_fastapi_response function."""

    def test_basic_response_conversion(self) -> None:
        """Test basic ResponseEnvelope to FastAPI response conversion."""
        envelope = ResponseEnvelope(
            content={"test": "data"},
            status_code=200,
            headers={"X-Custom": "test"},
        )

        response = to_fastapi_response(envelope)

        assert isinstance(response, JSONResponse)
        assert response.status_code == 200
        assert response.headers.get("X-Custom") == "test"

        # Check content
        content = response.body.decode()
        assert '"test":"data"' in content

    def test_response_with_default_headers(self) -> None:
        """Test response conversion with default headers."""
        envelope = ResponseEnvelope(
            content={"message": "success"},
            status_code=201,
        )

        response = to_fastapi_response(envelope)

        assert isinstance(response, JSONResponse)
        assert response.status_code == 201
        assert "content-type" in response.headers

    def test_response_with_none_headers(self) -> None:
        """Test response conversion with None headers."""
        envelope = ResponseEnvelope(
            content={"error": "not found"},
            status_code=404,
            headers=None,
        )

        response = to_fastapi_response(envelope)

        assert isinstance(response, JSONResponse)
        assert response.status_code == 404


class TestToFastapiStreamingResponse:
    """Tests for to_fastapi_streaming_response function."""

    def test_basic_streaming_response_conversion(self) -> None:
        """Test basic StreamingResponseEnvelope to FastAPI response conversion."""
        async def mock_iterator():
            yield b"chunk1"
            yield b"chunk2"

        envelope = StreamingResponseEnvelope(
            content=mock_iterator(),
            media_type="text/plain",
            headers={"X-Stream": "test"},
        )

        response = to_fastapi_streaming_response(envelope)

        assert isinstance(response, StreamingResponse)
        assert response.media_type == "text/plain"
        assert response.headers.get("X-Stream") == "test"

    def test_streaming_response_with_default_media_type(self) -> None:
        """Test streaming response with default media type."""
        async def mock_iterator():
            yield b"data"

        envelope = StreamingResponseEnvelope(
            content=mock_iterator(),
        )

        response = to_fastapi_streaming_response(envelope)

        assert isinstance(response, StreamingResponse)
        assert response.media_type == "text/event-stream"  # Default media type


class TestAdaptResponse:
    """Tests for adapt_response function."""

    def test_adapt_response_envelope(self) -> None:
        """Test adapting a ResponseEnvelope."""
        envelope = ResponseEnvelope(
            content={"test": "data"},
            status_code=200,
        )

        response = adapt_response(envelope)

        assert isinstance(response, JSONResponse)
        assert response.status_code == 200

    def test_adapt_streaming_response_envelope(self) -> None:
        """Test adapting a StreamingResponseEnvelope."""
        async def mock_iterator():
            yield b"data"

        envelope = StreamingResponseEnvelope(
            content=mock_iterator(),
            media_type="text/plain",
        )

        response = adapt_response(envelope)

        assert isinstance(response, StreamingResponse)
        assert response.media_type == "text/plain"

    def test_adapt_existing_response(self) -> None:
        """Test adapting an existing FastAPI Response."""
        existing_response = JSONResponse(
            content={"existing": "response"},
            status_code=200,
        )

        response = adapt_response(existing_response)

        # Should return the same response object
        assert response is existing_response

    def test_adapt_invalid_type(self) -> None:
        """Test adapting an invalid response type."""
        with pytest.raises(TypeError, match="Unexpected response type"):
            adapt_response("invalid response")


class TestWrapAsyncIterator:
    """Tests for wrap_async_iterator function."""

    @pytest.mark.asyncio
    async def test_wrap_without_mapper(self) -> None:
        """Test wrapping async iterator without mapper function."""
        async def source():
            yield b"chunk1"
            yield b"chunk2"
            yield b"chunk3"

        wrapped = wrap_async_iterator(source())

        chunks = []
        async for chunk in wrapped:
            chunks.append(chunk)

        assert chunks == [b"chunk1", b"chunk2", b"chunk3"]

    @pytest.mark.asyncio
    async def test_wrap_with_mapper(self) -> None:
        """Test wrapping async iterator with mapper function."""
        async def source():
            yield b"chunk1"
            yield b"chunk2"

        def uppercase_mapper(chunk: bytes) -> bytes:
            return chunk.upper()

        wrapped = wrap_async_iterator(source(), uppercase_mapper)

        chunks = []
        async for chunk in wrapped:
            chunks.append(chunk)

        assert chunks == [b"CHUNK1", b"CHUNK2"]

    @pytest.mark.asyncio
    async def test_wrap_empty_iterator(self) -> None:
        """Test wrapping empty async iterator."""
        async def empty_source():
            # Empty async generator function
            for _ in []:  # This creates an empty generator
                yield b"dummy"

        wrapped = wrap_async_iterator(empty_source())

        chunks = []
        async for chunk in wrapped:
            chunks.append(chunk)

        assert chunks == []

    @pytest.mark.asyncio
    async def test_wrap_single_chunk(self) -> None:
        """Test wrapping async iterator with single chunk."""
        async def single_source():
            yield b"single"

        wrapped = wrap_async_iterator(single_source())

        chunks = []
        async for chunk in wrapped:
            chunks.append(chunk)

        assert chunks == [b"single"]

    @pytest.mark.asyncio
    async def test_mapper_modifies_chunks(self) -> None:
        """Test that mapper function properly modifies each chunk."""
        async def source():
            yield b"hello"
            yield b"world"

        def add_prefix(chunk: bytes) -> bytes:
            return b"prefix_" + chunk

        wrapped = wrap_async_iterator(source(), add_prefix)

        chunks = []
        async for chunk in wrapped:
            chunks.append(chunk)

        assert chunks == [b"prefix_hello", b"prefix_world"]
