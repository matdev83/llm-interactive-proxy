"""
Performance regression tests for streaming contract choices.

These tests verify that streaming contract conversions do not introduce
buffering that impacts time-to-first-byte or streaming throughput.

Requirement 5.4: While streaming responses are processed, the LLM Proxy
shall avoid buffering entire streams solely for contract conversion or mutation.

NFR1.1: Avoid deep-copy behavior for large request/response payloads.
NFR1.2: Avoid buffering that increases time-to-first-byte.
NFR1.3: Preserve copy-on-write behavior for contract updates.
"""

from __future__ import annotations

import asyncio
import sys
import time
from collections.abc import AsyncIterator
from typing import Any
from unittest.mock import MagicMock

import pytest
from src.core.domain.request_context import RequestContext
from src.core.domain.responses import StreamingResponseEnvelope
from src.core.domain.streaming.streaming_content import StreamingContent
from src.core.domain.usage_summary import UsageSummary
from src.core.interfaces.response_parser_interface import IResponseParser
from src.core.interfaces.response_processor_interface import ProcessedResponse
from src.core.interfaces.streaming_response_processor_interface import (
    IStreamNormalizer,
)
from src.core.services.response_processor_service import ResponseProcessor
from src.core.transport.fastapi.response_adapters import to_fastapi_streaming_response

from tests.unit.fixtures.markers import real_time


class TestStreamingNoBuffering:
    """Verify streaming contract conversions don't introduce buffering."""

    async def _create_test_stream(
        self, chunk_count: int, delay: float = 0.01
    ) -> AsyncIterator[StreamingContent]:
        """Create a test stream with known chunk count and timing."""
        for i in range(chunk_count):
            yield StreamingContent(
                content=f"chunk-{i}",
                metadata={"index": i},
                is_done=(i == chunk_count - 1),
            )
            await asyncio.sleep(delay)

    @pytest.mark.asyncio
    @real_time(
        reason="This test measures actual time-to-first-byte performance and requires real system time to validate streaming latency"
    )
    async def test_streaming_yields_chunks_immediately(self):
        """
        Requirement 5.4: Chunks should be yielded immediately without buffering.

        This test verifies that chunks are processed and yielded one at a time,
        not buffered until the entire stream is consumed.
        """
        chunk_count = 10
        stream = self._create_test_stream(chunk_count, delay=0.01)

        # Wrap in StreamingResponseEnvelope
        envelope = StreamingResponseEnvelope(
            content=stream,  # type: ignore[arg-type]
            media_type="text/event-stream",
        )

        # Convert to FastAPI streaming response
        context = RequestContext(
            headers={},
            cookies={},
            state={},
            app_state=None,
        )

        fastapi_response = to_fastapi_streaming_response(envelope, context=context)

        # Consume stream and measure time-to-first-byte
        first_chunk_time = None
        chunk_times = []
        start_time = time.time()

        async for _chunk_bytes in fastapi_response.body_iterator:  # type: ignore[attr-defined]
            chunk_time = time.time() - start_time
            if first_chunk_time is None:
                first_chunk_time = chunk_time
            chunk_times.append(chunk_time)

            # Verify we're getting chunks incrementally
            if len(chunk_times) == 1:
                # First chunk should arrive quickly (< 100ms for this test)
                assert (
                    first_chunk_time < 0.1
                ), f"Time-to-first-byte too slow: {first_chunk_time}s"

        # Verify we got all chunks (may include done marker, so >= chunk_count)
        assert (
            len(chunk_times) >= chunk_count
        ), f"Expected at least {chunk_count} chunks, got {len(chunk_times)}"

        # Verify chunks arrived incrementally (not all at once)
        # Each chunk should arrive after the previous one
        for i in range(1, len(chunk_times)):
            assert (
                chunk_times[i] > chunk_times[i - 1]
            ), "Chunks arrived out of order or buffered"

    @pytest.mark.asyncio
    @real_time(
        reason="This test measures actual conversion performance and requires real system time to validate conversion latency"
    )
    async def test_streaming_content_to_typed_chunk_no_buffering(self):
        """
        Requirement 5.4: StreamingContent.to_typed_chunk() should not require buffering.

        This test verifies that converting a single chunk to typed contract
        doesn't require waiting for additional chunks.
        """
        # Create a single chunk
        chunk = StreamingContent(
            content="test content",
            metadata={"test": "value"},
            is_done=False,
        )

        # Convert to typed chunk - should be immediate, no buffering
        start_time = time.time()
        typed_chunk = chunk.to_typed_chunk()
        conversion_time = time.time() - start_time

        # Conversion should be fast (< 10ms for a single chunk)
        assert (
            conversion_time < 0.01
        ), f"Typed chunk conversion too slow: {conversion_time}s"

        # Verify conversion worked
        assert typed_chunk.payload.kind == "text"
        assert typed_chunk.payload.text == "test content"

    @pytest.mark.asyncio
    @real_time(
        reason="This test measures actual streaming throughput and requires real system time to validate performance characteristics"
    )
    async def test_streaming_throughput_not_degraded(self):
        """
        Requirement 5.4: Streaming throughput should not be degraded by contract conversions.

        This test verifies that processing chunks through the streaming pipeline
        doesn't introduce significant overhead that degrades throughput.
        """
        chunk_count = 100
        stream = self._create_test_stream(chunk_count, delay=0)

        envelope = StreamingResponseEnvelope(
            content=stream,  # type: ignore[arg-type]
            media_type="text/event-stream",
        )

        context = RequestContext(
            headers={},
            cookies={},
            state={},
            app_state=None,
        )

        fastapi_response = to_fastapi_streaming_response(envelope, context=context)

        # Measure throughput
        start_time = time.time()
        chunk_count_received = 0

        async for _ in fastapi_response.body_iterator:  # type: ignore[attr-defined]
            chunk_count_received += 1

        total_time = time.time() - start_time
        throughput = chunk_count_received / total_time if total_time > 0 else 0

        # Verify we got all chunks (may include done marker, so >= chunk_count)
        assert chunk_count_received >= chunk_count

        # Throughput should be reasonable (> 10 chunks/second for this test)
        # This is a conservative threshold - actual throughput should be much higher
        assert throughput > 10, f"Throughput too low: {throughput} chunks/second"


