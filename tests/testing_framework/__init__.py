"""
Comprehensive Testing Framework for Preventing Coroutine Warnings

This module provides enhanced test infrastructure that automatically prevents
common coroutine warning issues by enforcing proper async/sync usage patterns
through typing protocols, validated mock factories, and runtime validation.
"""

from __future__ import annotations

import asyncio
import inspect
import warnings
from abc import ABC, abstractmethod
from typing import Any, Protocol, TypeVar
from unittest.mock import AsyncMock, MagicMock, Mock

# Type definitions
T = TypeVar("T")
MockType = Mock | MagicMock | AsyncMock


class SyncOnlyService(Protocol):
    """Protocol for services that should only have synchronous methods."""

    def __call__(self, *args: Any, **kwargs: Any) -> Any:
        """Synchronous method calls only."""
        ...


class AsyncOnlyService(Protocol):
    """Protocol for services that should only have asynchronous methods."""

    async def __call__(self, *args: Any, **kwargs: Any) -> Any:
        """Asynchronous method calls only."""
        ...


class SafeSessionService:
    """Safe session service implementation that prevents coroutine warnings."""

    def __init__(self, session_data: dict[str, Any] | None = None) -> None:
        self._session_data = session_data or {}
        self.authenticated = True
        self.user_id = "test-user"

    def get(self, key: str, default: Any = None) -> Any:
        """Get session data synchronously."""
        return self._session_data.get(key, default)

    def set(self, key: str, value: Any) -> None:
        """Set session data synchronously."""
        self._session_data[key] = value

    def clear(self) -> None:
        """Clear session data synchronously."""
        self._session_data.clear()

    @property
    def is_authenticated(self) -> bool:
        """Check if session is authenticated."""
        return self.authenticated


class MockValidationError(Exception):
    """Exception raised when mock validation fails."""


class EnforcedMockFactory:
    """Factory for creating properly configured mocks that prevent coroutine warnings."""

    @staticmethod
    def create_sync_mock(spec: type | None = None, **kwargs: Any) -> Mock:
        """Create a synchronous mock that prevents async usage."""
        mock = Mock(spec=spec, **kwargs)

        # Ensure no async behavior is accidentally introduced
        if hasattr(mock, "__aenter__") or hasattr(mock, "__aexit__"):
            raise MockValidationError(
                f"Sync mock for {spec} should not have async context manager methods"
            )

        return mock

    @staticmethod
    def create_async_mock(spec: type | None = None, **kwargs: Any) -> AsyncMock:
        """Create an asynchronous mock for async services."""
        return AsyncMock(spec=spec, **kwargs)

    @staticmethod
    def create_session_mock(**kwargs: Any) -> SafeSessionService:
        """Create a safe session service mock."""
        return SafeSessionService(**kwargs)

    @classmethod
    def auto_mock(cls, service_class: type) -> MockType:
        """Automatically create the appropriate mock type based on service inspection."""
        if cls._is_async_service(service_class):
            return cls.create_async_mock(spec=service_class)
        else:
            return cls.create_sync_mock(spec=service_class)

    @staticmethod
    def _is_async_service(service_class: type) -> bool:
        """Check if a service class has primarily async methods."""
        async_methods = 0
        sync_methods = 0

        for name, method in inspect.getmembers(service_class, inspect.isfunction):
            if not name.startswith("_"):  # Skip private methods
                if inspect.iscoroutinefunction(method):
                    async_methods += 1
                else:
                    sync_methods += 1

        # Consider a service async if it has more async methods than sync
        return async_methods > sync_methods


