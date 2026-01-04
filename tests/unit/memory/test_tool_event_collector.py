"""Unit tests for DeterministicToolEventCollector and tool event models."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest
from freezegun import freeze_time
from pydantic import ValidationError
from src.core.memory.models import (
    FileEditEvent,
    GitCommitEvent,
)
from src.core.memory.tool_event_collector import DeterministicToolEventCollector


class TestFileEditEvent:
    """Tests for FileEditEvent model."""

    @freeze_time("2024-01-01 12:00:00")
    def test_create_file_edit_event(self) -> None:
        """Test creating a file edit event."""
        now = datetime.now(timezone.utc)
        event = FileEditEvent(
            path="src/feature.py",
            action="modified",
            tool="apply_patch",
            timestamp=now,
        )
        assert event.path == "src/feature.py"
        assert event.action == "modified"
        assert event.tool == "apply_patch"
        assert event.timestamp == now

    @freeze_time("2024-01-01 12:00:00")
    def test_file_edit_event_all_actions(self) -> None:
        """Test all valid action types."""
        now = datetime.now(timezone.utc)
        for action in ["created", "modified", "deleted", "unknown"]:
            event = FileEditEvent(
                path="test.py",
                action=action,  # type: ignore[arg-type]
                timestamp=now,
            )
            assert event.action == action

    @freeze_time("2024-01-01 12:00:00")
    def test_file_edit_event_optional_tool(self) -> None:
        """Test file edit without tool specified."""
        event = FileEditEvent(
            path="test.py",
            action="created",
            timestamp=datetime.now(timezone.utc),
        )
        assert event.tool is None

    @freeze_time("2024-01-01 12:00:00")
    def test_file_edit_event_is_frozen(self) -> None:
        """Test that FileEditEvent is immutable."""
        event = FileEditEvent(
            path="test.py",
            action="created",
            timestamp=datetime.now(timezone.utc),
        )
        with pytest.raises(ValidationError):
            event.path = "other.py"  # type: ignore[misc]


class TestGitCommitEvent:
    """Tests for GitCommitEvent model."""

    @freeze_time("2024-01-01 12:00:00")
    def test_create_git_commit_event(self) -> None:
        """Test creating a git commit event."""
        now = datetime.now(timezone.utc)
        event = GitCommitEvent(
            commit_hash="abc123def456",
            message="Add new feature",
            branch="main",
            timestamp=now,
        )
        assert event.commit_hash == "abc123def456"
        assert event.message == "Add new feature"
        assert event.branch == "main"
        assert event.timestamp == now

    @freeze_time("2024-01-01 12:00:00")
    def test_git_commit_event_minimal(self) -> None:
        """Test git commit with only required fields."""
        now = datetime.now(timezone.utc)
        event = GitCommitEvent(
            commit_hash="abc123",
            timestamp=now,
        )
        assert event.commit_hash == "abc123"
        assert event.message is None
        assert event.branch is None

    @freeze_time("2024-01-01 12:00:00")
    def test_git_commit_event_is_frozen(self) -> None:
        """Test that GitCommitEvent is immutable."""
        event = GitCommitEvent(
            commit_hash="abc123",
            timestamp=datetime.now(timezone.utc),
        )
        with pytest.raises(ValidationError):
            event.commit_hash = "def456"  # type: ignore[misc]


class TestDeterministicToolEventCollector:
    """Tests for DeterministicToolEventCollector."""

    @pytest.fixture
    def collector(self) -> DeterministicToolEventCollector:
        """Create a collector instance."""
        return DeterministicToolEventCollector()

    @pytest.mark.asyncio
    @freeze_time("2024-01-01 12:00:00")
    async def test_record_file_edit(
        self, collector: DeterministicToolEventCollector
    ) -> None:
        """Test recording a file edit event."""
        event = FileEditEvent(
            path="/home/user/project/src/test.py",
            action="modified",
            tool="apply_patch",
            timestamp=datetime.now(timezone.utc),
        )
        await collector.record_file_edit("sess-1", event, "/home/user/project")

        count = await collector.get_file_edit_count("sess-1")
        assert count == 1

    @pytest.mark.asyncio
    @freeze_time("2024-01-01 12:00:00")
    async def test_record_file_edit_normalizes_path(
        self, collector: DeterministicToolEventCollector
    ) -> None:
        """Test that file paths are normalized relative to project root."""
        event = FileEditEvent(
            path="C:\\Users\\test\\project\\src\\file.py",
            action="created",
            timestamp=datetime.now(timezone.utc),
        )
        await collector.record_file_edit("sess-1", event, "C:\\Users\\test\\project")

        file_edits, _ = await collector.get_and_clear("sess-1")
        assert len(file_edits) == 1
        # Path should be normalized with forward slashes and relative
        assert file_edits[0].path == "src/file.py"

    @pytest.mark.asyncio
    async def test_record_file_edit_deduplicates_by_path(
        self, collector: DeterministicToolEventCollector
    ) -> None:
        """Test that multiple edits to same file keep only the latest."""
        # Use explicit timestamps where event2 is clearly later
        event1 = FileEditEvent(
            path="src/test.py",
            action="created",
            timestamp=datetime(2025, 12, 7, 10, 0, 0, tzinfo=timezone.utc),
        )
        event2 = FileEditEvent(
            path="src/test.py",
            action="modified",
            timestamp=datetime(2025, 12, 7, 12, 0, 0, tzinfo=timezone.utc),
        )
        await collector.record_file_edit("sess-1", event1, None)
        await collector.record_file_edit("sess-1", event2, None)

        file_edits, _ = await collector.get_and_clear("sess-1")
        assert len(file_edits) == 1
        # Should have the latest event (event2 has later timestamp)
        assert file_edits[0].action == "modified"

    @pytest.mark.asyncio
    @freeze_time("2024-01-01 12:00:00")
    async def test_record_git_commit(
        self, collector: DeterministicToolEventCollector
    ) -> None:
        """Test recording a git commit event."""
        event = GitCommitEvent(
            commit_hash="abc123def456",
            message="Fix bug",
            branch="main",
            timestamp=datetime.now(timezone.utc),
        )
        await collector.record_git_commit("sess-1", event)

        count = await collector.get_git_commit_count("sess-1")
        assert count == 1

    @pytest.mark.asyncio
    @freeze_time("2024-01-01 12:00:00")
    async def test_record_git_commit_deduplicates_by_hash(
        self, collector: DeterministicToolEventCollector
    ) -> None:
        """Test that duplicate commits are ignored."""
        now = datetime.now(timezone.utc)
        event1 = GitCommitEvent(
            commit_hash="abc123",
            message="First",
            timestamp=now,
        )
        event2 = GitCommitEvent(
            commit_hash="abc123",  # Same hash
            message="Second",
            timestamp=now,
        )
        await collector.record_git_commit("sess-1", event1)
        await collector.record_git_commit("sess-1", event2)

        _, git_commits = await collector.get_and_clear("sess-1")
        assert len(git_commits) == 1
        assert git_commits[0].message == "First"  # First one was kept

    @pytest.mark.asyncio
    @freeze_time("2024-01-01 12:00:00")
    async def test_record_tool_event_dispatches_correctly(
        self, collector: DeterministicToolEventCollector
    ) -> None:
        """Test that record_tool_event dispatches to correct handler."""
        file_event = FileEditEvent(
            path="test.py",
            action="created",
            timestamp=datetime.now(timezone.utc),
        )
        git_event = GitCommitEvent(
            commit_hash="abc123",
            timestamp=datetime.now(timezone.utc),
        )

        await collector.record_tool_event("sess-1", file_event, None)
        await collector.record_tool_event("sess-1", git_event, None)

        file_count = await collector.get_file_edit_count("sess-1")
        git_count = await collector.get_git_commit_count("sess-1")
        assert file_count == 1
        assert git_count == 1

    @pytest.mark.asyncio
    @freeze_time("2024-01-01 12:00:00")
    async def test_get_and_clear(
        self, collector: DeterministicToolEventCollector
    ) -> None:
        """Test getting and clearing events."""
        event = FileEditEvent(
            path="test.py",
            action="created",
            timestamp=datetime.now(timezone.utc),
        )
        await collector.record_file_edit("sess-1", event, None)

        # First call should return data
        file_edits, git_commits = await collector.get_and_clear("sess-1")
        assert len(file_edits) == 1
        assert len(git_commits) == 0

        # Second call should return empty
        file_edits2, git_commits2 = await collector.get_and_clear("sess-1")
        assert len(file_edits2) == 0
        assert len(git_commits2) == 0

    @pytest.mark.asyncio
    @freeze_time("2024-01-01 12:00:00")
    async def test_session_isolation(
        self, collector: DeterministicToolEventCollector
    ) -> None:
        """Test that sessions are isolated."""
        event1 = FileEditEvent(
            path="file1.py",
            action="created",
            timestamp=datetime.now(timezone.utc),
        )
        event2 = FileEditEvent(
            path="file2.py",
            action="modified",
            timestamp=datetime.now(timezone.utc),
        )

        await collector.record_file_edit("sess-1", event1, None)
        await collector.record_file_edit("sess-2", event2, None)

        edits1, _ = await collector.get_and_clear("sess-1")
        edits2, _ = await collector.get_and_clear("sess-2")

        assert len(edits1) == 1
        assert edits1[0].path == "file1.py"
        assert len(edits2) == 1
        assert edits2[0].path == "file2.py"

    @pytest.mark.asyncio
    @freeze_time("2024-01-01 12:00:00")
    async def test_clear_session(
        self, collector: DeterministicToolEventCollector
    ) -> None:
        """Test clearing a session without returning data."""
        event = FileEditEvent(
            path="test.py",
            action="created",
            timestamp=datetime.now(timezone.utc),
        )
        await collector.record_file_edit("sess-1", event, None)

        await collector.clear_session("sess-1")

        file_edits, git_commits = await collector.get_and_clear("sess-1")
        assert len(file_edits) == 0
        assert len(git_commits) == 0

    @pytest.mark.asyncio
    @freeze_time("2024-01-01 12:00:00")
    async def test_has_session(
        self, collector: DeterministicToolEventCollector
    ) -> None:
        """Test checking if session has events."""
        assert await collector.has_session("sess-1") is False

        event = FileEditEvent(
            path="test.py",
            action="created",
            timestamp=datetime.now(timezone.utc),
        )
        await collector.record_file_edit("sess-1", event, None)

        assert await collector.has_session("sess-1") is True

    def test_classify_action_from_tool(self) -> None:
        """Test action classification from tool names."""
        assert (
            DeterministicToolEventCollector.classify_action_from_tool("write_to_file")
            == "created"
        )
        assert (
            DeterministicToolEventCollector.classify_action_from_tool("apply_patch")
            == "modified"
        )
        assert (
            DeterministicToolEventCollector.classify_action_from_tool("delete_file")
            == "deleted"
        )
        assert (
            DeterministicToolEventCollector.classify_action_from_tool("unknown_tool")
            == "unknown"
        )

    @pytest.mark.asyncio
    async def test_file_edits_sorted_by_path(
        self, collector: DeterministicToolEventCollector
    ) -> None:
        """Test that file edits are returned sorted by path."""
        from freezegun import freeze_time

        with freeze_time("2024-01-01 12:00:00"):
            now = datetime(2024, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
            for path in ["z.py", "a.py", "m.py"]:
                event = FileEditEvent(path=path, action="modified", timestamp=now)
                await collector.record_file_edit("sess-1", event, None)

            file_edits, _ = await collector.get_and_clear("sess-1")
            paths = [e.path for e in file_edits]
            assert paths == ["a.py", "m.py", "z.py"]
