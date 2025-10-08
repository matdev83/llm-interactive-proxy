from __future__ import annotations

import inspect
import logging
import os
import types
from collections.abc import Callable
from typing import Any, TypeVar, Union, get_args, get_origin

from src.core.common.exceptions import ServiceResolutionError
from src.core.interfaces.app_settings_interface import IAppSettings
from src.core.interfaces.application_state_interface import IApplicationState
from src.core.interfaces.backend_processor_interface import IBackendProcessor
from src.core.interfaces.backend_request_manager_interface import IBackendRequestManager
from src.core.interfaces.di_interface import (
    IServiceCollection,
    IServiceProvider,
    IServiceScope,
    ServiceLifetime,
)
from src.core.interfaces.request_processor_interface import IRequestProcessor
from src.core.interfaces.session_service_interface import ISessionService

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
            raise ServiceResolutionError(
                f"No service registered for {type_name}", service_name=type_name
            )
        return service

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
            raise ServiceResolutionError(
                f"No service registered for {type_name}", service_name=type_name
            )
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
            if self._diagnostics:
                type_name = getattr(service_type, "__name__", str(service_type))
                self._diag_logger.warning(
                    "DI: no descriptor for %s; registered=%d",
                    type_name,
                    len(self._descriptors),
                )
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
        def _annotation_accepts_service_provider(annotation: Any) -> bool:
            if annotation is inspect._empty:
                return False

            if annotation == IServiceProvider:
                return True

            if isinstance(annotation, str):
                return "IServiceProvider" in annotation.replace(" ", "")

            origin = get_origin(annotation)
            if origin in (types.UnionType, Union):
                return any(
                    _annotation_accepts_service_provider(arg)
                    for arg in get_args(annotation)
                )

            if origin is not None:
                return any(
                    _annotation_accepts_service_provider(arg)
                    for arg in get_args(annotation)
                )

            return False

        try:
            signature = inspect.signature(impl_type)
            has_provider_param = any(
                param.name == "service_provider"
                and _annotation_accepts_service_provider(param.annotation)
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
        from src.core.config.app_config import AppConfig
        from src.core.interfaces.usage_tracking_interface import (
            IUsageTrackingService,  # type: ignore[import-untyped]
        )
        from src.core.services.app_settings_service import AppSettings
        from src.core.services.application_state_service import (
            ApplicationStateService,  # type: ignore[import-untyped]
        )
        from src.core.services.backend_factory import (
            BackendFactory,  # type: ignore[import-untyped]
        )
        from src.core.services.backend_processor import (
            BackendProcessor,  # type: ignore[import-untyped]
        )
        from src.core.services.backend_registry import (
            BackendRegistry,  # type: ignore[import-untyped]
        )
        from src.core.services.backend_request_manager_service import (
            BackendRequestManager,  # type: ignore[import-untyped]
        )

        # Legacy CommandService removed - use NewCommandService from di/services.py
        from src.core.services.content_rewriter_service import ContentRewriterService
        from src.core.services.request_processor_service import RequestProcessor
        from src.core.services.session_service import (
            SessionService,  # type: ignore[import-untyped]
        )
        from src.core.services.translation_service import TranslationService
        from src.core.services.usage_tracking_service import (
            UsageTrackingService,  # type: ignore[import-untyped]
        )

        # Register all application services
        self.add_singleton(IApplicationState, ApplicationStateService)
        self.add_singleton(IAppSettings, AppSettings)

        # Register AppConfig as singleton
        self.add_singleton(
            AppConfig, implementation_factory=lambda _: AppConfig.from_env()
        )

        # Register TranslationService as singleton
        self.add_singleton(TranslationService)

        # Register BackendFactory with proper factory
        import httpx

        def _backend_factory_factory(provider: IServiceProvider) -> BackendFactory:
            """Create BackendFactory with all required dependencies."""
            return BackendFactory(
                provider.get_required_service(httpx.AsyncClient),
                provider.get_required_service(BackendRegistry),
                provider.get_required_service(AppConfig),
                provider.get_required_service(TranslationService),
            )

        self.add_singleton(
            BackendFactory, implementation_factory=_backend_factory_factory
        )
        self.add_singleton(BackendRegistry, BackendRegistry)
        self.add_singleton(IUsageTrackingService, UsageTrackingService)
        self.add_singleton(ISessionService, SessionService)
        # ICommandService registered in register_core_services()
        self.add_singleton(ContentRewriterService, ContentRewriterService)

        self.add_scoped(IBackendProcessor, BackendProcessor)
        self.add_scoped(IBackendRequestManager, BackendRequestManager)
        self.add_scoped(IRequestProcessor, RequestProcessor)

        # Register additional core services including ToolCallReactor
        from src.core.di.services import register_core_services

        register_core_services(self)

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
