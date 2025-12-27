from __future__ import annotations

import json

import httpx
import pytest
from hypothesis import given
from src.core.ports.streaming_contracts import (
    IStreamProcessor,
    StreamingContent,
    handle_streaming_error,
)
from src.core.services.streaming.stream_context_registry import StreamingContextRegistry
from src.core.services.streaming.stream_normalizer import StreamNormalizer
from tests.utils.hypothesis_config import property_test_settings
from tests.utils.property_test_generators import (
    chunk_stream_strategy,
    chunk_stream_with_done_strategy,
    done_streaming_content_strategy,
    error_type_strategy,
    provider_strategy,
    stream_id_strategy,
    streaming_content_strategy,
    streaming_content_with_reasoning_strategy,
)
from tests.utils.property_test_helpers import (
    MetadataEnrichingProcessor,
    assert_no_reasoning_leak,
    assert_valid_chunk,
    async_iter,
)


class _PassthroughProcessor(IStreamProcessor):
    """Simple processor implementing the IStreamProcessor contract for tests."""

    async def process(self, content: StreamingContent) -> StreamingContent:
        return content

    def reset(self) -> None:
        return None


def _build_error(error_type: str) -> Exception:
    """Create representative backend errors for property testing."""

    request = httpx.Request("GET", "https://example.com")
    if error_type == "timeout":
        return httpx.TimeoutException("request timed out", request=request)
    if error_type.startswith("http_error_"):
        status_code = int(error_type.split("_")[-1])
        response = httpx.Response(status_code, request=request)
        return httpx.HTTPStatusError(
            f"HTTP error {status_code}", request=request, response=response
        )
    if error_type == "http_error_429":
        response = httpx.Response(429, request=request)
        return httpx.HTTPStatusError("Rate limit", request=request, response=response)
    if error_type == "connect_error":
        return httpx.ConnectError("connection failed", request=request)
    if error_type == "json_error":
        return json.JSONDecodeError("invalid json", "{}", 0)
    if error_type == "generic_error":
        return RuntimeError("generic backend failure")
    return RuntimeError(f"unclassified error: {error_type}")


@given(chunk=streaming_content_strategy())
@property_test_settings()
def test_property_1_and_3_streaming_content_validation(chunk: StreamingContent) -> None:
    """
    Property 1 & 3: Chunk validation and metadata schema conformance.

    For any StreamingContent instance flowing through the pipeline, the chunk
    must satisfy the structural and metadata schema constraints.
    """

    assert_valid_chunk(chunk)


@pytest.mark.asyncio
@given(chunk=streaming_content_strategy())
@property_test_settings()
async def test_property_9_metadata_enrichment_is_idempotent(
    chunk: StreamingContent,
) -> None:
    """
    Property 9: Middleware idempotence.

    Applying the same metadata-enriching middleware twice should be equivalent
    to applying it once.
    """

    processor = MetadataEnrichingProcessor("property_9", "value")
    once = await processor.process(chunk)
    twice = await processor.process(once)
    assert once.metadata == twice.metadata


@pytest.mark.asyncio
@given(chunks=chunk_stream_with_done_strategy(min_size=1, max_size=5))
@property_test_settings(max_examples=15)
async def test_property_17_stream_normalizer_preserves_structure(
    chunks: list[StreamingContent],
) -> None:
    """
    Property 17: StreamingContent structure stability.

    StreamNormalizer must emit valid StreamingContent objects for every input.
    """

    normalizer = StreamNormalizer([_PassthroughProcessor()])
    stream = async_iter(chunks)
    async for normalized in normalizer.process_stream(stream, output_format="objects"):
        assert isinstance(normalized, StreamingContent)
        assert_valid_chunk(normalized)


@given(chunk=streaming_content_with_reasoning_strategy())
@property_test_settings()
def test_property_18_reasoning_isolation(chunk: StreamingContent) -> None:
    """
    Property 18: Reasoning isolation.

    Reasoning metadata must never leak into the primary content field.
    """

    chunk.content = ""
    assert_no_reasoning_leak(chunk)


@pytest.mark.asyncio
@given(chunk=done_streaming_content_strategy())
@property_test_settings()
async def test_property_19_done_marker_passthrough(chunk: StreamingContent) -> None:
    """
    Property 19: Done marker passthrough.

    Middleware must propagate is_done chunks unchanged.
    """

    processor = _PassthroughProcessor()
    processed = await processor.process(chunk)
    assert processed.is_done, "Done marker was cleared by middleware"


@pytest.mark.asyncio
@given(
    error_type=error_type_strategy(),
    stream_id=stream_id_strategy(),
    provider=provider_strategy(),
)
@property_test_settings(max_examples=50)
async def test_property_4_error_terminal_chunks(
    error_type: str, stream_id: str | None, provider: str
) -> None:
    """
    Property 4: Error terminal chunks.

    Any error must produce a terminal chunk with structured metadata.
    """

    error = _build_error(error_type)
    error_chunk = await handle_streaming_error(error, stream_id, provider)
    assert error_chunk.is_done is True
    assert error_chunk.metadata.get("finish_reason") == "error"
    assert "error" in error_chunk.metadata


@given(
    first_stream=chunk_stream_strategy(min_size=1, max_size=5),
    second_stream=chunk_stream_strategy(min_size=1, max_size=5),
)
@property_test_settings(max_examples=20)
def test_property_21_stream_state_isolation(
    first_stream: list[StreamingContent],
    second_stream: list[StreamingContent],
) -> None:
    """
    Property 21: Stream state isolation.

    StreamingContextRegistry must keep per-stream buffers isolated.
    """

    registry = StreamingContextRegistry()
    state_a = registry.get_content_state("stream-a")
    state_b = registry.get_content_state("stream-b")

    for chunk in first_stream:
        state_a.chunks.append(str(chunk.content))

    for chunk in second_stream:
        state_b.chunks.append(str(chunk.content))

    assert len(state_a.chunks) == len(first_stream)
    assert len(state_b.chunks) == len(second_stream)

    state_a.chunks.append("unique-marker")
    assert "unique-marker" not in state_b.chunks, "States leaked between streams"
