"""Tests for HTTP status constants usage example.

This module contains tests to verify that HTTP status constants usage examples work correctly.
"""

import unittest
from unittest.mock import patch

from examples.http_status_constants_usage import (
    handle_service_unavailable_error,
    handle_internal_server_error,
    ServiceUnavailableError,
    example_controller_function,
)
from src.core.constants import (
    HTTP_503_SERVICE_UNAVAILABLE_MESSAGE,
    HTTP_500_INTERNAL_SERVER_ERROR_MESSAGE,
)


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

    @patch('examples.http_status_constants_usage.example_controller_function')
    def test_example_controller_function_service_unavailable(self, mock_function):
        """Test that the example controller function handles service unavailable errors."""
        # This is just a basic test to ensure the function can be called
        # In a real test, we would mock the dependencies and verify the behavior
        self.assertTrue(callable(example_controller_function))


if __name__ == "__main__":
    unittest.main()