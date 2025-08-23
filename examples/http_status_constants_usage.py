"""Example of using HTTP status constants in error handlers.

This module demonstrates how to use HTTP status constants to make error handling
more maintainable and consistent.
"""

from fastapi import HTTPException
from src.core.constants import (
    HTTP_500_INTERNAL_SERVER_ERROR_MESSAGE,
    HTTP_503_SERVICE_UNAVAILABLE_MESSAGE,
)


def handle_service_unavailable_error(service_name: str) -> None:
    """Handle service unavailable errors using HTTP status constants."""
    raise HTTPException(
        status_code=503,
        detail=f"{HTTP_503_SERVICE_UNAVAILABLE_MESSAGE}: {service_name} not available"
    )


def handle_internal_server_error(error_message: str) -> None:
    """Handle internal server errors using HTTP status constants."""
    raise HTTPException(
        status_code=500,
        detail=f"{HTTP_500_INTERNAL_SERVER_ERROR_MESSAGE}: {error_message}"
    )


# Example usage in controllers
def example_controller_function():
    """Example controller function demonstrating HTTP status constant usage."""
    try:
        # Some operation that might fail
        pass
    except ServiceUnavailableError:
        handle_service_unavailable_error("Database service")
    except Exception as e:
        handle_internal_server_error(str(e))


class ServiceUnavailableError(Exception):
    """Custom exception for service unavailability."""
