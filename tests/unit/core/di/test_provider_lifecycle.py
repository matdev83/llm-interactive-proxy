"""Tests for provider lifecycle module."""

from collections.abc import Iterator
from unittest.mock import patch

import pytest
from src.core.common.exceptions import ServiceResolutionError
from src.core.di.container import ServiceCollection
from src.core.di.services import register_core_services
from src.core.interfaces.di_interface import IServiceProvider
from src.core.services.tool_call_reactor_service import ToolCallReactorService


class TestProviderLifecycle:
    """Tests for provider lifecycle management."""

    @pytest.fixture(autouse=True)
    def setup(self) -> Iterator[None]:
        """Reset provider state before each test."""
        # Import here to avoid circular imports
        from src.core.di import provider_lifecycle

        provider_lifecycle._service_provider = None
        yield
        provider_lifecycle._service_provider = None

    def test_get_service_provider_returns_built_provider(self) -> None:
        """Test that get_service_provider returns a provider without self-healing."""
        from src.core.di import provider_lifecycle

        services = ServiceCollection()
        register_core_services(services)
        provider = services.build_service_provider()

        # Set provider directly
        provider_lifecycle.set_service_provider(provider)

        # Get provider should return the same instance
        retrieved_provider = provider_lifecycle.get_service_provider()
        assert retrieved_provider is provider

    def test_get_service_provider_fails_fast_on_missing_services(self) -> None:
        """Test that missing services fail fast instead of self-healing."""
        from src.core.di import provider_lifecycle

        # Create a minimal provider without ToolCallReactorService
        minimal_services = ServiceCollection()
        minimal_provider = minimal_services.build_service_provider()

        provider_lifecycle.set_service_provider(minimal_provider)

        # Attempting to get a missing service should raise ServiceResolutionError
        with pytest.raises(ServiceResolutionError) as exc_info:
            minimal_provider.get_required_service(ToolCallReactorService)

        # Verify error details
        assert "ToolCallReactorService" in str(exc_info.value)

        # get_service_provider should return the provider as-is (no self-healing)
        retrieved_provider = provider_lifecycle.get_service_provider()
        assert retrieved_provider is minimal_provider

        # Provider should still not have the service
        assert retrieved_provider.get_service(ToolCallReactorService) is None

    def test_get_or_build_service_provider_builds_if_none(self) -> None:
        """Test that get_or_build_service_provider builds provider if none exists."""
        from src.core.di import provider_lifecycle

        # Reset provider
        provider_lifecycle._service_provider = None

        # Build provider (will use get_service_collection internally)
        provider = provider_lifecycle.get_or_build_service_provider()

        assert provider is not None
        assert isinstance(provider, IServiceProvider)

    def test_post_build_hooks_called_after_build(self) -> None:
        """Test that post-build hooks are called after provider build."""
        from src.core.di import provider_lifecycle

        services = ServiceCollection()
        register_core_services(services)
        provider = services.build_service_provider()

        # Call post-build hooks
        with patch(
            "src.core.di.provider_lifecycle._initialize_feature_parity_registry"
        ) as mock_init:
            provider_lifecycle.post_build_hooks(provider)
            mock_init.assert_called_once_with(provider)

    def test_set_service_provider_updates_global(self) -> None:
        """Test that set_service_provider updates the global provider."""
        from src.core.di import provider_lifecycle

        services = ServiceCollection()
        provider = services.build_service_provider()

        provider_lifecycle.set_service_provider(provider)

        assert provider_lifecycle._service_provider is provider

    def test_get_service_provider_with_diagnostics_enabled(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Test that diagnostics are included in errors when enabled."""
        from src.core.di import provider_lifecycle

        monkeypatch.setenv("DI_STRICT_DIAGNOSTICS", "true")

        minimal_services = ServiceCollection()
        minimal_provider = minimal_services.build_service_provider()

        provider_lifecycle.set_service_provider(minimal_provider)

        # Missing service should raise error with diagnostics
        with pytest.raises(ServiceResolutionError) as exc_info:
            minimal_provider.get_required_service(ToolCallReactorService)

        error = exc_info.value
        # When diagnostics enabled, error should have resolution path details
        if hasattr(error, "details"):
            # Diagnostics may include resolution path
            assert error.details is not None
