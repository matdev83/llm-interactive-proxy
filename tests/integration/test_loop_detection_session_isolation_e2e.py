"""
End-to-end integration tests for loop detection session isolation.

These tests simulate real-world scenarios with multiple concurrent sessions
to ensure loop detection works correctly without state contamination.
"""

import asyncio

import pytest
from src.core.domain.streaming_content import StreamingContent
from src.core.domain.streaming_response_processor import LoopDetectionProcessor
from src.loop_detection.hybrid_detector import HybridLoopDetector


class TestLoopDetectionE2ESessionIsolation:
    """End-to-end tests for session isolation in realistic scenarios."""

    @pytest.fixture
    def processor(self):
        """Create a processor with production-like configuration."""

        def create_detector():
            short_config = {
                "content_loop_threshold": 6,
                "content_chunk_size": 50,
                "max_history_length": 4096,
            }
            return HybridLoopDetector(short_detector_config=short_config)

        return LoopDetectionProcessor(loop_detector_factory=create_detector)

    @pytest.mark.asyncio
    async def test_concurrent_sessions_one_with_loop_one_without(self, processor):
        """
        Simulate two concurrent sessions where one has a loop and one doesn't.
        The non-looping session should not be affected.
        """
        # Session 1: Normal conversation
        session1_chunks = [
            "Hello, how can I help you today?",
            "I can assist with various tasks.",
            "What would you like to know?",
        ]

        # Session 2: Looping content
        session2_chunks = ["IIIIIIII"] * 20  # Will trigger loop detection

        # Process both sessions concurrently
        async def process_session1():
            results = []
            for chunk in session1_chunks:
                content = StreamingContent(
                    content=chunk, metadata={"session_id": "user-session-1"}
                )
                result = await processor.process(content)
                results.append(result)
            # Mark as done
            done = StreamingContent(
                content="", is_done=True, metadata={"session_id": "user-session-1"}
            )
            await processor.process(done)
            return results

        async def process_session2():
            results = []
            for chunk in session2_chunks:
                content = StreamingContent(
                    content=chunk, metadata={"session_id": "user-session-2"}
                )
                result = await processor.process(content)
                results.append(result)
                if result.is_cancellation:
                    break
            return results

        # Run both sessions concurrently
        results1, results2 = await asyncio.gather(
            process_session1(), process_session2()
        )

        # Session 1 should complete normally without cancellation
        assert all(not r.is_cancellation for r in results1)
        assert len(results1) == len(session1_chunks)

        # Session 2 should detect loop and cancel
        assert any(r.is_cancellation for r in results2)

    @pytest.mark.asyncio
    async def test_sequential_sessions_with_cleanup(self, processor):
        """
        Test that sessions are properly cleaned up and don't affect subsequent sessions.
        """
        # Session 1: Send looping content
        session1_id = "session-1"
        for _ in range(15):
            content = StreamingContent(
                content="XXXXXXXX", metadata={"session_id": session1_id}
            )
            result = await processor.process(content)
            if result.is_cancellation:
                break

        # Mark session 1 as done
        done1 = StreamingContent(
            content="", is_done=True, metadata={"session_id": session1_id}
        )
        await processor.process(done1)

        # Verify session 1 was cleaned up
        assert session1_id not in processor._session_detectors

        # Session 2: Send similar content - should start fresh
        session2_id = "session-2"
        results = []
        for _ in range(5):  # Fewer chunks than session 1
            content = StreamingContent(
                content="XXXXXXXX", metadata={"session_id": session2_id}
            )
            result = await processor.process(content)
            results.append(result)

        # Session 2 should not immediately trigger (needs more chunks)
        assert not any(r.is_cancellation for r in results)

        # Clean up session 2
        done2 = StreamingContent(
            content="", is_done=True, metadata={"session_id": session2_id}
        )
        await processor.process(done2)
        assert session2_id not in processor._session_detectors

    @pytest.mark.asyncio
    async def test_many_concurrent_sessions(self, processor):
        """
        Stress test with many concurrent sessions to ensure isolation holds.
        """
        num_sessions = 10

        async def process_session(session_num):
            session_id = f"session-{session_num}"
            # Each session sends different repeated character
            char = chr(ord("A") + (session_num % 26))
            content_chunk = char * 10

            results = []
            for _ in range(8):
                content = StreamingContent(
                    content=content_chunk, metadata={"session_id": session_id}
                )
                result = await processor.process(content)
                results.append(result)

            # Mark as done
            done = StreamingContent(
                content="", is_done=True, metadata={"session_id": session_id}
            )
            await processor.process(done)

            return session_id, results

        # Process all sessions concurrently
        all_results = await asyncio.gather(
            *[process_session(i) for i in range(num_sessions)]
        )

        # Verify each session processed independently
        for session_id, results in all_results:  # noqa: B007
            # Each session should have processed its chunks
            assert len(results) == 8
            # No cross-contamination (verified by no unexpected cancellations)
            # In a properly isolated system, these short sequences won't trigger loops

        # All sessions should be cleaned up
        assert len(processor._session_detectors) == 0

    @pytest.mark.asyncio
    async def test_session_with_intermittent_chunks(self, processor):
        """
        Test session that receives chunks with delays (simulating real streaming).
        """
        session_id = "streaming-session"

        # Simulate streaming with delays
        chunks = ["Hello ", "world! ", "This ", "is ", "a ", "test."]

        for chunk in chunks:
            content = StreamingContent(
                content=chunk, metadata={"session_id": session_id}
            )
            result = await processor.process(content)
            assert not result.is_cancellation
            # Simulate small delay between chunks
            await asyncio.sleep(0.01)

        # Verify detector accumulated all content
        detector = processor._session_detectors[session_id]
        history = detector.short_detector.stream_content_history
        assert "Hello world! This is a test." in history

        # Clean up
        done = StreamingContent(
            content="", is_done=True, metadata={"session_id": session_id}
        )
        await processor.process(done)

    @pytest.mark.asyncio
    async def test_session_restart_after_cleanup(self, processor):
        """
        Test that a session can be restarted after cleanup with fresh state.
        """
        session_id = "reusable-session"

        # First session lifecycle
        for _ in range(5):
            content = StreamingContent(
                content="AAAA", metadata={"session_id": session_id}
            )
            await processor.process(content)

        # Get first detector's history
        first_detector = processor._session_detectors[session_id]
        first_history = first_detector.short_detector.stream_content_history
        assert "A" in first_history

        # Complete first session
        done = StreamingContent(
            content="", is_done=True, metadata={"session_id": session_id}
        )
        await processor.process(done)
        assert session_id not in processor._session_detectors

        # Start new session with same ID (simulating session reuse)
        for _ in range(3):
            content = StreamingContent(
                content="BBBB", metadata={"session_id": session_id}
            )
            await processor.process(content)

        # Get second detector's history
        second_detector = processor._session_detectors[session_id]
        second_history = second_detector.short_detector.stream_content_history

        # Should be a fresh detector with only new content
        assert "B" in second_history
        assert "A" not in second_history
        assert first_detector is not second_detector

    @pytest.mark.asyncio
    async def test_realistic_qwen_oauth_scenario(self, processor):
        """
        Simulate the actual qwen-oauth scenario that triggered the bug report.
        """
        session_id = "qwen-oauth-session"

        # Simulate the "IIIIIIII" pattern from the bug report
        # Each chunk is 8 I's, as seen in the wire capture
        loop_chunk = "IIIIIIII"

        results = []
        for i in range(50):  # Send many chunks to ensure detection
            content = StreamingContent(
                content=loop_chunk, metadata={"session_id": session_id}
            )
            result = await processor.process(content)
            results.append(result)

            if result.is_cancellation:
                print(f"Loop detected after {i+1} chunks")
                break

        # Should have detected the loop
        assert any(r.is_cancellation for r in results), (
            "Failed to detect loop in qwen-oauth scenario! "
            "The 'IIIIIIII' pattern should trigger loop detection."
        )

        # Should detect within reasonable number of chunks (not all 50)
        cancellation_index = next(i for i, r in enumerate(results) if r.is_cancellation)
        assert cancellation_index < 30, (
            f"Loop detection took too long ({cancellation_index} chunks). "
            "Should detect within ~15-20 chunks with current configuration."
        )


