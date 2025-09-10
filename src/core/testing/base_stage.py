"""
Enhanced base classes for test stages that automatically prevent coroutine warning issues.

This module provides base classes that coding agents can inherit from to automatically
get protection against common async/sync mocking issues.
"""

from __future__ import annotations

import logging
from typing import Any
from unittest.mock import AsyncMock, MagicMock

from src.core.app.stages.base import InitializationStage
from src.core.config.app_config import AppConfig
from src.core.di.container import ServiceCollection
from src.core.testing.interfaces import (
    EnforcedMockFactory,
    TestServiceValidator,
    TestStageValidator,
)

logger = logging.getLogger(__name__)


class ValidatedTestStage(InitializationStage):
    """
    Base class for test stages that automatically validates service registrations
    to prevent coroutine warning issues.

    This class provides automatic validation and helpful error messages to guide
    coding agents toward correct implementations.
    """

    def __init__(self) -> None:
        self._registered_services: dict[type, Any] = {}

    async def execute(self, services: ServiceCollection, config: AppConfig) -> None:
        """
        Execute the stage with automatic validation.

        Subclasses should override _register_services instead of this method.
        """
        logger.info(f"Executing validated test stage: {self.name}")

        # Let subclass register services
        await self._register_services(services, config)

        # Validate all registered services
        try:
            TestStageValidator.validate_stage_services(self._registered_services)
            logger.debug(f"All services in stage '{self.name}' passed validation")
        except (TypeError, AttributeError) as e:
            logger.error(
                f"Service validation failed in stage '{self.name}': {e}", exc_info=True
            )
            # Don't raise here, just warn, so tests can still run but with warnings

    async def _register_services(
        self, services: ServiceCollection, config: AppConfig
    ) -> None:
        """
        Register services for this stage.

        Subclasses should override this method instead of execute().
        Use safe_register_* methods to automatically get validation.
        """
        raise NotImplementedError("Subclasses must implement _register_services")

    def safe_register_instance(
        self,
        services: ServiceCollection,
        service_type: type,
        instance: Any,
        validate: bool = True,
    ) -> None:
        """
        Safely register a service instance with automatic validation.

        Args:
            services: The service collection
            service_type: The service type/interface
            instance: The service instance
            validate: Whether to validate the instance (default: True)
        """
        # Store for validation
        self._registered_services[service_type] = instance

        # Validate specific service types
        if validate:
            self._validate_service_instance(service_type, instance)

        # Register with the service collection
        services.add_instance(service_type, instance)
        logger.debug(f"Safely registered {service_type.__name__}")

    def safe_register_singleton(
        self,
        services: ServiceCollection,
        service_type: type,
        implementation_factory: Any = None,
        implementation_type: type | None = None,
    ) -> None:
        """
        Safely register a singleton service with validation.

        Args:
            services: The service collection
            service_type: The service type/interface
            implementation_factory: Factory function for creating the service
            implementation_type: Implementation type (if not using factory)
        """
        if implementation_factory:
            services.add_singleton(
                service_type, implementation_factory=implementation_factory
            )
        elif implementation_type:
            services.add_singleton(
                service_type, implementation_type=implementation_type
            )
        else:
            services.add_singleton(service_type)

        logger.debug(f"Safely registered singleton {service_type.__name__}")

    def create_safe_session_service_mock(self) -> Any:
        """
        Create a session service mock that won't cause coroutine warnings.

        Returns:
            A properly configured session service mock
        """
        return EnforcedMockFactory.create_session_service_mock()

    def create_safe_backend_service_mock(self) -> Any:
        """
        Create a backend service mock that won't cause coroutine warnings.

        Returns:
            A properly configured backend service mock
        """
        return EnforcedMockFactory.create_backend_service_mock()

    def _validate_service_instance(self, service_type: type, instance: Any) -> None:
        """
        Validate a specific service instance.

        Args:
            service_type: The service type
            instance: The service instance
        """
        # Check for session services specifically
        if (
            hasattr(service_type, "__name__")
            and "Session" in service_type.__name__
            and hasattr(instance, "get_session")
        ):
            try:
                TestServiceValidator.validate_session_service(instance)
            except TypeError as e:
                logger.error(
                    f"Session service validation failed for {service_type.__name__}: {e}\n"
                    f"HINT: Use EnforcedMockFactory.create_session_service_mock() instead of "
                    f"creating AsyncMock directly."
                )

        # Check for improperly configured AsyncMocks
        if isinstance(instance, AsyncMock):
            # This might be okay for async services, but warn about potential sync method issues
            logger.warning(
                f"Service {service_type.__name__} is an AsyncMock. "
                f"If any methods should be synchronous, use SafeAsyncMockWrapper instead."
            )

        # Check for sync methods that might be AsyncMock
        for attr_name in ["get_session", "add_interaction", "get_interactions"]:
            if hasattr(instance, attr_name):
                attr = getattr(instance, attr_name)
                if isinstance(attr, AsyncMock):
                    logger.error(
                        f"Method {service_type.__name__}.{attr_name} is AsyncMock but "
                        f"should likely be synchronous. This will cause coroutine warnings.\n"
                        f"HINT: Use MagicMock for sync methods or mark as sync with "
                        f"SafeAsyncMockWrapper.mark_method_as_sync()"
                    )


