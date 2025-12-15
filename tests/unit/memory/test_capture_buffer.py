"""Unit tests for SessionCaptureBuffer."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest
from src.core.memory.capture_buffer import SessionCaptureBuffer
from src.core.memory.models import CapturedInteraction


def create_interaction(
    content: str = "Test content",
    role: str = "user",
) -> CapturedInteraction:
    """Create a test CapturedInteraction."""
    return CapturedInteraction(
        role=role,
        content=content,
        timestamp=datetime.now(timezone.utc),
    )


class TestSessionCaptureBuffer:
    """Tests for SessionCaptureBuffer."""

    @pytest.mark.asyncio
    async def test_append_and_retrieve(self) -> None:
        """Test basic append and retrieve operations."""
        buffer = SessionCaptureBuffer()

        interaction = create_interaction()
        result = await buffer.append("sess-1", interaction)

        assert result is True
        assert await buffer.get_interaction_count("sess-1") == 1

        interactions, is_partial = await buffer.get_and_clear("sess-1")
        assert len(interactions) == 1
        assert interactions[0].content == "Test content"
        assert is_partial is False

    @pytest.mark.asyncio
    async def test_multiple_interactions(self) -> None:
        """Test appending multiple interactions."""
        buffer = SessionCaptureBuffer()

        for i in range(5):
            interaction = create_interaction(
                content=f"Content {i}",
            )
            await buffer.append("sess-1", interaction)

        assert await buffer.get_interaction_count("sess-1") == 5

        interactions, _ = await buffer.get_and_clear("sess-1")
        assert len(interactions) == 5
        assert interactions[0].content == "Content 0"
        assert interactions[4].content == "Content 4"

    @pytest.mark.asyncio
    async def test_session_isolation(self) -> None:
        """Test that sessions are isolated from each other."""
        buffer = SessionCaptureBuffer()

        await buffer.append("sess-1", create_interaction(content="Session 1"))
        await buffer.append("sess-2", create_interaction(content="Session 2"))

        assert await buffer.get_interaction_count("sess-1") == 1
        assert await buffer.get_interaction_count("sess-2") == 1

        interactions1, _ = await buffer.get_and_clear("sess-1")
        interactions2, _ = await buffer.get_and_clear("sess-2")

        assert interactions1[0].content == "Session 1"
        assert interactions2[0].content == "Session 2"

    @pytest.mark.asyncio
    async def test_buffer_size_tracking(self) -> None:
        """Test that buffer size is tracked correctly."""
        buffer = SessionCaptureBuffer()

        interaction = create_interaction(content="A" * 100)
        await buffer.append("sess-1", interaction)

        size = await buffer.get_buffer_size("sess-1")
        assert size > 100  # At least the content size

    @pytest.mark.asyncio
    async def test_buffer_overflow(self) -> None:
        """Test buffer overflow handling."""
        buffer = SessionCaptureBuffer(max_buffer_size_bytes=100)

        # First small interaction should succeed
        small = create_interaction(content="A" * 10)
        result1 = await buffer.append("sess-1", small)
        assert result1 is True

        # Large interaction should fail
        large = create_interaction(content="B" * 200)
        result2 = await buffer.append("sess-1", large)
        assert result2 is False

        # Session should be marked as partial
        assert await buffer.is_partial("sess-1") is True

        interactions, is_partial = await buffer.get_and_clear("sess-1")
        assert len(interactions) == 1  # Only the first one
        assert is_partial is True

    @pytest.mark.asyncio
    async def test_get_and_clear_removes_buffer(self) -> None:
        """Test that get_and_clear removes the session buffer."""
        buffer = SessionCaptureBuffer()

        await buffer.append("sess-1", create_interaction())
        assert await buffer.has_session("sess-1") is True

        await buffer.get_and_clear("sess-1")
        assert await buffer.has_session("sess-1") is False

    @pytest.mark.asyncio
    async def test_get_and_clear_nonexistent_session(self) -> None:
        """Test get_and_clear on nonexistent session."""
        buffer = SessionCaptureBuffer()

        interactions, is_partial = await buffer.get_and_clear("nonexistent")
        assert interactions == []
        assert is_partial is False

    @pytest.mark.asyncio
    async def test_clear_session(self) -> None:
        """Test clearing a session buffer."""
        buffer = SessionCaptureBuffer()

        await buffer.append("sess-1", create_interaction())
        assert await buffer.has_session("sess-1") is True

        await buffer.clear_session("sess-1")
        assert await buffer.has_session("sess-1") is False

    @pytest.mark.asyncio
    async def test_get_active_session_count(self) -> None:
        """Test counting active sessions."""
        buffer = SessionCaptureBuffer()

        assert await buffer.get_active_session_count() == 0

        await buffer.append("sess-1", create_interaction())
        await buffer.append("sess-2", create_interaction())
        await buffer.append("sess-3", create_interaction())

        assert await buffer.get_active_session_count() == 3

        await buffer.get_and_clear("sess-1")
        assert await buffer.get_active_session_count() == 2

    @pytest.mark.asyncio
    async def test_nonexistent_session_returns_zero(self) -> None:
        """Test that queries on nonexistent sessions return zero/false."""
        buffer = SessionCaptureBuffer()

        assert await buffer.get_buffer_size("nonexistent") == 0
        assert await buffer.get_interaction_count("nonexistent") == 0
        assert await buffer.is_partial("nonexistent") is False
        assert await buffer.has_session("nonexistent") is False

    @pytest.mark.asyncio
    async def test_metadata_included_in_size(self) -> None:
        """Test that metadata is included in size estimation."""
        buffer = SessionCaptureBuffer()

        interaction_without_meta = create_interaction(content="A" * 100)
        interaction_with_meta = CapturedInteraction(
            role="user",
            content="A" * 100,
            timestamp=datetime.now(timezone.utc),
            metadata={"key1": "value1", "key2": "value2" * 100},
        )

        await buffer.append("sess-1", interaction_without_meta)
        await buffer.append("sess-2", interaction_with_meta)

        size1 = await buffer.get_buffer_size("sess-1")
        size2 = await buffer.get_buffer_size("sess-2")

        assert size2 > size1  # Metadata adds to size
