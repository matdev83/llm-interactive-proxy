import pytest
import logging
from src.core.ports.streaming_contracts import IStreamNormalizer, StreamingContent
from src.core.ports.streaming_orchestrator import StreamingPipeline

class DummyNormalizer(IStreamNormalizer):
    """Minimal normalizer for testing pipeline plumbing."""
    def normalize_stream(self, stream, provider: str):
        async def _gen():
            async for item in stream:
                yield StreamingContent(content=str(item), metadata={"provider": provider})
        return _gen()
    def validate_chunk(self, chunk: StreamingContent) -> bool: return True

class BadStream:
    """Async iterator that raises RuntimeError in aclose()."""
    def __init__(self, error_msg="async generator ignored GeneratorExit"):
        self.error_msg = error_msg
        self.closed = False

    def __aiter__(self):
        async def _gen():
            yield "data"
        return _gen()

    async def aclose(self):
        self.closed = True
        raise RuntimeError(self.error_msg)

@pytest.mark.asyncio
async def test_pipeline_handles_ignored_generator_exit(caplog):
    """Ensure pipeline tolerates 'async generator ignored GeneratorExit' in aclose()."""
    caplog.set_level(logging.DEBUG)
    
    raw_stream = BadStream("async generator ignored GeneratorExit")
    pipeline = StreamingPipeline(normalizer=DummyNormalizer())

    # Drain the pipeline
    chunks = []
    async for chunk_bytes in pipeline.process_stream(
        raw_stream, provider="test", stream_id="test-123", output_format="sse"
    ):
        chunks.append(chunk_bytes)

    assert raw_stream.closed is True
    # Verify we logged the debug message instead of crashing
    assert "Skipping stream aclose; generator already closing or ignored exit" in caplog.text
    
    # Optional: Check records for details if needed
    # match = [r for r in caplog.records if "Skipping stream aclose" in r.message]
    # assert len(match) > 0

@pytest.mark.asyncio
async def test_pipeline_handles_already_running(caplog):
    """Ensure pipeline tolerates 'aclose(): asynchronous generator is already running'."""
    caplog.set_level(logging.DEBUG)
    
    raw_stream = BadStream("aclose(): asynchronous generator is already running")
    pipeline = StreamingPipeline(normalizer=DummyNormalizer())

    chunks = []
    async for chunk_bytes in pipeline.process_stream(
        raw_stream, provider="test", stream_id="test-456", output_format="sse"
    ):
        chunks.append(chunk_bytes)

    assert raw_stream.closed is True
    assert "Skipping stream aclose; generator already closing or ignored exit" in caplog.text
