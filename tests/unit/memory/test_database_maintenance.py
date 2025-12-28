"""Unit tests for DatabaseMaintenance."""

from __future__ import annotations

import tempfile
from collections.abc import AsyncGenerator, Generator
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from freezegun import freeze_time
from src.core.memory.config import MemoryConfiguration
from src.core.memory.maintenance import DatabaseMaintenance
from src.core.memory.models import SessionSummary
from src.core.memory.sqlite_repository import MemoryRepository


def create_summary(
    user_id: str = "user-1",
    session_id: str = "sess-1",
    days_ago: int = 0,
) -> SessionSummary:
    """Create a test SessionSummary."""
    with freeze_time("2024-01-01 12:00:00"):
        now = datetime.now(timezone.utc) - timedelta(days=days_ago)
        return SessionSummary(
            id=f"sum-{session_id}",
            user_id=user_id,
            session_id=session_id,
            session_start=now,
            backend_model="openai:gpt-4o",
            title="Test Session",
            scope="Testing",
            completion_status="completed",
            full_analysis="<session_summary/>",
            summary_version="v1",
            created_at=now,
        )


class TestDatabaseMaintenance:
    """Tests for DatabaseMaintenance."""

    @pytest.fixture
    def temp_db_path(self) -> Generator[Path, None, None]:
        """Create a temporary database path."""
        with tempfile.TemporaryDirectory() as tmpdir:
            yield Path(tmpdir) / "test_memory.sqlite3"

    @pytest.fixture
    def config(self, temp_db_path: Path) -> MemoryConfiguration:
        """Create test configuration."""
        return MemoryConfiguration(
            available=True,
            database_path=str(temp_db_path),
            retention_days=90,
            require_project_discovery=False,
        )

    @pytest.fixture
    async def repository(
        self, config: MemoryConfiguration
    ) -> AsyncGenerator[MemoryRepository, None]:
        """Create repository instance."""
        repo = MemoryRepository(config)
        yield repo
        await repo.close()

    @pytest.fixture
    def maintenance(
        self, config: MemoryConfiguration, repository: MemoryRepository
    ) -> DatabaseMaintenance:
        """Create maintenance instance."""
        return DatabaseMaintenance(config, repository)

    @pytest.mark.asyncio
    async def test_cleanup_deletes_old_sessions(
        self, maintenance: DatabaseMaintenance, repository: MemoryRepository
    ) -> None:
        """Test cleanup deletes sessions older than retention."""
        await repository.initialize_schema()

        with freeze_time("2024-01-01 12:00:00"):
            # Create old and recent sessions
            old_summary = create_summary(session_id="old", days_ago=100)
            recent_summary = create_summary(session_id="recent", days_ago=10)

            await repository.save_session_summary(old_summary)
            await repository.save_session_summary(recent_summary)

            # Run cleanup
            deleted = await maintenance.run_cleanup()

        assert deleted == 1

        # Verify only recent remains
        summaries = await repository.get_recent_sessions("user-1", limit=10)
        assert len(summaries) == 1
        assert summaries[0].session_id == "recent"

    @pytest.mark.asyncio
    async def test_cleanup_returns_zero_when_no_old_sessions(
        self, maintenance: DatabaseMaintenance, repository: MemoryRepository
    ) -> None:
        """Test cleanup returns 0 when no old sessions exist."""
        await repository.initialize_schema()

        with freeze_time("2024-01-01 12:00:00"):
            recent_summary = create_summary(session_id="recent", days_ago=10)
            await repository.save_session_summary(recent_summary)

            deleted = await maintenance.run_cleanup()

        assert deleted == 0

    @pytest.mark.asyncio
    async def test_cleanup_with_custom_retention(self, temp_db_path: Path) -> None:
        """Test cleanup with custom retention period."""
        config = MemoryConfiguration(
            available=True,
            database_path=str(temp_db_path),
            retention_days=30,
            require_project_discovery=False,
        )
        repo = MemoryRepository(config)
        try:
            maint = DatabaseMaintenance(config, repo)

            await repo.initialize_schema()

            with freeze_time("2024-01-01 12:00:00"):
                # Session at 40 days should be deleted with 30-day retention
                summary = create_summary(days_ago=40)
                await repo.save_session_summary(summary)

                deleted = await maint.run_cleanup()
            assert deleted == 1
        finally:
            await repo.close()

    @pytest.mark.asyncio
    async def test_start_stop_periodic_cleanup(
        self, maintenance: DatabaseMaintenance
    ) -> None:
        """Test starting and stopping periodic cleanup."""
        assert maintenance.is_running is False

        await maintenance.start_periodic_cleanup(interval_hours=1)
        assert maintenance.is_running is True

        await maintenance.stop_periodic_cleanup()
        assert maintenance.is_running is False

    @pytest.mark.asyncio
    async def test_double_start_warning(self, maintenance: DatabaseMaintenance) -> None:
        """Test that double start doesn't create multiple tasks."""
        await maintenance.start_periodic_cleanup(interval_hours=1)
        task1 = maintenance._task

        await maintenance.start_periodic_cleanup(interval_hours=1)
        task2 = maintenance._task

        # Should be the same task
        assert task1 is task2

        await maintenance.stop_periodic_cleanup()

    @pytest.mark.asyncio
    async def test_cleanup_handles_empty_database(
        self, maintenance: DatabaseMaintenance, repository: MemoryRepository
    ) -> None:
        """Test cleanup handles empty database gracefully."""
        await repository.initialize_schema()

        deleted = await maintenance.run_cleanup()
        assert deleted == 0
