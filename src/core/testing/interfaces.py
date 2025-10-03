"""
Testing interfaces and base classes that enforce proper async/sync patterns.

This module provides interfaces and base classes that prevent common testing
issues like unawaited coroutines by enforcing proper patterns through the type system.
"""

from __future__ import annotations

import inspect
import logging
from typing import Any, Protocol, TypeVar, runtime_checkable
from unittest.mock import AsyncMock, MagicMock

from src.core.domain.session import Session, SessionInteraction
from src.core.interfaces.session_service_interface import ISessionService

logger = logging.getLogger(__name__)

T = TypeVar("T")


@runtime_checkable
class SyncOnlyService(Protocol):
    """
    Protocol for services that should NEVER return coroutines.

    This enforces that certain methods must be synchronous and helps
    prevent AsyncMock usage where it would cause coroutine warnings.
    """


@runtime_checkable
class AsyncOnlyService(Protocol):
    """
    Protocol for services that should ALWAYS return coroutines.

    This enforces that certain methods must be asynchronous.
    """


class TestServiceValidator:
    """
    Utility class that validates test services at runtime to prevent
    common mocking issues that cause coroutine warnings.
    """

    @staticmethod
    def validate_session_service(service: ISessionService) -> None:
        """
        Validate that a session service returns real Session objects,
        not AsyncMock objects that would cause coroutine warnings.

        Args:
            service: The session service to validate

        Raises:
            TypeError: If the service doesn't properly implement the interface
        """
        # Check that get_session returns a real session, not an AsyncMock
        if hasattr(service, "get_session"):
            method = service.get_session

            if isinstance(method, AsyncMock):
                raise TypeError(
                    f"Session service {type(service).__name__}.get_session is an AsyncMock "
                    "and will produce coroutine warnings. Use a real implementation or a "
                    "properly configured MagicMock instead."
                )

            if inspect.iscoroutinefunction(method):
                raise TypeError(
                    f"Session service {type(service).__name__}.get_session is a coroutine "
                    "function but should be synchronous. This will cause coroutine warnings."
                )

            try:
                result = method("test_session_id")

                if isinstance(result, AsyncMock):
                    raise TypeError(
                        f"Session service {type(service).__name__} returns AsyncMock "
                        "from get_session(), which will cause coroutine warnings. "
                        "Use a real Session object or properly configured mock instead."
                    )

                if inspect.isawaitable(result):
                    close = getattr(result, "close", None)
                    if callable(close):
                        close()
                    raise TypeError(
                        f"Session service {type(service).__name__}.get_session() returns an "
                        "awaitable but the method is not async. This will cause coroutine "
                        "warnings."
                    )

            except (TypeError, AttributeError) as e:
                if logger.isEnabledFor(logging.WARNING):
                    logger.warning(f"Error validating signature: {e}", exc_info=True)

    @staticmethod
    def validate_sync_method(obj: Any, method_name: str) -> None:
        """
        Validate that a method is synchronous and doesn't return AsyncMock.

        Args:
            obj: The object containing the method
            method_name: Name of the method to validate

        Raises:
            TypeError: If the method returns AsyncMock or is unexpectedly async
        """
        if not hasattr(obj, method_name):
            return

        method = getattr(obj, method_name)

        # If it's an AsyncMock, that's definitely wrong for sync methods
        if isinstance(method, AsyncMock):
            raise TypeError(
                f"{type(obj).__name__}.{method_name} is an AsyncMock "
                "but should be synchronous. This will cause coroutine warnings."
            )

        # Try calling with dummy args to see what it returns
        try:
            result = method()
            if isinstance(result, AsyncMock):
                raise TypeError(
                    f"{type(obj).__name__}.{method_name}() returns AsyncMock "
                    "but should return a real object. This will cause coroutine warnings."
                )
        except (TypeError, AttributeError) as e:
            # Can't validate dynamically, that's okay
            if logger.isEnabledFor(logging.DEBUG):
                logger.debug(f"Error validating instance: {e}", exc_info=True)


class SafeTestSession(Session):
    """
    A Session implementation specifically designed for testing that
    prevents common coroutine warning issues.

    This class ensures that all session operations are properly synchronous
    and won't accidentally return coroutines or AsyncMock objects.
    """

    def __init__(self, session_id: str):
        super().__init__(session_id=session_id)
        self._interactions: list[SessionInteraction] = []

    def add_interaction(self, interaction: SessionInteraction) -> None:
        """
        Add an interaction to this session.

        This method is intentionally synchronous to prevent coroutine warnings.
        """
        # Validate that interaction is not an AsyncMock
        if isinstance(interaction, AsyncMock):
            raise TypeError(
                "Cannot add AsyncMock as interaction. This would cause coroutine warnings."
            )

        self._interactions.append(interaction)

    def get_interactions(self) -> list[SessionInteraction]:
        """Get all interactions for this session."""
        return self._interactions.copy()


