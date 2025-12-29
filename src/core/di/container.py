from __future__ import annotations

import asyncio
import contextlib
import inspect
import logging
import os
import threading
from collections.abc import Callable
from typing import Any, TypeVar

from src.core.common.exceptions import ServiceResolutionError
from src.core.di.diagnostics import (
    enrich_factory_error,
    enrich_missing_service_error,
    enrich_scoped_from_root_error,
    pop_resolution,
    push_resolution,
)
from src.core.interfaces.di_interface import (
    IServiceCollection,
    IServiceProvider,
    IServiceScope,
    ServiceLifetime,
)

T = TypeVar("T")

logger = logging.getLogger(__name__)


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
    ) -> None:
        """Initialize a service scope.

        Args:
            provider: The service provider that created this scope
            parent_scope: The parent scope (if this is a nested scope)
        """
        self._provider = ScopedServiceProvider(provider, self)
        self._parent_scope = parent_scope
        self._instances: dict[type, Any] = {}
        # Use a re-entrant lock to avoid deadlocks when resolving nested singletons.
        self._lock = threading.RLock()
        self._disposed = False

    @property
    def service_provider(self) -> IServiceProvider:
        """Get the service provider for this scope."""
        if self._disposed:
            raise RuntimeError("This scope has been disposed")
        return self._provider

    async def dispose(self) -> None:
        """Dispose of this scope and any scoped services."""
        with self._lock:
            if self._disposed:
                return

            self._disposed = True

            # Dispose any instances that implement disposable pattern
            for instance in self._instances.values():
                if hasattr(instance, "__aenter__") and hasattr(instance, "__aexit__"):
                    await instance.__aexit__(None, None, None)
                elif hasattr(instance, "dispose") and callable(instance.dispose):
                    instance.dispose()

            self._instances.clear()


class ScopedServiceProvider(IServiceProvider):
    """A service provider for a specific scope."""

    def __init__(self, root_provider: ServiceProvider, scope: ServiceScope) -> None:
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
            type_name = getattr(service_type, "__name__", str(service_type))
            base_error = ServiceResolutionError(
                f"No service registered for {type_name}", service_name=type_name
            )
            enriched_error = enrich_missing_service_error(service_type, base_error)
            pop_resolution()  # Pop after enriching error (service was pushed in _get_service)
            raise enriched_error
        return service

    def has_service(self, service_type: type[T]) -> bool:
        """Check if a service of the given type is registered."""
        return self._root.has_service(service_type)

    def create_scope(self) -> IServiceScope:
        """Create a new nested service scope."""
        return ServiceScope(self._root, self._scope)


