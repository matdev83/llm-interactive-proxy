"""
Security middleware for enforcing access control and proper state management.

This module provides middleware that enforces security boundaries between
different layers of the application, ensuring that:

1. Domain layer doesn't access infrastructure directly
2. State access is properly controlled through interfaces
3. Security boundaries are maintained through dependency injection

This moves the security enforcement from the domain layer to the infrastructure layer,
adhering to proper separation of concerns and SOLID principles.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import TypeVar

from fastapi import FastAPI, Request, Response
from src.core.interfaces.application_state_interface import IApplicationState
from src.core.interfaces.state_provider_interface import (
    ISecureStateAccess,
    ISecureStateModification,
)
from src.core.services.secure_state_service import StateAccessProxy

T = TypeVar("T")


class SecurityMiddleware:
    """
    Middleware to enforce security boundaries and prevent direct state access.

    This middleware intercepts requests and applies the StateAccessProxy to
    app.state, ensuring that state can only be accessed through proper interfaces.
    """

    def __init__(
        self,
        app: FastAPI,
        allowed_interfaces: list[type] | None = None,
    ):
        """
        Initialize the security middleware.

        Args:
            app: The FastAPI application
            allowed_interfaces: List of interfaces that are allowed to access state directly
        """
        self.app = app
        self.allowed_interfaces = allowed_interfaces or [
            ISecureStateAccess,
            ISecureStateModification,
            IApplicationState,
        ]

    async def __call__(
        self, request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        """
        Process a request, securing app.state access during handling.

        Args:
            request: The incoming request
            call_next: The next middleware or endpoint handler

        Returns:
            The response
        """
        # Replace app.state with the secure proxy before processing
        original_state = request.app.state

        # Use strict proxy in all environments
        request.app.state = StateAccessProxy(original_state, self.allowed_interfaces)

        try:
            # Process the request with secure state
            response = await call_next(request)
            return response
        finally:
            # Restore the original state for next request
            request.app.state = original_state


def add_security_middleware(
    app: FastAPI, allowed_interfaces: list[type] | None = None
) -> None:
    """
    Add security middleware to a FastAPI application.

    This is a convenience function to add the security middleware to an app.

    Args:
        app: The FastAPI application
        allowed_interfaces: List of interfaces that are allowed to access state directly
    """
    middleware = SecurityMiddleware(
        app,
        allowed_interfaces=allowed_interfaces,
    )
    app.middleware("http")(middleware.__call__)
