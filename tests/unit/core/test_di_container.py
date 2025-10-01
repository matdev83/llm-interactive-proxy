"""
Tests for the dependency injection container.
"""

import pytest
from src.core.di.container import ServiceCollection
from src.core.interfaces.di_interface import IServiceProvider
from src.core.services.backend_factory import BackendFactory


class ExampleService:
    """A test service for DI testing."""

    def __init__(self) -> None:
        self.value = "test"


class ExampleServiceWithDependency:
    """A test service that depends on another service."""

    def __init__(self, service_provider: IServiceProvider) -> None:
        self.dependency = service_provider.get_required_service(ExampleService)


def test_service_collection_singleton() -> None:
    """Test registering and resolving a singleton service."""
    # Arrange
    services = ServiceCollection()

    # Act
    services.add_singleton(ExampleService)
    provider = services.build_service_provider()
    service1 = provider.get_service(ExampleService)
    service2 = provider.get_service(ExampleService)

    # Assert
    assert service1 is not None
    assert service2 is not None
    assert service1 is service2  # Same instance


def test_service_collection_transient() -> None:
    """Test registering and resolving a transient service."""
    # Arrange
    services = ServiceCollection()

    # Act
    services.add_transient(ExampleService)
    provider = services.build_service_provider()
    service1 = provider.get_service(ExampleService)
    service2 = provider.get_service(ExampleService)

    # Assert
    assert service1 is not None
    assert service2 is not None
    assert service1 is not service2  # Different instances


def test_service_collection_scoped() -> None:
    """Test registering and resolving a scoped service."""
    # Arrange
    services = ServiceCollection()

    # Act
    services.add_scoped(ExampleService)
    provider = services.build_service_provider()

    # First scope
    scope1 = provider.create_scope()
    service1_1 = scope1.service_provider.get_service(ExampleService)
    service1_2 = scope1.service_provider.get_service(ExampleService)

    # Second scope
    scope2 = provider.create_scope()
    service2_1 = scope2.service_provider.get_service(ExampleService)

    # Assert
    assert service1_1 is not None
    assert service1_2 is not None
    assert service2_1 is not None
    assert service1_1 is service1_2  # Same instance within a scope
    assert service1_1 is not service2_1  # Different instances across scopes


def test_service_provider_get_required_service() -> None:
    """Test that get_required_service throws for unregistered services."""
    # Arrange
    provider = ServiceCollection().build_service_provider()

    # Act & Assert
    from src.core.common.exceptions import ServiceResolutionError

    with pytest.raises(ServiceResolutionError):
        provider.get_required_service(ExampleService)


def test_service_factory() -> None:
    """Test registering a service with a factory."""
    # Arrange
    services = ServiceCollection()

    # Act
    services.add_singleton(
        ExampleService, implementation_factory=lambda _: ExampleService()
    )
    provider = services.build_service_provider()
    service = provider.get_service(ExampleService)

    # Assert
    assert service is not None
    assert isinstance(service, ExampleService)


def test_service_with_dependency() -> None:
    """Test a service that depends on another service."""
    # Arrange
    services = ServiceCollection()

    # Act
    services.add_singleton(ExampleService)
    services.add_singleton(
        ExampleServiceWithDependency,
        implementation_factory=lambda provider: ExampleServiceWithDependency(provider),
    )
    provider = services.build_service_provider()
    service = provider.get_service(ExampleServiceWithDependency)

    # Assert
    assert service is not None
    assert service.dependency is not None
    assert isinstance(service.dependency, ExampleService)


def test_register_app_services_resolves_backend_factory() -> None:
    """register_app_services should configure BackendFactory via DI."""

    services = ServiceCollection()

    services.register_app_services()
    provider = services.build_service_provider()

    backend_factory = provider.get_service(BackendFactory)

    assert isinstance(backend_factory, BackendFactory)
