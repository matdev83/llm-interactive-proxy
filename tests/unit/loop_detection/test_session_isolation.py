"""
Test cases for loop detection session isolation.

These tests ensure that loop detector state is never shared between different sessions,
preventing state contamination and ensuring each session has independent loop detection.
"""

import pytest
from src.core.domain.streaming_response_processor import LoopDetectionProcessor
from src.core.ports.streaming_contracts import StreamingContent
from src.loop_detection.hybrid_detector import HybridLoopDetector


class TestLoopDetectionSessionIsolation:
    """Test suite for verifying session isolation in loop detection."""

    @pytest.fixture
    def detector_factory(self):
        """Factory function to create new detector instances."""

        def create_detector():
            short_config = {
                "content_loop_threshold": 6,
                "content_chunk_size": 50,
                "max_history_length": 4096,
            }
            return HybridLoopDetector(short_detector_config=short_config)

        return create_detector

    @pytest.fixture
    def processor(self, detector_factory):
        """Create a LoopDetectionProcessor with factory."""
        return LoopDetectionProcessor(loop_detector_factory=detector_factory)

    @pytest.mark.asyncio
    async def test_different_sessions_have_independent_detectors(
        self, processor, detector_factory
    ):
        """Test that different sessions get different detector instances."""
        # Create content for two different sessions
        content_session_a = StreamingContent(
            content="test", metadata={"session_id": "session-a"}
        )
        content_session_b = StreamingContent(
            content="test", metadata={"session_id": "session-b"}
        )

        # Process content for both sessions
        await processor.process(content_session_a)
        await processor.process(content_session_b)

        # Verify that two different detector instances were created
        assert "session-a" in processor._session_detectors
        assert "session-b" in processor._session_detectors
        assert (
            processor._session_detectors["session-a"]
            is not processor._session_detectors["session-b"]
        )

    @pytest.mark.asyncio
    async def test_session_state_does_not_leak_between_sessions(self, processor):
        """Test that loop detection state from one session doesn't affect another."""
        # Session A: Send repetitive content that should accumulate state
        session_a_content = "AAAAAAAAAA" * 10  # 100 A's
        for _ in range(5):
            content = StreamingContent(
                content=session_a_content, metadata={"session_id": "session-a"}
            )
            await processor.process(content)

        # Session B: Send different content - should start with clean state
        session_b_content = "BBBBBBBBBB" * 10  # 100 B's
        content = StreamingContent(
            content=session_b_content, metadata={"session_id": "session-b"}
        )
        await processor.process(content)

        # Verify that session B's detector has no history from session A
        detector_a = processor._session_detectors["session-a"]
        detector_b = processor._session_detectors["session-b"]

        # Session A should have accumulated content
        history_a = detector_a.short_detector.stream_content_history
        assert "A" in history_a
        assert len(history_a) > 0

        # Session B should only have its own content, not session A's
        history_b = detector_b.short_detector.stream_content_history
        assert "B" in history_b
        assert "A" not in history_b

    @pytest.mark.asyncio
    async def test_loop_detection_in_one_session_does_not_affect_another(
        self, processor
    ):
        """Test that detecting a loop in one session doesn't trigger in another."""
        # Session A: Send content that will trigger loop detection
        loop_content = "IIIIIIII"  # 8 I's
        for _ in range(15):  # Send enough to trigger detection
            content = StreamingContent(
                content=loop_content, metadata={"session_id": "session-a"}
            )
            result = await processor.process(content)
            if result.is_cancellation:
                break

        # Session B: Send normal content - should NOT be affected by session A's loop
        normal_content = "This is normal text without any loops."
        content = StreamingContent(
            content=normal_content, metadata={"session_id": "session-b"}
        )
        result = await processor.process(content)

        # Session B should process normally, not be cancelled
        assert not result.is_cancellation
        assert result.content == normal_content

    @pytest.mark.asyncio
    async def test_session_cleanup_removes_detector(self, processor):
        """Test that detector is cleaned up when session completes."""
        session_id = "test-session"

        # Send some content
        content = StreamingContent(
            content="test content", metadata={"session_id": session_id}
        )
        await processor.process(content)

        # Verify detector was created
        assert session_id in processor._session_detectors

        # Send done marker
        done_content = StreamingContent(
            content="", is_done=True, metadata={"session_id": session_id}
        )
        await processor.process(done_content)

        # Verify detector was cleaned up
        assert session_id not in processor._session_detectors

    @pytest.mark.asyncio
    async def test_concurrent_sessions_maintain_isolation(self, processor):
        """Test that multiple concurrent sessions maintain independent state."""
        sessions = ["session-1", "session-2", "session-3"]

        # Send different content to each session concurrently
        for i, session_id in enumerate(sessions):
            # Each session gets different repeated character
            char = chr(ord("A") + i)  # A, B, C
            content = StreamingContent(
                content=char * 50, metadata={"session_id": session_id}
            )
            await processor.process(content)

        # Verify each session has its own detector with its own content
        for i, session_id in enumerate(sessions):
            detector = processor._session_detectors[session_id]
            history = detector.short_detector.stream_content_history
            expected_char = chr(ord("A") + i)

            # Each session should only have its own character
            assert expected_char in history
            # And should not have other sessions' characters
            for j, other_session in enumerate(sessions):  # noqa: B007
                if i != j:
                    other_char = chr(ord("A") + j)
                    assert other_char not in history

    @pytest.mark.asyncio
    async def test_same_session_reuses_detector(self, processor):
        """Test that the same session reuses its detector instance."""
        session_id = "test-session"

        # Send first chunk
        content1 = StreamingContent(
            content="first chunk", metadata={"session_id": session_id}
        )
        await processor.process(content1)
        detector1 = processor._session_detectors[session_id]

        # Send second chunk
        content2 = StreamingContent(
            content="second chunk", metadata={"session_id": session_id}
        )
        await processor.process(content2)
        detector2 = processor._session_detectors[session_id]

        # Should be the same detector instance
        assert detector1 is detector2

        # And should have accumulated both chunks
        history = detector1.short_detector.stream_content_history
        assert "first chunk" in history
        assert "second chunk" in history

    @pytest.mark.asyncio
    async def test_session_without_id_uses_generated_stream_id(self, processor):
        """Test that content without session_id generates a unique stream_id."""
        # Send content without session_id
        content = StreamingContent(content="test content", metadata={})
        await processor.process(content)

        # Should create detector with a generated stream_id
        assert len(processor._session_detectors) == 1
        # The generated stream_id should be a UUID hex string (32 characters)
        session_key = next(iter(processor._session_detectors.keys()))
        assert len(session_key) == 32  # UUID hex without dashes

    @pytest.mark.asyncio
    async def test_stream_id_fallback_when_no_session_id(self, processor):
        """Test that stream_id is used as fallback when session_id is not present."""
        stream_id = "stream-123"

        # Send content with stream_id but no session_id
        content = StreamingContent(
            content="test content", metadata={"stream_id": stream_id}
        )
        await processor.process(content)

        # Should create detector using stream_id
        assert stream_id in processor._session_detectors

    @pytest.mark.asyncio
    async def test_multiple_cleanup_calls_are_safe(self, processor):
        """Test that cleaning up the same session multiple times doesn't cause errors."""
        session_id = "test-session"

        # Create a detector
        content = StreamingContent(content="test", metadata={"session_id": session_id})
        await processor.process(content)
        assert session_id in processor._session_detectors

        # Clean up multiple times
        processor.cleanup_session(session_id)
        processor.cleanup_session(session_id)  # Should not raise error
        processor.cleanup_session(session_id)  # Should not raise error

        assert session_id not in processor._session_detectors

    @pytest.mark.asyncio
    async def test_detector_state_persists_within_session(self, processor):
        """Test that detector state accumulates correctly within a single session."""
        session_id = "test-session"

        # Send multiple chunks of DIFFERENT content to avoid triggering loop detection
        for i in range(10):
            content = StreamingContent(
                content=f"Chunk {i} with unique content here.",
                metadata={"session_id": session_id},
            )
            await processor.process(content)

        # Verify that content accumulated in the detector
        detector = processor._session_detectors[session_id]
        history = detector.short_detector.stream_content_history

        # Should have accumulated all chunks
        assert "Chunk 0" in history
        assert "Chunk 9" in history
        assert len(history) > 200  # Should have accumulated substantial content

    @pytest.mark.asyncio
    async def test_factory_creates_fresh_detectors(self, detector_factory):
        """Test that the factory function creates independent detector instances."""
        detector1 = detector_factory()
        detector2 = detector_factory()

        # Should be different instances
        assert detector1 is not detector2

        # Should have independent state
        detector1.process_chunk("test1")
        detector2.process_chunk("test2")

        history1 = detector1.short_detector.stream_content_history
        history2 = detector2.short_detector.stream_content_history

        assert "test1" in history1
        assert "test1" not in history2
        assert "test2" in history2
        assert "test2" not in history1


