"""
Test utilities for dependency injection.

This module provides helper functions for setting up tests with proper dependency injection,
avoiding direct app.state modifications.
"""

from typing import TypeVar
from unittest.mock import MagicMock, Mock

from fastapi import FastAPI
from src.core.di.container import ServiceProvider
from src.core.interfaces.application_state_interface import IApplicationState
from src.core.interfaces.backend_service_interface import IBackendService
from src.core.interfaces.session_service_interface import ISessionService
from src.core.services.application_state_service import ApplicationStateService
from src.core.services.sync_session_manager import SyncSessionManager
from src.rate_limit import RateLimitRegistry

T = TypeVar("T")


def get_service_from_app(app: FastAPI, service_type: type[T]) -> T | None:
    """
    Get a service from the app's DI container using proper dependency injection.

    Args:
        app: FastAPI application instance
        service_type: Type of service to retrieve

    Returns:
        Service instance or None if not found
    """
    service_provider = getattr(app.state, "service_provider", None)
    if service_provider:
        return service_provider.get_service(service_type)
    return None


def get_required_service_from_app(app: FastAPI, service_type: type[T]) -> T:
    """
    Get a required service from the app's DI container.

    Args:
        app: FastAPI application instance
        service_type: Type of service to retrieve

    Returns:
        Service instance

    Raises:
        ValueError: If service is not found
    """
    service = get_service_from_app(app, service_type)
    if service is None:
        raise ValueError(f"Required service {service_type.__name__} not found")
    return service


def configure_test_state(
    app: FastAPI,
    *,
    backend_type: str = "openrouter",
    disable_interactive_commands: bool = True,
    command_prefix: str = "!/",
    api_key_redaction_enabled: bool = False,
    backends: dict[str, Mock] | None = None,
    available_models: dict[str, list[str]] | None = None,
    functional_backends: list[str] | None = None,
) -> None:
    """
    Configure test state using proper DI instead of direct app.state manipulation.

    Args:
        app: FastAPI application instance
        backend_type: The backend type to use
        disable_interactive_commands: Whether interactive commands are disabled
        command_prefix: The command prefix to use
        api_key_redaction_enabled: Whether API key redaction is enabled
        backends: Dictionary of backend name to mock backend instance
        available_models: Dictionary of backend name to list of available models
        functional_backends: List of functional backend names
    """
    # Get or create application state service
    service_provider = getattr(app.state, "service_provider", None)
    if not service_provider:
        service_provider = ServiceProvider()
        app.state.service_provider = service_provider

    app_state = service_provider.get_service(IApplicationState)
    if not app_state:
        app_state = ApplicationStateService()
        service_provider.add_instance(IApplicationState, app_state)

    # Configure settings
    app_state.set_backend_type(backend_type)
    app_state.set_disable_interactive_commands(disable_interactive_commands)
    app_state.set_command_prefix(command_prefix)
    app_state.set_api_key_redaction_enabled(api_key_redaction_enabled)

    # Set up functional backends
    if functional_backends:
        app_state.set_functional_backends(functional_backends)

    # Set up mock backends
    if backends:
        backend_service = service_provider.get_service(IBackendService)
        if backend_service is None:
            backend_service = MagicMock()
            service_provider.add_instance(IBackendService, backend_service)

        # Add all backends to the backend service
        for backend_name, mock_backend in backends.items():
            # Add necessary methods to mock backend (not covered by spec)
            if not hasattr(mock_backend, "get_available_models"):
                mock_backend.get_available_models = Mock()

            # Configure model lists if provided
            if available_models and backend_name in available_models:
                mock_backend.get_available_models.return_value = available_models[
                    backend_name
                ]
            else:
                mock_backend.get_available_models.return_value = ["model1", "model2"]

            # Set the mock backend in the application state
            app_state.set_setting(f"{backend_name}_backend", mock_backend)

    # Ensure session manager is available
    session_service = service_provider.get_service(ISessionService)
    if session_service is None:
        mock_session_service = MagicMock(spec=ISessionService)
        service_provider.add_instance(ISessionService, mock_session_service)

        # Create SyncSessionManager for legacy code
        session_manager = SyncSessionManager(mock_session_service)
        app_state.set_setting("session_manager", session_manager)

    # Initialize rate limits
    rate_limits = app_state.get_setting("rate_limits")
    if not rate_limits:
        app_state.set_setting("rate_limits", RateLimitRegistry())
