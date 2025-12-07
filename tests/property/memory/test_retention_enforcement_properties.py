"""Property-based tests for retention enforcement.

Feature: proxy-mem
Property: 12
Validates: Requirements 10.1, 10.2 - Retention enforcement
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st
from src.core.memory.config import MemoryConfiguration
from src.core.memory.models import SessionSummary
from src.core.memory.sqlite_repository import MemoryRepository

# Reduce logging verbosity for tests
logging.getLogger("src.core.memory.sqlite_repository").setLevel(logging.WARNING)


def create_summary(
    user_id: str,
    session_id: str,
    session_start: datetime,
) -> SessionSummary:
    """Create a minimal SessionSummary for testing."""
    return SessionSummary(
        id=f"sum-{session_id}",
        user_id=user_id,
        session_id=session_id,
        session_start=session_start,
        backend_model="openai:gpt-4o",
        title="Test summary",
        scope="Testing",
        completion_status="completed",
        full_analysis="<session_summary/>",
        summary_version="v1",
        created_at=session_start,
    )


@pytest.mark.asyncio
@given(
    retention_days=st.integers(min_value=1, max_value=365),
    old_session_age_days=st.integers(min_value=1, max_value=500),
    recent_session_age_days=st.integers(min_value=0, max_value=30),
)
@settings(
    max_examples=20,
    deadline=None,
    suppress_health_check=[HealthCheck.function_scoped_fixture],
)
async def test_property_12_retention_enforcement(
    retention_days: int,
    old_session_age_days: int,
    recent_session_age_days: int,
) -> None:
    """
    Property 12: Retention enforcement.

    For any session record older than the configured retention period,
    the cleanup task should delete it.

    Validates: Requirements 10.1, 10.2
    """
    # Use in-memory database for speed and avoid disk I/O
    config = MemoryConfiguration(database_path=":memory:")
    repository = MemoryRepository(config)
    await repository.initialize_schema()

    try:
        now = datetime.now(timezone.utc)
        cutoff = now - timedelta(days=retention_days)

        # Create old session (may or may not be deleted)
        old_date = now - timedelta(days=old_session_age_days)
        old_summary = create_summary("user-1", "old-sess", old_date)
        await repository.save_session_summary(old_summary)

        # Create recent session (should never be deleted)
        recent_date = now - timedelta(days=recent_session_age_days)
        recent_summary = create_summary("user-1", "recent-sess", recent_date)
        await repository.save_session_summary(recent_summary)

        # Delete sessions older than retention period
        deleted = await repository.delete_old_sessions(cutoff)

        # Verify results
        remaining = await repository.get_recent_sessions("user-1", limit=100)

        if old_session_age_days > retention_days:
            # Old session should have been deleted
            assert deleted >= 1
            assert not any(s.session_id == "old-sess" for s in remaining)
        else:
            # Old session is within retention, should NOT be deleted
            assert any(s.session_id == "old-sess" for s in remaining)

        if recent_session_age_days <= retention_days:
            # Recent session should always remain
            assert any(s.session_id == "recent-sess" for s in remaining)

    finally:
        await repository.close()


@pytest.mark.asyncio
@given(
    num_sessions=st.integers(min_value=1, max_value=10),
    retention_days=st.integers(min_value=30, max_value=180),
)
@settings(
    max_examples=15,
    deadline=None,
    suppress_health_check=[HealthCheck.function_scoped_fixture],
)
async def test_property_12_bulk_retention(
    num_sessions: int,
    retention_days: int,
) -> None:
    """
    Property 12: Bulk retention enforcement.

    When multiple sessions exist with varying ages, only those
    older than retention period should be deleted.

    Validates: Requirements 10.1, 10.2
    """
    config = MemoryConfiguration(database_path=":memory:")
    repository = MemoryRepository(config)
    await repository.initialize_schema()

    try:
        now = datetime.now(timezone.utc)
        cutoff = now - timedelta(days=retention_days)

        expected_remaining = 0
        expected_deleted = 0

        # Create sessions with various ages
        for i in range(num_sessions):
            age_days = i * 20  # 0, 20, 40, 60, ...
            session_date = now - timedelta(days=age_days)
            summary = create_summary("user-1", f"sess-{i}", session_date)
            await repository.save_session_summary(summary)

            if age_days > retention_days:
                expected_deleted += 1
            else:
                expected_remaining += 1

        # Delete old sessions
        deleted = await repository.delete_old_sessions(cutoff)

        # Verify
        remaining = await repository.get_recent_sessions("user-1", limit=100)

        assert deleted == expected_deleted
        assert len(remaining) == expected_remaining

    finally:
        await repository.close()


@pytest.mark.asyncio
async def test_property_12_delete_returns_count() -> None:
    """
    Property 12: Delete returns accurate count.

    The delete_old_sessions method should return the exact count
    of deleted records.

    Validates: Requirements 10.3
    """
    config = MemoryConfiguration(database_path=":memory:")
    repository = MemoryRepository(config)
    await repository.initialize_schema()

    try:
        now = datetime.now(timezone.utc)

        # Create 5 old sessions
        for i in range(5):
            old_date = now - timedelta(days=100 + i)
            summary = create_summary("user-1", f"old-{i}", old_date)
            await repository.save_session_summary(summary)

        # Create 3 recent sessions
        for i in range(3):
            recent_date = now - timedelta(days=10 + i)
            summary = create_summary("user-1", f"recent-{i}", recent_date)
            await repository.save_session_summary(summary)

        # Delete sessions older than 90 days
        cutoff = now - timedelta(days=90)
        deleted = await repository.delete_old_sessions(cutoff)

        assert deleted == 5

        remaining = await repository.get_recent_sessions("user-1", limit=100)
        assert len(remaining) == 3

    finally:
        await repository.close()


@pytest.mark.asyncio
async def test_property_12_delete_no_matching_sessions() -> None:
    """
    Property 12: Delete with no matching sessions.

    When no sessions match the retention criteria, delete should return 0.

    Validates: Requirements 10.1
    """
    config = MemoryConfiguration(database_path=":memory:")
    repository = MemoryRepository(config)
    await repository.initialize_schema()

    try:
        now = datetime.now(timezone.utc)

        # Create only recent sessions
        for i in range(3):
            recent_date = now - timedelta(days=10 + i)
            summary = create_summary("user-1", f"recent-{i}", recent_date)
            await repository.save_session_summary(summary)

        # Delete sessions older than 90 days (none should match)
        cutoff = now - timedelta(days=90)
        deleted = await repository.delete_old_sessions(cutoff)

        assert deleted == 0

        remaining = await repository.get_recent_sessions("user-1", limit=100)
        assert len(remaining) == 3

    finally:
        await repository.close()
