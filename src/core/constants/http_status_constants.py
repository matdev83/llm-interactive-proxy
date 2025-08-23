"""Constants for HTTP status messages.

This module contains constants for common HTTP status messages to make the test suite
less fragile and more maintainable.
"""

# 2xx Success
HTTP_200_OK_MESSAGE = "OK"
HTTP_201_CREATED_MESSAGE = "Created"
HTTP_202_ACCEPTED_MESSAGE = "Accepted"
HTTP_204_NO_CONTENT_MESSAGE = "No Content"

# 4xx Client Errors
HTTP_400_BAD_REQUEST_MESSAGE = "Bad Request"
HTTP_401_UNAUTHORIZED_MESSAGE = "Unauthorized"
HTTP_403_FORBIDDEN_MESSAGE = "Forbidden"
HTTP_404_NOT_FOUND_MESSAGE = "Not Found"
HTTP_422_UNPROCESSABLE_ENTITY_MESSAGE = "Unprocessable Entity"
HTTP_429_TOO_MANY_REQUESTS_MESSAGE = "Too Many Requests"

# 5xx Server Errors
HTTP_500_INTERNAL_SERVER_ERROR_MESSAGE = "Internal Server Error"
HTTP_501_NOT_IMPLEMENTED_MESSAGE = "Not Implemented"
HTTP_502_BAD_GATEWAY_MESSAGE = "Bad Gateway"
HTTP_503_SERVICE_UNAVAILABLE_MESSAGE = "Service Unavailable"
HTTP_504_GATEWAY_TIMEOUT_MESSAGE = "Gateway Timeout"