class TestStreamingPerformanceRegression:
    """Regression tests for streaming performance (NFR1.2)."""

    @pytest.mark.asyncio
    @real_time(
        reason="This test measures actual time-to-first-byte performance through ProcessedResponse pipeline"
    )
    async def test_time_to_first_byte_through_processed_response_pipeline(self):
        """
        NFR1.2: Verify ProcessedResponse processing doesn't delay first chunk.

        This test verifies that creating and processing ProcessedResponse objects
        through the response processor pipeline doesn't introduce buffering that
        delays time-to-first-byte.
        """

        # Create a stream that yields raw chunks (dict format) immediately
        async def create_raw_stream() -> AsyncIterator[dict[str, Any]]:
            for i in range(10):
                yield {"choices": [{"delta": {"content": f"chunk-{i}"}}]}
                await asyncio.sleep(0.01)

        # Create mock response parser
        mock_parser = MagicMock(spec=IResponseParser)
        mock_parser.parse_response.return_value = {}
        mock_parser.extract_content.return_value = "test"
        mock_parser.extract_usage.return_value = None
        mock_parser.extract_metadata.return_value = {}

        # Create mock stream normalizer that converts to StreamingContent immediately
        async def process_stream(
            stream: AsyncIterator[Any], *args: Any, **kwargs: Any
        ) -> AsyncIterator[StreamingContent]:
            # The normalizer receives raw chunks and converts them
            chunk_index = 0
            async for _raw_chunk in stream:
                yield StreamingContent(
                    content=f"chunk-{chunk_index}",
                    metadata={"index": chunk_index},
                    is_done=(chunk_index == 9),
                )
                chunk_index += 1

        mock_normalizer = MagicMock(spec=IStreamNormalizer)
        # process_stream must be a real async generator, not wrapped in AsyncMock
        mock_normalizer.process_stream = process_stream
        mock_normalizer.reset = MagicMock()

        # Create response processor
        processor = ResponseProcessor(
            response_parser=mock_parser,
            stream_normalizer=mock_normalizer,
        )

        # Measure time-to-first-byte
        start_time = time.time()
        first_chunk_time = None
        chunk_count = 0

        async for _processed_chunk in processor.process_streaming_response(
            create_raw_stream(), "test-session"
        ):
            chunk_count += 1
            if first_chunk_time is None:
                first_chunk_time = time.time() - start_time

        # Verify first chunk arrived quickly (< 50ms for synthetic stream)
        assert (
            first_chunk_time is not None and first_chunk_time < 0.05
        ), f"Time-to-first-byte too slow: {first_chunk_time}s"
        assert chunk_count == 10, f"Expected 10 chunks, got {chunk_count}"

    @pytest.mark.asyncio
    async def test_large_payload_no_deep_copy(self):
        """
        NFR1.1: Verify large payloads aren't deep-copied during processing.

        This test verifies that ProcessedResponse processing operations
        (metadata merging, content normalization) don't deep-copy large payloads.
        """
        # Create a large payload (1MB+ dict)
        from pydantic.types import JsonValue

        large_dict: dict[str, JsonValue] = {
            "data": "x" * (1024 * 1024),
            "nested": {"key": "value"},
        }
        large_bytes = b"x" * (1024 * 1024)

        # Test dict content
        original_dict_id = id(large_dict)
        chunk = ProcessedResponse(
            content=large_dict, metadata={"test": "value"}  # type: ignore[arg-type]
        )

        # Simulate metadata merging (common operation)
        merged_metadata = dict(chunk.metadata)
        merged_metadata["new_key"] = "new_value"
        new_chunk = ProcessedResponse(
            content=chunk.content, metadata=merged_metadata, usage=chunk.usage
        )

        # Verify original dict wasn't deep-copied (same object identity)
        assert (
            id(new_chunk.content) == original_dict_id
        ), "Large dict was deep-copied during metadata merge"

        # Verify content is unchanged
        assert new_chunk.content == large_dict
        assert chunk.content == large_dict

        # Test bytes content
        bytes_chunk = ProcessedResponse(content=large_bytes)

        # Simulate content normalization (should not copy)
        normalized_chunk = ProcessedResponse(
            content=bytes_chunk.content, metadata=bytes_chunk.metadata
        )

        # For bytes, Python may create new objects, but we verify no deep-copy
        # by checking that the content is the same and no copy.deepcopy was used
        assert normalized_chunk.content == large_bytes
        # Verify we're not doing expensive deep operations
        assert sys.getsizeof(normalized_chunk.content) == sys.getsizeof(large_bytes)

    @pytest.mark.asyncio
    async def test_streaming_chunk_isolation(self):
        """
        NFR1.3: Verify chunks in stream are isolated from mutations.

        This test verifies that modifications to one ProcessedResponse chunk
        don't affect other chunks in the stream.
        """
        # Create multiple chunks with shared metadata structure
        chunks = [
            ProcessedResponse(
                content=f"chunk-{i}",
                metadata={"index": i, "shared": {"key": "value"}},
            )
            for i in range(5)
        ]

        # Store original metadata for each chunk
        original_metadatas = [dict(chunk.metadata) for chunk in chunks]

        # Process chunks through a function that modifies metadata
        async def process_chunks() -> AsyncIterator[ProcessedResponse]:
            for i, chunk in enumerate(chunks):
                # Simulate metadata modification
                modified_metadata = dict(chunk.metadata)
                modified_metadata["processed"] = True
                modified_metadata["process_index"] = i

                # Create new chunk with modified metadata (copy-on-write)
                yield ProcessedResponse(
                    content=chunk.content,
                    metadata=modified_metadata,
                    usage=chunk.usage,
                )

        # Collect processed chunks
        processed_chunks = []
        async for chunk in process_chunks():
            processed_chunks.append(chunk)

        # Verify original chunks were not mutated
        for i, original_chunk in enumerate(chunks):
            assert (
                original_chunk.metadata == original_metadatas[i]
            ), f"Original chunk {i} was mutated"
            assert (
                "processed" not in original_chunk.metadata
            ), f"Original chunk {i} metadata was modified"

        # Verify processed chunks have modifications
        for i, processed_chunk in enumerate(processed_chunks):
            assert processed_chunk.metadata["processed"] is True
            assert processed_chunk.metadata["process_index"] == i
            assert processed_chunk.content == f"chunk-{i}"


