"""
Tests for UsageTrackingService.

This module provides comprehensive test coverage for the UsageTrackingService implementation.
"""

import asyncio
import uuid
from datetime import datetime, timedelta
from unittest.mock import AsyncMock, Mock, patch

import pytest

from src.core.domain.usage_data import UsageData
from src.core.interfaces.repositories_interface import IUsageRepository
from src.core.services.usage_tracking_service import UsageTrackingService


class TestUsageTrackingService:
    """Tests for UsageTrackingService class."""

    @pytest.fixture
    def mock_repository(self) -> IUsageRepository:
        """Create a mock usage repository."""
        return AsyncMock(spec=IUsageRepository)

    @pytest.fixture
    def service(self, mock_repository: IUsageRepository) -> UsageTrackingService:
        """Create a UsageTrackingService instance."""
        return UsageTrackingService(mock_repository)

    def test_initialization(self, service: UsageTrackingService, mock_repository: IUsageRepository) -> None:
        """Test service initialization."""
        assert service._repository == mock_repository
        assert service._repository is not None

    @pytest.mark.asyncio
    async def test_track_usage_basic(self, service: UsageTrackingService, mock_repository: IUsageRepository) -> None:
        """Test basic usage tracking."""
        mock_repository.add.return_value = None

        result = await service.track_usage(
            model="gpt-4",
            prompt_tokens=100,
            completion_tokens=50,
            cost=0.02,
            backend="openai",
            username="testuser",
            project="testproject",
            session_id="session123",
        )

        assert isinstance(result, UsageData)
        assert result.model == "openai:gpt-4"
        assert result.prompt_tokens == 100
        assert result.completion_tokens == 50
        assert result.total_tokens == 150
        assert result.cost == 0.02
        assert result.project == "testproject"
        assert result.session_id == "session123"

        mock_repository.add.assert_called_once_with(result)

    @pytest.mark.asyncio
    async def test_track_usage_with_none_session_id(self, service: UsageTrackingService, mock_repository: IUsageRepository) -> None:
        """Test usage tracking with None session_id."""
        mock_repository.add.return_value = None

        result = await service.track_usage(
            model="claude-3",
            session_id=None,
        )

        assert result.session_id == "unknown"
        mock_repository.add.assert_called_once_with(result)

    @pytest.mark.asyncio
    async def test_track_usage_computes_total_tokens(self, service: UsageTrackingService, mock_repository: IUsageRepository) -> None:
        """Test that total_tokens is computed when not provided."""
        mock_repository.add.return_value = None

        result = await service.track_usage(
            model="gpt-3.5",
            prompt_tokens=10,
            completion_tokens=20,
            # total_tokens not provided
        )

        assert result.total_tokens == 30
        mock_repository.add.assert_called_once_with(result)

    @pytest.mark.asyncio
    async def test_track_usage_provided_total_tokens(self, service: UsageTrackingService, mock_repository: IUsageRepository) -> None:
        """Test that provided total_tokens is used when given."""
        mock_repository.add.return_value = None

        result = await service.track_usage(
            model="gpt-3.5",
            prompt_tokens=10,
            completion_tokens=20,
            total_tokens=25,  # Different from sum
        )

        assert result.total_tokens == 25  # Uses provided value
        mock_repository.add.assert_called_once_with(result)

    @pytest.mark.asyncio
    async def test_track_usage_default_values(self, service: UsageTrackingService, mock_repository: IUsageRepository) -> None:
        """Test usage tracking with default values."""
        mock_repository.add.return_value = None

        result = await service.track_usage(model="test-model")

        assert result.model == "test-model"
        assert result.prompt_tokens == 0
        assert result.completion_tokens == 0
        assert result.total_tokens == 0
        assert result.cost == 0.0
        assert result.project is None
        assert result.session_id == "unknown"

    @pytest.mark.asyncio
    async def test_track_usage_generates_unique_ids(self, service: UsageTrackingService, mock_repository: IUsageRepository) -> None:
        """Test that each usage tracking generates unique IDs."""
        mock_repository.add.return_value = None

        result1 = await service.track_usage(model="model1")
        result2 = await service.track_usage(model="model2")

        assert result1.id != result2.id
        assert len(result1.id) > 0
        assert len(result2.id) > 0

    @pytest.mark.asyncio
    async def test_track_usage_timestamp(self, service: UsageTrackingService, mock_repository: IUsageRepository) -> None:
        """Test that usage tracking sets proper timestamps."""
        mock_repository.add.return_value = None

        fixed_time = datetime(2023, 12, 25, 12, 0, 0)

        with patch('src.core.services.usage_tracking_service.datetime') as mock_datetime:
            mock_datetime.utcnow.return_value = fixed_time

            result = await service.track_usage(model="test-model")

            assert result.timestamp == fixed_time

    @pytest.mark.asyncio
    async def test_track_request_context_manager(self, service: UsageTrackingService, mock_repository: IUsageRepository) -> None:
        """Test track_request context manager."""
        mock_repository.add.return_value = None

        async with service.track_request(
            model="gpt-4",
            backend="openai",
            messages=[{"role": "user", "content": "Hello"}],
            username="testuser",
            project="testproject",
            session_id="session123",
        ) as tracker:
            assert tracker is not None
            assert hasattr(tracker, "response")
            assert hasattr(tracker, "response_headers")
            assert hasattr(tracker, "cost")

        # Verify that usage was tracked after context exit
        mock_repository.add.assert_called_once()

    @pytest.mark.asyncio
    async def test_track_request_with_kwargs(self, service: UsageTrackingService, mock_repository: IUsageRepository) -> None:
        """Test track_request with additional kwargs."""
        mock_repository.add.return_value = None

        kwargs = {"temperature": 0.7, "max_tokens": 100}

        async with service.track_request(
            model="gpt-4",
            backend="openai",
            messages=[{"role": "user", "content": "Hello"}],
            **kwargs
        ) as tracker:
            assert tracker is not None

        # Should still work with kwargs
        mock_repository.add.assert_called_once()

    @pytest.mark.asyncio
    async def test_get_usage_stats(self, service: UsageTrackingService, mock_repository: IUsageRepository) -> None:
        """Test getting usage statistics."""
        mock_stats = {
            "gpt-4": {
                "total_tokens": 1000,
                "prompt_tokens": 600,
                "completion_tokens": 400,
                "cost": 0.1,
                "requests": 5,
            }
        }
        mock_repository.get_stats.return_value = mock_stats

        result = await service.get_usage_stats(project="testproject", days=7)

        assert result == mock_stats
        mock_repository.get_stats.assert_called_once_with("testproject")

    @pytest.mark.asyncio
    async def test_get_usage_stats_defaults(self, service: UsageTrackingService, mock_repository: IUsageRepository) -> None:
        """Test getting usage statistics with defaults."""
        mock_stats = {}
        mock_repository.get_stats.return_value = mock_stats

        result = await service.get_usage_stats()

        assert result == mock_stats
        mock_repository.get_stats.assert_called_once_with(None)

    @pytest.mark.asyncio
    async def test_get_recent_usage(self, service: UsageTrackingService, mock_repository: IUsageRepository) -> None:
        """Test getting recent usage data."""
        mock_usage_data = [
            UsageData(
                id="1",
                session_id="session1",
                model="gpt-4",
                prompt_tokens=100,
                completion_tokens=50,
                total_tokens=150,
                cost=0.02,
                timestamp=datetime.utcnow(),
            )
        ]
        mock_repository.get_by_session_id.return_value = mock_usage_data

        result = await service.get_recent_usage(session_id="session1", limit=10)

        assert result == mock_usage_data
        mock_repository.get_by_session_id.assert_called_once_with("session1")

    @pytest.mark.asyncio
    async def test_get_recent_usage_defaults(self, service: UsageTrackingService, mock_repository: IUsageRepository) -> None:
        """Test getting recent usage with defaults."""
        mock_usage_data = []
        mock_repository.get_all.return_value = mock_usage_data

        result = await service.get_recent_usage()

        assert result == mock_usage_data
        mock_repository.get_all.assert_called_once()

    @pytest.mark.asyncio
    async def test_get_recent_usage_with_session_id(self, service: UsageTrackingService, mock_repository: IUsageRepository) -> None:
        """Test getting recent usage filtered by session_id."""
        mock_usage_data = [
            UsageData(
                id="1",
                session_id="session1",
                model="gpt-4",
                prompt_tokens=50,
                completion_tokens=25,
                total_tokens=75,
                cost=0.01,
                timestamp=datetime.utcnow(),
            )
        ]
        mock_repository.get_by_session_id.return_value = mock_usage_data

        result = await service.get_recent_usage(session_id="session1")

        assert result == mock_usage_data
        mock_repository.get_by_session_id.assert_called_once_with("session1")

    @pytest.mark.asyncio
    async def test_track_usage_repository_error(self, service: UsageTrackingService, mock_repository: IUsageRepository) -> None:
        """Test handling repository errors during usage tracking."""
        mock_repository.add.side_effect = Exception("Repository error")

        with pytest.raises(Exception, match="Repository error"):
            await service.track_usage(model="test-model")

    @pytest.mark.asyncio
    async def test_get_usage_stats_repository_error(self, service: UsageTrackingService, mock_repository: IUsageRepository) -> None:
        """Test handling repository errors during stats retrieval."""
        mock_repository.get_stats.side_effect = Exception("Repository error")

        with pytest.raises(Exception, match="Repository error"):
            await service.get_usage_stats()

    @pytest.mark.asyncio
    async def test_get_recent_usage_repository_error(self, service: UsageTrackingService, mock_repository: IUsageRepository) -> None:
        """Test handling repository errors during recent usage retrieval."""
        mock_repository.get_all.side_effect = Exception("Repository error")

        with pytest.raises(Exception, match="Repository error"):
            await service.get_recent_usage()

    @pytest.mark.asyncio
    async def test_track_request_exception_handling(self, service: UsageTrackingService, mock_repository: IUsageRepository) -> None:
        """Test exception handling in track_request context manager."""
        mock_repository.add.return_value = None

        with pytest.raises(RuntimeError, match="Context error"):
            async with service.track_request(
                model="gpt-4",
                backend="openai",
                messages=[{"role": "user", "content": "Hello"}],
            ) as tracker:
                raise RuntimeError("Context error")

        # Should still try to track usage despite the error
        mock_repository.add.assert_called_once()

    @pytest.mark.asyncio
    async def test_multiple_concurrent_usage_tracking(self, service: UsageTrackingService, mock_repository: IUsageRepository) -> None:
        """Test concurrent usage tracking."""
        mock_repository.add.return_value = None

        # Track multiple usage events concurrently
        tasks = [
            service.track_usage(model=f"model{i}", session_id=f"session{i}")
            for i in range(5)
        ]

        results = await asyncio.gather(*tasks)

        assert len(results) == 5
        assert all(isinstance(r, UsageData) for r in results)
        assert len(set(r.id for r in results)) == 5  # All unique IDs

        assert mock_repository.add.call_count == 5

    @pytest.mark.asyncio
    async def test_track_request_with_complex_messages(self, service: UsageTrackingService, mock_repository: IUsageRepository) -> None:
        """Test track_request with complex message structures."""
        mock_repository.add.return_value = None

        complex_messages = [
            {"role": "system", "content": "You are a helpful assistant."},
            {"role": "user", "content": "Hello"},
            {"role": "assistant", "content": "Hi there!"},
            {"role": "user", "content": "How are you?"},
        ]

        async with service.track_request(
            model="gpt-4",
            backend="openai",
            messages=complex_messages,
            username="testuser",
            project="testproject",
            session_id="session123",
            temperature=0.7,
            max_tokens=1000,
        ) as tracker:
            assert tracker is not None

        mock_repository.add.assert_called_once()

    @pytest.mark.asyncio
    async def test_track_usage_large_values(self, service: UsageTrackingService, mock_repository: IUsageRepository) -> None:
        """Test usage tracking with large values."""
        mock_repository.add.return_value = None

        result = await service.track_usage(
            model="large-model",
            prompt_tokens=100000,
            completion_tokens=50000,
            cost=100.0,
            execution_time=300.0,
        )

        assert result.prompt_tokens == 100000
        assert result.completion_tokens == 50000
        assert result.total_tokens == 150000
        assert result.cost == 100.0

    @pytest.mark.asyncio
    async def test_track_usage_zero_values(self, service: UsageTrackingService, mock_repository: IUsageRepository) -> None:
        """Test usage tracking with zero values."""
        mock_repository.add.return_value = None

        result = await service.track_usage(
            model="zero-model",
            prompt_tokens=0,
            completion_tokens=0,
            cost=0.0,
            execution_time=0.0,
        )

        assert result.prompt_tokens == 0
        assert result.completion_tokens == 0
        assert result.total_tokens == 0
        assert result.cost == 0.0

    @pytest.mark.asyncio
    async def test_track_usage_negative_values(self, service: UsageTrackingService, mock_repository: IUsageRepository) -> None:
        """Test usage tracking with negative values (should still work)."""
        mock_repository.add.return_value = None

        result = await service.track_usage(
            model="negative-model",
            prompt_tokens=-10,  # Unusual but should be handled
            completion_tokens=-5,
            cost=-0.01,
            execution_time=-1.0,
        )

        assert result.prompt_tokens == -10
        assert result.completion_tokens == -5
        assert result.total_tokens == -15
        assert result.cost == -0.01

    @pytest.mark.asyncio
    async def test_track_request_empty_messages(self, service: UsageTrackingService, mock_repository: IUsageRepository) -> None:
        """Test track_request with empty messages."""
        mock_repository.add.return_value = None

        async with service.track_request(
            model="gpt-4",
            backend="openai",
            messages=[],
        ) as tracker:
            assert tracker is not None

        mock_repository.add.assert_called_once()

    @pytest.mark.asyncio
    async def test_get_usage_stats_edge_cases(self, service: UsageTrackingService, mock_repository: IUsageRepository) -> None:
        """Test get_usage_stats with edge cases."""
        # Test with very large days value
        mock_repository.get_stats.return_value = {}
        await service.get_usage_stats(days=36500)  # 100 years

        mock_repository.get_stats.assert_called_with(None)

        # Test with empty project string
        await service.get_usage_stats(project="")

        mock_repository.get_stats.assert_called_with("")

    @pytest.mark.asyncio
    async def test_get_recent_usage_edge_cases(self, service: UsageTrackingService, mock_repository: IUsageRepository) -> None:
        """Test get_recent_usage with edge cases."""
        # Test with empty session_id (should use get_all)
        mock_repository.get_all.return_value = []
        await service.get_recent_usage(session_id="")

        assert mock_repository.get_all.call_count == 1

        # Test with very large limit
        mock_repository.get_all.return_value = []
        await service.get_recent_usage(limit=1000000)

        assert mock_repository.get_all.call_count == 2

    @pytest.mark.asyncio
    async def test_track_usage_special_model_names(self, service: UsageTrackingService, mock_repository: IUsageRepository) -> None:
        """Test usage tracking with special model names."""
        mock_repository.add.return_value = None

        special_models = [
            "model/with/slashes",
            "model-with-dashes",
            "model_with_underscores",
            "model.with.dots",
            "model with spaces",
            "model/with/special-chars_!@#$%",
        ]

        for model in special_models:
            result = await service.track_usage(model=model)
            assert result.model == model

    @pytest.mark.asyncio
    async def test_track_usage_unicode_metadata(self, service: UsageTrackingService, mock_repository: IUsageRepository) -> None:
        """Test usage tracking with Unicode metadata."""
        mock_repository.add.return_value = None

        result = await service.track_usage(
            model="unicode-model",
            username="用户",  # Chinese
            project="项目",  # Chinese
            session_id="session-ñáéíóú",  # Spanish accents
        )

        assert result.project == "项目"
        assert result.session_id == "session-ñáéíóú"

    def test_service_with_none_repository(self) -> None:
        """Test service initialization with None repository."""
        # The service doesn't validate the repository parameter
        service = UsageTrackingService(None)  # type: ignore
        assert service._repository is None
