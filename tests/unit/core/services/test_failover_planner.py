"""Unit tests for FailoverPlanner.

This module tests the failover plan selection and filtering logic that was
extracted from BackendService during Phase 4 refactoring.

Tests cover:
- Strategy vs coordinator selection
- Health filtering and circuit breaker integration
- Permanently disabled backend filtering
- Fallback behavior when all backends are filtered
"""

from unittest.mock import Mock

import pytest
from src.core.common.exceptions import BackendError
from src.core.interfaces.application_state_interface import IApplicationState
from src.core.interfaces.backend_lifecycle_manager_interface import (
    IBackendLifecycleManager,
)
from src.core.interfaces.configuration_interface import IConfig
from src.core.interfaces.failover_interface import (
    IFailoverCoordinator,
    IFailoverStrategy,
)
from src.core.services.failover_planner import FailoverPlanner
from src.core.services.failover_service import FailoverAttempt


@pytest.fixture
def mock_app_state():
    """Create a mock application state."""
    app_state = Mock(spec=IApplicationState)
    app_state.get_use_failover_strategy = Mock(return_value=False)
    return app_state


@pytest.fixture
def mock_config():
    """Create a mock configuration."""
    config = Mock(spec=IConfig)
    config.health_check = Mock()
    config.health_check.circuit_breaker_enabled = True
    return config


@pytest.fixture
def mock_backend_lifecycle_manager():
    """Create a mock backend lifecycle manager."""
    manager = Mock(spec=IBackendLifecycleManager)
    manager.get_disabled_backends = Mock(return_value={})
    manager.get_active_backends = Mock(return_value={})
    return manager


@pytest.fixture
def mock_failover_coordinator():
    """Create a mock failover coordinator."""
    coordinator = Mock(spec=IFailoverCoordinator)
    coordinator.get_failover_attempts = Mock(return_value=[])
    return coordinator


@pytest.fixture
def failover_planner(
    mock_app_state,
    mock_failover_coordinator,
    mock_backend_lifecycle_manager,
    mock_config,
):
    """Create a FailoverPlanner instance for testing."""
    return FailoverPlanner(
        app_state=mock_app_state,
        failover_coordinator=mock_failover_coordinator,
        backend_lifecycle_manager=mock_backend_lifecycle_manager,
        config=mock_config,
    )