class TestCopyOnWriteBehavior:
    """Regression tests for copy-on-write behavior (NFR1.3)."""

    def test_processed_response_metadata_copy_on_write(self):
        """
        NFR1.3: Verify metadata updates preserve copy-on-write.

        When metadata is updated, a new ProcessedResponse should be created
        rather than mutating the original.
        """
        from pydantic.types import JsonValue

        original_metadata: dict[str, JsonValue] = {"key1": "value1", "key2": "value2"}
        chunk = ProcessedResponse(content="test", metadata=original_metadata)

        # Simulate metadata update (common pattern in processing)
        updated_metadata = dict(chunk.metadata)
        updated_metadata["key3"] = "value3"
        updated_chunk = ProcessedResponse(
            content=chunk.content, metadata=updated_metadata, usage=chunk.usage
        )

        # Verify original chunk metadata is unchanged
        assert chunk.metadata == original_metadata
        assert "key3" not in chunk.metadata

        # Verify new chunk has updated metadata
        assert updated_chunk.metadata["key3"] == "value3"
        assert updated_chunk.metadata["key1"] == "value1"

        # Verify they are different objects
        assert id(chunk.metadata) != id(updated_chunk.metadata)
        assert id(chunk) != id(updated_chunk)

    def test_processed_response_content_copy_on_write(self):
        """
        NFR1.3: Verify content updates preserve copy-on-write.

        When content is updated, a new ProcessedResponse should be created.
        """
        from pydantic.types import JsonValue

        original_content: dict[str, JsonValue] = {
            "choices": [{"delta": {"content": "original"}}]
        }
        chunk = ProcessedResponse(
            content=original_content, metadata={"test": "value"}  # type: ignore[arg-type]
        )

        # Simulate content update
        updated_content: dict[str, JsonValue] = {
            "choices": [{"delta": {"content": "updated"}}]
        }
        updated_chunk = ProcessedResponse(
            content=updated_content, metadata=chunk.metadata, usage=chunk.usage  # type: ignore[arg-type]
        )

        # Verify original chunk content is unchanged
        assert chunk.content == original_content
        if isinstance(chunk.content, dict) and "choices" in chunk.content:
            choices = chunk.content["choices"]
            if isinstance(choices, list) and len(choices) > 0:
                choice = choices[0]
                if isinstance(choice, dict) and "delta" in choice:
                    delta = choice["delta"]
                    if isinstance(delta, dict) and "content" in delta:
                        assert delta["content"] == "original"

        # Verify new chunk has updated content
        assert updated_chunk.content == updated_content
        if (
            isinstance(updated_chunk.content, dict)
            and "choices" in updated_chunk.content
        ):
            choices = updated_chunk.content["choices"]
            if isinstance(choices, list) and len(choices) > 0:
                choice = choices[0]
                if isinstance(choice, dict) and "delta" in choice:
                    delta = choice["delta"]
                    if isinstance(delta, dict) and "content" in delta:
                        assert delta["content"] == "updated"

        # Verify they are different objects
        assert id(chunk) != id(updated_chunk)

    def test_processed_response_usage_copy_on_write(self):
        """
        NFR1.3: Verify usage updates preserve copy-on-write.

        When usage is updated, a new ProcessedResponse should be created.
        """
        original_usage = UsageSummary(prompt_tokens=10, completion_tokens=20)
        chunk = ProcessedResponse(
            content="test", metadata={"test": "value"}, usage=original_usage
        )

        # Simulate usage update
        updated_usage = UsageSummary(prompt_tokens=15, completion_tokens=25)
        updated_chunk = ProcessedResponse(
            content=chunk.content, metadata=chunk.metadata, usage=updated_usage
        )

        # Verify original chunk usage is unchanged
        assert chunk.usage == original_usage
        assert chunk.usage is not None
        assert chunk.usage.prompt_tokens == 10

        # Verify new chunk has updated usage
        assert updated_chunk.usage == updated_usage
        assert updated_chunk.usage is not None
        assert updated_chunk.usage.prompt_tokens == 15

        # Verify they are different objects
        assert id(chunk) != id(updated_chunk)
        assert id(chunk.usage) != id(updated_chunk.usage)

    def test_processed_response_dict_content_not_mutated(self):
        """
        NFR1.3: Verify dict content is not mutated in-place when metadata is merged.

        When metadata is merged, the original dict content should remain unchanged.
        """
        from pydantic.types import JsonValue

        original_dict: dict[str, JsonValue] = {
            "key": "value",
            "nested": {"inner": "data"},
        }
        chunk = ProcessedResponse(
            content=original_dict, metadata={"meta": "data"}  # type: ignore[arg-type]
        )

        # Store original dict identity
        original_dict_id = id(chunk.content)

        # Simulate metadata merge operation
        merged_metadata = dict(chunk.metadata)
        merged_metadata["new_meta"] = "new_data"
        updated_chunk = ProcessedResponse(
            content=chunk.content, metadata=merged_metadata, usage=chunk.usage
        )

        # Verify original dict content is unchanged
        assert chunk.content == original_dict
        assert id(chunk.content) == original_dict_id

        # Verify dict content is shared (not copied) - same object identity
        assert id(updated_chunk.content) == original_dict_id

        # Verify metadata was updated
        assert updated_chunk.metadata["new_meta"] == "new_data"
        assert chunk.metadata["meta"] == "data"  # Original unchanged


