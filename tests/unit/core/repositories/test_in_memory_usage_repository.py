"""
Tests for InMemoryUsageRepository.

This module tests the in-memory usage repository implementation.
"""

from collections import defaultdict
from datetime import datetime, timezone

import pytest
from src.core.domain.usage_data import UsageData
from src.core.repositories.in_memory_usage_repository import InMemoryUsageRepository


class TestInMemoryUsageRepository:
    """Tests for InMemoryUsageRepository class."""

    @pytest.fixture
    def repository(self) -> InMemoryUsageRepository:
        """Create a fresh InMemoryUsageRepository for each test."""
        return InMemoryUsageRepository()

    @pytest.fixture
    def sample_usage_data(self) -> UsageData:
        """Create sample usage data for testing."""
        return UsageData(
            id="usage-123",
            session_id="session-456",
            project="test-project",
            model="gpt-4",
            prompt_tokens=100,
            completion_tokens=200,
            total_tokens=300,
            cost=0.06,
            timestamp=datetime(2024, 1, 1, 12, 0, 0, tzinfo=timezone.utc),
        )

    @pytest.fixture
    def sample_usage_data_no_session(self) -> UsageData:
        """Create sample usage data with empty session ID."""
        return UsageData(
            id="usage-no-session",
            session_id="",  # Use empty string instead of None
            project="test-project",
            model="claude-3",
            prompt_tokens=50,
            completion_tokens=150,
            total_tokens=200,
            cost=0.04,
        )

    def test_initialization(self, repository: InMemoryUsageRepository) -> None:
        """Test repository initialization."""
        assert repository._usage == {}
        assert repository._session_usage == {}

    @pytest.mark.asyncio
    async def test_get_by_id_empty_repository(
        self, repository: InMemoryUsageRepository
    ) -> None:
        """Test get_by_id on empty repository."""
        result = await repository.get_by_id("nonexistent")
        assert result is None

    @pytest.mark.asyncio
    async def test_get_all_empty_repository(
        self, repository: InMemoryUsageRepository
    ) -> None:
        """Test get_all on empty repository."""
        result = await repository.get_all()
        assert result == []

    @pytest.mark.asyncio
    async def test_add_usage_data(
        self, repository: InMemoryUsageRepository, sample_usage_data: UsageData
    ) -> None:
        """Test adding usage data."""
        result = await repository.add(sample_usage_data)

        assert result is sample_usage_data
        assert sample_usage_data.id in repository._usage
        assert repository._usage[sample_usage_data.id] is sample_usage_data

        # Check session tracking
        assert "session-456" in repository._session_usage
        assert sample_usage_data.id in repository._session_usage["session-456"]

    @pytest.mark.asyncio
    async def test_add_usage_data_without_session_id(
        self,
        repository: InMemoryUsageRepository,
        sample_usage_data_no_session: UsageData,
    ) -> None:
        """Test adding usage data without session ID."""
        result = await repository.add(sample_usage_data_no_session)

        assert result is sample_usage_data_no_session
        assert sample_usage_data_no_session.id in repository._usage

        # Should not create session tracking for usage without session_id
        assert repository._session_usage == {}

    @pytest.mark.asyncio
    async def test_get_by_id_existing_usage(
        self, repository: InMemoryUsageRepository, sample_usage_data: UsageData
    ) -> None:
        """Test get_by_id for existing usage data."""
        await repository.add(sample_usage_data)

        result = await repository.get_by_id(sample_usage_data.id)
        assert result is sample_usage_data

    @pytest.mark.asyncio
    async def test_get_all_with_usage_data(
        self,
        repository: InMemoryUsageRepository,
        sample_usage_data: UsageData,
        sample_usage_data_no_session: UsageData,
    ) -> None:
        """Test get_all with multiple usage data entries."""
        await repository.add(sample_usage_data)
        await repository.add(sample_usage_data_no_session)

        result = await repository.get_all()
        assert len(result) == 2
        assert sample_usage_data in result
        assert sample_usage_data_no_session in result

    @pytest.mark.asyncio
    async def test_update_existing_usage_data(
        self, repository: InMemoryUsageRepository, sample_usage_data: UsageData
    ) -> None:
        """Test updating existing usage data."""
        await repository.add(sample_usage_data)

        # Modify the usage data
        sample_usage_data.cost = 0.08
        result = await repository.update(sample_usage_data)

        assert result is sample_usage_data
        assert repository._usage[sample_usage_data.id] is sample_usage_data
        assert repository._usage[sample_usage_data.id].cost == 0.08

    @pytest.mark.asyncio
    async def test_update_nonexistent_usage_data(
        self, repository: InMemoryUsageRepository, sample_usage_data: UsageData
    ) -> None:
        """Test updating nonexistent usage data (should add it)."""
        result = await repository.update(sample_usage_data)

        assert result is sample_usage_data
        assert sample_usage_data.id in repository._usage

    @pytest.mark.asyncio
    async def test_delete_existing_usage_data(
        self, repository: InMemoryUsageRepository, sample_usage_data: UsageData
    ) -> None:
        """Test deleting existing usage data."""
        await repository.add(sample_usage_data)

        result = await repository.delete(sample_usage_data.id)
        assert result is True
        assert sample_usage_data.id not in repository._usage

        # Check session tracking cleanup
        assert sample_usage_data.id not in repository._session_usage["session-456"]

    @pytest.mark.asyncio
    async def test_delete_nonexistent_usage_data(
        self, repository: InMemoryUsageRepository
    ) -> None:
        """Test deleting nonexistent usage data."""
        result = await repository.delete("nonexistent")
        assert result is False

    @pytest.mark.asyncio
    async def test_get_by_session_id_existing_session(
        self, repository: InMemoryUsageRepository, sample_usage_data: UsageData
    ) -> None:
        """Test get_by_session_id for existing session."""
        await repository.add(sample_usage_data)

        # Create another usage data entry for the same session
        usage2 = sample_usage_data.model_copy()
        usage2.id = "usage-789"
        usage2.prompt_tokens = 200
        usage2.completion_tokens = 300
        usage2.total_tokens = 500
        usage2.cost = 0.10
        await repository.add(usage2)

        result = await repository.get_by_session_id("session-456")
        assert len(result) == 2
        assert sample_usage_data in result
        assert usage2 in result

    @pytest.mark.asyncio
    async def test_get_by_session_id_nonexistent_session(
        self, repository: InMemoryUsageRepository
    ) -> None:
        """Test get_by_session_id for nonexistent session."""
        result = await repository.get_by_session_id("nonexistent")
        assert result == []

    @pytest.mark.asyncio
    async def test_get_stats_no_data(self, repository: InMemoryUsageRepository) -> None:
        """Test get_stats with no data."""
        result = await repository.get_stats()
        expected = defaultdict(
            lambda: {
                "total_tokens": 0,
                "prompt_tokens": 0,
                "completion_tokens": 0,
                "cost": 0.0,
                "requests": 0,
            }
        )
        assert result == dict(expected)

    @pytest.mark.asyncio
    async def test_get_stats_with_data(
        self, repository: InMemoryUsageRepository, sample_usage_data: UsageData
    ) -> None:
        """Test get_stats with usage data."""
        await repository.add(sample_usage_data)

        result = await repository.get_stats()

        expected = {
            "gpt-4": {
                "total_tokens": 300,
                "prompt_tokens": 100,
                "completion_tokens": 200,
                "cost": 0.06,
                "requests": 1,
            }
        }

        assert result == expected

    @pytest.mark.asyncio
    async def test_get_stats_filtered_by_project(
        self, repository: InMemoryUsageRepository, sample_usage_data: UsageData
    ) -> None:
        """Test get_stats filtered by project."""
        await repository.add(sample_usage_data)

        # Add usage data for different project
        usage_different_project = sample_usage_data.model_copy()
        usage_different_project.id = "usage-different"
        usage_different_project.project = "different-project"
        usage_different_project.model = "claude-3"
        await repository.add(usage_different_project)

        # Get stats for specific project
        result = await repository.get_stats("test-project")

        expected = {
            "gpt-4": {
                "total_tokens": 300,
                "prompt_tokens": 100,
                "completion_tokens": 200,
                "cost": 0.06,
                "requests": 1,
            }
        }

        assert result == expected
        assert "claude-3" not in result

    @pytest.mark.asyncio
    async def test_get_stats_multiple_models(
        self, repository: InMemoryUsageRepository
    ) -> None:
        """Test get_stats with multiple models."""
        # Add usage data for different models
        usage_gpt4 = UsageData(
            id="usage-gpt4",
            session_id="session-1",
            project="test-project",
            model="gpt-4",
            prompt_tokens=100,
            completion_tokens=200,
            total_tokens=300,
            cost=0.06,
        )

        usage_claude = UsageData(
            id="usage-claude",
            session_id="session-1",
            project="test-project",
            model="claude-3",
            prompt_tokens=150,
            completion_tokens=250,
            total_tokens=400,
            cost=0.08,
        )

        await repository.add(usage_gpt4)
        await repository.add(usage_claude)

        result = await repository.get_stats()

        expected = {
            "gpt-4": {
                "total_tokens": 300,
                "prompt_tokens": 100,
                "completion_tokens": 200,
                "cost": 0.06,
                "requests": 1,
            },
            "claude-3": {
                "total_tokens": 400,
                "prompt_tokens": 150,
                "completion_tokens": 250,
                "cost": 0.08,
                "requests": 1,
            },
        }

        assert result == expected

    @pytest.mark.asyncio
    async def test_get_stats_aggregated_data(
        self, repository: InMemoryUsageRepository
    ) -> None:
        """Test get_stats with multiple entries for same model."""
        usage1 = UsageData(
            id="usage-1",
            session_id="session-1",
            project="test-project",
            model="gpt-4",
            prompt_tokens=100,
            completion_tokens=200,
            total_tokens=300,
            cost=0.06,
        )

        usage2 = UsageData(
            id="usage-2",
            session_id="session-2",
            project="test-project",
            model="gpt-4",
            prompt_tokens=150,
            completion_tokens=100,
            total_tokens=250,
            cost=0.04,
        )

        await repository.add(usage1)
        await repository.add(usage2)

        result = await repository.get_stats()

        expected = {
            "gpt-4": {
                "total_tokens": 550,  # 300 + 250
                "prompt_tokens": 250,  # 100 + 150
                "completion_tokens": 300,  # 200 + 100
                "cost": 0.10,  # 0.06 + 0.04
                "requests": 2,
            }
        }

        assert result == expected

    @pytest.mark.asyncio
    async def test_usage_data_without_session_not_tracked(
        self,
        repository: InMemoryUsageRepository,
        sample_usage_data_no_session: UsageData,
    ) -> None:
        """Test that usage data without session_id is not tracked by session."""
        await repository.add(sample_usage_data_no_session)

        # Should not appear in any session queries
        for session_id in repository._session_usage:
            assert (
                sample_usage_data_no_session.id
                not in repository._session_usage[session_id]
            )

        # Should still be retrievable by ID
        result = await repository.get_by_session_id("any-session")
        assert len(result) == 0

    @pytest.mark.asyncio
    async def test_session_tracking_cleanup_on_delete(
        self, repository: InMemoryUsageRepository, sample_usage_data: UsageData
    ) -> None:
        """Test that session tracking is cleaned up when usage data is deleted."""
        await repository.add(sample_usage_data)

        # Verify session tracking exists
        assert "session-456" in repository._session_usage
        assert sample_usage_data.id in repository._session_usage["session-456"]

        # Delete the usage data
        await repository.delete(sample_usage_data.id)

        # Verify session tracking is cleaned up
        assert sample_usage_data.id not in repository._session_usage["session-456"]

    @pytest.mark.asyncio
    async def test_get_all_returns_copy(
        self, repository: InMemoryUsageRepository, sample_usage_data: UsageData
    ) -> None:
        """Test that get_all returns a copy of the usage data list."""
        await repository.add(sample_usage_data)

        result1 = await repository.get_all()
        result2 = await repository.get_all()

        # Should be different list objects
        assert result1 is not result2
        # But should contain the same usage data
        assert result1 == result2

    @pytest.mark.asyncio
    async def test_empty_repository_operations(
        self, repository: InMemoryUsageRepository
    ) -> None:
        """Test various operations on an empty repository."""
        # All operations should work without errors
        assert await repository.get_all() == []
        assert await repository.get_by_id("any") is None
        assert await repository.delete("any") is False
        assert await repository.get_by_session_id("any") == []
        assert await repository.get_stats() == defaultdict(
            lambda: {
                "total_tokens": 0,
                "prompt_tokens": 0,
                "completion_tokens": 0,
                "cost": 0.0,
                "requests": 0,
            }
        )

    @pytest.mark.asyncio
    async def test_usage_data_with_none_cost(
        self, repository: InMemoryUsageRepository
    ) -> None:
        """Test usage data with None cost (should be handled correctly in stats)."""
        usage = UsageData(
            id="usage-none-cost",
            session_id="session-1",
            project="test-project",
            model="gpt-4",
            prompt_tokens=100,
            completion_tokens=200,
            total_tokens=300,
            cost=None,  # No cost
        )

        await repository.add(usage)

        result = await repository.get_stats()

        expected = {
            "gpt-4": {
                "total_tokens": 300,
                "prompt_tokens": 100,
                "completion_tokens": 200,
                "cost": 0.0,  # Should be 0.0, not None
                "requests": 1,
            }
        }

        assert result == expected
