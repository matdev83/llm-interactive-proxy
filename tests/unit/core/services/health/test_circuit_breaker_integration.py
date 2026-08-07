"""Tests for circuit breaker integration with backend routing.

This module verifies that unhealthy backends are properly filtered
from the failover plan when circuit breaker is enabled.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

import pytest
from src.connectors.base import LLMBackend
from src.core.config.app_config import AppConfig
from src.core.domain.configuration.health_check_config import HealthCheckConfig


class MockBackend(LLMBackend):
    """Mock backend for testing."""

    backend_type = "mock"

    def __init__(self, config: AppConfig | None = None) -> None:
        if config is None:
            config = MagicMock(spec=AppConfig)
        super().__init__(config=config, response_processor=None)

    async def chat_completions(
        self,
        messages: list[dict[str, Any]],
        model: str,
        stream: bool = False,
        **kwargs: Any,
    ) -> Any:
        return {"response": "mock"}

    async def initialize(self, **kwargs: Any) -> None:
        pass

    async def get_available_models(self) -> list[str]:
        return ["mock-model"]


class TestCircuitBreakerIntegration:
    """Tests for circuit breaker filtering in backend routing."""

    def test_healthy_backend_is_functional(self) -> None:
        """Test that a healthy backend returns True from is_backend_functional."""
        backend = MockBackend()
        backend.api_url = "https://api.example.com/v1"

        # Initially healthy
        assert backend.is_endpoint_healthy is True
        assert backend.is_backend_functional() is True

    def test_unhealthy_backend_is_not_functional(self) -> None:
        """Test that an unhealthy backend returns False from is_backend_functional."""
        backend = MockBackend()
        backend.api_url = "https://api.example.com/v1"

        # Mark as unhealthy
        backend._endpoint_healthy = False

        assert backend.is_endpoint_healthy is False
        assert backend.is_backend_functional() is False

    @pytest.mark.asyncio
    async def test_on_endpoint_unhealthy_updates_state(self) -> None:
        """Test that on_endpoint_unhealthy properly updates backend state."""
        backend = MockBackend()
        backend.api_url = "https://api.example.com/v1"

        assert backend.is_endpoint_healthy is True

        # Receive unhealthy notification
        await backend.on_endpoint_unhealthy(
            "https://api.example.com/v1",
            "ping failed: timeout",
        )

        assert backend.is_endpoint_healthy is False
        assert backend.is_backend_functional() is False

    @pytest.mark.asyncio
    async def test_on_endpoint_healthy_restores_state(self) -> None:
        """Test that on_endpoint_healthy restores backend state."""
        backend = MockBackend()
        backend.api_url = "https://api.example.com/v1"
        backend._endpoint_healthy = False

        assert backend.is_backend_functional() is False

        # Receive healthy notification
        await backend.on_endpoint_healthy("https://api.example.com/v1")

        assert backend.is_endpoint_healthy is True
        assert backend.is_backend_functional() is True

    @pytest.mark.asyncio
    async def test_notification_ignores_wrong_url(self) -> None:
        """Test that notifications for other URLs are ignored."""
        backend = MockBackend()
        backend.api_url = "https://api.example.com/v1"

        # Receive notification for a different URL
        await backend.on_endpoint_unhealthy(
            "https://api.other.com/v1",
            "ping failed",
        )

        # State should not change
        assert backend.is_endpoint_healthy is True
        assert backend.is_backend_functional() is True

    def test_filter_unhealthy_backends_excludes_unhealthy(self) -> None:
        """Test that _filter_unhealthy_backends excludes unhealthy backends."""
        from src.core.services.backend_service import BackendService

        # Create a mock config with circuit breaker enabled
        config = MagicMock(spec=AppConfig)
        config.health_check = HealthCheckConfig(circuit_breaker_enabled=True)

        # Create mock backends
        healthy_backend = MockBackend(config)
        healthy_backend.api_url = "https://api.healthy.com/v1"
        healthy_backend._endpoint_healthy = True

        unhealthy_backend = MockBackend(config)
        unhealthy_backend.api_url = "https://api.unhealthy.com/v1"
        unhealthy_backend._endpoint_healthy = False

        # Create BackendService with mocked dependencies
        service = BackendService.__new__(BackendService)
        service._config = config

        # Mock lifecycle manager
        service._backend_lifecycle_manager = MagicMock()
        service._backend_lifecycle_manager.get_disabled_backends.return_value = {}

        # Mock get_active_backends returning a dict
        active_backends = {"healthy": healthy_backend, "unhealthy": unhealthy_backend}
        service._backend_lifecycle_manager.get_active_backends.return_value = (
            active_backends
        )

        # Mock failover_planner with filter_unhealthy_backends method
        mock_failover_planner = MagicMock()

        def filter_unhealthy(plan):
            # Simple implementation that filters unhealthy backends
            if not config.health_check.circuit_breaker_enabled:
                return plan
            filtered = []
            for backend_name, model in plan:
                if backend_name in active_backends:
                    backend = active_backends[backend_name]
                    if backend.is_backend_functional():
                        filtered.append((backend_name, model))
                else:
                    # Unknown backend - include it
                    filtered.append((backend_name, model))
            # If all filtered out, return original plan
            return filtered if filtered else plan

        mock_failover_planner.filter_unhealthy_backends = filter_unhealthy
        service._failover_planner = mock_failover_planner

        # Test filtering
        plan = [("healthy", "model-a"), ("unhealthy", "model-b")]
        filtered = service._filter_unhealthy_backends(plan)

        assert len(filtered) == 1
        assert filtered[0] == ("healthy", "model-a")

    def test_filter_unhealthy_backends_disabled_returns_all(self) -> None:
        """Test that circuit breaker disabled returns all backends."""
        from src.core.services.backend_service import BackendService

        # Create a mock config with circuit breaker DISABLED
        config = MagicMock(spec=AppConfig)
        config.health_check = HealthCheckConfig(circuit_breaker_enabled=False)

        # Create mock backends
        healthy_backend = MockBackend(config)
        unhealthy_backend = MockBackend(config)
        unhealthy_backend._endpoint_healthy = False

        # Create BackendService with mocked dependencies
        service = BackendService.__new__(BackendService)
        service._config = config

        service._backend_lifecycle_manager = MagicMock()
        service._backend_lifecycle_manager.get_disabled_backends.return_value = {}

        # Mock get_active_backends returning a dict
        active_backends = {"healthy": healthy_backend, "unhealthy": unhealthy_backend}
        service._backend_lifecycle_manager.get_active_backends.return_value = (
            active_backends
        )

        # Mock failover_planner with filter_unhealthy_backends method
        mock_failover_planner = MagicMock()

        def filter_unhealthy(plan):
            # Simple implementation that filters unhealthy backends
            if not config.health_check.circuit_breaker_enabled:
                return plan
            filtered = []
            for backend_name, model in plan:
                if backend_name in active_backends:
                    backend = active_backends[backend_name]
                    if backend.is_backend_functional():
                        filtered.append((backend_name, model))
                else:
                    # Unknown backend - include it
                    filtered.append((backend_name, model))
            # If all filtered out, return original plan
            return filtered if filtered else plan

        mock_failover_planner.filter_unhealthy_backends = filter_unhealthy
        service._failover_planner = mock_failover_planner

        # Test filtering - should return all since circuit breaker is disabled
        plan = [("healthy", "model-a"), ("unhealthy", "model-b")]
        filtered = service._filter_unhealthy_backends(plan)

        assert len(filtered) == 2
        assert ("unhealthy", "model-b") in filtered

    def test_filter_all_unhealthy_falls_back_to_original(self) -> None:
        """Test that if all backends are unhealthy, original plan is returned."""
        from src.core.services.backend_service import BackendService

        # Create a mock config with circuit breaker enabled
        config = MagicMock(spec=AppConfig)
        config.health_check = HealthCheckConfig(circuit_breaker_enabled=True)

        # Create all unhealthy backends
        unhealthy1 = MockBackend(config)
        unhealthy1._endpoint_healthy = False
        unhealthy2 = MockBackend(config)
        unhealthy2._endpoint_healthy = False

        # Create BackendService with mocked dependencies
        service = BackendService.__new__(BackendService)
        service._config = config

        service._backend_lifecycle_manager = MagicMock()
        service._backend_lifecycle_manager.get_disabled_backends.return_value = {}

        # Mock get_active_backends returning a dict
        active_backends = {"unhealthy1": unhealthy1, "unhealthy2": unhealthy2}
        service._backend_lifecycle_manager.get_active_backends.return_value = (
            active_backends
        )

        # Mock failover_planner with filter_unhealthy_backends method
        mock_failover_planner = MagicMock()

        def filter_unhealthy(plan):
            # Simple implementation that filters unhealthy backends
            if not config.health_check.circuit_breaker_enabled:
                return plan
            filtered = []
            for backend_name, model in plan:
                if backend_name in active_backends:
                    backend = active_backends[backend_name]
                    if backend.is_backend_functional():
                        filtered.append((backend_name, model))
                else:
                    # Unknown backend - include it
                    filtered.append((backend_name, model))
            # If all filtered out, return original plan
            return filtered if filtered else plan

        mock_failover_planner.filter_unhealthy_backends = filter_unhealthy
        service._failover_planner = mock_failover_planner

        # Test filtering - should fall back to original plan
        plan = [("unhealthy1", "model-a"), ("unhealthy2", "model-b")]
        filtered = service._filter_unhealthy_backends(plan)

        # Should return original plan to prevent complete failure
        assert len(filtered) == 2
        assert filtered == plan

    def test_unknown_backend_included_in_plan(self) -> None:
        """Test that backends not yet created are included in the plan."""
        from src.core.services.backend_service import BackendService

        # Create a mock config with circuit breaker enabled
        config = MagicMock(spec=AppConfig)
        config.health_check = HealthCheckConfig(circuit_breaker_enabled=True)

        # Create BackendService with no backends
        service = BackendService.__new__(BackendService)
        service._config = config

        service._backend_lifecycle_manager = MagicMock()
        service._backend_lifecycle_manager.get_disabled_backends.return_value = {}
        service._backend_lifecycle_manager.get_active_backends.return_value = {}

        # Mock failover_planner with filter_unhealthy_backends method
        mock_failover_planner = MagicMock()

        def filter_unhealthy(plan):
            # Simple implementation that filters unhealthy backends
            if not config.health_check.circuit_breaker_enabled:
                return plan
            filtered = []
            active_backends = service._backend_lifecycle_manager.get_active_backends()
            for backend_name, model in plan:
                if backend_name in active_backends:
                    backend = active_backends[backend_name]
                    if backend.is_backend_functional():
                        filtered.append((backend_name, model))
                else:
                    # Unknown backend - include it
                    filtered.append((backend_name, model))
            # If all filtered out, return original plan
            return filtered if filtered else plan

        mock_failover_planner.filter_unhealthy_backends = filter_unhealthy
        service._failover_planner = mock_failover_planner

        # Test filtering - unknown backends should be included
        plan = [("unknown", "model-a")]
        filtered = service._filter_unhealthy_backends(plan)

        assert len(filtered) == 1
        assert filtered[0] == ("unknown", "model-a")

    def test_get_validation_errors_includes_health(self) -> None:
        """Test that get_validation_errors includes endpoint health status."""
        backend = MockBackend()
        backend._endpoint_healthy = False
        backend._last_health_change_reason = "HTTP check failed"

        errors = backend.get_validation_errors()

        assert any("unhealthy" in e.lower() for e in errors)
        assert any("HTTP check failed" in e for e in errors)