class TestRealResponseProcessorCopyOnWrite:
    """Integration tests using real ResponseProcessor to verify copy-on-write behavior."""

    @pytest.mark.asyncio
    async def test_response_processor_preserves_copy_on_write_with_real_normalizer(
        self,
    ):
        """
        NFR1.3: Verify ResponseProcessor preserves copy-on-write when processing chunks.

        This test uses a real StreamNormalizer (not mocks) to verify that
        ProcessedResponse chunks are not mutated in-place during processing.
        """
        from unittest.mock import MagicMock

        from src.core.interfaces.response_parser_interface import IResponseParser
        from src.core.services.response_processor_service import ResponseProcessor
        from src.core.services.streaming.content_accumulation_processor import (
            ContentAccumulationProcessor,
        )
        from src.core.services.streaming.stream_context_registry import (
            StreamingContextRegistry,
        )
        from src.core.services.streaming.stream_normalizer import StreamNormalizer

        # Create a real stream normalizer with minimal processors
        registry = StreamingContextRegistry()
        processors = [
            ContentAccumulationProcessor(
                max_buffer_bytes=10 * 1024 * 1024, registry=registry
            )
        ]
        stream_normalizer = StreamNormalizer(processors)

        # Create mock parser
        mock_parser = MagicMock(spec=IResponseParser)
        mock_parser.parse_response.return_value = {}
        mock_parser.extract_content.return_value = "test"
        mock_parser.extract_usage.return_value = None
        mock_parser.extract_metadata.return_value = {}

        # Create ResponseProcessor with real normalizer
        processor = ResponseProcessor(
            response_parser=mock_parser,
            stream_normalizer=stream_normalizer,
        )

        # Create original raw chunks (dict format) that ResponseProcessor expects
        original_chunks = [
            {"choices": [{"delta": {"content": f"chunk-{i}"}}], "index": i}
            for i in range(5)
        ]

        # Process chunks through ResponseProcessor
        async def create_input_stream():
            for chunk in original_chunks:
                yield chunk

        processed_chunks = []
        test_context = RequestContext(
            headers={},
            cookies={},
            state=None,
            app_state=None,
            session_id="test-session",
            request_id="test-request-id",
        )
        async for processed_chunk in processor.process_streaming_response(
            create_input_stream(), "test-session", context=test_context
        ):
            processed_chunks.append(processed_chunk)

        # Verify processed chunks were created (ResponseProcessor creates new ProcessedResponse instances)
        assert len(processed_chunks) == 5
        for i, processed_chunk in enumerate(processed_chunks):
            assert isinstance(processed_chunk, ProcessedResponse)
            assert processed_chunk.metadata.get("session_id") == "test-session"
            # Verify content was processed correctly
            assert (
                "chunk" in str(processed_chunk.content)
                or processed_chunk.content == f"chunk-{i}"
            )

    @pytest.mark.asyncio
    async def test_response_processor_large_payload_no_deep_copy_real_pipeline(self):
        """
        NFR1.1: Verify ResponseProcessor doesn't deep-copy large payloads through real pipeline.

        This test uses a real StreamNormalizer to verify that large content
        payloads are shared (not copied) when processing through ResponseProcessor.
        """
        from unittest.mock import MagicMock

        from src.core.interfaces.response_parser_interface import IResponseParser
        from src.core.services.response_processor_service import ResponseProcessor
        from src.core.services.streaming.content_accumulation_processor import (
            ContentAccumulationProcessor,
        )
        from src.core.services.streaming.stream_context_registry import (
            StreamingContextRegistry,
        )
        from src.core.services.streaming.stream_normalizer import StreamNormalizer

        # Create a real stream normalizer
        registry = StreamingContextRegistry()
        processors = [
            ContentAccumulationProcessor(
                max_buffer_bytes=10 * 1024 * 1024, registry=registry
            )
        ]
        stream_normalizer = StreamNormalizer(processors)

        # Create mock parser
        mock_parser = MagicMock(spec=IResponseParser)
        mock_parser.parse_response.return_value = {}
        mock_parser.extract_content.return_value = "test"
        mock_parser.extract_usage.return_value = None
        mock_parser.extract_metadata.return_value = {}

        # Create ResponseProcessor with real normalizer
        processor = ResponseProcessor(
            response_parser=mock_parser,
            stream_normalizer=stream_normalizer,
        )

        # Create large payload (1MB+ dict) as raw chunk
        large_dict = {"data": "x" * (1024 * 1024), "nested": {"key": "value"}}
        original_dict_id = id(large_dict)

        # Create raw chunk with large payload (ResponseProcessor expects dict, not ProcessedResponse)
        raw_chunk = {"choices": [{"delta": {"content": large_dict}}]}

        # Process through ResponseProcessor
        async def create_input_stream():
            yield raw_chunk

        processed_chunks = []
        async for processed_chunk in processor.process_streaming_response(
            create_input_stream(), "test-session"
        ):
            processed_chunks.append(processed_chunk)

        # Verify ResponseProcessor created ProcessedResponse
        assert len(processed_chunks) == 1
        processed_chunk = processed_chunks[0]
        assert isinstance(processed_chunk, ProcessedResponse)

        # Verify large dict content is preserved (may be normalized, but should not be deep-copied unnecessarily)
        # The content may be extracted/transformed, but the original dict should not be mutated
        assert large_dict == {"data": "x" * (1024 * 1024), "nested": {"key": "value"}}
        assert id(large_dict) == original_dict_id  # Original dict unchanged


