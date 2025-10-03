from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Callable
from enum import Enum, auto
from typing import TypeVar

T = TypeVar("T")


class ServiceLifetime(Enum):
    """Defines the lifetime of a service in the container."""

    TRANSIENT = auto()
    SINGLETON = auto()
    SCOPED = auto()


class IServiceProvider(ABC):
    @abstractmethod
    def get_service(self, service_type: type[T]) -> T | None:
        pass

    @abstractmethod
    def get_required_service(self, service_type: type[T]) -> T:
        pass

    def get_required_service_or_default(
        self, service_type: type[T], default_factory: Callable[[], T]
    ) -> T:
        """Get a service of the given type, using a default factory if not found.

        This is a default implementation that can be overridden for more efficient behavior.

        Args:
            service_type: The type of service to get
            default_factory: Factory function to create a default instance if not registered

        Returns:
            The registered service or a default instance
        """
        service = self.get_service(service_type)
        if service is None:
            return default_factory()
        return service

    @abstractmethod
    def create_scope(self) -> IServiceScope:
        pass


class IServiceScope(ABC):
    @property
    @abstractmethod
    def service_provider(self) -> IServiceProvider:
        pass

    @abstractmethod
    async def dispose(self) -> None:
        pass


class IServiceCollection(ABC):
    @abstractmethod
    def add_singleton(
        self,
        service_type: type[T],
        implementation_type: type | None = None,
        implementation_factory: Callable[[IServiceProvider], T] | None = None,
    ) -> IServiceCollection:
        pass

    @abstractmethod
    def add_singleton_factory(
        self,
        service_type: type[T],
        implementation_factory: Callable[[IServiceProvider], T],
    ) -> IServiceCollection:
        pass

    @abstractmethod
    def add_transient(
        self,
        service_type: type[T],
        implementation_type: type | None = None,
        implementation_factory: Callable[[IServiceProvider], T] | None = None,
    ) -> IServiceCollection:
        pass

    @abstractmethod
    def add_scoped(
        self,
        service_type: type[T],
        implementation_type: type | None = None,
        implementation_factory: Callable[[IServiceProvider], T] | None = None,
    ) -> IServiceCollection:
        pass

    @abstractmethod
    def add_instance(self, service_type: type[T], instance: T) -> IServiceCollection:
        pass

    @abstractmethod
    def build_service_provider(self) -> IServiceProvider:
        pass
