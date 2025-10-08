"""
Tests for Exception Adapters module.

This module tests the exception handling and conversion functions.
"""

import json
from unittest.mock import Mock

import pytest
from fastapi import Request
from fastapi.responses import JSONResponse
from src.core.adapters.exception_adapters import (
    create_exception_handler,
    register_exception_handlers,
)
from src.core.common.exceptions import (
    AuthenticationError,
    BackendError,
    ConfigurationError,
    LLMProxyError,
    LoopDetectionError,
    RateLimitExceededError,
    ServiceUnavailableError,
)
from starlette.exceptions import HTTPException as StarletteHTTPException


class TestCreateExceptionHandler:
    """Tests for create_exception_handler function."""

    @pytest.fixture
    def mock_request(self) -> Mock:
        """Create a mock FastAPI request."""
        request = Mock(spec=Request)
        request.url = Mock()
        request.url.path = "/test"
        return request

    @pytest.fixture
    def exception_handler(self):
        """Create an exception handler."""
        return create_exception_handler()

    @pytest.mark.asyncio
    async def test_handle_llm_proxy_error(
        self, mock_request: Mock, exception_handler
    ) -> None:
        """Test handling LLMProxyError."""
        error = LLMProxyError(
            message="Test error",
            status_code=400,
            code="test_error",
        )

        response = await exception_handler(mock_request, error)

        assert isinstance(response, JSONResponse)
        assert response.status_code == 400
        content = response.body.decode()
        assert "Test error" in content
        assert "test_error" in content

    @pytest.mark.asyncio
    async def test_handle_rate_limit_error_with_reset(
        self, mock_request: Mock, exception_handler, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Test handling RateLimitExceededError with reset time."""
        monkeypatch.setattr(
            "src.core.adapters.exception_adapters.time.time",
            lambda: 100.0,
        )
        error = RateLimitExceededError(
            message="Rate limit exceeded",
            reset_at=160.0,
        )

        response = await exception_handler(mock_request, error)

        assert isinstance(response, JSONResponse)
        assert response.status_code == 429
        assert "Retry-After" in response.headers
        assert response.headers["Retry-After"] == "60"

    @pytest.mark.asyncio
    async def test_handle_rate_limit_error_without_reset(
        self, mock_request: Mock, exception_handler
    ) -> None:
        """Test handling RateLimitExceededError without reset time."""
        error = RateLimitExceededError(
            message="Rate limit exceeded",
            reset_at=None,
        )

        response = await exception_handler(mock_request, error)

        assert isinstance(response, JSONResponse)
        assert response.status_code == 429
        assert "Retry-After" not in response.headers

    @pytest.mark.asyncio
    async def test_handle_rate_limit_error_with_expired_reset(
        self,
        mock_request: Mock,
        exception_handler,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Test handling RateLimitExceededError when reset time is in the past."""
        current_time = 1_700_000_500.0
        monkeypatch.setattr(
            "src.core.adapters.exception_adapters.time.time",
            lambda: current_time,
        )

        error = RateLimitExceededError(
            message="Rate limit exceeded",
            reset_at=current_time - 100.0,
        )

        response = await exception_handler(mock_request, error)

        assert isinstance(response, JSONResponse)
        assert response.status_code == 429
        assert response.headers["Retry-After"] == "0"

    @pytest.mark.asyncio
    async def test_handle_authentication_error(
        self, mock_request: Mock, exception_handler
    ) -> None:
        """Test handling AuthenticationError."""
        error = AuthenticationError(
            message="Authentication failed",
            code="auth_error",
        )

        response = await exception_handler(mock_request, error)

        assert isinstance(response, JSONResponse)
        assert response.status_code == 401
        content = response.body.decode()
        assert "Authentication failed" in content

    @pytest.mark.asyncio
    async def test_handle_backend_error(
        self, mock_request: Mock, exception_handler
    ) -> None:
        """Test handling BackendError."""
        error = BackendError(
            message="Backend unavailable",
            backend_name="test_backend",
            status_code=502,
        )

        response = await exception_handler(mock_request, error)

        assert isinstance(response, JSONResponse)
        assert response.status_code == 502
        content = response.body.decode()
        assert "Backend unavailable" in content

    @pytest.mark.asyncio
    async def test_handle_configuration_error(
        self, mock_request: Mock, exception_handler
    ) -> None:
        """Test handling ConfigurationError."""
        error = ConfigurationError(
            message="Configuration invalid",
            details={"config_key": "test_key"},
        )

        response = await exception_handler(mock_request, error)

        assert isinstance(response, JSONResponse)
        assert response.status_code == 400
        content = response.body.decode()
        assert "Configuration invalid" in content

    @pytest.mark.asyncio
    async def test_handle_service_unavailable_error(
        self, mock_request: Mock, exception_handler
    ) -> None:
        """Test handling ServiceUnavailableError."""
        error = ServiceUnavailableError(
            message="Service unavailable",
            code="service_unavailable",
        )

        response = await exception_handler(mock_request, error)

        assert isinstance(response, JSONResponse)
        assert response.status_code == 503
        content = response.body.decode()
        assert "Service unavailable" in content

    @pytest.mark.asyncio
    async def test_handle_loop_detection_error(
        self, mock_request: Mock, exception_handler
    ) -> None:
        """Test handling LoopDetectionError."""
        error = LoopDetectionError(
            message="Loop detected",
            pattern="repeating pattern",
            repetitions=5,
        )

        response = await exception_handler(mock_request, error)

        assert isinstance(response, JSONResponse)
        assert response.status_code == 400
        content = response.body.decode()
        assert "Loop detected" in content

    @pytest.mark.asyncio
    async def test_handle_fastapi_http_exception(
        self, mock_request: Mock, exception_handler
    ) -> None:
        """Test handling FastAPI HTTPException."""
        error = StarletteHTTPException(
            status_code=404,
            detail="Not found",
        )

        response = await exception_handler(mock_request, error)

        assert isinstance(response, JSONResponse)
        assert response.status_code == 404
        content = response.body.decode()
        assert "Not found" in content

    @pytest.mark.asyncio
    async def test_handle_fastapi_http_exception_with_dict_detail(
        self, mock_request: Mock, exception_handler
    ) -> None:
        """Ensure dictionary details from HTTPException are preserved."""
        detail = {"error": {"message": "Detailed", "code": "X123"}}
        error = StarletteHTTPException(status_code=418, detail=detail)

        response = await exception_handler(mock_request, error)

        assert isinstance(response, JSONResponse)
        assert response.status_code == 418
        assert json.loads(response.body) == detail

    @pytest.mark.asyncio
    async def test_handle_generic_exception(
        self, mock_request: Mock, exception_handler
    ) -> None:
        """Test handling generic Exception."""
        error = ValueError("Something went wrong")

        response = await exception_handler(mock_request, error)

        assert isinstance(response, JSONResponse)
        assert response.status_code == 500
        content = response.body.decode()
        assert "An unexpected error occurred" in content


class TestRegisterExceptionHandlers:
    """Tests for register_exception_handlers function."""

    def test_register_exception_handlers(self) -> None:
        """Test registering exception handlers on a FastAPI app."""
        mock_app = Mock()

        register_exception_handlers(mock_app)

        # Verify that exception handlers were registered for all expected exception types
        expected_exceptions = [
            LLMProxyError,
            AuthenticationError,
            ConfigurationError,
            BackendError,
            RateLimitExceededError,
            ServiceUnavailableError,
            LoopDetectionError,
            StarletteHTTPException,
            Exception,
        ]

        for exc_type in expected_exceptions:
            mock_app.exception_handler.assert_any_call(exc_type)

        # Verify total number of calls
        assert mock_app.exception_handler.call_count == len(expected_exceptions)