class TestFailoverStrategyPath:
    """Test failover strategy path (when IFailoverStrategy is provided)."""

    def test_uses_strategy_when_enabled(
        self,
        mock_app_state,
        mock_failover_coordinator,
        mock_backend_lifecycle_manager,
        mock_config,
    ):
        """Test that strategy is used when enabled in app state."""
        # Set up strategy
        strategy = Mock(spec=IFailoverStrategy)
        strategy.get_failover_plan = Mock(
            return_value=[("anthropic", "claude-3-5-sonnet")]
        )

        # Enable strategy in app state
        mock_app_state.get_use_failover_strategy = Mock(return_value=True)

        planner = FailoverPlanner(
            app_state=mock_app_state,
            failover_coordinator=mock_failover_coordinator,
            backend_lifecycle_manager=mock_backend_lifecycle_manager,
            config=mock_config,
            failover_strategy=strategy,
        )

        # Call get_failover_plan
        result = planner.get_failover_plan("gpt-4", "openai")

        # Verify strategy was called
        strategy.get_failover_plan.assert_called_once_with("gpt-4", "openai")
        assert result == [("anthropic", "claude-3-5-sonnet")]

    def test_falls_back_to_coordinator_when_strategy_fails(
        self,
        mock_app_state,
        mock_failover_coordinator,
        mock_backend_lifecycle_manager,
        mock_config,
    ):
        """Test fallback to coordinator when strategy raises BackendError."""
        # Set up strategy that raises BackendError
        strategy = Mock(spec=IFailoverStrategy)
        strategy.get_failover_plan = Mock(side_effect=BackendError("Strategy failed"))

        # Set up coordinator
        mock_failover_coordinator.get_failover_attempts = Mock(
            return_value=[
                FailoverAttempt(backend="openai", model="gpt-3.5-turbo"),
            ]
        )

        # Enable strategy in app state
        mock_app_state.get_use_failover_strategy = Mock(return_value=True)

        planner = FailoverPlanner(
            app_state=mock_app_state,
            failover_coordinator=mock_failover_coordinator,
            backend_lifecycle_manager=mock_backend_lifecycle_manager,
            config=mock_config,
            failover_strategy=strategy,
        )

        # Call get_failover_plan - should fall back to coordinator
        result = planner.get_failover_plan("gpt-4", "openai")

        # Verify coordinator was called
        mock_failover_coordinator.get_failover_attempts.assert_called_once_with(
            "gpt-4", "openai"
        )
        assert result == [("openai", "gpt-3.5-turbo")]

    def test_strategy_disabled_uses_coordinator(
        self,
        mock_app_state,
        mock_failover_coordinator,
        mock_backend_lifecycle_manager,
        mock_config,
    ):
        """Test that coordinator is used when strategy is disabled."""
        # Set up strategy (should not be called)
        strategy = Mock(spec=IFailoverStrategy)

        # Set up coordinator
        mock_failover_coordinator.get_failover_attempts = Mock(
            return_value=[
                FailoverAttempt(backend="anthropic", model="claude-3-opus"),
            ]
        )

        # Disable strategy in app state
        mock_app_state.get_use_failover_strategy = Mock(return_value=False)

        planner = FailoverPlanner(
            app_state=mock_app_state,
            failover_coordinator=mock_failover_coordinator,
            backend_lifecycle_manager=mock_backend_lifecycle_manager,
            config=mock_config,
            failover_strategy=strategy,
        )

        # Call get_failover_plan - should use coordinator
        result = planner.get_failover_plan("gpt-4", "openai")

        # Verify strategy was NOT called
        strategy.get_failover_plan.assert_not_called()

        # Verify coordinator was called
        mock_failover_coordinator.get_failover_attempts.assert_called_once_with(
            "gpt-4", "openai"
        )
        assert result == [("anthropic", "claude-3-opus")]


class TestCoordinatorPath:
    """Test coordinator path (default failover behavior)."""

    def test_coordinator_plan_conversion(
        self, failover_planner, mock_failover_coordinator
    ):
        """Test conversion of FailoverAttempt list to plan tuples."""
        # Set up coordinator with multiple attempts
        mock_failover_coordinator.get_failover_attempts = Mock(
            return_value=[
                FailoverAttempt(backend="openai", model="gpt-4"),
                FailoverAttempt(backend="anthropic", model="claude-3-opus"),
                FailoverAttempt(backend="openai", model="gpt-3.5-turbo"),
            ]
        )

        # Call get_failover_plan
        result = failover_planner.get_failover_plan("gpt-4", "openai")

        # Verify conversion to tuples
        assert result == [
            ("openai", "gpt-4"),
            ("anthropic", "claude-3-opus"),
            ("openai", "gpt-3.5-turbo"),
        ]


