"""
Unit tests for GeminiErrorMapper.

Tests verify error mapping behavior including exception type handling,
status code preservation, and error code preservation.

Note: map_exception returns LLMProxyError instances (except HTTPException
which is raised for FastAPI compatibility). Callers are responsible for
raising the returned exceptions.
"""

from unittest.mock import Mock

import pytest
from fastapi import HTTPException
from src.connectors.gemini_base.error_mapper import GeminiErrorMapper
from src.core.common.exceptions import (
    AuthenticationError,
    BackendError,
    InvalidRequestError,
    LLMProxyError,
)


@pytest.fixture
def error_mapper():
    """Create a GeminiErrorMapper instance."""
    return GeminiErrorMapper()


@pytest.fixture
def error_mapper_with_logger():
    """Create a GeminiErrorMapper instance with custom logger."""
    logger = Mock()
    return GeminiErrorMapper(logger_instance=logger)


class TestMapException:
    """Test map_exception method."""

    def test_http_exception_re_raised(self, error_mapper):
        """Verify HTTPException is re-raised as-is."""
        http_exc = HTTPException(status_code=400, detail="Bad request")

        with pytest.raises(HTTPException) as exc_info:
            error_mapper.map_exception(http_exc, backend_name="test-backend")

        assert exc_info.value is http_exc
        assert exc_info.value.status_code == 400

    def test_authentication_error_returned(self, error_mapper):
        """Verify AuthenticationError is returned as-is."""
        auth_error = AuthenticationError(
            message="Authentication failed",
            details={"reason": "invalid_token"},
        )

        result = error_mapper.map_exception(auth_error, backend_name="test-backend")

        assert result is auth_error
        assert result.status_code == 401

    def test_backend_error_returned(self, error_mapper):
        """Verify BackendError is returned as-is."""
        backend_error = BackendError(
            message="Backend operation failed",
            backend_name="test-backend",
            code="backend_error",
            status_code=502,
        )

        result = error_mapper.map_exception(backend_error, backend_name="test-backend")

        assert result is backend_error
        assert result.status_code == 502
        assert result.code == "backend_error"

    def test_invalid_request_error_returned(self, error_mapper):
        """Verify InvalidRequestError is returned as-is."""
        invalid_error = InvalidRequestError(
            message="Invalid request",
            details={"field": "model"},
            status_code=400,
        )

        result = error_mapper.map_exception(invalid_error, backend_name="test-backend")

        assert result is invalid_error
        assert result.status_code == 400

    def test_generic_exception_mapped_to_backend_error(self, error_mapper):
        """Verify generic Exception is mapped to BackendError."""
        generic_error = ValueError("Something went wrong")

        result = error_mapper.map_exception(generic_error, backend_name="test-backend")

        assert isinstance(result, BackendError)
        assert isinstance(result, LLMProxyError)
        assert "test-backend chat completion failed" in result.message
        assert result.backend_name == "test-backend"
        # Note: Exception chaining is not preserved when returning (only when raising)
        # The original error is included in the message instead

    def test_generic_exception_logs_with_exc_info(self, error_mapper_with_logger):
        """Verify generic exceptions are logged with exc_info=True."""
        generic_error = RuntimeError("Runtime error occurred")

        result = error_mapper_with_logger.map_exception(
            generic_error, backend_name="test-backend"
        )

        # Verify result is BackendError
        assert isinstance(result, BackendError)

        # Verify logger was called with exc_info=True
        error_mapper_with_logger._logger.error.assert_called_once()
        call_kwargs = error_mapper_with_logger._logger.error.call_args[1]
        assert call_kwargs.get("exc_info") is True

    def test_status_code_preserved_in_backend_error(self, error_mapper):
        """Verify status codes are preserved when returning BackendError."""
        backend_error = BackendError(
            message="Rate limit exceeded",
            backend_name="test-backend",
            status_code=429,
        )

        result = error_mapper.map_exception(backend_error, backend_name="test-backend")

        assert result.status_code == 429

    def test_error_code_preserved_in_backend_error(self, error_mapper):
        """Verify error codes are preserved when returning BackendError."""
        backend_error = BackendError(
            message="Model not found",
            backend_name="test-backend",
            code="model_not_found",
            status_code=400,
        )

        result = error_mapper.map_exception(backend_error, backend_name="test-backend")

        assert result.code == "model_not_found"

    def test_custom_exception_mapped_to_backend_error(self, error_mapper):
        """Verify custom exceptions are mapped to BackendError."""

        class CustomError(Exception):
            pass

        custom_error = CustomError("Custom error message")

        result = error_mapper.map_exception(custom_error, backend_name="test-backend")

        assert isinstance(result, BackendError)
        assert "test-backend chat completion failed" in result.message
        # Note: Exception chaining is not preserved when returning (only when raising)
        # The original error is included in the message instead

    def test_backend_name_in_error_message(self, error_mapper):
        """Verify backend name is included in mapped error message."""
        generic_error = KeyError("missing_key")

        result = error_mapper.map_exception(generic_error, backend_name="my-backend")

        assert "my-backend chat completion failed" in result.message
        assert result.backend_name == "my-backend"