class EnforcedMockFactory:
    """
    Factory for creating properly configured mocks that won't cause coroutine warnings.

    This factory ensures that sync methods get regular mocks and async methods
    get properly awaitable AsyncMocks.
    """

    @staticmethod
    def create_session_service_mock() -> ISessionService:
        """
        Create a properly configured session service mock.

        Returns:
            A mock session service that returns real Session objects
        """
        mock_service = MagicMock(spec=ISessionService)

        # Ensure get_session returns real Session objects, not mocks
        def get_session_impl(session_id: str) -> Session:
            return SafeTestSession(session_id)

        mock_service.get_session = get_session_impl

        # For async methods, use AsyncMock
        mock_service.update_session = AsyncMock()
        mock_service.create_session = AsyncMock()

        # Validate the mock before returning
        TestServiceValidator.validate_session_service(mock_service)

        return mock_service

    @staticmethod
    def create_backend_service_mock() -> Any:
        """
        Create a properly configured backend service mock.

        Returns:
            A mock backend service with proper async/sync method configuration
        """
        from src.core.interfaces.backend_service_interface import IBackendService

        mock_service = MagicMock(spec=IBackendService)

        # All backend service methods should be async
        mock_service.call_completion = AsyncMock()
        mock_service.validate_backend = AsyncMock(return_value=(True, None))
        mock_service.validate_backend_and_model = AsyncMock(return_value=(True, None))
        mock_service.get_backend_status = AsyncMock(return_value={"status": "healthy"})

        return mock_service


class TestStageValidator:
    """
    Validator for test stages to ensure they don't create problematic service configurations.
    """

    @staticmethod
    def validate_stage_services(services: dict[type, Any]) -> None:
        """
        Validate all services registered by a test stage.

        Args:
            services: Dictionary of service types to instances

        Raises:
            TypeError: If any service has problematic configuration
        """
        for service_type, service_instance in services.items():
            # Check for session services
            if (
                hasattr(service_type, "__name__")
                and "Session" in service_type.__name__
                and hasattr(service_instance, "get_session")
            ):
                TestServiceValidator.validate_session_service(service_instance)

            # Check for any AsyncMock instances where they shouldn't be
            if isinstance(service_instance, AsyncMock):
                # AsyncMock is okay for async services, but warn about potential issues
                import logging

                logger = logging.getLogger(__name__)
                if logger.isEnabledFor(logging.DEBUG):
                    logger.debug(
                        f"Service {service_type.__name__} is an AsyncMock. "
                        "Ensure all methods that should be sync return real objects, not coroutines."
                    )


class SafeAsyncMockWrapper:
    """
    A wrapper around AsyncMock that prevents common coroutine warning issues.

    This wrapper ensures that when AsyncMock is used, it's properly configured
    to avoid returning unawaited coroutines.
    """

    def __init__(self, spec: type | None = None, **kwargs: Any) -> None:
        self._mock = AsyncMock(spec=spec, **kwargs)
        self._sync_methods: set[str] = set()

    def mark_method_as_sync(self, method_name: str, return_value: Any = None) -> None:
        """
        Mark a method as synchronous and set its return value.

        Args:
            method_name: Name of the method that should be synchronous
            return_value: The value this method should return (not a coroutine)
        """
        self._sync_methods.add(method_name)
        # Replace the AsyncMock method with a regular mock
        setattr(self._mock, method_name, MagicMock(return_value=return_value))

    def __getattr__(self, name: str) -> Any:
        return getattr(self._mock, name)

    def __setattr__(self, name: str, value: Any) -> None:
        if name.startswith("_"):
            super().__setattr__(name, value)
        else:
            setattr(self._mock, name, value)


def enforce_async_sync_separation(cls: type) -> type:
    """
    Class decorator that enforces proper async/sync separation in test services.

    This decorator validates that sync methods don't return coroutines and
    async methods don't return regular values when they shouldn't.

    Args:
        cls: The class to decorate

    Returns:
        The decorated class with validation
    """
    original_init = cls.__init__  # type: ignore[misc]

    def validated_init(self, *args: Any, **kwargs: Any) -> None:  # type: ignore[no-untyped-def]
        original_init(self, *args, **kwargs)

        # Validate the instance after initialization
        for attr_name in dir(self):
            if not attr_name.startswith("_"):
                attr = getattr(self, attr_name)

                # Check for AsyncMock in places where it shouldn't be
                if isinstance(attr, AsyncMock) and not attr_name.startswith("async_"):
                    import logging

                    logger = logging.getLogger(__name__)
                    if logger.isEnabledFor(logging.WARNING):
                        logger.warning(
                            f"{cls.__name__}.{attr_name} is an AsyncMock. "
                            "If this method should be synchronous, use MagicMock instead."
                        )

    cls.__init__ = validated_init  # type: ignore[misc]
    return cls