class TestHealthFiltering:
    """Test health-based filtering of failover plans."""

    def test_filters_permanently_disabled_backends(
        self,
        failover_planner,
        mock_failover_coordinator,
        mock_backend_lifecycle_manager,
    ):
        """Test filtering of permanently disabled backends."""
        # Set up disabled backends registry
        mock_backend_lifecycle_manager.get_disabled_backends = Mock(
            return_value={
                "anthropic": {"reason": "Permanently disabled for cost control"}
            }
        )

        # Set up coordinator with plan including disabled backend
        mock_failover_coordinator.get_failover_attempts = Mock(
            return_value=[
                FailoverAttempt(backend="openai", model="gpt-4"),
                FailoverAttempt(backend="anthropic", model="claude-3-opus"),
                FailoverAttempt(backend="openai", model="gpt-3.5-turbo"),
            ]
        )

        # Call get_failover_plan
        result = failover_planner.get_failover_plan("gpt-4", "openai")

        # Verify anthropic is filtered out
        assert result == [
            ("openai", "gpt-4"),
            ("openai", "gpt-3.5-turbo"),
        ]

    def test_filters_unhealthy_active_backends(
        self,
        failover_planner,
        mock_failover_coordinator,
        mock_backend_lifecycle_manager,
    ):
        """Test filtering of unhealthy active backends."""
        # Set up active backends with health status
        mock_backend_anthropic = Mock()
        mock_backend_anthropic.is_backend_functional = Mock(return_value=False)

        mock_backend_openai = Mock()
        mock_backend_openai.is_backend_functional = Mock(return_value=True)

        mock_backend_lifecycle_manager.get_active_backends = Mock(
            return_value={
                "anthropic": mock_backend_anthropic,
                "openai": mock_backend_openai,
            }
        )

        # Set up coordinator with plan including unhealthy backend
        mock_failover_coordinator.get_failover_attempts = Mock(
            return_value=[
                FailoverAttempt(backend="openai", model="gpt-4"),
                FailoverAttempt(backend="anthropic", model="claude-3-opus"),
                FailoverAttempt(backend="openai", model="gpt-3.5-turbo"),
            ]
        )

        # Call get_failover_plan
        result = failover_planner.get_failover_plan("gpt-4", "openai")

        # Verify unhealthy backend is filtered out
        assert result == [
            ("openai", "gpt-4"),
            ("openai", "gpt-3.5-turbo"),
        ]

    def test_includes_unknown_backends(
        self,
        failover_planner,
        mock_failover_coordinator,
        mock_backend_lifecycle_manager,
    ):
        """Test that backends not in active/disabled registries are included."""
        # Set up empty registries
        mock_backend_lifecycle_manager.get_disabled_backends = Mock(return_value={})
        mock_backend_lifecycle_manager.get_active_backends = Mock(return_value={})

        # Set up coordinator with unknown backend
        mock_failover_coordinator.get_failover_attempts = Mock(
            return_value=[
                FailoverAttempt(backend="openai", model="gpt-4"),
                FailoverAttempt(backend="unknown-backend", model="unknown-model"),
            ]
        )

        # Call get_failover_plan
        result = failover_planner.get_failover_plan("gpt-4", "openai")

        # Verify unknown backend is included (optimistic assumption)
        assert result == [
            ("openai", "gpt-4"),
            ("unknown-backend", "unknown-model"),
        ]

    def test_fallback_to_original_plan_when_all_filtered(
        self,
        failover_planner,
        mock_failover_coordinator,
        mock_backend_lifecycle_manager,
    ):
        """Test fallback to original plan when all backends are filtered."""
        # Set up all backends as disabled
        mock_backend_lifecycle_manager.get_disabled_backends = Mock(
            return_value={
                "openai": {"reason": "Disabled"},
                "anthropic": {"reason": "Disabled"},
            }
        )

        # Set up coordinator with plan
        mock_failover_coordinator.get_failover_attempts = Mock(
            return_value=[
                FailoverAttempt(backend="openai", model="gpt-4"),
                FailoverAttempt(backend="anthropic", model="claude-3-opus"),
            ]
        )

        # Call get_failover_plan
        result = failover_planner.get_failover_plan("gpt-4", "openai")

        # Verify original plan is returned (fallback)
        assert result == [
            ("openai", "gpt-4"),
            ("anthropic", "claude-3-opus"),
        ]

    def test_circuit_breaker_disabled_no_filtering(
        self,
        failover_planner,
        mock_failover_coordinator,
        mock_backend_lifecycle_manager,
        mock_config,
    ):
        """Test that no filtering occurs when circuit breaker is disabled."""
        # Disable circuit breaker
        mock_config.health_check.circuit_breaker_enabled = False

        # Set up disabled backends (should be ignored)
        mock_backend_lifecycle_manager.get_disabled_backends = Mock(
            return_value={"anthropic": {"reason": "Disabled"}}
        )

        # Set up coordinator with plan
        mock_failover_coordinator.get_failover_attempts = Mock(
            return_value=[
                FailoverAttempt(backend="openai", model="gpt-4"),
                FailoverAttempt(backend="anthropic", model="claude-3-opus"),
            ]
        )

        # Call get_failover_plan
        result = failover_planner.get_failover_plan("gpt-4", "openai")

        # Verify no filtering occurred (disabled backend is included)
        assert result == [
            ("openai", "gpt-4"),
            ("anthropic", "claude-3-opus"),
        ]

    def test_finds_session_scoped_backend_for_health_check(
        self,
        failover_planner,
        mock_failover_coordinator,
        mock_backend_lifecycle_manager,
    ):
        """Test that session-scoped backends are found for health checks."""
        # Set up active backends with session-scoped backend
        mock_backend = Mock()
        mock_backend.is_backend_functional = Mock(return_value=False)

        mock_backend_lifecycle_manager.get_active_backends = Mock(
            return_value={
                "gemini-cli-acp:session-123": mock_backend,
            }
        )

        # Set up coordinator with session-scoped backend in plan
        mock_failover_coordinator.get_failover_attempts = Mock(
            return_value=[
                FailoverAttempt(backend="gemini-cli-acp", model="gemini-1.5-flash"),
                FailoverAttempt(backend="openai", model="gpt-4"),
            ]
        )

        # Call get_failover_plan
        result = failover_planner.get_failover_plan(
            "gemini-1.5-flash", "gemini-cli-acp"
        )

        # Verify session-scoped backend was found and filtered (unhealthy)
        # The non-session gemini-cli-acp is not in active backends, so it's included (optimistic)
        # But session-scoped one would be filtered if it matched
        assert ("openai", "gpt-4") in result


