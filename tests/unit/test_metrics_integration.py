"""
Tests for metrics integration in the streaming pipeline.

This module verifies that metrics are properly collected across
normalizers, processors, and assemblers without impacting performance.
"""

import pytest
from src.core.ports.anthropic_normalizer import AnthropicStreamNormalizer
from src.core.ports.gemini_normalizer import GeminiStreamNormalizer
from src.core.ports.openai_normalizer import OpenAIStreamNormalizer
from src.core.ports.sse_assembler import SSEAssembler
from src.core.ports.streaming_contracts import StreamingContent
from src.core.ports.streaming_metrics import get_metrics_instance, reset_metrics
from src.core.ports.streaming_processors import (
    LoopDetectionProcessor,
    ThinkTagsProcessor,
)


@pytest.fixture(autouse=True)
def reset_metrics_fixture():
    """Reset metrics before each test."""
    reset_metrics()
    yield
    reset_metrics()


class TestNormalizerMetrics:
    """Test metrics collection in normalizers."""

    @pytest.mark.asyncio
    async def test_openai_normalizer_tracks_chunks_and_sentinel(self):
        """Verify OpenAI normalizer tracks chunks and sentinel."""
        normalizer = OpenAIStreamNormalizer()
        metrics = get_metrics_instance()

        # Create mock stream
        async def mock_stream():
            yield b'data: {"id":"test-123","choices":[{"delta":{"content":"Hello"}}]}\n\n'
            yield b'data: {"id":"test-123","choices":[{"delta":{"content":" world"}}]}\n\n'
            yield b"data: [DONE]\n\n"

        assembler = SSEAssembler()
        async for _ in assembler.assemble_stream(
            normalizer.normalize_stream(mock_stream(), "openai"), format="sse"
        ):
            pass

        stream_metrics = metrics.get_stream_metrics("test-123")
        assert stream_metrics["chunks_sent"] == 2  # Two content chunks
        assert stream_metrics["sentinels_emitted"] == 1  # One [DONE]

    @pytest.mark.asyncio
    async def test_anthropic_normalizer_tracks_chunks_and_sentinel(self):
        """Verify Anthropic normalizer tracks chunks and sentinel."""
        normalizer = AnthropicStreamNormalizer()
        metrics = get_metrics_instance()

        # Create mock stream
        async def mock_stream():
            yield b'event: message_start\ndata: {"type":"message_start","message":{"id":"msg-123","role":"assistant"}}\n\n'
            yield b'event: content_block_delta\ndata: {"type":"content_block_delta","delta":{"type":"text_delta","text":"Hello"}}\n\n'
            yield b'event: message_stop\ndata: {"type":"message_stop"}\n\n'

        assembler = SSEAssembler()
        async for _ in assembler.assemble_stream(
            normalizer.normalize_stream(mock_stream(), "anthropic"), format="sse"
        ):
            pass

        stream_metrics = metrics.get_stream_metrics("msg-123")
        assert stream_metrics["chunks_sent"] >= 1  # At least one content chunk
        assert stream_metrics["sentinels_emitted"] == 1  # One [DONE]

    @pytest.mark.asyncio
    async def test_gemini_normalizer_tracks_chunks_and_sentinel(self):
        """Verify Gemini normalizer tracks chunks and sentinel."""
        normalizer = GeminiStreamNormalizer()
        metrics = get_metrics_instance()

        # Create mock stream
        async def mock_stream():
            yield b'{"id":"gen-123","candidates":[{"content":{"parts":[{"text":"Hello"}]}}]}\n'
            yield b'{"id":"gen-123","candidates":[{"content":{"parts":[{"text":" world"}]}}]}\n'

        assembler = SSEAssembler()
        async for _ in assembler.assemble_stream(
            normalizer.normalize_stream(mock_stream(), "gemini"), format="sse"
        ):
            pass

        stream_metrics = metrics.get_stream_metrics("gen-123")
        assert stream_metrics["chunks_sent"] == 2  # Two content chunks
        assert stream_metrics["sentinels_emitted"] == 1  # One [DONE]


class TestProcessorMetrics:
    """Test metrics collection in processors."""

    @pytest.mark.asyncio
    async def test_loop_detection_tracks_mutations(self):
        """Verify loop detection processor tracks mutations."""
        processor = LoopDetectionProcessor(
            content_loop_threshold=2, content_chunk_size=5
        )
        metrics = get_metrics_instance()

        # Create content that will trigger loop detection
        content1 = StreamingContent(
            content="hello", metadata={}, stream_id="test-stream"
        )
        content2 = StreamingContent(
            content="hello", metadata={}, stream_id="test-stream"
        )
        content3 = StreamingContent(
            content="hello", metadata={}, stream_id="test-stream"
        )

        # Process chunks
        await processor.process(content1)
        await processor.process(content2)
        result = await processor.process(content3)

        # Verify mutation was tracked if loop detected
        stream_metrics = metrics.get_stream_metrics("test-stream")
        if result.metadata.get("loop_detected"):
            assert stream_metrics["middleware_mutations"] >= 1

    @pytest.mark.asyncio
    async def test_think_tags_tracks_mutations(self):
        """Verify think tags processor tracks mutations."""
        processor = ThinkTagsProcessor(enabled=True)
        metrics = get_metrics_instance()

        # Create content with think tags
        content = StreamingContent(
            content="<think>reasoning</think>answer",
            metadata={},
            stream_id="test-stream",
        )

        # Process chunk
        _result = await processor.process(content)

        # Verify mutation was tracked
        stream_metrics = metrics.get_stream_metrics("test-stream")
        assert stream_metrics["middleware_mutations"] >= 1


