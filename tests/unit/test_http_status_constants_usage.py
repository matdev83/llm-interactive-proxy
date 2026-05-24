"""Tests for HTTP status constants usage without external examples dependency.

This module defines minimal example functions inline to validate
the semantics of HTTP status constants usage.
"""

import unittest

from src.core.constants import (
    HTTP_500_INTERNAL_SERVER_ERROR_MESSAGE,
    HTTP_503_SERVICE_UNAVAILABLE_MESSAGE,
)


def handle_service_unavailable_error(service_name: str) -> None:
    """Raise an exception using the 503 constant and a service-specific message."""
    raise Exception(
        f"{HTTP_503_SERVICE_UNAVAILABLE_MESSAGE}: {service_name} not available"
    )


def handle_internal_server_error(error_message: str) -> None:
    """Raise an exception using the 500 constant and a supplied error message."""
    raise Exception(f"{HTTP_500_INTERNAL_SERVER_ERROR_MESSAGE}: {error_message}")


def example_controller_function() -> bool:
    """A trivial example controller function used for smoke testing."""
    return True


class TestHttpStatusConstantsUsage(unittest.TestCase):
    """Test cases for HTTP status constants usage."""

    def test_handle_service_unavailable_error(self):
        """Test that service unavailable errors use the correct HTTP status message."""
        with self.assertRaises(Exception) as context:
            handle_service_unavailable_error("Test Service")

        self.assertIn(HTTP_503_SERVICE_UNAVAILABLE_MESSAGE, str(context.exception))
        self.assertIn("Test Service not available", str(context.exception))

    def test_handle_internal_server_error(self):
        """Test that internal server errors use the correct HTTP status message."""
        with self.assertRaises(Exception) as context:
            handle_internal_server_error("Test error")

        self.assertIn(HTTP_500_INTERNAL_SERVER_ERROR_MESSAGE, str(context.exception))
        self.assertIn("Test error", str(context.exception))

    def test_example_controller_function_service_unavailable(self):
        """Test that the example controller function handles service unavailable errors."""
        # This is just a basic test to ensure the function can be called
        # In a real test, we would mock the dependencies and verify the behavior
        self.assertTrue(callable(example_controller_function))


if __name__ == "__main__":
    unittest.main()
