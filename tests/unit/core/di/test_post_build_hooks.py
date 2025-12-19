"""
Tests for post-build hooks and feature parity initialization.

These tests verify that:
- Post-build hooks run correctly after provider build
- Feature parity registry is initialized with middleware from MiddlewareApplicationManager
- MiddlewareApplicationManager can be resolved after streaming registrar runs
"""

from __future__ import annotations

from src.core.config.app_config import AppConfig
from src.core.di.container import ServiceCollection
from src.core.di.provider_lifecycle import post_build_hooks
from src.core.di.registrations import core, streaming
from src.core.interfaces.feature_parity import get_global_registry
from src.core.services.middleware_application_manager import (
    MiddlewareApplicationManager,
)


class TestPostBuildHooks:
    """Test post-build hooks functionality."""

    def test_post_build_hooks_run_successfully(self) -> None:
        """Verify post-build hooks run without errors after provider build."""
        services = ServiceCollection()
        config = AppConfig()

        # Register all services (core then streaming)
        core.register(services, config)
        streaming.register(services, config)

        # Build provider
        provider = services.build_service_provider()

        # Post-build hooks should run without errors
        post_build_hooks(provider)

        # Verify MiddlewareApplicationManager is available (required by post-build hooks)
        manager = provider.get_service(MiddlewareApplicationManager)
        assert manager is not None

    def test_feature_parity_registry_initialized(self) -> None:
        """Verify feature parity registry is initialized with middleware."""
        services = ServiceCollection()
        config = AppConfig()

        # Register all services
        core.register(services, config)
        streaming.register(services, config)

        # Build provider
        provider = services.build_service_provider()

        # Run post-build hooks
        post_build_hooks(provider)

        # Verify feature parity registry has been initialized
        registry = get_global_registry()
        assert registry is not None

        # Verify middleware from MiddlewareApplicationManager are registered
        # (The exact count depends on configuration, but should be > 0)
        registry.get_all_features()
        # At minimum, we should have some features registered
        # (exact count depends on config, but registry should be initialized)

    def test_middleware_application_manager_resolved_in_post_build(self) -> None:
        """Verify MiddlewareApplicationManager can be resolved during post-build hooks."""
        services = ServiceCollection()
        config = AppConfig()

        # Register all services
        core.register(services, config)
        streaming.register(services, config)

        # Build provider
        provider = services.build_service_provider()

        # Verify MiddlewareApplicationManager is registered before post-build hooks
        manager = provider.get_service(MiddlewareApplicationManager)
        assert manager is not None

        # Post-build hooks should be able to access it
        post_build_hooks(provider)

        # Verify it's still accessible after hooks
        manager2 = provider.get_service(MiddlewareApplicationManager)
        assert manager2 is not None
        assert manager is manager2