class ServiceProvider(IServiceProvider):
    """Implementation of a service provider."""

    def __init__(self, descriptors: dict[type, ServiceDescriptor]) -> None:
        """Initialize a service provider.

        Args:
            descriptors: The service descriptors to use for resolution
        """
        self._descriptors = descriptors
        self._singleton_instances: dict[type, Any] = {}
        # Use a re-entrant lock to avoid deadlocks during nested resolution.
        self._lock = threading.RLock()
        self._diagnostics = os.getenv("DI_STRICT_DIAGNOSTICS", "false").lower() in (
            "true",
            "1",
            "yes",
        )
        self._diag_logger = logging.getLogger("llm.di")

    def get_service(self, service_type: type[T]) -> T | None:
        """Get a service of the given type if registered."""
        return self._get_service(service_type, None)

    def get_required_service(self, service_type: type[T]) -> T:
        """Get a service of the given type, throwing if not found."""
        service = self.get_service(service_type)
        if service is None:
            type_name = getattr(service_type, "__name__", str(service_type))
            base_error = ServiceResolutionError(
                f"No service registered for {type_name}", service_name=type_name
            )
            enriched_error = enrich_missing_service_error(service_type, base_error)
            pop_resolution()  # Pop after enriching error (service was pushed in _get_service)
            raise enriched_error
        return service

    def has_service(self, service_type: type[T]) -> bool:
        """Check if a service of the given type is registered."""
        return service_type in self._descriptors

    def create_scope(self) -> IServiceScope:
        """Create a new service scope."""
        return ServiceScope(self)

    async def dispose(self) -> None:
        """Dispose of service provider and clean up singleton instances.

        This method ensures that all singleton instances are properly cleaned up:
        - Async context managers (like httpx.AsyncClient) have __aexit__ called
        - Other resources with dispose() methods are disposed
        - The _singleton_instances dict is cleared to prevent memory leaks

        Should be called during application shutdown to release all resources.
        """
        with self._lock:
            for service_type, instance in list(self._singleton_instances.items()):
                try:
                    if hasattr(instance, "__aexit__") and callable(instance.__aexit__):
                        await instance.__aexit__(None, None, None)  # type: ignore[misc]
                    elif hasattr(instance, "dispose") and callable(instance.dispose):
                        if asyncio.iscoroutinefunction(instance.dispose):
                            await instance.dispose()
                        else:
                            instance.dispose()
                except Exception as e:
                    if self._diag_logger.isEnabledFor(logging.WARNING):
                        self._diag_logger.warning(
                            "Error disposing singleton instance %s: %s",
                            service_type,
                            e,
                            exc_info=True,
                        )
            self._singleton_instances.clear()

    def _get_service(
        self, service_type: type[T], scope: ServiceScope | None
    ) -> T | None:
        """Internal method to get a service of the given type."""
        push_resolution(service_type)
        try:
            descriptor = self._descriptors.get(service_type)
            if descriptor is None:
                if self._diagnostics:
                    type_name = getattr(service_type, "__name__", str(service_type))
                    self._diag_logger.warning(
                        "DI: no descriptor for %s; registered=%d",
                        type_name,
                        len(self._descriptors),
                    )
                # Don't pop here - keep on stack for error enrichment
                return None

            # Check if it's a singleton with existing instance
            if descriptor.instance is not None:
                pop_resolution()  # Pop before returning successfully resolved service
                return descriptor.instance  # type: ignore[no-any-return]

            # Handle based on lifetime
            if descriptor.lifetime == ServiceLifetime.SINGLETON:
                # Check for cached singleton instance (with lock for thread safety)
                with self._lock:
                    if service_type in self._singleton_instances:
                        pop_resolution()  # Pop before returning successfully resolved service
                        return self._singleton_instances[service_type]  # type: ignore[no-any-return]

                    # Create and cache singleton instance
                    instance = self._create_instance(descriptor, scope)  # type: ignore[no-any-return]
                    self._singleton_instances[service_type] = instance
                    pop_resolution()  # Pop before returning successfully resolved service
                    return instance  # type: ignore[no-any-return]

            elif descriptor.lifetime == ServiceLifetime.SCOPED:
                if scope is None:
                    # Handle Mock objects which don't have __name__
                    type_name = getattr(service_type, "__name__", str(service_type))
                    if self._diagnostics:
                        pop_resolution()  # Pop before raising error
                        raise enrich_scoped_from_root_error(service_type)
                    pop_resolution()  # Pop before raising error
                    raise RuntimeError(
                        f"Cannot resolve scoped service {type_name} from root provider"
                    )

                # Check for cached scoped instance (with lock for thread safety)
                with self._lock:
                    if service_type in scope._instances:
                        pop_resolution()  # Pop before returning successfully resolved service
                        return scope._instances[service_type]  # type: ignore[no-any-return]

                    # Create and cache scoped instance
                    instance = self._create_instance(descriptor, scope)  # type: ignore[no-any-return]
                    scope._instances[service_type] = instance
                    pop_resolution()  # Pop before returning successfully resolved service
                    return instance  # type: ignore[no-any-return]

            else:  # TRANSIENT
                instance = self._create_instance(descriptor, scope)  # type: ignore[no-any-return]
                pop_resolution()  # Pop before returning successfully resolved service
                return instance  # type: ignore[no-any-return]
        except (RuntimeError, AttributeError, TypeError, ValueError) as e:
            # Expected exceptions from service resolution (factory errors, type mismatches, etc.)
            # Pop before re-raising to ensure resolution stack is properly cleaned up
            # Note: BaseException (KeyboardInterrupt, SystemExit) will propagate
            # without cleanup, which is correct behavior for shutdown signals
            type_name = getattr(service_type, "__name__", str(service_type))
            logger.error(
                "Error resolving service %s (%s)",
                type_name,
                type(e).__name__,
                exc_info=True,
                extra={"service_type": type_name, "exception_type": type(e).__name__},
            )
            pop_resolution()
            raise
        except Exception as e:
            # Unexpected exceptions - log with more detail for debugging
            # Pop before re-raising to ensure resolution stack is properly cleaned up
            # Note: BaseException (KeyboardInterrupt, SystemExit) will propagate
            # without cleanup, which is correct behavior for shutdown signals
            type_name = getattr(service_type, "__name__", str(service_type))
            logger.error(
                "Unexpected error resolving service %s (%s)",
                type_name,
                type(e).__name__,
                exc_info=True,
                extra={"service_type": type_name, "exception_type": type(e).__name__},
            )
            pop_resolution()
            raise

    def _create_instance(
        self, descriptor: ServiceDescriptor, scope: ServiceScope | None
    ) -> Any:
        """Create an instance of a service."""
        service_type = descriptor.service_type
        push_resolution(service_type)
        try:
            # Use factory if provided
            if descriptor.implementation_factory:
                provider = scope.service_provider if scope else self
                try:
                    return descriptor.implementation_factory(provider)
                except Exception as e:
                    if self._diagnostics:
                        raise enrich_factory_error(service_type, e) from e
                    raise

            # Otherwise, create instance of implementation type
            impl_type = descriptor.implementation_type
            if impl_type is None:
                error = RuntimeError(
                    "Implementation type is None and no factory provided"
                )
                if self._diagnostics:
                    raise enrich_factory_error(service_type, error) from error
                raise error

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

            try:
                if has_provider_param:
                    provider = scope.service_provider if scope else self
                    return impl_type(service_provider=provider)
                else:
                    return impl_type()
            except Exception as e:
                if self._diagnostics:
                    raise enrich_factory_error(service_type, e) from e
                raise
        finally:
            pop_resolution()


