"""Property-based tests for session state isolation.

Feature: proxy-mem
Property: 3
Validates: Requirements 3.5 - Session state isolation
"""

from __future__ import annotations

import tempfile
from datetime import datetime, timezone
from pathlib import Path

import pytest
from freezegun import freeze_time
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st
from src.core.memory.config import MemoryConfiguration
from src.core.memory.models import CapturedInteraction
from src.core.memory.service import MemoryService
from src.core.memory.sqlite_repository import MemoryRepository


def create_interaction(content: str) -> CapturedInteraction:
    """Create a test CapturedInteraction."""
    # Use fixed time - tests should use @freeze_time decorator
    fixed_time = datetime(2024, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
    return CapturedInteraction(
        role="user",
        content=content,
        timestamp=fixed_time,
    )


@pytest.mark.asyncio
@given(
    session_ids=st.lists(
        st.text(
            min_size=5, max_size=20, alphabet="abcdefghijklmnopqrstuvwxyz0123456789"
        ),
        min_size=2,
        max_size=5,
        unique=True,
    ),
    user_ids=st.lists(
        st.text(
            min_size=3, max_size=15, alphabet="abcdefghijklmnopqrstuvwxyz0123456789"
        ),
        min_size=2,
        max_size=5,
    ),
)
@settings(
    max_examples=10,  # Reduced from 15 for performance
    deadline=None,
    suppress_health_check=[HealthCheck.function_scoped_fixture],
)
@freeze_time("2024-01-01 12:00:00")
async def test_property_3_session_states_are_isolated(
    session_ids: list[str],
    user_ids: list[str],
) -> None:
    """
    Property 3: Session states are isolated from each other.

    Enabling/disabling memory for one session does not affect others.

    Validates: Requirements 3.5
    """
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "test.sqlite3"
        config = MemoryConfiguration(
            available=True,
            database_path=str(db_path),
            require_project_discovery=False,
        )
        repo = MemoryRepository(config)
        service = MemoryService(config, repo)

        # Enable memory for all sessions
        for i, session_id in enumerate(session_ids):
            user_id = user_ids[i % len(user_ids)]
            result = await service.enable_for_session(session_id, user_id)
            assert result is True

        # All sessions should be enabled
        for session_id in session_ids:
            assert await service.is_enabled_for_session(session_id) is True

        # Disable first session
        await service.disable_for_session(session_ids[0])

        # First session should be disabled
        assert await service.is_enabled_for_session(session_ids[0]) is False

        # Other sessions should still be enabled
        for session_id in session_ids[1:]:
            assert await service.is_enabled_for_session(session_id) is True


@pytest.mark.asyncio
@given(
    session1_content=st.text(min_size=5, max_size=100),
    session2_content=st.text(min_size=5, max_size=100),
)
@settings(
    max_examples=6,  # Reduced from 8 for performance
    deadline=None,
    suppress_health_check=[HealthCheck.function_scoped_fixture],
)
@freeze_time("2024-01-01 12:00:00")
async def test_property_3_captured_interactions_are_isolated(
    session1_content: str,
    session2_content: str,
) -> None:
    """
    Property 3: Captured interactions are isolated per session.

    Interactions captured for one session do not appear in another.

    Validates: Requirements 3.5
    """
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "test.sqlite3"
        config = MemoryConfiguration(
            available=True,
            database_path=str(db_path),
            require_project_discovery=False,
        )
        repo = MemoryRepository(config)
        service = MemoryService(config, repo)

        # Enable both sessions
        await service.enable_for_session("sess-1", "user-1")
        await service.enable_for_session("sess-2", "user-2")

        # Capture different content for each session
        await service.capture_interaction(
            "sess-1", create_interaction(session1_content)
        )
        await service.capture_interaction(
            "sess-2", create_interaction(session2_content)
        )

        # Retrieve interactions
        int1, _ = await service.get_captured_interactions("sess-1")
        int2, _ = await service.get_captured_interactions("sess-2")

        # Each session should have exactly its own content
        assert len(int1) == 1
        assert len(int2) == 1
        assert int1[0].content == session1_content
        assert int2[0].content == session2_content


@pytest.mark.asyncio
@given(
    user_id1=st.text(min_size=3, max_size=20, alphabet="abcdefghijklmnopqrstuvwxyz"),
    user_id2=st.text(min_size=3, max_size=20, alphabet="0123456789"),
)
@settings(
    max_examples=6,  # Reduced from 8 for performance
    deadline=None,
    suppress_health_check=[HealthCheck.function_scoped_fixture],
)
@freeze_time("2024-01-01 12:00:00")
async def test_property_3_user_assignment_is_isolated(
    user_id1: str,
    user_id2: str,
) -> None:
    """
    Property 3: User assignment is isolated per session.

    Each session maintains its own user_id.

    Validates: Requirements 3.5
    """
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "test.sqlite3"
        config = MemoryConfiguration(
            available=True,
            database_path=str(db_path),
            require_project_discovery=False,
        )
        repo = MemoryRepository(config)
        service = MemoryService(config, repo)

        # Enable sessions with different users
        await service.enable_for_session("sess-1", user_id1)
        await service.enable_for_session("sess-2", user_id2)

        # Each session should have its own user_id
        assert await service.get_session_user_id("sess-1") == user_id1
        assert await service.get_session_user_id("sess-2") == user_id2


@pytest.mark.asyncio
@freeze_time("2024-01-01 12:00:00")
async def test_property_3_get_and_clear_only_clears_one_session() -> None:
    """
    Property 3: get_and_clear only affects the specified session.

    Validates: Requirements 3.5
    """
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "test.sqlite3"
        config = MemoryConfiguration(
            available=True,
            database_path=str(db_path),
            require_project_discovery=False,
        )
        repo = MemoryRepository(config)
        service = MemoryService(config, repo)

        # Enable and capture for both sessions
        await service.enable_for_session("sess-1", "user-1")
        await service.enable_for_session("sess-2", "user-2")

        await service.capture_interaction("sess-1", create_interaction("Content 1"))
        await service.capture_interaction("sess-2", create_interaction("Content 2"))

        # Clear session 1
        int1, _ = await service.get_captured_interactions("sess-1")
        assert len(int1) == 1

        # Session 2 should still have its content
        int2, _ = await service.get_captured_interactions("sess-2")
        assert len(int2) == 1
        assert int2[0].content == "Content 2"

        # Session 1 should now be empty
        int1_after, _ = await service.get_captured_interactions("sess-1")
        assert len(int1_after) == 0