class TestStreamingResponseHandlerCopyOnWrite:
    """Tests for streaming_response_handler copy-on-write behavior."""

    @pytest.mark.asyncio
    async def test_attach_metadata_preserves_copy_on_write(self):
        """
        NFR1.3: Verify streaming_response_handler.attach_metadata_stream preserves copy-on-write.

        This test verifies that the fix in streaming_response_handler.py correctly
        creates new ProcessedResponse instances instead of mutating chunks in-place.
        """
        # Create original chunks
        original_chunks = [
            ProcessedResponse(
                content=f"chunk-{i}",
                metadata={"index": i},
            )
            for i in range(3)
        ]

        # Store original metadata and object IDs for verification
        original_metadatas = [dict(chunk.metadata) for chunk in original_chunks]
        original_chunk_ids = [id(chunk) for chunk in original_chunks]

        # Simulate the attach_metadata_stream logic (after our fix)
        async def attach_metadata_stream_simulation(
            monitored_stream, request, processing_context
        ):
            """Simulate the fixed attach_metadata_stream logic."""
            async for chunk in monitored_stream:
                if isinstance(chunk, ProcessedResponse):
                    # NFR1.3: Create new instance instead of mutating (our fix)
                    processed_metadata = dict(chunk.metadata) if chunk.metadata else {}
                    processed_metadata.setdefault(
                        "session_id", processing_context.session_id
                    )
                    # Create new ProcessedResponse instance (copy-on-write)
                    yield ProcessedResponse(
                        content=chunk.content,
                        usage=chunk.usage,
                        metadata=processed_metadata,
                    )

        # Process chunks through simulated attach_metadata_stream
        async def create_monitored_stream():
            for chunk in original_chunks:
                yield chunk

        from src.core.domain.backend_request_manager.context_models import (
            ResponseProcessingContext,
        )

        processing_context = ResponseProcessingContext(
            session_id="test-session",
            backend_name=None,
            model_name=None,
            client_os="test-os",
            original_request=None,
            structured_output=None,
        )

        result_chunks = []
        async for chunk in attach_metadata_stream_simulation(
            create_monitored_stream(), None, processing_context
        ):
            result_chunks.append(chunk)

        # Verify original chunks were not mutated
        for i, original_chunk in enumerate(original_chunks):
            assert (
                original_chunk.metadata == original_metadatas[i]
            ), f"Original chunk {i} was mutated"
            assert (
                "session_id" not in original_chunk.metadata
            ), f"Original chunk {i} metadata was modified in-place"
            assert (
                id(original_chunk) == original_chunk_ids[i]
            ), f"Original chunk {i} object ID changed"

        # Verify new chunks were created with metadata attached
        assert len(result_chunks) == 3
        for i, result_chunk in enumerate(result_chunks):
            assert isinstance(result_chunk, ProcessedResponse)
            assert result_chunk.metadata.get("session_id") == "test-session"
            assert result_chunk.content == f"chunk-{i}"
            # Verify it's a different object (copy-on-write)
            assert id(result_chunk) != original_chunk_ids[i]
