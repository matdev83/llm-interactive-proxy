"""
Tests for the streaming normalizer and related components.
"""

import pytest
from src.core.domain.chat import (
    CanonicalStreamChunk,
    StreamingChatCompletionChoice,
    StreamingChatCompletionChoiceDelta,
    StreamingFunctionCall,
    StreamingToolCall,
)
from src.core.domain.streaming_response_processor import (
    IStreamProcessor,
    StreamingContent,
)
from src.core.interfaces.response_processor_interface import ProcessedResponse
from src.core.services.streaming.stream_normalizer import StreamNormalizer


class TestStreamingContent:
    """Tests for the StreamingContent class."""

    def test_from_raw_bytes(self) -> None:
        """Test creating StreamingContent from raw bytes."""
        # SSE format with data prefix
        raw = b'data: {"choices":[{"delta":{"content":"Hello"}}]}\n\n'
        content = StreamingContent.from_raw(raw)
        assert content.content == "Hello"
        assert not content.is_done

        # Done marker
        raw = b"data: [DONE]\n\n"
        content = StreamingContent.from_raw(raw)
        assert content.is_done
        assert content.content == ""

    def test_from_raw_dict(self) -> None:
        """Test creating StreamingContent from a dictionary."""
        # OpenAI format
        raw = {
            "id": "test-id",
            "model": "test-model",
            "choices": [{"delta": {"content": "Hello"}}],
        }
        content = StreamingContent.from_raw(raw)
        assert content.content == "Hello"
        assert content.metadata["id"] == "test-id"
        assert content.metadata["model"] == "test-model"

    def test_from_raw_processed_response_dict(self) -> None:
        """ProcessedResponse chunks with dict content should round-trip like raw dicts."""
        chunk = {
            "id": "chunk-1",
            "model": "test-model",
            "choices": [
                {
                    "delta": {
                        "role": "assistant",
                        "content": "Hello!",
                        "tool_calls": None,
                        "reasoning": None,
                    },
                    "finish_reason": None,
                }
            ],
        }

        processed = ProcessedResponse(
            content=chunk,
            metadata={"session_id": "abc123"},
            usage={"prompt_tokens": 12},
        )

        content = StreamingContent.from_raw(processed)

        assert content.content == "Hello!"
        # Metadata extracted from the chunk should still be preserved
        assert content.metadata["id"] == "chunk-1"
        assert content.metadata["model"] == "test-model"
        # Existing metadata from the processed response should merge in
        assert content.metadata["session_id"] == "abc123"
        # Usage is forwarded when provided
        assert content.usage == {"prompt_tokens": 12}

    def test_from_raw_processed_response_canonical_stream_chunk_preserves_tool_calls(
        self,
    ) -> None:
        """TranslationService yields CanonicalStreamChunk; parser must not stringify it."""
        canonical = CanonicalStreamChunk(
            id="chatcmpl-tool",
            model="gpt-test",
            created=1700000000,
            choices=[
                StreamingChatCompletionChoice(
                    index=0,
                    delta=StreamingChatCompletionChoiceDelta(
                        tool_calls=[
                            StreamingToolCall(
                                index=0,
                                id="fc_1",
                                function=StreamingFunctionCall(
                                    name="shell",
                                    arguments='{"command":["bash","-lc","git log -1"]}',
                                ),
                            )
                        ]
                    ),
                    finish_reason="tool_calls",
                )
            ],
        )
        processed = ProcessedResponse(content=canonical, metadata={"session_id": "s1"})
        content = StreamingContent.from_raw(processed)
        tcs = content.metadata.get("tool_calls")
        assert isinstance(tcs, list) and len(tcs) == 1
        fn = tcs[0].get("function") if isinstance(tcs[0], dict) else None
        assert isinstance(fn, dict)
        assert fn.get("name") == "shell"
        assert "git log" in str(fn.get("arguments", ""))
        assert content.metadata.get("session_id") == "s1"

    def test_from_raw_str(self) -> None:
        """Test creating StreamingContent from a string."""
        # Plain text
        raw = "Hello world"
        content = StreamingContent.from_raw(raw)
        assert content.content == "Hello world"

        # JSON string
        raw = '{"choices":[{"delta":{"content":"Hello"}}]}'
        content = StreamingContent.from_raw(raw)
        assert content.content == "Hello"

    def test_to_bytes(self) -> None:
        """Test converting StreamingContent to bytes."""
        content = StreamingContent(content="Hello", metadata={"id": "test-id"})
        bytes_data = content.to_bytes()
        assert b"Hello" in bytes_data
        assert b"test-id" in bytes_data

        # Done marker
        done = StreamingContent(is_done=True)
        assert done.to_bytes() == b"data: [DONE]\n\n"

    def test_to_bytes_cancellation_message(self) -> None:
        """Cancellation chunks should include the message before the done marker."""
        content = StreamingContent(
            content="Loop detected", is_done=True, is_cancellation=True
        )
        bytes_data = content.to_bytes()
        assert b"Loop detected" in bytes_data
        assert bytes_data.endswith(b"data: [DONE]\n\n")