class ServiceCollection(IServiceCollection):
    """Implementation of a service collection."""

    def __init__(self) -> None:
        """Initialize a service collection."""
        self._descriptors: dict[type, ServiceDescriptor] = {}
        # Track cleanup tasks to prevent resource leaks
        # Use regular set instead of WeakSet to prevent premature GC before tasks complete
        self._cleanup_tasks: set[asyncio.Task[None]] = set()
        self._cleanup_lock = asyncio.Lock()
        self._disposed = False
        self._logger = logging.getLogger("llm.di")

    def add_singleton(
        self,
        service_type: type[Any],
        implementation_type: type | None = None,
        implementation_factory: Callable[[IServiceProvider], Any] | None = None,
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
        service_type: type[Any],
        implementation_factory: Callable[[IServiceProvider], Any],
    ) -> IServiceCollection:
        """Register a singleton service with a factory."""
        return self.add_singleton(
            service_type, implementation_factory=implementation_factory
        )

    def add_transient(
        self,
        service_type: type[Any],
        implementation_type: type | None = None,
        implementation_factory: Callable[[IServiceProvider], Any] | None = None,
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
        service_type: type[Any],
        implementation_type: type | None = None,
        implementation_factory: Callable[[IServiceProvider], Any] | None = None,
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

    def add_instance(
        self, service_type: type[Any], instance: Any
    ) -> IServiceCollection:
        """Register an existing instance as a singleton.

        If replacing an existing instance, the old instance is closed if it's
        an httpx.AsyncClient to prevent resource leaks.
        """
        # Check if we're replacing an existing instance that needs cleanup
        old_descriptor = self._descriptors.get(service_type)
        if old_descriptor is not None and old_descriptor.instance is not None:
            old_instance = old_descriptor.instance
            # Close httpx.AsyncClient instances to prevent leaks
            if hasattr(old_instance, "aclose") and callable(old_instance.aclose):
                import httpx

                if isinstance(old_instance, httpx.AsyncClient):
                    try:
                        loop = asyncio.get_event_loop()
                        if loop.is_running():
                            # Schedule async close task and track it to prevent resource leaks
                            cleanup_task = asyncio.create_task(old_instance.aclose())
                            self._cleanup_tasks.add(cleanup_task)
                        else:

                            # Run synchronously if no event loop
                            loop.run_until_complete(old_instance.aclose())
                    except (RuntimeError, AttributeError):
                        # No event loop - client will be closed by finalizer
                        pass

        self._descriptors[service_type] = ServiceDescriptor(
            service_type=service_type,
            lifetime=ServiceLifetime.SINGLETON,
            instance=instance,
        )
        return self

    def build_service_provider(self) -> IServiceProvider:
        """Build a service provider with the registered services."""
        provider = ServiceProvider(self._descriptors.copy())
        # Execute post-build hooks (handler registration, etc.)
        try:
            from src.core.di.provider_lifecycle import post_build_hooks

            post_build_hooks(provider)
        except ImportError:
            # Don't fail if provider_lifecycle is not available (e.g., in tests)
            pass
        except (AttributeError, RuntimeError, TypeError) as err:
            # Log unexpected errors in post-build hooks but continue
            logger = logging.getLogger("llm.di")
            if logger.isEnabledFor(logging.WARNING):
                logger.warning(
                    "Post-build hooks failed: %s",
                    err,
                    exc_info=True,
                )
        return provider

    async def dispose(self) -> None:
        """Dispose of of service collection and await pending cleanup tasks.

        This method ensures that all cleanup tasks created when replacing
        httpx.AsyncClient instances are properly awaited before collection
        is destroyed, preventing resource leaks.

        Should be called when ServiceCollection is about to be destroyed,
        e.g., during application shutdown or stage failure.
        """
        if self._disposed:
            return

        self._disposed = True

        # Await all pending cleanup tasks to prevent resource leaks
        async with self._cleanup_lock:
            pending_tasks = [t for t in self._cleanup_tasks if not t.done()]
            if pending_tasks:
                try:
                    await asyncio.wait_for(
                        asyncio.gather(*pending_tasks, return_exceptions=True),
                        timeout=5.0,
                    )
                except asyncio.TimeoutError:
                    # Cancel tasks that didn't complete in time
                    for task in pending_tasks:
                        if not task.done():
                            task.cancel()
                    # Await cancelled tasks to ensure they complete
                    with contextlib.suppress(Exception):
                        await asyncio.gather(*pending_tasks, return_exceptions=True)
                except RuntimeError:
                    # If gather fails, cancel all tasks
                    for task in pending_tasks:
                        if not task.done():
                            task.cancel()
                    with contextlib.suppress(Exception):
                        await asyncio.gather(*pending_tasks, return_exceptions=True)

            # Clear the cleanup tasks set to prevent memory leaks
            self._cleanup_tasks.clear()

    def register_app_services(self) -> None:
        """Register all application services via registrar orchestration.

        This legacy method delegates to the registrar orchestrator to ensure
        consistent registration across all code paths and avoid drift.
        """
        from src.core.di.registrations._orchestrator import register_all

        # Delegate to orchestrator which calls all registrars in deterministic order
        # Use None for app_config to let registrars handle defaults
        register_all(self, None)

    def register_singleton(
        self,
        service_type: type[Any],
        implementation_type: type[Any] | None = None,
        implementation_factory: Callable[[IServiceProvider], Any] | None = None,
    ) -> IServiceCollection:
        """Alias for add_singleton to maintain compatibility."""
        return self.add_singleton(
            service_type, implementation_type, implementation_factory
        )

    def register_transient(
        self,
        service_type: type[Any],
        implementation_type: type[Any] | None = None,
        implementation_factory: Callable[[IServiceProvider], Any] | None = None,
    ) -> IServiceCollection:
        """Alias for add_transient to maintain compatibility."""
        return self.add_transient(
            service_type, implementation_type, implementation_factory
        )

    def register_scoped(
        self,
        service_type: type[Any],
        implementation_type: type[Any] | None = None,
        implementation_factory: Callable[[IServiceProvider], Any] | None = None,
    ) -> IServiceCollection:
        """Alias for add_scoped to maintain compatibility."""
        return self.add_scoped(
            service_type, implementation_type, implementation_factory
        )
