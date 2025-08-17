from __future__ import annotations

import inspect
from collections.abc import Callable
from typing import Any, TypeVar

from src.core.interfaces.di import (
    IServiceCollection,
    IServiceProvider,
    IServiceScope,
    ServiceLifetime,
)

T = TypeVar("T")


class ServiceDescriptor:
    """Describes a service registration in the container."""

    def __init__(
        self,
        service_type: type,
        lifetime: ServiceLifetime,
        implementation_type: type | None = None,
        implementation_factory: Callable[[IServiceProvider], Any] | None = None,
        instance: Any | None = None,
    ):
        """Initialize a service descriptor.

        Args:
            service_type: The type of service being registered
            lifetime: The lifetime of the service
            implementation_type: The implementation type (if different from service_type)
            implementation_factory: Factory function to create the service
            instance: An existing instance (for singleton services)
        """
        self.service_type = service_type
        self.lifetime = lifetime
        self.implementation_type = implementation_type or service_type
        self.implementation_factory = implementation_factory
        self.instance = instance

        # Validate that at least one implementation method is provided
        if not implementation_type and not implementation_factory and instance is None:
            raise ValueError(
                "Either implementation_type, implementation_factory, or instance must be provided"
            )


class ServiceScope(IServiceScope):
    """Implementation of a service scope."""

    def __init__(
        self, provider: ServiceProvider, parent_scope: ServiceScope | None = None
    ):
        """Initialize a service scope.

        Args:
            provider: The service provider that created this scope
            parent_scope: The parent scope (if this is a nested scope)
        """
        self._provider = ScopedServiceProvider(provider, self)
        self._parent_scope = parent_scope
        self._instances: dict[type, Any] = {}
        self._disposed = False

    @property
    def service_provider(self) -> IServiceProvider:
        """Get the service provider for this scope."""
        if self._disposed:
            raise RuntimeError("This scope has been disposed")
        return self._provider

    async def dispose(self) -> None:
        """Dispose of this scope and any scoped services."""
        if self._disposed:
            return

        self._disposed = True

        # Dispose any instances that implement disposable pattern
        for instance in self._instances.values():
            if hasattr(instance, "__aenter__") and hasattr(instance, "__aexit__"):
                await instance.__aexit__(None, None, None)
            elif hasattr(instance, "dispose") and callable(instance.dispose):
                await instance.dispose()

        self._instances.clear()


class ScopedServiceProvider(IServiceProvider):
    """A service provider for a specific scope."""

    def __init__(self, root_provider: ServiceProvider, scope: ServiceScope):
        """Initialize a scoped service provider.

        Args:
            root_provider: The root service provider
            scope: The scope this provider belongs to
        """
        self._root = root_provider
        self._scope = scope

    def get_service(self, service_type: type[T]) -> T | None:
        """Get a service of the given type if registered."""
        return self._root._get_service(service_type, self._scope)

    def get_required_service(self, service_type: type[T]) -> T:
        """Get a service of the given type, throwing if not found."""
        service = self.get_service(service_type)
        if service is None:
            # Handle Mock objects which don't have __name__
            type_name = getattr(service_type, "__name__", str(service_type))
            raise KeyError(f"No service registered for {type_name}")
        return service

    def create_scope(self) -> IServiceScope:
        """Create a new nested service scope."""
        return ServiceScope(self._root, self._scope)


class ServiceProvider(IServiceProvider):
    """Implementation of a service provider."""

    def __init__(self, descriptors: dict[type, ServiceDescriptor]):
        """Initialize a service provider.

        Args:
            descriptors: The service descriptors to use for resolution
        """
        self._descriptors = descriptors
        self._singleton_instances: dict[type, Any] = {}

    def get_service(self, service_type: type[T]) -> T | None:
        """Get a service of the given type if registered."""
        return self._get_service(service_type, None)

    def get_required_service(self, service_type: type[T]) -> T:
        """Get a service of the given type, throwing if not found."""
        service = self.get_service(service_type)
        if service is None:
            # Handle Mock objects which don't have __name__
            type_name = getattr(service_type, "__name__", str(service_type))
            raise KeyError(f"No service registered for {type_name}")
        return service

    def create_scope(self) -> IServiceScope:
        """Create a new service scope."""
        return ServiceScope(self)

    def _get_service(
        self, service_type: type[T], scope: ServiceScope | None
    ) -> T | None:
        """Internal method to get a service of the given type."""
        descriptor = self._descriptors.get(service_type)
        if descriptor is None:
            return None

        # Check if it's a singleton with existing instance
        if descriptor.instance is not None:
            return descriptor.instance  # type: ignore[no-any-return]

        # Handle based on lifetime
        if descriptor.lifetime == ServiceLifetime.SINGLETON:
            # Check for cached singleton instance
            if service_type in self._singleton_instances:
                return self._singleton_instances[service_type]  # type: ignore[no-any-return]

            # Create and cache singleton instance
            instance = self._create_instance(descriptor, scope)  # type: ignore[no-any-return]
            self._singleton_instances[service_type] = instance
            return instance  # type: ignore[no-any-return]

        elif descriptor.lifetime == ServiceLifetime.SCOPED:
            if scope is None:
                # Handle Mock objects which don't have __name__
                type_name = getattr(service_type, "__name__", str(service_type))
                raise RuntimeError(
                    f"Cannot resolve scoped service {type_name} from root provider"
                )

            # Check for cached scoped instance
            if service_type in scope._instances:
                return scope._instances[service_type]  # type: ignore[no-any-return]

            # Create and cache scoped instance
            instance = self._create_instance(descriptor, scope)  # type: ignore[no-any-return]
            scope._instances[service_type] = instance
            return instance  # type: ignore[no-any-return]

        else:  # TRANSIENT
            return self._create_instance(descriptor, scope)  # type: ignore[no-any-return]

    def _create_instance(
        self, descriptor: ServiceDescriptor, scope: ServiceScope | None
    ) -> Any:
        """Create an instance of a service."""
        # Use factory if provided
        if descriptor.implementation_factory:
            provider = scope.service_provider if scope else self
            return descriptor.implementation_factory(provider)

        # Otherwise, create instance of implementation type
        impl_type = descriptor.implementation_type
        if impl_type is None:
            raise RuntimeError("Implementation type is None and no factory provided")

        # Check if constructor needs service provider
        try:
            signature = inspect.signature(impl_type)
            has_provider_param = any(
                param.name == "service_provider"
                and param.annotation == IServiceProvider
                for param in signature.parameters.values()
            )
        except (ValueError, TypeError):
            has_provider_param = False

        if has_provider_param:
            provider = scope.service_provider if scope else self
            return impl_type(service_provider=provider)
        else:
            return impl_type()