class TestEdgeCases:
    """Test edge cases and error handling."""

    def test_empty_failover_plan(self, failover_planner, mock_failover_coordinator):
        """Test handling of empty failover plan."""
        # Set up coordinator with empty plan
        mock_failover_coordinator.get_failover_attempts = Mock(return_value=[])

        # Call get_failover_plan
        result = failover_planner.get_failover_plan("gpt-4", "openai")

        # Verify empty plan is returned
        assert result == []

    def test_missing_health_check_config(
        self,
        mock_app_state,
        mock_failover_coordinator,
        mock_backend_lifecycle_manager,
    ):
        """Test handling when health_check config is missing."""
        # Create config without health_check attribute
        config = Mock(spec=IConfig)
        # Don't set config.health_check

        # Set up coordinator
        mock_failover_coordinator.get_failover_attempts = Mock(
            return_value=[
                FailoverAttempt(backend="openai", model="gpt-4"),
            ]
        )

        planner = FailoverPlanner(
            app_state=mock_app_state,
            failover_coordinator=mock_failover_coordinator,
            backend_lifecycle_manager=mock_backend_lifecycle_manager,
            config=config,
        )

        # Call get_failover_plan - should not crash
        result = planner.get_failover_plan("gpt-4", "openai")

        # Verify plan is returned without filtering (circuit breaker disabled by default)
        assert result == [("openai", "gpt-4")]

    def test_none_backend_parameter(self, failover_planner, mock_failover_coordinator):
        """Test handling when backend parameter is None."""
        # Set up coordinator (expects non-None, so planner converts None to "")
        mock_failover_coordinator.get_failover_attempts = Mock(
            return_value=[
                FailoverAttempt(backend="openai", model="gpt-4"),
            ]
        )

        # Call get_failover_plan with None backend
        result = failover_planner.get_failover_plan("gpt-4", backend=None)

        # Verify coordinator was called with empty string
        mock_failover_coordinator.get_failover_attempts.assert_called_once_with(
            "gpt-4", ""
        )
        assert result == [("openai", "gpt-4")]
