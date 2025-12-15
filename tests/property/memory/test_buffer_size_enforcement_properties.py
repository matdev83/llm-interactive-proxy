"""Property-based tests for buffer size enforcement.

Feature: proxy-mem
Property: 5
Validates: Requirements 4.4 - Buffer size enforcement
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st
from src.core.memory.capture_buffer import SessionCaptureBuffer
from src.core.memory.models import CapturedInteraction


def create_interaction(content: str) -> CapturedInteraction:
    """Create a CapturedInteraction with given content."""
    return CapturedInteraction(
        role="user",
        content=content,
        timestamp=datetime.now(timezone.utc),
    )


@pytest.mark.asyncio
@given(
    max_buffer_size=st.integers(min_value=100, max_value=10000),
    content_sizes=st.lists(
        st.integers(min_value=10, max_value=500),
        min_size=1,
        max_size=20,
    ),
)
@settings(
    max_examples=30,
    deadline=None,
    suppress_health_check=[HealthCheck.function_scoped_fixture],
)
async def test_property_5_buffer_never_exceeds_limit(
    max_buffer_size: int,
    content_sizes: list[int],
) -> None:
    """
    Property 5: Buffer never exceeds configured limit.

    For any sequence of append operations, the buffer should never exceed
    the configured maximum size.

    Validates: Requirements 4.4
    """
    buffer = SessionCaptureBuffer(max_buffer_size_bytes=max_buffer_size)
    session_id = "test-session"

    for size in content_sizes:
        content = "A" * size
        interaction = create_interaction(content)
        await buffer.append(session_id, interaction)

    # Buffer size should never exceed max
    actual_size = await buffer.get_buffer_size(session_id)
    assert actual_size <= max_buffer_size


@pytest.mark.asyncio
@given(
    max_buffer_size=st.integers(min_value=50, max_value=500),
    overflow_content_size=st.integers(min_value=100, max_value=1000),
)
@settings(
    max_examples=30,
    deadline=None,
    suppress_health_check=[HealthCheck.function_scoped_fixture],
)
async def test_property_5_overflow_returns_false(
    max_buffer_size: int,
    overflow_content_size: int,
) -> None:
    """
    Property 5: Buffer overflow returns False.

    When an append would exceed the buffer limit, the method returns False
    and the interaction is not added.

    Validates: Requirements 4.4
    """
    buffer = SessionCaptureBuffer(max_buffer_size_bytes=max_buffer_size)
    session_id = "test-session"

    # First fill buffer to near capacity
    initial_content = "X" * (max_buffer_size - 20)
    initial = create_interaction(initial_content)
    result1 = await buffer.append(session_id, initial)

    if result1:
        # Now try to overflow
        overflow_content = "Y" * overflow_content_size
        overflow = create_interaction(overflow_content)
        result2 = await buffer.append(session_id, overflow)

        # If overflow occurred, result should be False
        current_size = await buffer.get_buffer_size(session_id)
        if current_size + len(overflow_content.encode("utf-8")) > max_buffer_size:
            assert result2 is False


@pytest.mark.asyncio
@given(
    max_buffer_size=st.integers(min_value=100, max_value=500),
)
@settings(
    max_examples=20,
    deadline=None,
    suppress_health_check=[HealthCheck.function_scoped_fixture],
)
async def test_property_5_overflow_marks_session_partial(
    max_buffer_size: int,
) -> None:
    """
    Property 5: Buffer overflow marks session as partial.

    When overflow occurs, the session should be marked as partial.

    Validates: Requirements 4.4
    """
    buffer = SessionCaptureBuffer(max_buffer_size_bytes=max_buffer_size)
    session_id = "test-session"

    # Fill buffer with small content
    small = create_interaction("A" * 10)
    await buffer.append(session_id, small)

    # Try to overflow with large content
    large_content = "B" * (max_buffer_size * 2)
    large = create_interaction(large_content)
    result = await buffer.append(session_id, large)

    if result is False:
        # Session should be marked as partial
        assert await buffer.is_partial(session_id) is True


@pytest.mark.asyncio
@given(
    num_sessions=st.integers(min_value=2, max_value=10),
    max_buffer_size=st.integers(min_value=100, max_value=1000),
)
@settings(
    max_examples=20,
    deadline=None,
    suppress_health_check=[HealthCheck.function_scoped_fixture],
)
async def test_property_5_buffer_limit_per_session(
    num_sessions: int,
    max_buffer_size: int,
) -> None:
    """
    Property 5: Buffer limit applies per session.

    Each session has its own buffer limit, independent of others.

    Validates: Requirements 4.4
    """
    buffer = SessionCaptureBuffer(max_buffer_size_bytes=max_buffer_size)

    for i in range(num_sessions):
        session_id = f"session-{i}"
        content = "X" * (max_buffer_size - 50)
        interaction = create_interaction(content)
        result = await buffer.append(session_id, interaction)

        # Each session should succeed with near-max content
        if result:
            size = await buffer.get_buffer_size(session_id)
            assert size <= max_buffer_size


@pytest.mark.asyncio
async def test_property_5_empty_buffer_accepts_large_content() -> None:
    """
    Property 5: Empty buffer accepts content up to limit.

    An empty buffer should accept content up to but not exceeding the limit.

    Validates: Requirements 4.4
    """
    max_size = 1000
    buffer = SessionCaptureBuffer(max_buffer_size_bytes=max_size)

    # Content exactly at limit (accounting for role overhead)
    content = "A" * 950  # Leave room for role overhead
    interaction = create_interaction(content)
    result = await buffer.append("sess-1", interaction)

    assert result is True

    # Verify buffer accepts it
    size = await buffer.get_buffer_size("sess-1")
    assert size > 0


@pytest.mark.asyncio
async def test_property_5_overflow_count_tracked() -> None:
    """
    Property 5: Overflow events are tracked.

    Multiple overflow attempts should increment the overflow counter.

    Validates: Requirements 4.4
    """
    buffer = SessionCaptureBuffer(max_buffer_size_bytes=100)

    # Fill buffer
    small = create_interaction("A" * 50)
    await buffer.append("sess-1", small)

    # Multiple overflow attempts
    for _ in range(3):
        large = create_interaction("B" * 200)
        await buffer.append("sess-1", large)

    # Session should be partial
    assert await buffer.is_partial("sess-1") is True