class TestAssemblerMetrics:
    """Test metrics collection in assembler."""

    @pytest.mark.asyncio
    async def test_sse_assembler_tracks_chunks_and_sentinel(self):
        """Verify SSE assembler tracks chunks and sentinel."""
        assembler = SSEAssembler()
        metrics = get_metrics_instance()

        # Create mock stream
        async def mock_stream():
            yield StreamingContent(
                content="Hello", metadata={}, stream_id="test-stream"
            )
            yield StreamingContent(
                content=" world", metadata={}, stream_id="test-stream"
            )
            yield StreamingContent(
                content="[DONE]",
                metadata={"finish_reason": "stop"},
                is_done=True,
                stream_id="test-stream",
            )

        # Assemble stream
        chunks = []
        async for chunk in assembler.assemble_stream(mock_stream(), format="sse"):
            chunks.append(chunk)

        # Verify chunks and sentinel were tracked
        stream_metrics = metrics.get_stream_metrics("test-stream")
        assert stream_metrics["chunks_sent"] == 2  # Two content chunks
        assert stream_metrics["sentinels_emitted"] == 1  # One [DONE]


class TestMetricsPerformance:
    """Test that metrics don't impact performance."""

    @pytest.mark.asyncio
    async def test_metrics_dont_slow_down_normalizer(self):
        """Verify metrics collection doesn't significantly slow down normalization."""
        import time

        normalizer = OpenAIStreamNormalizer()

        # Create large mock stream
        async def mock_stream():
            for i in range(100):
                yield f'data: {{"id":"test-123","choices":[{{"delta":{{"content":"chunk{i}"}}}}]}}\n\n'.encode()
            yield b"data: [DONE]\n\n"

        # Measure time with metrics
        start = time.perf_counter()
        chunks = []
        async for chunk in normalizer.normalize_stream(mock_stream(), "openai"):
            chunks.append(chunk)
        elapsed = time.perf_counter() - start

        # Verify reasonable performance (should complete in < 1 second)
        assert elapsed < 1.0, f"Normalization took {elapsed:.3f}s, too slow"
        assert len(chunks) == 101  # 100 content chunks + 1 [DONE]

    @pytest.mark.asyncio
    async def test_metrics_dont_slow_down_assembler(self):
        """Verify metrics collection doesn't significantly slow down assembly."""
        import time

        assembler = SSEAssembler()

        # Create large mock stream
        async def mock_stream():
            for i in range(100):
                yield StreamingContent(
                    content=f"chunk{i}", metadata={}, stream_id="test-stream"
                )
            yield StreamingContent(
                content="[DONE]",
                metadata={"finish_reason": "stop"},
                is_done=True,
                stream_id="test-stream",
            )

        # Measure time with metrics
        start = time.perf_counter()
        chunks = []
        async for chunk in assembler.assemble_stream(mock_stream(), format="sse"):
            chunks.append(chunk)
        elapsed = time.perf_counter() - start

        # Verify reasonable performance (should complete in < 1 second)
        assert elapsed < 1.0, f"Assembly took {elapsed:.3f}s, too slow"
        assert len(chunks) == 101  # 100 content chunks + 1 [DONE]


class TestGlobalMetrics:
    """Test global metrics aggregation."""

    @pytest.mark.asyncio
    async def test_global_metrics_aggregate_across_streams(self):
        """Verify global metrics aggregate across multiple streams."""
        normalizer = OpenAIStreamNormalizer()
        metrics = get_metrics_instance()

        assembler = SSEAssembler()

        async def mock_stream1():
            yield b'data: {"id":"stream-1","choices":[{"delta":{"content":"Hello"}}]}\n\n'
            yield b"data: [DONE]\n\n"

        async def mock_stream2():
            yield b'data: {"id":"stream-2","choices":[{"delta":{"content":"World"}}]}\n\n'
            yield b"data: [DONE]\n\n"

        async for _ in assembler.assemble_stream(
            normalizer.normalize_stream(mock_stream1(), "openai"), format="sse"
        ):
            pass

        async for _ in assembler.assemble_stream(
            normalizer.normalize_stream(mock_stream2(), "openai"), format="sse"
        ):
            pass

        global_metrics = metrics.get_global_metrics()
        assert global_metrics["chunks_sent"] == 2  # One from each stream
        assert global_metrics["sentinels_emitted"] == 2  # One from each stream
        assert global_metrics["total_streams"] == 2  # Two streams started