class ValidatedTestStage(ABC):
    """Base class for test stages with automatic validation of service configurations."""

    def __init__(self) -> None:
        self._services: dict[str, Any] = {}
        self._validation_enabled = True

    def register_service(
        self, name: str, service: Any, force_sync: bool = False
    ) -> None:
        """Register a service with automatic validation."""
        if self._validation_enabled:
            validated_service = self._validate_service(service, name, force_sync)
            self._services[name] = validated_service
        else:
            self._services[name] = service

    def get_service(self, name: str) -> Any:
        """Get a registered service."""
        return self._services.get(name)

    def _validate_service(
        self, service: Any, name: str, force_sync: bool = False
    ) -> Any:
        """Validate that service mocks are properly configured."""
        # Check for common problematic patterns
        if isinstance(service, AsyncMock) and (
            force_sync or self._should_be_sync_service(name)
        ):
            warnings.warn(
                f"Service '{name}' is using AsyncMock but should be synchronous. "
                f"Consider using EnforcedMockFactory.create_sync_mock() instead.",
                UserWarning,
                stacklevel=3,
            )
            # Auto-fix: convert to sync mock
            return EnforcedMockFactory.create_sync_mock(spec=type(service))

        # Special handling for session services
        if name.lower() in ["session", "session_service"] and not isinstance(
            service, SafeSessionService
        ):
            warnings.warn(
                f"Session service '{name}' should use SafeSessionService to prevent coroutine warnings.",
                UserWarning,
                stacklevel=3,
            )
            # Auto-fix: convert to safe session service
            return EnforcedMockFactory.create_session_mock()

        return service

    def _should_be_sync_service(self, service_name: str) -> bool:
        """Determine if a service should be synchronous based on naming conventions."""
        sync_patterns = [
            "session",
            "config",
            "registry",
            "cache",
            "validator",
            "parser",
            "formatter",
            "logger",
            "metrics",
        ]
        return any(pattern in service_name.lower() for pattern in sync_patterns)

    @abstractmethod
    def setup(self) -> None:
        """Set up the test stage. Must be implemented by subclasses."""


class MockBackendTestStage(ValidatedTestStage):
    """Test stage for full mock environments."""

    def setup(self) -> None:
        """Set up mock backend services."""
        # Register common services with proper mock types
        self.register_service(
            "session_service",
            EnforcedMockFactory.create_session_mock(),
            force_sync=True,
        )

        self.register_service(
            "config_service", EnforcedMockFactory.create_sync_mock(), force_sync=True
        )

        self.register_service(
            "backend_registry", EnforcedMockFactory.create_sync_mock(), force_sync=True
        )


class RealBackendTestStage(ValidatedTestStage):
    """Test stage for tests requiring real backend calls with HTTPX mocking."""

    def setup(self) -> None:
        """Set up test stage with real backend support."""
        # Use real session service to avoid coroutine warnings
        self.register_service(
            "session_service", SafeSessionService({"test_mode": True}), force_sync=True
        )

        # Mock only the HTTP layer, not the service layer
        self.register_service(
            "http_client", EnforcedMockFactory.create_async_mock(), force_sync=False
        )


class CoroutineWarningDetector:
    """Utility for detecting and preventing coroutine warning patterns."""

    @staticmethod
    def check_for_unawaited_coroutines(obj: Any) -> list[str]:
        """Check an object for patterns that might cause unawaited coroutine warnings."""
        warnings_found = []

        if hasattr(obj, "__dict__"):
            for attr_name, attr_value in obj.__dict__.items():
                if inspect.iscoroutine(attr_value):
                    warnings_found.append(
                        f"Unawaited coroutine found in attribute '{attr_name}'"
                    )
                elif isinstance(
                    attr_value, AsyncMock
                ) and not asyncio.iscoroutinefunction(getattr(obj, attr_name, None)):
                    warnings_found.append(
                        f"AsyncMock used for non-async attribute '{attr_name}'"
                    )

        return warnings_found

    @staticmethod
    def validate_mock_setup(mock_obj: MockType, expected_type: type) -> bool:
        """Validate that a mock is set up correctly for its expected type."""
        if inspect.iscoroutinefunction(expected_type.__init__):
            return isinstance(mock_obj, AsyncMock)
        else:
            return not isinstance(mock_obj, AsyncMock)


# Convenience imports for easy access
SafeTestSession = SafeSessionService

__all__ = [
    "AsyncOnlyService",
    "CoroutineWarningDetector",
    "EnforcedMockFactory",
    "MockBackendTestStage",
    "MockValidationError",
    "RealBackendTestStage",
    "SafeSessionService",
    "SafeTestSession",
    "SyncOnlyService",
    "ValidatedTestStage",
]
