"""Tests for think tags fix middleware streaming functionality."""

import pytest
from src.core.interfaces.response_processor_interface import ProcessedResponse
from src.core.services.think_tags_fix_middleware import ThinkTagsFixMiddleware


class TestThinkTagsStreamingSupport:
    """Test cases for streaming support in ThinkTagsFixMiddleware."""

    @pytest.mark.asyncio
    async def test_single_chunk_with_complete_think_tags(self):
        """Test streaming with think tags contained in a single chunk."""
        middleware = ThinkTagsFixMiddleware(enabled=True)

        chunk_content = "<think>Single chunk reasoning</think>Single chunk response"
        response = ProcessedResponse(content=chunk_content)

        result = await middleware.process(response, "session1", {}, is_streaming=True)

        assert result.content == "Single chunk response"
        assert result.metadata["reasoning"] == "Single chunk reasoning"
        assert result.metadata["streaming_extraction"] is True

    @pytest.mark.asyncio
    async def test_think_tags_split_across_chunks(self):
        """Test streaming with think tags split across multiple chunks."""
        middleware = ThinkTagsFixMiddleware(enabled=True)

        # Chunk 1: Opening think tag and partial reasoning
        chunk1 = "<think>This is partial"
        response1 = ProcessedResponse(content=chunk1)
        result1 = await middleware.process(response1, "session1", {}, is_streaming=True)

        # Should return empty content (buffering)
        assert result1.content == ""
        assert result1.metadata is None or "reasoning" not in result1.metadata

        # Chunk 2: Continue reasoning
        chunk2 = " reasoning that spans"
        response2 = ProcessedResponse(content=chunk2)
        result2 = await middleware.process(response2, "session1", {}, is_streaming=True)

        # Should still return empty content (still buffering)
        assert result2.content == ""

        # Chunk 3: Complete reasoning and start response
        chunk3 = " multiple chunks</think>Here is the"
        response3 = ProcessedResponse(content=chunk3)
        result3 = await middleware.process(response3, "session1", {}, is_streaming=True)

        # Should return the response content and reasoning metadata
        assert result3.content == "Here is the"
        assert (
            result3.metadata["reasoning"]
            == "This is partial reasoning that spans multiple chunks"
        )
        assert result3.metadata["streaming_extraction"] is True

        # Chunk 4: Continue response
        chunk4 = " final answer"
        response4 = ProcessedResponse(content=chunk4)
        result4 = await middleware.process(response4, "session1", {}, is_streaming=True)

        # Should pass through normally
        assert result4.content == " final answer"

    @pytest.mark.asyncio
    async def test_no_think_tags_streaming(self):
        """Test streaming without think tags."""
        middleware = ThinkTagsFixMiddleware(enabled=True)

        # Multiple chunks without think tags
        chunks = ["This is ", "a normal ", "streaming ", "response"]

        for _i, chunk in enumerate(chunks):
            response = ProcessedResponse(content=chunk)
            result = await middleware.process(
                response, "session1", {}, is_streaming=True
            )

            # Should pass through unchanged
            assert result.content == chunk
            assert result.metadata is None or "reasoning" not in result.metadata

    @pytest.mark.asyncio
    async def test_reasoning_only_streaming(self):
        """Test streaming with only reasoning content (no actual response)."""
        middleware = ThinkTagsFixMiddleware(enabled=True)

        # Chunk 1: Start thinking
        chunk1 = "<think>This is pure"
        response1 = ProcessedResponse(content=chunk1)
        result1 = await middleware.process(response1, "session1", {}, is_streaming=True)
        assert result1.content == ""

        # Chunk 2: Continue thinking without closing tag
        chunk2 = " reasoning without response"
        response2 = ProcessedResponse(content=chunk2)
        result2 = await middleware.process(response2, "session1", {}, is_streaming=True)
        assert result2.content == ""

        # Simulate end of stream - buffer should be processed
        # In real implementation, this would be handled by stream completion
        reasoning = middleware.get_session_reasoning("session1")
        assert reasoning is None  # No complete tags yet

        # Reset session to trigger buffer processing
        middleware.reset_session("session1")

    @pytest.mark.asyncio
    async def test_buffer_overflow_protection(self):
        """Test that buffer overflow is handled gracefully."""
        # Use small buffer size for testing
        middleware = ThinkTagsFixMiddleware(enabled=True, streaming_buffer_size=50)

        # Create content that exceeds buffer size
        large_chunk = "<think>" + "x" * 100 + "</think>response"
        response = ProcessedResponse(content=large_chunk)

        result = await middleware.process(response, "session1", {}, is_streaming=True)

        # Should process as-is when buffer overflows
        assert "response" in result.content

    @pytest.mark.asyncio
    async def test_multiple_sessions_isolation(self):
        """Test that streaming state is isolated between sessions."""
        middleware = ThinkTagsFixMiddleware(enabled=True)

        # Session 1: Start think tags
        chunk1_s1 = "<think>Session 1 reasoning"
        response1_s1 = ProcessedResponse(content=chunk1_s1)
        result1_s1 = await middleware.process(
            response1_s1, "session1", {}, is_streaming=True
        )
        assert result1_s1.content == ""

        # Session 2: Different content
        chunk1_s2 = "Session 2 normal content"
        response1_s2 = ProcessedResponse(content=chunk1_s2)
        result1_s2 = await middleware.process(
            response1_s2, "session2", {}, is_streaming=True
        )
        assert result1_s2.content == "Session 2 normal content"

        # Session 1: Complete think tags
        chunk2_s1 = "</think>Session 1 response"
        response2_s1 = ProcessedResponse(content=chunk2_s1)
        result2_s1 = await middleware.process(
            response2_s1, "session1", {}, is_streaming=True
        )

        assert result2_s1.content == "Session 1 response"
        assert result2_s1.metadata["reasoning"] == "Session 1 reasoning"

        # Verify session 2 is unaffected
        reasoning_s2 = middleware.get_session_reasoning("session2")
        assert reasoning_s2 is None

    @pytest.mark.asyncio
    async def test_session_state_cleanup(self):
        """Test that session state is properly cleaned up."""
        middleware = ThinkTagsFixMiddleware(enabled=True)

        # Create some streaming state
        chunk = "<think>Some reasoning"
        response = ProcessedResponse(content=chunk)
        await middleware.process(response, "session1", {}, is_streaming=True)

        # Verify state exists
        assert "session1" in middleware._streaming_buffers
        assert "session1" in middleware._stream_states

        # Reset session
        middleware.reset_session("session1")

        # Verify state is cleaned up
        assert "session1" not in middleware._streaming_buffers
        assert "session1" not in middleware._stream_states

    @pytest.mark.asyncio
    async def test_get_session_reasoning(self):
        """Test retrieving extracted reasoning for a session."""
        middleware = ThinkTagsFixMiddleware(enabled=True)

        # Process complete think tags in streaming mode
        chunk = "<think>Extracted reasoning</think>Response content"
        response = ProcessedResponse(content=chunk)
        result = await middleware.process(response, "session1", {}, is_streaming=True)

        # Verify reasoning was extracted
        assert result.metadata["reasoning"] == "Extracted reasoning"

        # Test public method to get reasoning
        reasoning = middleware.get_session_reasoning("session1")
        assert reasoning is not None
        assert reasoning["reasoning"] == "Extracted reasoning"
        assert reasoning["streaming_extraction"] is True

    @pytest.mark.asyncio
    async def test_streaming_without_session_id_uses_fallback(self):
        """Ensure fallback session identifiers prevent cross-stream contamination."""
        middleware = ThinkTagsFixMiddleware(enabled=True)

        first_chunk = ProcessedResponse(content="<think>Reasoning</think>Reply")
        result = await middleware.process(first_chunk, "", {}, is_streaming=True)
        assert result.metadata["reasoning"] == "Reasoning"

        keys = list(middleware._streaming_buffers.keys())
        assert "" not in keys
        assert len(keys) == 1
        fallback_id = keys[0]

        second_chunk = ProcessedResponse(content="<think>Other</think>Second")
        await middleware.process(second_chunk, "", {}, is_streaming=True)
        assert fallback_id in middleware._streaming_buffers
        middleware.reset_session("")
        assert "" not in middleware._streaming_buffers
        assert fallback_id not in middleware._streaming_buffers

    @pytest.mark.asyncio
    async def test_mixed_streaming_and_non_streaming(self):
        """Test that the same middleware handles both streaming and non-streaming."""
        middleware = ThinkTagsFixMiddleware(enabled=True)

        # Non-streaming request
        non_streaming_content = (
            "<think>Non-streaming reasoning</think>Non-streaming response"
        )
        non_streaming_response = ProcessedResponse(content=non_streaming_content)
        non_streaming_result = await middleware.process(
            non_streaming_response, "session1", {}, is_streaming=False
        )

        assert non_streaming_result.content == "Non-streaming response"
        assert non_streaming_result.metadata["reasoning"] == "Non-streaming reasoning"
        assert "streaming_extraction" not in non_streaming_result.metadata

        # Streaming request (different session)
        streaming_chunk = "<think>Streaming reasoning</think>Streaming response"
        streaming_response = ProcessedResponse(content=streaming_chunk)
        streaming_result = await middleware.process(
            streaming_response, "session2", {}, is_streaming=True
        )

        assert streaming_result.content == "Streaming response"
        assert streaming_result.metadata["reasoning"] == "Streaming reasoning"
        assert streaming_result.metadata["streaming_extraction"] is True

    @pytest.mark.asyncio
    async def test_complex_streaming_scenario(self):
        """Test a complex real-world streaming scenario."""
        middleware = ThinkTagsFixMiddleware(enabled=True)

        # Simulate a complex model response split across many chunks
        chunks = [
            "<think>\n",
            "Let me analyze this step by step.\n",
            "First, I need to understand the requirements.\n",
            "Then, I'll design the solution.\n",
            "Finally, I'll implement it.\n",
            "</think>Here's my recommendation:\n",
            "\n",
            "1. Use approach A for better performance\n",
            "2. Implement caching for efficiency\n",
            "3. Add proper error handling",
        ]

        results = []
        for _i, chunk in enumerate(chunks):
            response = ProcessedResponse(content=chunk)
            result = await middleware.process(
                response, "session1", {}, is_streaming=True
            )
            results.append(result)

        # First 5 chunks should return empty (buffering reasoning)
        for i in range(5):
            assert results[i].content == ""

        # 6th chunk should contain the response start and reasoning metadata
        assert "Here's my recommendation:" in results[5].content
        assert (
            results[5]
            .metadata["reasoning"]
            .startswith("Let me analyze this step by step.")
        )

        # Remaining chunks should pass through normally
        for i in range(6, len(results)):
            assert results[i].content == chunks[i]
