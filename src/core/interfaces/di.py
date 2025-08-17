from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Callable
from enum import Enum, auto
from typing import TypeVar

T = TypeVar("T")


class ServiceLifetime(Enum):
    """Defines the lifetime of a service in the container."""

    # A new instance is created each time the service is requested
    TRANSIENT = auto()

    # A single instance is created and reused for the lifetime of the container
    SINGLETON = auto()

    # A single instance is created and reused for the lifetime of a scope
    SCOPED = auto()


class IServiceProvider(ABC):
    """Interface for service provider that resolves services."""

    @abstractmethod
    def get_service(self, service_type: type[T]) -> T | None:
        """Get a service of the given type if registered.

        Args:
            service_type: The type of service to resolve

        Returns:
            An instance of the requested service or None if not found
        """

    @abstractmethod
    def get_required_service(self, service_type: type[T]) -> T:
        """Get a service of the given type, throwing if not found.

        Args:
            service_type: The type of service to resolve

        Returns:
            An instance of the requested service

        Raises:
            KeyError: If the service is not registered
        """

    @abstractmethod
    def create_scope(self) -> IServiceScope:
        """Create a new service scope.

        Returns:
            A new service scope
        """


class IServiceScope(ABC):
    """Interface for a service scope.

    A service scope manages the lifetime of scoped services.
    """

    @property
    @abstractmethod
    def service_provider(self) -> IServiceProvider:
        """Get the service provider for this scope."""

    @abstractmethod
    async def dispose(self) -> None:
        """Dispose of this scope and any scoped services."""


class IServiceCollection(ABC):
    """Interface for service collection used to register services."""

    @abstractmethod
    def add_singleton(
        self,
        service_type: type[T],
        implementation_type: type[T] | None = None,
        implementation_factory: Callable[[IServiceProvider], T] | None = None,
    ) -> IServiceCollection:
        """Register a singleton service.

        Args:
            service_type: The type of service being registered
            implementation_type: The implementation type (if different from service_type)
            implementation_factory: Factory function to create the service

        Returns:
            This service collection for chaining
        """

    @abstractmethod
    def add_singleton_factory(
        self,
        service_type: type[T],
        implementation_factory: Callable[[IServiceProvider], T],
    ) -> IServiceCollection:
        """Register a singleton service with a factory.

        Args:
            service_type: The type of service being registered
            implementation_factory: Factory function to create the service

        Returns:
            This service collection for chaining
        """

    @abstractmethod
    def add_transient(
        self,
        service_type: type[T],
        implementation_type: type[T] | None = None,
        implementation_factory: Callable[[IServiceProvider], T] | None = None,
    ) -> IServiceCollection:
        """Register a transient service.

        Args:
            service_type: The type of service being registered
            implementation_type: The implementation type (if different from service_type)
            implementation_factory: Factory function to create the service

        Returns:
            This service collection for chaining
        """

    @abstractmethod
    def add_scoped(
        self,
        service_type: type[T],
        implementation_type: type[T] | None = None,
        implementation_factory: Callable[[IServiceProvider], T] | None = None,
    ) -> IServiceCollection:
        """Register a scoped service.

        Args:
            service_type: The type of service being registered
            implementation_type: The implementation type (if different from service_type)
            implementation_factory: Factory function to create the service

        Returns:
            This service collection for chaining
        """

    @abstractmethod
    def add_instance(self, service_type: type[T], instance: T) -> IServiceCollection:
        """Register an existing instance as a singleton.

        Args:
            service_type: The type of service being registered
            instance: The instance to register

        Returns:
            This service collection for chaining
        """

    @abstractmethod
    def build_service_provider(self) -> IServiceProvider:
        """Build a service provider with the registered services.

        Returns:
            A new service provider
        """