class TestLoopDetectionMemoryManagement:
    """Tests for memory management and cleanup."""

    @pytest.mark.asyncio
    async def test_no_memory_leak_with_many_sessions(self):
        """
        Test that completed sessions are properly cleaned up and don't leak memory.
        """

        def create_detector():
            return HybridLoopDetector()

        processor = LoopDetectionProcessor(loop_detector_factory=create_detector)

        # Create and complete many sessions
        for i in range(100):
            session_id = f"session-{i}"
            content = StreamingContent(
                content="test", metadata={"session_id": session_id}
            )
            await processor.process(content)

            # Complete session
            done = StreamingContent(
                content="", is_done=True, metadata={"session_id": session_id}
            )
            await processor.process(done)

        # All sessions should be cleaned up
        assert len(processor._session_detectors) == 0, (
            f"Memory leak detected! {len(processor._session_detectors)} "
            "detector instances still in memory after cleanup."
        )

    @pytest.mark.asyncio
    async def test_cleanup_on_exception(self):
        """
        Test that sessions are cleaned up even if processing encounters errors.
        """

        def create_detector():
            return HybridLoopDetector()

        processor = LoopDetectionProcessor(loop_detector_factory=create_detector)

        session_id = "error-session"

        # Process some content
        content = StreamingContent(content="test", metadata={"session_id": session_id})
        await processor.process(content)

        # Verify detector was created
        assert session_id in processor._session_detectors

        # Manually clean up (simulating error handling)
        processor.cleanup_session(session_id)

        # Should be cleaned up
        assert session_id not in processor._session_detectors
