import pytest
from src.core.ports.streaming_contracts import IStreamNormalizer, StreamingContent
from src.core.ports.streaming_orchestrator import StreamingPipeline


class DummyNormalizer(IStreamNormalizer):
    """Minimal normalizer for testing pipeline plumbing."""

    def normalize_stream(self, stream, provider: str):
        async def _gen():
            async for item in stream:
                yield StreamingContent(
                    content=str(item), metadata={"provider": provider}
                )

        return _gen()

    def validate_chunk(self, chunk: StreamingContent) -> bool:
        return True


class ClosableStream:
    """Async iterator that records when aclose() is invoked."""

    def __init__(self) -> None:
        self.closed = False

    def __aiter__(self):
        async def _gen():
            yield "foo"

        return _gen()

    async def aclose(self) -> None:
        self.closed = True


@pytest.mark.asyncio
async def test_pipeline_closes_raw_stream() -> None:
    """Ensure upstream raw stream aclose() is called when pipeline finishes."""

    raw_stream = ClosableStream()
    pipeline = StreamingPipeline(normalizer=DummyNormalizer())

    # Drain the pipeline
    chunks = []
    async for chunk_bytes in pipeline.process_stream(
        raw_stream, provider="openai", output_format="sse"
    ):
        chunks.append(chunk_bytes)

    assert raw_stream.closed is True
    # Sanity: we streamed out the single chunk ("foo")
    combined = b"".join(chunks).decode("utf-8")
    assert "foo" in combined