class MockStreamProcessor(IStreamProcessor):
    """Mock stream processor for testing."""

    def __init__(self, transform_func=None):
        """Initialize with optional transform function."""
        self.processed = []
        self.transform_func = transform_func or (lambda x: x)

    async def process(self, content: StreamingContent) -> StreamingContent:
        """Process a streaming content chunk."""
        self.processed.append(content)
        if self.transform_func:
            content.content = self.transform_func(content.content)
        return content


class TestStreamNormalizer:
    """Tests for the StreamNormalizer class."""

    @pytest.mark.asyncio
    async def test_reset_called_before_stream(self) -> None:
        """Test that reset() is NOT called on processors before processing a stream.

        Note: StreamNormalizer is registered as a Singleton, so calling reset() here
        would wipe state for ALL concurrent streams in shared processors (like
        ToolCallRepairProcessor -> StreamingContextRegistry). Processors must be
        session-aware and manage state per-stream instead of relying on reset.
        """

        # Create a processor that tracks reset calls
        class ResetTrackingProcessor(IStreamProcessor):
            def __init__(self):
                self.reset_count = 0
                self.process_count = 0

            def reset(self):
                self.reset_count += 1

            async def process(self, content: StreamingContent) -> StreamingContent:
                self.process_count += 1
                return content

        # Create processors
        processor1 = ResetTrackingProcessor()
        processor2 = ResetTrackingProcessor()
        normalizer = StreamNormalizer([processor1, processor2])

        # Create a simple stream
        async def mock_stream():
            yield "Hello"
            yield "world"

        # Process the stream
        chunks = []
        async for chunk in normalizer.process_stream(
            mock_stream(), output_format="objects"
        ):
            chunks.append(chunk)

        # Verify reset was NOT called (intentional - singleton issue)
        assert (
            processor1.reset_count == 0
        ), "Processor 1 reset should NOT be called (singleton)"
        assert (
            processor2.reset_count == 0
        ), "Processor 2 reset should NOT be called (singleton)"
        assert processor1.process_count == 2, "Processor 1 should process 2 chunks"
        assert processor2.process_count == 2, "Processor 2 should process 2 chunks"

    @pytest.mark.asyncio
    async def test_normalize_stream(self) -> None:
        """Test normalizing a stream of different formats."""

        # Create a mixed format stream
        async def mock_stream():
            yield b'data: {"choices":[{"delta":{"content":"Hello"}}]}\n\n'
            yield {"choices": [{"delta": {"content": " world"}}]}
            yield "!"
            yield b"data: [DONE]\n\n"

        # Create a processor that tracks calls
        processor = MockStreamProcessor()
        normalizer = StreamNormalizer([processor])

        # Normalize the stream
        results: list[StreamingContent] = []
        async for chunk in normalizer.process_stream(
            mock_stream(), output_format="objects"
        ):
            assert isinstance(chunk, StreamingContent)
            results.append(chunk)

        # Check results
        assert len(results) == 4  # Hello, world, !, [DONE]
        assert results[0].content == "Hello"
        assert results[1].content == " world"
        assert results[2].content == "!"
        assert results[3].is_done

        # Check processor was called
        assert len(processor.processed) == 4

    @pytest.mark.asyncio
    async def test_process_stream_bytes_output(self) -> None:
        """Test processing a stream with bytes output."""

        # Create a simple stream
        async def mock_stream():
            yield "Hello"
            yield "world"

        normalizer = StreamNormalizer()

        # Process the stream to bytes
        chunks = []
        async for chunk in normalizer.process_stream(
            mock_stream(), output_format="bytes"
        ):
            chunks.append(chunk)

        # Check results
        assert all(isinstance(c, bytes) for c in chunks)
        assert len(chunks) == 2

    @pytest.mark.asyncio
    async def test_processor_transforms_content(self) -> None:
        """Test that processors can transform content."""
        # Create a processor that uppercases content
        processor = MockStreamProcessor(lambda s: s.upper())
        normalizer = StreamNormalizer([processor])

        # Create a simple stream
        async def mock_stream():
            yield "hello"
            yield "world"

        # Process the stream
        results: list[StreamingContent] = []
        async for chunk in normalizer.process_stream(
            mock_stream(), output_format="objects"
        ):
            assert isinstance(chunk, StreamingContent)
            results.append(chunk)

        # Check results
        assert len(results) == 2
        assert results[0].content == "HELLO"
        assert results[1].content == "WORLD"
