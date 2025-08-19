"""
Tests for the streaming normalizer and related components.
"""


import pytest
from src.core.domain.streaming_response_processor import (
    IStreamProcessor,
    StreamingContent,
    StreamNormalizer,
)


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
        results = []
        async for content in normalizer.normalize_stream(mock_stream()):
            results.append(content)
            
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
        async for chunk in normalizer.process_stream(mock_stream(), output_format="bytes"):
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
        results = []
        async for content in normalizer.normalize_stream(mock_stream()):
            results.append(content)
            
        # Check results
        assert len(results) == 2
        assert results[0].content == "HELLO"
        assert results[1].content == "WORLD"
