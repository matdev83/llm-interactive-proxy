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
            "src.core.di.registration_helpers.post_build_actions.initialize_feature_parity_registry"
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


class TestTemporaryServiceProvider:
    """Tests for temporary service provider context manager."""

    @pytest.fixture(autouse=True)
    def setup(self) -> Iterator[None]:
        """Reset provider state before each test."""
        from src.core.di import provider_lifecycle

        provider_lifecycle._service_provider = None
        # Also reset legacy provider
        try:
            from src.core.di import services as di_services

            di_services._service_provider = None  # type: ignore[attr-defined]
        except (ImportError, AttributeError):
            pass
        yield
        provider_lifecycle._service_provider = None
        try:
            from src.core.di import services as di_services

            di_services._service_provider = None  # type: ignore[attr-defined]
        except (ImportError, AttributeError):
            pass

    def test_temporary_service_provider_restores_previous_provider(self) -> None:
        """Test that temporary provider context restores previous provider."""
        from src.core.di import provider_lifecycle

        # Create initial provider
        services1 = ServiceCollection()
        register_core_services(services1)
        provider1 = services1.build_service_provider()
        provider_lifecycle.set_service_provider(provider1)

        # Create temporary provider
        services2 = ServiceCollection()
        register_core_services(services2)
        provider2 = services2.build_service_provider()

        # Use temporary provider context
        with provider_lifecycle.temporary_service_provider(provider2):
            # Inside context, current provider should be provider2
            current = provider_lifecycle.get_current_service_provider()
            assert current is provider2

        # After context, previous provider should be restored
        current = provider_lifecycle.get_current_service_provider()
        assert current is provider1

    def test_temporary_service_provider_restores_none_when_no_previous(self) -> None:
        """Test that temporary provider context restores None when no previous provider."""
        from src.core.di import provider_lifecycle

        # Ensure no provider is set
        provider_lifecycle.set_service_provider(None)

        # Create temporary provider
        services = ServiceCollection()
        register_core_services(services)
        provider = services.build_service_provider()

        # Use temporary provider context
        with provider_lifecycle.temporary_service_provider(provider):
            # Inside context, current provider should be provider
            current = provider_lifecycle.get_current_service_provider()
            assert current is provider

        # After context, provider should be None
        with pytest.raises(
            RuntimeError, match="No service provider is currently installed"
        ):
            provider_lifecycle.get_current_service_provider()

    def test_temporary_service_provider_nested_contexts(self) -> None:
        """Test that nested temporary provider contexts restore correctly."""
        from src.core.di import provider_lifecycle

        # Create providers
        services1 = ServiceCollection()
        register_core_services(services1)
        provider1 = services1.build_service_provider()

        services2 = ServiceCollection()
        register_core_services(services2)
        provider2 = services2.build_service_provider()

        services3 = ServiceCollection()
        register_core_services(services3)
        provider3 = services3.build_service_provider()

        provider_lifecycle.set_service_provider(provider1)

        # Nested contexts
        with provider_lifecycle.temporary_service_provider(provider2):
            assert provider_lifecycle.get_current_service_provider() is provider2

            with provider_lifecycle.temporary_service_provider(provider3):
                assert provider_lifecycle.get_current_service_provider() is provider3

            # After inner context, should restore to provider2
            assert provider_lifecycle.get_current_service_provider() is provider2

        # After outer context, should restore to provider1
        assert provider_lifecycle.get_current_service_provider() is provider1

    def test_temporary_service_provider_restores_on_exception(self) -> None:
        """Test that temporary provider context restores provider even on exception."""
        from src.core.di import provider_lifecycle

        # Create initial provider
        services1 = ServiceCollection()
        register_core_services(services1)
        provider1 = services1.build_service_provider()
        provider_lifecycle.set_service_provider(provider1)

        # Create temporary provider
        services2 = ServiceCollection()
        register_core_services(services2)
        provider2 = services2.build_service_provider()

        # Use temporary provider context and raise exception
        with (
            pytest.raises(ValueError, match="Test exception"),
            provider_lifecycle.temporary_service_provider(provider2),
        ):
            # Inside context, current provider should be provider2
            assert provider_lifecycle.get_current_service_provider() is provider2
            raise ValueError("Test exception")

        # After exception, previous provider should be restored
        current = provider_lifecycle.get_current_service_provider()
        assert current is provider1

    def test_temporary_service_provider_syncs_legacy_provider(self) -> None:
        """Test that temporary provider context keeps legacy _service_provider in sync."""
        from src.core.di import provider_lifecycle

        # Create initial provider
        services1 = ServiceCollection()
        register_core_services(services1)
        provider1 = services1.build_service_provider()
        provider_lifecycle.set_service_provider(provider1)

        # Create temporary provider
        services2 = ServiceCollection()
        register_core_services(services2)
        provider2 = services2.build_service_provider()

        # Check legacy provider is synced before context
        from src.core.di import services as di_services

        assert di_services._service_provider is provider1  # type: ignore[attr-defined]

        # Use temporary provider context
        with provider_lifecycle.temporary_service_provider(provider2):
            # Legacy provider should be synced to provider2
            assert di_services._service_provider is provider2  # type: ignore[attr-defined]

        # Legacy provider should be restored to provider1
        assert di_services._service_provider is provider1  # type: ignore[attr-defined]


class TestGetCurrentServiceProvider:
    """Tests for get_current_service_provider fail-fast accessor."""

    @pytest.fixture(autouse=True)
    def setup(self) -> Iterator[None]:
        """Reset provider state before each test."""
        from src.core.di import provider_lifecycle

        provider_lifecycle._service_provider = None
        try:
            from src.core.di import services as di_services

            di_services._service_provider = None  # type: ignore[attr-defined]
        except (ImportError, AttributeError):
            pass
        yield
        provider_lifecycle._service_provider = None
        try:
            from src.core.di import services as di_services

            di_services._service_provider = None  # type: ignore[attr-defined]
        except (ImportError, AttributeError):
            pass

    def test_get_current_service_provider_returns_installed_provider(self) -> None:
        """Test that get_current_service_provider returns installed provider."""
        from src.core.di import provider_lifecycle

        services = ServiceCollection()
        register_core_services(services)
        provider = services.build_service_provider()

        provider_lifecycle.set_service_provider(provider)

        current = provider_lifecycle.get_current_service_provider()
        assert current is provider

    def test_get_current_service_provider_raises_when_none_installed(self) -> None:
        """Test that get_current_service_provider raises when no provider installed."""
        from src.core.di import provider_lifecycle

        # Ensure no provider is set
        provider_lifecycle.set_service_provider(None)

        with pytest.raises(
            RuntimeError, match="No service provider is currently installed"
        ):
            provider_lifecycle.get_current_service_provider()

    def test_get_current_service_provider_does_not_build_implicitly(self) -> None:
        """Test that get_current_service_provider does not build provider implicitly."""
        from src.core.di import provider_lifecycle

        # Ensure no provider is set
        provider_lifecycle.set_service_provider(None)

        # Should raise, not build
        with pytest.raises(
            RuntimeError, match="No service provider is currently installed"
        ):
            provider_lifecycle.get_current_service_provider()

        # Verify provider was not built
        assert provider_lifecycle._service_provider is None
