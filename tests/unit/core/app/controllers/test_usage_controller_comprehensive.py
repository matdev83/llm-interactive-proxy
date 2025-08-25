"""
Tests for UsageController.

This module provides comprehensive test coverage for the UsageController class.
"""

import pytest
from datetime import datetime
from unittest.mock import AsyncMock

from src.core.app.controllers.usage_controller import UsageController
from src.core.domain.usage_data import UsageData
from src.core.interfaces.usage_tracking_interface import IUsageTrackingService


class TestUsageController:
    """Tests for UsageController class."""

    @pytest.fixture
    def mock_usage_service(self) -> IUsageTrackingService:
        """Create a mock usage tracking service."""
        return AsyncMock(spec=IUsageTrackingService)

    @pytest.fixture
    def controller(self, mock_usage_service: IUsageTrackingService) -> UsageController:
        """Create a UsageController instance."""
        return UsageController(usage_service=mock_usage_service)

    @pytest.fixture
    def controller_no_service(self) -> UsageController:
        """Create a UsageController without a service."""
        return UsageController()

    def test_initialization_with_service(self, controller: UsageController, mock_usage_service: IUsageTrackingService) -> None:
        """Test initialization with a service."""
        assert controller.usage_service == mock_usage_service

    def test_initialization_without_service(self, controller_no_service: UsageController) -> None:
        """Test initialization without a service."""
        assert controller_no_service.usage_service is None

    @pytest.mark.asyncio
    async def test_get_usage_stats_with_service(self, controller: UsageController, mock_usage_service: IUsageTrackingService) -> None:
        """Test get_usage_stats with a service."""
        mock_stats = {"total_cost": 10.5, "total_tokens": 1000}
        mock_usage_service.get_usage_stats.return_value = mock_stats

        result = await controller.get_usage_stats(project="testproject", days=7)

        assert result == mock_stats
        mock_usage_service.get_usage_stats.assert_called_once_with(project="testproject", days=7)

    @pytest.mark.asyncio
    async def test_get_usage_stats_without_service(self, controller_no_service: UsageController) -> None:
        """Test get_usage_stats without a service."""
        result = await controller_no_service.get_usage_stats()

        assert result == {"error": "Usage tracking service not available"}

    @pytest.mark.asyncio
    async def test_get_usage_stats_defaults(self, controller: UsageController, mock_usage_service: IUsageTrackingService) -> None:
        """Test get_usage_stats with default parameters."""
        mock_stats = {"total_cost": 5.0, "total_tokens": 500}
        mock_usage_service.get_usage_stats.return_value = mock_stats

        result = await controller.get_usage_stats()

        assert result == mock_stats
        mock_usage_service.get_usage_stats.assert_called_once_with(project=None, days=30)

    @pytest.mark.asyncio
    async def test_get_usage_stats_with_project(self, controller: UsageController, mock_usage_service: IUsageTrackingService) -> None:
        """Test get_usage_stats with project filter."""
        mock_stats = {"project_cost": 2.5, "project_tokens": 250}
        mock_usage_service.get_usage_stats.return_value = mock_stats

        result = await controller.get_usage_stats(project="myproject", days=14)

        assert result == mock_stats
        mock_usage_service.get_usage_stats.assert_called_once_with(project="myproject", days=14)

    @pytest.mark.asyncio
    async def test_get_usage_stats_empty_project(self, controller: UsageController, mock_usage_service: IUsageTrackingService) -> None:
        """Test get_usage_stats with empty project string."""
        mock_stats = {}
        mock_usage_service.get_usage_stats.return_value = mock_stats

        result = await controller.get_usage_stats(project="")

        assert result == mock_stats
        mock_usage_service.get_usage_stats.assert_called_once_with(project="", days=30)

    @pytest.mark.asyncio
    async def test_get_usage_stats_large_days(self, controller: UsageController, mock_usage_service: IUsageTrackingService) -> None:
        """Test get_usage_stats with large days value."""
        mock_stats = {"long_term_cost": 100.0, "long_term_tokens": 10000}
        mock_usage_service.get_usage_stats.return_value = mock_stats

        result = await controller.get_usage_stats(days=365)

        assert result == mock_stats
        mock_usage_service.get_usage_stats.assert_called_once_with(project=None, days=365)

    @pytest.mark.asyncio
    async def test_get_recent_usage_with_service(self, controller: UsageController, mock_usage_service: IUsageTrackingService) -> None:
        """Test get_recent_usage with a service."""
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
        mock_usage_service.get_recent_usage.return_value = mock_usage_data

        result = await controller.get_recent_usage(session_id="session1", limit=10)

        assert result == mock_usage_data
        mock_usage_service.get_recent_usage.assert_called_once_with(session_id="session1", limit=10)

    @pytest.mark.asyncio
    async def test_get_recent_usage_without_service(self, controller_no_service: UsageController) -> None:
        """Test get_recent_usage without a service."""
        result = await controller_no_service.get_recent_usage()

        assert result == []

    @pytest.mark.asyncio
    async def test_get_recent_usage_defaults(self, controller: UsageController, mock_usage_service: IUsageTrackingService) -> None:
        """Test get_recent_usage with default parameters."""
        mock_usage_data = []
        mock_usage_service.get_recent_usage.return_value = mock_usage_data

        result = await controller.get_recent_usage()

        assert result == mock_usage_data
        mock_usage_service.get_recent_usage.assert_called_once_with(session_id=None, limit=100)

    @pytest.mark.asyncio
    async def test_get_recent_usage_with_session_id(self, controller: UsageController, mock_usage_service: IUsageTrackingService) -> None:
        """Test get_recent_usage with session ID filter."""
        mock_usage_data = [
            UsageData(
                id="2",
                session_id="session2",
                model="claude-3",
                prompt_tokens=200,
                completion_tokens=100,
                total_tokens=300,
                cost=0.04,
                timestamp=datetime.utcnow(),
            )
        ]
        mock_usage_service.get_recent_usage.return_value = mock_usage_data

        result = await controller.get_recent_usage(session_id="session2", limit=50)

        assert result == mock_usage_data
        mock_usage_service.get_recent_usage.assert_called_once_with(session_id="session2", limit=50)

    @pytest.mark.asyncio
    async def test_get_recent_usage_empty_session_id(self, controller: UsageController, mock_usage_service: IUsageTrackingService) -> None:
        """Test get_recent_usage with empty session ID."""
        mock_usage_data = []
        mock_usage_service.get_recent_usage.return_value = mock_usage_data

        result = await controller.get_recent_usage(session_id="")

        assert result == mock_usage_data
        mock_usage_service.get_recent_usage.assert_called_once_with(session_id="", limit=100)

    @pytest.mark.asyncio
    async def test_get_recent_usage_large_limit(self, controller: UsageController, mock_usage_service: IUsageTrackingService) -> None:
        """Test get_recent_usage with large limit."""
        mock_usage_data = []
        mock_usage_service.get_recent_usage.return_value = mock_usage_data

        result = await controller.get_recent_usage(limit=10000)

        assert result == mock_usage_data
        mock_usage_service.get_recent_usage.assert_called_once_with(session_id=None, limit=10000)

    @pytest.mark.asyncio
    async def test_get_recent_usage_zero_limit(self, controller: UsageController, mock_usage_service: IUsageTrackingService) -> None:
        """Test get_recent_usage with zero limit."""
        mock_usage_data = []
        mock_usage_service.get_recent_usage.return_value = mock_usage_data

        result = await controller.get_recent_usage(limit=0)

        assert result == mock_usage_data
        mock_usage_service.get_recent_usage.assert_called_once_with(session_id=None, limit=0)

    @pytest.mark.asyncio
    async def test_service_error_handling_stats(self, controller: UsageController, mock_usage_service: IUsageTrackingService) -> None:
        """Test error handling when service raises an exception for stats."""
        mock_usage_service.get_usage_stats.side_effect = Exception("Service error")

        with pytest.raises(Exception, match="Service error"):
            await controller.get_usage_stats()

    @pytest.mark.asyncio
    async def test_service_error_handling_recent(self, controller: UsageController, mock_usage_service: IUsageTrackingService) -> None:
        """Test error handling when service raises an exception for recent usage."""
        mock_usage_service.get_recent_usage.side_effect = Exception("Service error")

        with pytest.raises(Exception, match="Service error"):
            await controller.get_recent_usage()

    @pytest.mark.asyncio
    async def test_multiple_calls_with_service(self, controller: UsageController, mock_usage_service: IUsageTrackingService) -> None:
        """Test multiple calls to controller methods."""
        mock_stats = {"cost": 1.0}
        mock_usage_data = []

        mock_usage_service.get_usage_stats.return_value = mock_stats
        mock_usage_service.get_recent_usage.return_value = mock_usage_data

        # Call stats method
        stats_result = await controller.get_usage_stats(project="test", days=1)
        assert stats_result == mock_stats

        # Call recent usage method
        recent_result = await controller.get_recent_usage(session_id="test", limit=5)
        assert recent_result == mock_usage_data

        # Verify both methods were called
        assert mock_usage_service.get_usage_stats.call_count == 1
        assert mock_usage_service.get_recent_usage.call_count == 1

    @pytest.mark.asyncio
    async def test_multiple_calls_without_service(self, controller_no_service: UsageController) -> None:
        """Test multiple calls to controller methods without service."""
        # Call stats method
        stats_result = await controller_no_service.get_usage_stats()
        assert stats_result == {"error": "Usage tracking service not available"}

        # Call recent usage method
        recent_result = await controller_no_service.get_recent_usage()
        assert recent_result == []

    @pytest.mark.asyncio
    async def test_get_usage_stats_unicode_project(self, controller: UsageController, mock_usage_service: IUsageTrackingService) -> None:
        """Test get_usage_stats with Unicode project name."""
        mock_stats = {"unicode_project": True}
        mock_usage_service.get_usage_stats.return_value = mock_stats

        result = await controller.get_usage_stats(project="项目测试", days=30)

        assert result == mock_stats
        mock_usage_service.get_usage_stats.assert_called_once_with(project="项目测试", days=30)

    @pytest.mark.asyncio
    async def test_get_recent_usage_unicode_session_id(self, controller: UsageController, mock_usage_service: IUsageTrackingService) -> None:
        """Test get_recent_usage with Unicode session ID."""
        mock_usage_data = []
        mock_usage_service.get_recent_usage.return_value = mock_usage_data

        result = await controller.get_recent_usage(session_id="session-ñáéíóú", limit=10)

        assert result == mock_usage_data
        mock_usage_service.get_recent_usage.assert_called_once_with(session_id="session-ñáéíóú", limit=10)

    @pytest.mark.asyncio
    async def test_get_usage_stats_special_characters(self, controller: UsageController, mock_usage_service: IUsageTrackingService) -> None:
        """Test get_usage_stats with special characters in project."""
        mock_stats = {}
        mock_usage_service.get_usage_stats.return_value = mock_stats

        result = await controller.get_usage_stats(project="project_with_!@#$%^&*()")

        assert result == mock_stats
        mock_usage_service.get_usage_stats.assert_called_once_with(project="project_with_!@#$%^&*()", days=30)

    @pytest.mark.asyncio
    async def test_get_recent_usage_special_characters(self, controller: UsageController, mock_usage_service: IUsageTrackingService) -> None:
        """Test get_recent_usage with special characters in session ID."""
        mock_usage_data = []
        mock_usage_service.get_recent_usage.return_value = mock_usage_data

        result = await controller.get_recent_usage(session_id="session-!@#$%^&*()")

        assert result == mock_usage_data
        mock_usage_service.get_recent_usage.assert_called_once_with(session_id="session-!@#$%^&*()", limit=100)

    @pytest.mark.asyncio
    async def test_get_usage_stats_negative_days(self, controller: UsageController, mock_usage_service: IUsageTrackingService) -> None:
        """Test get_usage_stats with negative days value."""
        mock_stats = {}
        mock_usage_service.get_usage_stats.return_value = mock_stats

        result = await controller.get_usage_stats(days=-1)

        assert result == mock_stats
        mock_usage_service.get_usage_stats.assert_called_once_with(project=None, days=-1)

    @pytest.mark.asyncio
    async def test_get_recent_usage_negative_limit(self, controller: UsageController, mock_usage_service: IUsageTrackingService) -> None:
        """Test get_recent_usage with negative limit value."""
        mock_usage_data = []
        mock_usage_service.get_recent_usage.return_value = mock_usage_data

        result = await controller.get_recent_usage(limit=-10)

        assert result == mock_usage_data
        mock_usage_service.get_recent_usage.assert_called_once_with(session_id=None, limit=-10)

    @pytest.mark.asyncio
    async def test_get_usage_stats_zero_days(self, controller: UsageController, mock_usage_service: IUsageTrackingService) -> None:
        """Test get_usage_stats with zero days."""
        mock_stats = {}
        mock_usage_service.get_usage_stats.return_value = mock_stats

        result = await controller.get_usage_stats(days=0)

        assert result == mock_stats
        mock_usage_service.get_usage_stats.assert_called_once_with(project=None, days=0)

    @pytest.mark.asyncio
    async def test_get_recent_usage_zero_limit(self, controller: UsageController, mock_usage_service: IUsageTrackingService) -> None:
        """Test get_recent_usage with zero limit."""
        mock_usage_data = []
        mock_usage_service.get_recent_usage.return_value = mock_usage_data

        result = await controller.get_recent_usage(limit=0)

        assert result == mock_usage_data
        mock_usage_service.get_recent_usage.assert_called_once_with(session_id=None, limit=0)

    @pytest.mark.asyncio
    async def test_controller_service_assignment(self) -> None:
        """Test that controller service can be assigned after initialization."""
        controller = UsageController()
        assert controller.usage_service is None

        mock_service = AsyncMock(spec=IUsageTrackingService)
        controller.usage_service = mock_service

        assert controller.usage_service == mock_service

    @pytest.mark.asyncio
    async def test_controller_with_none_service_assignment(self) -> None:
        """Test that controller service can be set to None."""
        mock_service = AsyncMock(spec=IUsageTrackingService)
        controller = UsageController(usage_service=mock_service)
        assert controller.usage_service is not None

        controller.usage_service = None
        assert controller.usage_service is None
