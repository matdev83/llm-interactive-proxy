"""Tests for HTTP status constants.

This module contains tests to verify that HTTP status constants are properly defined
and imported.
"""

import unittest

from src.core.constants.http_status_constants import (
    HTTP_200_OK_MESSAGE,
    HTTP_201_CREATED_MESSAGE,
    HTTP_202_ACCEPTED_MESSAGE,
    HTTP_204_NO_CONTENT_MESSAGE,
    HTTP_400_BAD_REQUEST_MESSAGE,
    HTTP_401_UNAUTHORIZED_MESSAGE,
    HTTP_403_FORBIDDEN_MESSAGE,
    HTTP_404_NOT_FOUND_MESSAGE,
    HTTP_422_UNPROCESSABLE_ENTITY_MESSAGE,
    HTTP_429_TOO_MANY_REQUESTS_MESSAGE,
    HTTP_500_INTERNAL_SERVER_ERROR_MESSAGE,
    HTTP_501_NOT_IMPLEMENTED_MESSAGE,
    HTTP_502_BAD_GATEWAY_MESSAGE,
    HTTP_503_SERVICE_UNAVAILABLE_MESSAGE,
    HTTP_504_GATEWAY_TIMEOUT_MESSAGE,
)


class TestHttpStatusConstants(unittest.TestCase):
    """Test cases for HTTP status constants."""

    def test_success_status_messages(self):
        """Test that success status messages are correctly defined."""
        self.assertEqual(HTTP_200_OK_MESSAGE, "OK")
        self.assertEqual(HTTP_201_CREATED_MESSAGE, "Created")
        self.assertEqual(HTTP_202_ACCEPTED_MESSAGE, "Accepted")
        self.assertEqual(HTTP_204_NO_CONTENT_MESSAGE, "No Content")

    def test_client_error_status_messages(self):
        """Test that client error status messages are correctly defined."""
        self.assertEqual(HTTP_400_BAD_REQUEST_MESSAGE, "Bad Request")
        self.assertEqual(HTTP_401_UNAUTHORIZED_MESSAGE, "Unauthorized")
        self.assertEqual(HTTP_403_FORBIDDEN_MESSAGE, "Forbidden")
        self.assertEqual(HTTP_404_NOT_FOUND_MESSAGE, "Not Found")
        self.assertEqual(HTTP_422_UNPROCESSABLE_ENTITY_MESSAGE, "Unprocessable Entity")
        self.assertEqual(HTTP_429_TOO_MANY_REQUESTS_MESSAGE, "Too Many Requests")

    def test_server_error_status_messages(self):
        """Test that server error status messages are correctly defined."""
        self.assertEqual(
            HTTP_500_INTERNAL_SERVER_ERROR_MESSAGE, "Internal Server Error"
        )
        self.assertEqual(HTTP_501_NOT_IMPLEMENTED_MESSAGE, "Not Implemented")
        self.assertEqual(HTTP_502_BAD_GATEWAY_MESSAGE, "Bad Gateway")
        self.assertEqual(HTTP_503_SERVICE_UNAVAILABLE_MESSAGE, "Service Unavailable")
        self.assertEqual(HTTP_504_GATEWAY_TIMEOUT_MESSAGE, "Gateway Timeout")


if __name__ == "__main__":
    unittest.main()