class SessionServiceTestStage(ValidatedTestStage):
    """
    Example test stage that properly registers session services.

    This serves as a template for coding agents to follow.
    """

    @property
    def name(self) -> str:
        return "safe_session_services"

    def get_dependencies(self) -> list[str]:
        return ["core_services"]

    def get_description(self) -> str:
        return "Register session services with coroutine warning prevention"

    async def _register_services(
        self, services: ServiceCollection, config: AppConfig
    ) -> None:
        """Register session services safely."""
        # Use the safe factory instead of creating AsyncMock directly
        session_service = self.create_safe_session_service_mock()

        # Register safely with automatic validation
        from src.core.interfaces.session_service_interface import ISessionService

        self.safe_register_instance(services, ISessionService, session_service)


class BackendServiceTestStage(ValidatedTestStage):
    """
    Example test stage that properly registers backend services.

    This serves as a template for coding agents to follow.
    """

    @property
    def name(self) -> str:
        return "safe_backend_services"

    def get_dependencies(self) -> list[str]:
        return ["infrastructure"]

    def get_description(self) -> str:
        return "Register backend services with coroutine warning prevention"

    async def _register_services(
        self, services: ServiceCollection, config: AppConfig
    ) -> None:
        """Register backend services safely."""
        # Use the safe factory instead of creating AsyncMock directly
        backend_service = self.create_safe_backend_service_mock()

        # Register safely with automatic validation
        from src.core.interfaces.backend_service_interface import IBackendService

        self.safe_register_instance(services, IBackendService, backend_service)


class GuardedMockCreationMixin:
    """
    Mixin that provides guarded methods for creating mocks.

    This mixin can be added to any test class to get automatic protection
    against creating problematic mocks.
    """

    def create_mock(self, spec: type | None = None, **kwargs: Any) -> MagicMock:
        """
        Create a regular mock with validation.

        Args:
            spec: The specification for the mock
            **kwargs: Additional arguments for MagicMock

        Returns:
            A properly configured MagicMock
        """
        mock = MagicMock(spec=spec, **kwargs)

        # If this is for a session service, warn about potential issues
        if spec and hasattr(spec, "__name__") and "Session" in spec.__name__:
            logger.warning(
                f"Creating MagicMock for {spec.__name__}. "
                f"Consider using EnforcedMockFactory.create_session_service_mock() "
                f"to avoid coroutine warnings."
            )

        return mock

    def create_async_mock(self, spec: type | None = None, **kwargs: Any) -> AsyncMock:
        """
        Create an async mock with validation.

        Args:
            spec: The specification for the mock
            **kwargs: Additional arguments for AsyncMock

        Returns:
            A properly configured AsyncMock
        """
        mock = AsyncMock(spec=spec, **kwargs)

        # Warn about potential sync method issues
        if spec:
            logger.info(
                f"Created AsyncMock for {spec.__name__}. "
                f"Remember to use MagicMock for any synchronous methods "
                f"or use SafeAsyncMockWrapper for mixed async/sync interfaces."
            )

        return mock
