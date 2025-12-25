"""
Weak reference-based dependency injection container to prevent circular references.

This module provides a DI container that uses weak references to break
circular dependencies and prevent memory leaks.
"""

import asyncio
import logging
import weakref
from collections.abc import Callable
from typing import Any, TypeVar, cast
from weakref import WeakValueDictionary

from src.core.di.models import DIContainerHealth, DIContainerStats

logger = logging.getLogger(__name__)

T = TypeVar("T")

# mypy: disable-error-code="assignment,attr-defined,index,var-annotated"


class WeakDIContainer:
    """Dependency injection container using weak references to prevent cycles."""

    def __init__(self) -> None:  # type: ignore[override]
        """Initialize weak DI container."""
        # Use weak references for service instances
        self._instances: WeakValueDictionary[type[Any], Any] = WeakValueDictionary()
        self._factories: dict[type[Any], Callable[[], Any]] = {}
        self._singletons: dict[type[Any], bool] = {}
        self._cleanup_callbacks: dict[type[Any], Callable[[Any], None]] = {}
        self._lock = asyncio.Lock()
        self._creation_stack: list[type[Any]] = []  # Track creation to detect cycles

    def register_factory(
        self,
        service_type: type[T],
        factory: Callable[[], T],
        singleton: bool = True,
        cleanup_callback: Callable[[T], None] | None = None,
    ) -> None:
        """Register a factory for a service type.

        Args:
            service_type: Type of service to register
            factory: Factory function to create instances
            singleton: Whether to create singleton instances
            cleanup_callback: Called when instance is garbage collected
        """
        self._factories[service_type] = factory
        self._singletons[service_type] = singleton
        if cleanup_callback:
            self._cleanup_callbacks[service_type] = cleanup_callback

    def register_instance(
        self,
        service_type: type[T],
        instance: T,
        cleanup_callback: Callable[[T], None] | None = None,
    ) -> None:
        """Register a specific instance for a service type.

        Args:
            service_type: Type of service
            instance: Instance to register
            cleanup_callback: Called when instance is garbage collected
        """
        self._instances[service_type] = instance
        self._singletons[service_type] = True

        if cleanup_callback:
            self._cleanup_callbacks[service_type] = cleanup_callback

            # Set up weak reference callback for cleanup
            def on_delete(ref):
                try:
                    cleanup_callback(instance)
                except Exception as e:
                    if logger.isEnabledFor(logging.WARNING):
                        logger.warning(
                            f"Error in cleanup callback for {service_type}: {e}"
                        )

            weakref.ref(instance, on_delete)

    async def get_service(self, service_type: type[T]) -> T:
        """Get a service instance.

        Args:
            service_type: Type of service to get

        Returns:
            Service instance

        Raises:
            ValueError: If service is not registered
            RuntimeError: If circular dependency is detected
        """
        async with self._lock:
            # Check for circular dependencies
            if service_type in self._creation_stack:
                cycle_path = " -> ".join(str(t.__name__) for t in self._creation_stack)
                cycle_path += f" -> {service_type.__name__}"
                raise RuntimeError(f"Circular dependency detected: {cycle_path}")

            # Check if we have a singleton instance
            if self._singletons.get(service_type, True):
                instance = self._instances.get(service_type)  # type: ignore[assignment]
                if instance is not None:
                    return cast(T, instance)

            # Create new instance
            factory = self._factories.get(service_type)
            if factory is None:
                raise ValueError(f"No factory registered for {service_type}")

            # Track creation to detect cycles
            self._creation_stack.append(service_type)
            try:
                instance = factory()

                # Store singleton instances with weak reference
                if self._singletons.get(service_type, True):
                    self._instances[service_type] = instance  # type: ignore[index]

                    # Set up cleanup callback if registered
                    cleanup_callback = self._cleanup_callbacks.get(service_type)
                    if cleanup_callback:

                        def on_delete(ref):
                            try:
                                cleanup_callback(instance)
                            except Exception as e:
                                if logger.isEnabledFor(logging.WARNING):
                                    logger.warning(
                                        f"Error in cleanup callback for {service_type}: {e}"
                                    )

                        weakref.ref(instance, on_delete)

                return cast(T, instance)

            finally:
                self._creation_stack.pop()

    async def clear_instances(self) -> None:
        """Clear all service instances."""
        async with self._lock:
            # Call cleanup callbacks for existing instances
            for service_type, instance in list(self._instances.items()):
                cleanup_callback = self._cleanup_callbacks.get(service_type)
                if cleanup_callback:
                    try:
                        cleanup_callback(instance)
                    except Exception as e:
                        if logger.isEnabledFor(logging.WARNING):
                            logger.warning(
                                f"Error in cleanup callback for {service_type}: {e}"
                            )

            self._instances.clear()

    async def remove_service(self, service_type: type[Any]) -> bool:
        """Remove a service registration.

        Args:
            service_type: Type of service to remove

        Returns:
            True if service was removed
        """
        async with self._lock:
            removed = False

            # Remove instance
            if service_type in self._instances:
                instance = self._instances[service_type]  # type: ignore[assignment]
                cleanup_callback = self._cleanup_callbacks.get(service_type)
                if cleanup_callback:
                    try:
                        cleanup_callback(instance)
                    except Exception as e:
                        if logger.isEnabledFor(logging.WARNING):
                            logger.warning(
                                f"Error in cleanup callback for {service_type}: {e}"
                            )

                del self._instances[service_type]  # type: ignore[arg-type]
                removed = True

            # Remove factory
            if service_type in self._factories:
                del self._factories[service_type]
                removed = True

            # Remove other registrations
            self._singletons.pop(service_type, None)
            self._cleanup_callbacks.pop(service_type, None)

            return removed

    async def get_stats(self) -> DIContainerStats:
        """Get container statistics."""
        async with self._lock:
            return DIContainerStats(
                instances=len(self._instances),
                factories=len(self._factories),
                singletons=sum(
                    1 for is_singleton in self._singletons.values() if is_singleton
                ),
                cleanup_callbacks=len(self._cleanup_callbacks),
                creation_stack_depth=len(self._creation_stack),
            )

    async def health_check(self) -> DIContainerHealth:
        """Perform health check on the container."""
        async with self._lock:
            stats = await self.get_stats()

            # Check for potential issues
            issues = []

            if len(self._creation_stack) > 0:
                issues.append(
                    f"Active creation stack: {len(self._creation_stack)} items"
                )

            if len(self._instances) > 100:
                issues.append(f"Large number of instances: {len(self._instances)}")

            return DIContainerHealth(stats=stats, issues=issues, healthy=len(issues) == 0)