class TestLoopDetectionRegressionPrevention:
    """Tests to prevent regression to shared detector state."""

    @pytest.mark.asyncio
    async def test_processor_does_not_share_single_detector_instance(self):
        """
        REGRESSION TEST: Ensure processor doesn't use a single shared detector.

        This test would FAIL if someone reverts to the old implementation where
        a single detector instance was shared across all sessions.
        """

        # Create processor with factory
        def create_detector():
            return HybridLoopDetector()

        processor = LoopDetectionProcessor(loop_detector_factory=create_detector)

        # Process content for two sessions
        content_a = StreamingContent(
            content="AAAA", metadata={"session_id": "session-a"}
        )
        content_b = StreamingContent(
            content="BBBB", metadata={"session_id": "session-b"}
        )

        await processor.process(content_a)
        await processor.process(content_b)

        # CRITICAL: Must have separate detector instances
        detector_a = processor._session_detectors["session-a"]
        detector_b = processor._session_detectors["session-b"]

        # This assertion would FAIL if using shared detector
        assert detector_a is not detector_b, (
            "REGRESSION: Detector instances are shared between sessions! "
            "Each session must have its own isolated detector instance."
        )

    @pytest.mark.asyncio
    async def test_detector_state_is_not_global(self):
        """
        REGRESSION TEST: Ensure detector state is not stored globally.

        This test would FAIL if detector state was stored in a class variable
        or module-level variable instead of per-instance.
        """

        def create_detector():
            return HybridLoopDetector()

        processor = LoopDetectionProcessor(loop_detector_factory=create_detector)

        # Session A accumulates state
        for _ in range(5):
            content = StreamingContent(
                content="AAAA", metadata={"session_id": "session-a"}
            )
            await processor.process(content)

        # Session B should start fresh
        content_b = StreamingContent(
            content="BBBB", metadata={"session_id": "session-b"}
        )
        await processor.process(content_b)

        # Get histories
        history_a = processor._session_detectors[
            "session-a"
        ].short_detector.stream_content_history
        history_b = processor._session_detectors[
            "session-b"
        ].short_detector.stream_content_history

        # This assertion would FAIL if state was global
        assert "A" not in history_b, (
            "REGRESSION: Session B's detector contains Session A's content! "
            "Detector state is being shared globally instead of per-session."
        )

        assert "B" not in history_a, (
            "REGRESSION: Session A's detector contains Session B's content! "
            "Detector state is being shared globally instead of per-session."
        )
