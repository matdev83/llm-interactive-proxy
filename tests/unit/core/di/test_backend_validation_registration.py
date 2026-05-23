"""Tests for backend validation services DI registration."""

from collections.abc import Iterator

import pytest
from src.core.di.container import ServiceCollection
from src.core.di.services import (
    register_core_services,
    set_service_provider,
)
from src.core.interfaces.backend_validator_interface import IBackendValidator
from src.core.interfaces.http_client_manager_interface import IHttpClientManager
from src.core.services.backend_validation_service import BackendValidationService
from src.core.services.validation_http_client_manager import (
    ValidationHttpClientManager,
)


class TestBackendValidationRegistration:
    """Tests for backend validation services DI registration."""

    @pytest.fixture(autouse=True)
    def setup(self) -> Iterator[None]:
        """Reset service provider before/after tests."""
        set_service_provider(None)
        yield
        set_service_provider(None)

    def test_validation_http_client_manager_registration(self) -> None:
        """Verify ValidationHttpClientManager is registered as singleton."""
        services = ServiceCollection()
        register_core_services(services)
        provider = services.build_service_provider()

        # Resolve via concrete type
        manager1 = provider.get_required_service(ValidationHttpClientManager)
        manager2 = provider.get_required_service(ValidationHttpClientManager)
        assert isinstance(manager1, ValidationHttpClientManager)
        assert manager1 is manager2

        # Resolve via interface
        interface_manager1 = provider.get_required_service(IHttpClientManager)  # type: ignore[type-abstract]
        interface_manager2 = provider.get_required_service(IHttpClientManager)  # type: ignore[type-abstract]
        assert isinstance(interface_manager1, ValidationHttpClientManager)
        assert interface_manager1 is interface_manager2
        assert interface_manager1 is manager1

    def test_backend_validation_service_registration(self) -> None:
        """Verify BackendValidationService is registered as singleton."""
        services = ServiceCollection()
        register_core_services(services)
        provider = services.build_service_provider()

        # Resolve via concrete type
        service1 = provider.get_required_service(BackendValidationService)
        service2 = provider.get_required_service(BackendValidationService)
        assert isinstance(service1, BackendValidationService)
        assert service1 is service2

        # Resolve via interface
        interface_service1 = provider.get_required_service(IBackendValidator)  # type: ignore[type-abstract]
        interface_service2 = provider.get_required_service(IBackendValidator)  # type: ignore[type-abstract]
        assert isinstance(interface_service1, BackendValidationService)
        assert interface_service1 is interface_service2
        assert interface_service1 is service1

    def test_backend_validation_service_dependencies(self) -> None:
        """Verify BackendValidationService receives injected dependencies."""
        services = ServiceCollection()
        register_core_services(services)
        provider = services.build_service_provider()

        # Resolve BackendValidationService
        validation_service = provider.get_required_service(IBackendValidator)  # type: ignore[type-abstract]
        assert isinstance(validation_service, BackendValidationService)

        # Check that dependencies were injected
        # Note: We access private attributes here to verify injection
        assert validation_service._backend_factory is not None
        assert isinstance(
            validation_service._http_client_manager, ValidationHttpClientManager
        )
        assert validation_service._backend_registry is not None

    def test_backend_validation_service_fails_fast_without_ibackend_factory(
        self,
    ) -> None:
        """Test that BackendValidationService fails fast if IBackendFactory is missing (Fix 2)."""
        from src.core.common.exceptions import ServiceResolutionError
        from src.core.di.registrations._backend.validation import (
            register_backend_validation_services,
        )
        from src.core.services.backend_registry import BackendRegistry

        services = ServiceCollection()
        # Register only validation services and minimal dependencies (BackendRegistry)
        # but NOT IBackendFactory - this simulates missing dependency scenario
        services.add_singleton(BackendRegistry)
        register_backend_validation_services(services)

        provider = services.build_service_provider()

        # Attempting to resolve BackendValidationService should fail fast
        # because IBackendFactory is not registered (no fallback to BackendFactory)
        with pytest.raises(ServiceResolutionError) as exc_info:
            provider.get_required_service(IBackendValidator)  # type: ignore[type-abstract]

        # Verify error message indicates missing IBackendFactory
        error_message = str(exc_info.value).lower()
        assert "ibackendfactory" in error_message or "backend" in error_message