class ServiceCollection(IServiceCollection):
    """Implementation of a service collection."""

    def __init__(self) -> None:
        """Initialize a service collection."""
        self._descriptors: dict[type, ServiceDescriptor] = {}

    def add_singleton(
        self,
        service_type: type[T],
        implementation_type: type | None = None,
        implementation_factory: Callable[[IServiceProvider], T] | None = None,
    ) -> IServiceCollection:
        """Register a singleton service."""
        # If only service_type is provided, use it as the implementation type
        if implementation_type is None and implementation_factory is None:
            implementation_type = service_type

        self._descriptors[service_type] = ServiceDescriptor(
            service_type=service_type,
            lifetime=ServiceLifetime.SINGLETON,
            implementation_type=implementation_type,
            implementation_factory=implementation_factory,
        )
        return self

    def add_singleton_factory(
        self,
        service_type: type[T],
        implementation_factory: Callable[[IServiceProvider], T],
    ) -> IServiceCollection:
        """Register a singleton service with a factory."""
        return self.add_singleton(
            service_type, implementation_factory=implementation_factory
        )

    def add_transient(
        self,
        service_type: type[T],
        implementation_type: type | None = None,
        implementation_factory: Callable[[IServiceProvider], T] | None = None,
    ) -> IServiceCollection:
        """Register a transient service."""
        # If only service_type is provided, use it as the implementation type
        if implementation_type is None and implementation_factory is None:
            implementation_type = service_type

        self._descriptors[service_type] = ServiceDescriptor(
            service_type=service_type,
            lifetime=ServiceLifetime.TRANSIENT,
            implementation_type=implementation_type,
            implementation_factory=implementation_factory,
        )
        return self

    def add_scoped(
        self,
        service_type: type[T],
        implementation_type: type | None = None,
        implementation_factory: Callable[[IServiceProvider], T] | None = None,
    ) -> IServiceCollection:
        """Register a scoped service."""
        # If only service_type is provided, use it as the implementation type
        if implementation_type is None and implementation_factory is None:
            implementation_type = service_type

        self._descriptors[service_type] = ServiceDescriptor(
            service_type=service_type,
            lifetime=ServiceLifetime.SCOPED,
            implementation_type=implementation_type,
            implementation_factory=implementation_factory,
        )
        return self

    def add_instance(self, service_type: type[T], instance: T) -> IServiceCollection:
        """Register an existing instance as a singleton."""
        self._descriptors[service_type] = ServiceDescriptor(
            service_type=service_type,
            lifetime=ServiceLifetime.SINGLETON,
            instance=instance,
        )
        return self

    def build_service_provider(self) -> IServiceProvider:
        """Build a service provider with the registered services."""
        return ServiceProvider(self._descriptors.copy())

    def register_app_services(self) -> None:
        """Register all application services.

        This is a placeholder method to satisfy the interface requirement.
        Actual service registration is done in the application factory.
        """

    def register_singleton(
        self,
        service_type: type[T],
        implementation_type: type[T] | None = None,
        implementation_factory: Callable[[IServiceProvider], T] | None = None,
    ) -> IServiceCollection:
        """Alias for add_singleton to maintain compatibility."""
        return self.add_singleton(
            service_type, implementation_type, implementation_factory
        )

    def register_transient(
        self,
        service_type: type[T],
        implementation_type: type[T] | None = None,
        implementation_factory: Callable[[IServiceProvider], T] | None = None,
    ) -> IServiceCollection:
        """Alias for add_transient to maintain compatibility."""
        return self.add_transient(
            service_type, implementation_type, implementation_factory
        )

    def register_scoped(
        self,
        service_type: type[T],
        implementation_type: type[T] | None = None,
        implementation_factory: Callable[[IServiceProvider], T] | None = None,
    ) -> IServiceCollection:
        """Alias for add_scoped to maintain compatibility."""
        return self.add_scoped(
            service_type, implementation_type, implementation_factory
        )
