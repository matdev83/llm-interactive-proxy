"""Example usage of HTTP status constants in controller-style helpers.

This module exists solely to satisfy unit tests that validate how constants are
referenced and used. The functions raise Exceptions embedding the constants so
tests can assert their presence without coupling to a specific web framework.
"""

from __future__ import annotations

from src.core.constants import (
    HTTP_500_INTERNAL_SERVER_ERROR_MESSAGE,
    HTTP_503_SERVICE_UNAVAILABLE_MESSAGE,
)


def handle_service_unavailable_error(service_name: str) -> None:
    """Raise an exception indicating the service is unavailable.

    Args:
        service_name: Human-readable service name
    """
    raise Exception(
        f"{HTTP_503_SERVICE_UNAVAILABLE_MESSAGE}: {service_name} not available"
    )


def handle_internal_server_error(error_message: str) -> None:
    """Raise an exception representing an internal server error condition."""
    raise Exception(f"{HTTP_500_INTERNAL_SERVER_ERROR_MESSAGE}: {error_message}")


def example_controller_function(*args, **kwargs):  # type: ignore[no-untyped-def]
    """Dummy controller-like function present so it can be patched in tests."""
    return None
