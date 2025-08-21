# HTTP Status Constants

This module contains constants for common HTTP status messages to make the test suite less fragile and more maintainable.

## Purpose

The HTTP status constants provide standardized messages for HTTP status codes used throughout the application. This approach:

1. **Reduces Test Fragility**: Tests can reference these constants instead of hardcoded strings
2. **Improves Maintainability**: All HTTP status messages are centralized in one location
3. **Ensures Consistency**: Standardized error message formats across the entire codebase
4. **Reduces Duplication**: Eliminates duplicate HTTP status message strings throughout the codebase

## Usage

```python
from src.core.constants import HTTP_503_SERVICE_UNAVAILABLE_MESSAGE

# In error handlers
def handle_service_unavailable():
    raise HTTPException(
        status_code=503,
        detail=HTTP_503_SERVICE_UNAVAILABLE_MESSAGE
    )

# In tests
def test_service_unavailable_error():
    assert error_message == HTTP_503_SERVICE_UNAVAILABLE_MESSAGE
```

## Available Constants

### 2xx Success
- `HTTP_200_OK_MESSAGE` = "OK"
- `HTTP_201_CREATED_MESSAGE` = "Created"
- `HTTP_202_ACCEPTED_MESSAGE` = "Accepted"
- `HTTP_204_NO_CONTENT_MESSAGE` = "No Content"

### 4xx Client Errors
- `HTTP_400_BAD_REQUEST_MESSAGE` = "Bad Request"
- `HTTP_401_UNAUTHORIZED_MESSAGE` = "Unauthorized"
- `HTTP_403_FORBIDDEN_MESSAGE` = "Forbidden"
- `HTTP_404_NOT_FOUND_MESSAGE` = "Not Found"
- `HTTP_422_UNPROCESSABLE_ENTITY_MESSAGE` = "Unprocessable Entity"
- `HTTP_429_TOO_MANY_REQUESTS_MESSAGE` = "Too Many Requests"

### 5xx Server Errors
- `HTTP_500_INTERNAL_SERVER_ERROR_MESSAGE` = "Internal Server Error"
- `HTTP_501_NOT_IMPLEMENTED_MESSAGE` = "Not Implemented"
- `HTTP_502_BAD_GATEWAY_MESSAGE` = "Bad Gateway"
- `HTTP_503_SERVICE_UNAVAILABLE_MESSAGE` = "Service Unavailable"
- `HTTP_504_GATEWAY_TIMEOUT_MESSAGE` = "Gateway Timeout"

## Adding New Constants

To add new HTTP status constants:

1. Add the constant to `src/core/constants/http_status_constants.py`
2. Update the `__init__.py` file in the constants directory if needed
3. Add tests in `tests/unit/test_http_status_constants.py`
4. Update this README documentation

## Benefits

1. **Reduced Test Fragility**: Tests now use standardized HTTP status message formats instead of hardcoded strings
2. **Improved Maintainability**: All HTTP status messages are centralized in one location, making updates easier
3. **Better Consistency**: Standardized HTTP status message formats across the entire codebase
4. **Reduced Duplication**: Eliminated duplicate HTTP status message strings throughout the codebase