class ServiceLifecycleManager:
    """Manage service lifecycle with proper cleanup."""

    def __init__(self, container: WeakDIContainer):
        """Initialize lifecycle manager.

        Args:
            container: DI container to manage
        """
        self._container = container
        self._startup_callbacks: list[Callable[[], None]] = []
        self._shutdown_callbacks: list[Callable[[], None]] = []
        self._started = False

    def add_startup_callback(self, callback: Callable[[], None]) -> None:
        """Add a startup callback.

        Args:
            callback: Function to call during startup
        """
        self._startup_callbacks.append(callback)

    def add_shutdown_callback(self, callback: Callable[[], None]) -> None:
        """Add a shutdown callback.

        Args:
            callback: Function to call during shutdown
        """
        self._shutdown_callbacks.append(callback)

    async def startup(self) -> None:
        """Start all services."""
        if self._started:
            return

        if logger.isEnabledFor(logging.INFO):
            logger.info("Starting service lifecycle manager")

        # Call startup callbacks
        for callback in self._startup_callbacks:
            try:
                if asyncio.iscoroutinefunction(callback):
                    await callback()
                else:
                    callback()
            except Exception as e:
                if logger.isEnabledFor(logging.ERROR):
                    logger.error(f"Error in startup callback: {e}")
                raise

        self._started = True
        if logger.isEnabledFor(logging.INFO):
            logger.info("Service lifecycle manager started")

    async def shutdown(self) -> None:
        """Shutdown all services."""
        if not self._started:
            return

        if logger.isEnabledFor(logging.INFO):
            logger.info("Shutting down service lifecycle manager")

        # Call shutdown callbacks in reverse order
        for callback in reversed(self._shutdown_callbacks):
            try:
                if asyncio.iscoroutinefunction(callback):
                    await callback()
                else:
                    callback()
            except Exception as e:
                if logger.isEnabledFor(logging.WARNING):
                    logger.warning(f"Error in shutdown callback: {e}")

        # Clear container instances
        await self._container.clear_instances()

        self._started = False
        if logger.isEnabledFor(logging.INFO):
            logger.info("Service lifecycle manager shutdown completed")


# Global weak DI container
_global_weak_container: WeakDIContainer | None = None
_global_lifecycle_manager: ServiceLifecycleManager | None = None


def get_weak_container() -> WeakDIContainer:
    """Get the global weak DI container."""
    global _global_weak_container  # type: ignore[misc]
    if _global_weak_container is None:
        _global_weak_container = WeakDIContainer()
    return _global_weak_container


def get_lifecycle_manager() -> ServiceLifecycleManager:
    """Get the global service lifecycle manager."""
    global _global_lifecycle_manager, _global_weak_container  # type: ignore[misc]
    if _global_lifecycle_manager is None:
        if _global_weak_container is None:
            _global_weak_container = WeakDIContainer()
        _global_lifecycle_manager = ServiceLifecycleManager(_global_weak_container)
    return _global_lifecycle_manager


async def shutdown_global_container() -> None:
    """Shutdown the global DI container and lifecycle manager."""
    global _global_lifecycle_manager, _global_weak_container  # type: ignore[misc]

    if _global_lifecycle_manager is not None:
        await _global_lifecycle_manager.shutdown()
        _global_lifecycle_manager = None

    if _global_weak_container is not None:
        await _global_weak_container.clear_instances()
        _global_weak_container = None
