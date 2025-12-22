"""Regression test for DeterministicToolEventCollector git commits memory leak fix.

This test verifies that git commits are limited per session to prevent unbounded growth.
"""

import asyncio
from datetime import datetime, timezone

import pytest

from src.core.memory.models import GitCommitEvent
from src.core.memory.tool_event_collector import (
    DeterministicToolEventCollector,
    _MAX_GIT_COMMITS_PER_SESSION,
)


class TestToolEventCollectorGitCommitsLeakRegression:
    """Regression tests for DeterministicToolEventCollector git commits leak fix."""

    @pytest.mark.asyncio
    async def test_git_commits_bounded_per_session(self) -> None:
        """Test that git commits are bounded per session."""
        collector = DeterministicToolEventCollector()
        session_id = "test-session"
        num_commits = _MAX_GIT_COMMITS_PER_SESSION + 100

        # Record many unique commits
        for i in range(num_commits):
            commit_hash = f"abc{i:08d}"
            event = GitCommitEvent(
                commit_hash=commit_hash,
                message=f"Commit {i}",
                timestamp=datetime.now(timezone.utc),
            )
            await collector.record_git_commit(session_id, event)

        # Check the size of the commit list
        commit_count = await collector.get_git_commit_count(session_id)
        assert commit_count <= _MAX_GIT_COMMITS_PER_SESSION, (
            f"Git commits ({commit_count}) should be <= {_MAX_GIT_COMMITS_PER_SESSION}. "
            "Per-session limit is not being enforced."
        )

    @pytest.mark.asyncio
    async def test_multiple_sessions_git_commits_bounded(self) -> None:
        """Test that multiple sessions can accumulate git commits but are bounded."""
        collector = DeterministicToolEventCollector()
        num_sessions = 100
        commits_per_session = _MAX_GIT_COMMITS_PER_SESSION + 50

        # Create many sessions with many commits each
        for session_idx in range(num_sessions):
            session_id = f"session-{session_idx}"
            for i in range(commits_per_session):
                commit_hash = f"abc{session_idx:04d}{i:04d}"
                event = GitCommitEvent(
                    commit_hash=commit_hash,
                    message=f"Commit {i}",
                    timestamp=datetime.now(timezone.utc),
                )
                await collector.record_git_commit(session_id, event)

        # Check total commits across all sessions
        total_commits = 0
        for session_idx in range(num_sessions):
            session_id = f"session-{session_idx}"
            commit_count = await collector.get_git_commit_count(session_id)
            total_commits += commit_count
            assert commit_count <= _MAX_GIT_COMMITS_PER_SESSION, (
                f"Session {session_id} has {commit_count} commits, "
                f"should be <= {_MAX_GIT_COMMITS_PER_SESSION}"
            )

        # Total should be bounded by per-session limit
        max_expected_total = num_sessions * _MAX_GIT_COMMITS_PER_SESSION
        assert total_commits <= max_expected_total, (
            f"Total commits ({total_commits}) should be <= {max_expected_total}. "
            "Per-session limits are not being enforced."
        )

    @pytest.mark.asyncio
    async def test_git_commits_oldest_evicted(self) -> None:
        """Test that oldest commits are evicted when limit is reached."""
        collector = DeterministicToolEventCollector()
        session_id = "test-session"

        # Record commits up to limit
        for i in range(_MAX_GIT_COMMITS_PER_SESSION):
            commit_hash = f"abc{i:08d}"
            event = GitCommitEvent(
                commit_hash=commit_hash,
                message=f"Commit {i}",
                timestamp=datetime.now(timezone.utc),
            )
            await collector.record_git_commit(session_id, event)

        # Record one more commit - should evict the oldest
        oldest_hash = "abc00000000"
        new_hash = f"abc{_MAX_GIT_COMMITS_PER_SESSION:08d}"
        new_event = GitCommitEvent(
            commit_hash=new_hash,
            message="New commit",
            timestamp=datetime.now(timezone.utc),
        )
        await collector.record_git_commit(session_id, new_event)

        # Check that oldest was evicted and new one is present
        commit_count = await collector.get_git_commit_count(session_id)
        assert commit_count == _MAX_GIT_COMMITS_PER_SESSION, (
            f"Expected {_MAX_GIT_COMMITS_PER_SESSION} commits, got {commit_count}"
        )

        # Get commits and verify oldest is gone and new one is present
        file_edits, commits = await collector.get_and_clear(session_id)
        commit_hashes = {c.commit_hash for c in commits}
        assert oldest_hash not in commit_hashes, "Oldest commit should be evicted"
        assert new_hash in commit_hashes, "New commit should be present"
