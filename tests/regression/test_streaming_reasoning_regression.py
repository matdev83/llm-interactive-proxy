
"""Regression tests for streaming reasoning content handling."""

import json

import pytest
from src.core.domain.chat import (
    CanonicalStreamChunk,
    StreamingChatCompletionChoice,
    StreamingChatCompletionChoiceDelta,
)
from src.core.domain.streaming.streaming_content import StreamingContent
from src.core.domain.translators.anthropic.streaming import (
    from_domain_to_anthropic_stream_chunk,
)
from src.core.domain.translators.openai.streaming import (
    from_domain_to_openai_stream_chunk,
)
from src.core.services.streaming.content_accumulation_processor import (
    ContentAccumulationProcessor,
)
from src.core.services.streaming.stream_context_registry import StreamingContextRegistry
from src.core.transport.streaming.sse_serializer import SSESerializer


class TestStreamingReasoningRegression:
    """Regression tests for reasoning content in streaming pipeline."""

    def test_sse_serializer_preserves_reasoning_in_openai_dict(self) -> None:
        """
        Regression test: Ensure SSESerializer injects reasoning_content from metadata
        into the delta when serializing OpenAI-formatted dict chunks.
        
        Bug fixed: SSESerializer was ignoring metadata.reasoning_content for 
        'opaque_json_dict' payloads that looked like OpenAI chunks.
        """
        serializer = SSESerializer()
        
        # Create an OpenAI-style dict chunk (as produced by Gemini translator)
        openai_dict = {
            "id": "test-id",
            "choices": [{"index": 0, "delta": {"content": "Hello"}}],
        }
        
        content = StreamingContent(
            content=openai_dict,
            metadata={
                "reasoning_content": "I am thinking...",
                "model": "gemini-2.0",
                "id": "test-id"
            }
        )
        
        # Serialize to SSE bytes
        sse_bytes = serializer.serialize(content)
        sse_str = sse_bytes.decode("utf-8")
        
        # Verify reasoning is present in the output JSON
        # Format is data: {...}\n\n
        lines = sse_str.strip().split("\n")
        data_line = next(line for line in lines if line.startswith("data: "))
        json_str = data_line[6:]
        data = json.loads(json_str)
        
        delta = data["choices"][0]["delta"]
        
        assert "reasoning_content" in delta
        assert delta["reasoning_content"] == "I am thinking..."
        # Verify alias is also present for compatibility
        assert "reasoning" in delta
        assert delta["reasoning"] == "I am thinking..."

    @pytest.mark.asyncio
    async def test_content_accumulation_extracts_reasoning(self) -> None:
        """
        Regression test: Ensure ContentAccumulationProcessor extracts and accumulates
        reasoning content from OpenAI-style chunks.
        
        Bug fixed: Processor was only looking for 'content' in delta, ignoring 'reasoning_content'.
        """
        registry = StreamingContextRegistry()
        processor = ContentAccumulationProcessor(registry=registry)
        
        # Chunk 1: Content only
        chunk1 = StreamingContent(
            content={
                "choices": [{"index": 0, "delta": {"content": "Hello"}}]
            },
            metadata={"stream_id": "stream-1"}
        )
        
        # Chunk 2: Reasoning only
        chunk2 = StreamingContent(
            content={
                "choices": [{"index": 0, "delta": {"reasoning_content": "Thinking..."}}]
            },
            metadata={"stream_id": "stream-1"}
        )
        
        # Chunk 3: Done/Stop
        chunk3 = StreamingContent(
            content="",
            is_done=True,
            metadata={"stream_id": "stream-1", "finish_reason": "stop"}
        )
        
        # Process chunks
        await processor.process(chunk1)
        await processor.process(chunk2)
        final_result = await processor.process(chunk3)
        
        # Verify accumulated metadata in final result
        assert final_result.metadata.get("accumulated_content") == "Hello"
        assert final_result.metadata.get("accumulated_reasoning") == "Thinking..."

    def test_openai_translator_includes_reasoning_alias(self) -> None:
        """
        Regression test: Ensure OpenAI translator includes 'reasoning' alias
        alongside 'reasoning_content'.
        """
        delta = StreamingChatCompletionChoiceDelta(
            role="assistant",
            content="Answer",
            reasoning_content="Thought"
        )
        choice = StreamingChatCompletionChoice(index=0, delta=delta)
        chunk = CanonicalStreamChunk(
            id="test-id",
            choices=[choice],
            model="gpt-4o"
        )
        
        openai_chunk = from_domain_to_openai_stream_chunk(chunk)
        output_delta = openai_chunk["choices"][0]["delta"]
        
        assert output_delta["reasoning_content"] == "Thought"
        assert output_delta["reasoning"] == "Thought"

    def test_anthropic_translator_handles_reasoning(self) -> None:
        """
        Regression test: Ensure Anthropic translator handles reasoning content correctly.
        """
        # Case 1: Reasoning in delta
        delta = StreamingChatCompletionChoiceDelta(
            role="assistant",
            reasoning_content="Thinking process"
        )
        choice = StreamingChatCompletionChoice(index=0, delta=delta)
        chunk = CanonicalStreamChunk(
            id="test-id",
            choices=[choice],
            model="claude-3-5-sonnet"
        )
        
        anthropic_chunk = from_domain_to_anthropic_stream_chunk(chunk)
        
        # Should produce a thinking_delta block
        assert anthropic_chunk["type"] == "content_block_delta"
        assert anthropic_chunk["delta"]["type"] == "thinking_delta"
        assert anthropic_chunk["delta"]["thinking"] == "Thinking process"
