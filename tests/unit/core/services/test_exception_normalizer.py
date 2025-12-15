"""Unit tests for ExceptionNormalizer service.

Validates behavior equivalence with BackendService._normalize_provider_exception.

Feature: backend-service-refactoring
Phase 9: Extract ExceptionNormalizer
"""

from __future__ import annotations

import time

from src.core.common.exceptions import (
    BackendError,
    InvalidRequestError,
    RateLimitExceededError,
)
from src.core.services.exception_normalizer import ExceptionNormalizer
from starlette.exceptions import HTTPException


class TestExceptionNormalizerBasics:
    """Basic functionality tests for ExceptionNormalizer."""

    def test_interface_implementation(self) -> None:
        """ExceptionNormalizer should implement IExceptionNormalizer."""
        from src.core.interfaces.exception_normalizer_interface import (
            IExceptionNormalizer,
        )

        normalizer = ExceptionNormalizer()
        assert isinstance(normalizer, IExceptionNormalizer)

    def test_normalize_method_exists(self) -> None:
        """ExceptionNormalizer should have normalize method."""
        normalizer = ExceptionNormalizer()
        assert hasattr(normalizer, "normalize")
        assert callable(normalizer.normalize)


class TestHTTP429Translation:
    """Tests for HTTP 429 to RateLimitExceededError translation."""

    def test_http_429_translates_to_rate_limit_error(self) -> None:
        """HTTP 429 should translate to RateLimitExceededError."""
        normalizer = ExceptionNormalizer()
        exc = HTTPException(status_code=429, detail={"message": "Rate limit hit"})

        result = normalizer.normalize(exc, "openai")

        assert isinstance(result, RateLimitExceededError)

    def test_http_429_includes_backend_in_details(self) -> None:
        """Translated 429 should include backend type in details."""
        normalizer = ExceptionNormalizer()
        exc = HTTPException(status_code=429, detail="Rate limited")

        result = normalizer.normalize(exc, "anthropic")

        assert isinstance(result, RateLimitExceededError)
        assert result.details.get("backend") == "anthropic"
        assert result.details.get("status_code") == 429

    def test_http_429_extracts_message_from_dict_message_key(self) -> None:
        """Should extract message from detail.message."""
        normalizer = ExceptionNormalizer()
        exc = HTTPException(status_code=429, detail={"message": "Too many requests"})

        result = normalizer.normalize(exc, "gemini")

        assert isinstance(result, RateLimitExceededError)
        assert "Too many requests" in result.message

    def test_http_429_extracts_message_from_nested_error(self) -> None:
        """Should extract message from detail.error.message."""
        normalizer = ExceptionNormalizer()
        exc = HTTPException(
            status_code=429,
            detail={"error": {"message": "Nested rate limit message"}},
        )

        result = normalizer.normalize(exc, "openai")

        assert isinstance(result, RateLimitExceededError)
        assert "Nested rate limit message" in result.message

    def test_http_429_uses_string_detail_as_message(self) -> None:
        """Should use string detail as message."""
        normalizer = ExceptionNormalizer()
        exc = HTTPException(status_code=429, detail="Plain rate limit message")

        result = normalizer.normalize(exc, "openai")

        assert isinstance(result, RateLimitExceededError)
        assert "Plain rate limit message" in result.message

    def test_http_429_default_message_when_no_detail(self) -> None:
        """Should provide default message when detail is None."""
        normalizer = ExceptionNormalizer()
        exc = HTTPException(status_code=429, detail=None)

        result = normalizer.normalize(exc, "openai")

        assert isinstance(result, RateLimitExceededError)
        assert result.message  # Should have some message

    def test_http_429_preserves_retry_after_header(self) -> None:
        """Should preserve Retry-After header as reset_at."""
        normalizer = ExceptionNormalizer()
        exc = HTTPException(status_code=429, detail="Rate limited")
        exc.headers = {"Retry-After": "60"}

        before = time.time()
        result = normalizer.normalize(exc, "openai")
        after = time.time()

        assert isinstance(result, RateLimitExceededError)
        assert result.reset_at is not None
        assert before + 60 <= result.reset_at <= after + 60 + 1

    def test_http_429_handles_lowercase_retry_after(self) -> None:
        """Should handle lowercase retry-after header."""
        normalizer = ExceptionNormalizer()
        exc = HTTPException(status_code=429, detail="Rate limited")
        exc.headers = {"retry-after": "30"}

        result = normalizer.normalize(exc, "openai")

        assert isinstance(result, RateLimitExceededError)
        assert result.reset_at is not None

    def test_http_429_handles_float_retry_after(self) -> None:
        """Should handle float Retry-After values."""
        normalizer = ExceptionNormalizer()
        exc = HTTPException(status_code=429, detail="Rate limited")
        exc.headers = {"Retry-After": "1.5"}

        result = normalizer.normalize(exc, "openai")

        assert isinstance(result, RateLimitExceededError)
        assert result.reset_at is not None

    def test_http_429_handles_invalid_retry_after(self) -> None:
        """Should handle invalid Retry-After values gracefully."""
        normalizer = ExceptionNormalizer()
        exc = HTTPException(status_code=429, detail="Rate limited")
        exc.headers = {"Retry-After": "invalid"}

        result = normalizer.normalize(exc, "openai")

        assert isinstance(result, RateLimitExceededError)
        # reset_at should be None when Retry-After is invalid
        assert result.reset_at is None

    def test_http_429_includes_headers_in_details(self) -> None:
        """Should include allowlisted headers in details when present."""
        normalizer = ExceptionNormalizer()
        exc = HTTPException(status_code=429, detail="Rate limited")
        exc.headers = {"Retry-After": "60", "X-RateLimit-Reset": "1234567890"}

        result = normalizer.normalize(exc, "openai")

        assert isinstance(result, RateLimitExceededError)
        assert "headers" in result.details
        assert result.details["headers"].get("Retry-After") == "60"
        assert "X-RateLimit-Reset" not in result.details["headers"]


class TestHTTP4xxTranslation:
    """Tests for HTTP 4xx to InvalidRequestError translation."""

    def test_http_400_translates_to_invalid_request_error(self) -> None:
        """HTTP 400 should translate to InvalidRequestError."""
        normalizer = ExceptionNormalizer()
        exc = HTTPException(status_code=400, detail="Bad request")

        result = normalizer.normalize(exc, "openai")

        assert isinstance(result, InvalidRequestError)

    def test_http_401_translates_to_invalid_request_error(self) -> None:
        """HTTP 401 should translate to InvalidRequestError."""
        normalizer = ExceptionNormalizer()
        exc = HTTPException(status_code=401, detail="Unauthorized")

        result = normalizer.normalize(exc, "openai")

        assert isinstance(result, InvalidRequestError)

    def test_http_403_translates_to_invalid_request_error(self) -> None:
        """HTTP 403 should translate to InvalidRequestError."""
        normalizer = ExceptionNormalizer()
        exc = HTTPException(status_code=403, detail="Forbidden")

        result = normalizer.normalize(exc, "openai")

        assert isinstance(result, InvalidRequestError)

    def test_http_404_translates_to_invalid_request_error(self) -> None:
        """HTTP 404 should translate to InvalidRequestError."""
        normalizer = ExceptionNormalizer()
        exc = HTTPException(status_code=404, detail="Not found")

        result = normalizer.normalize(exc, "openai")

        assert isinstance(result, InvalidRequestError)

    def test_http_422_translates_to_invalid_request_error(self) -> None:
        """HTTP 422 should translate to InvalidRequestError."""
        normalizer = ExceptionNormalizer()
        exc = HTTPException(status_code=422, detail="Unprocessable entity")

        result = normalizer.normalize(exc, "openai")

        assert isinstance(result, InvalidRequestError)

    def test_http_4xx_includes_backend_and_status_in_details(self) -> None:
        """4xx errors should include backend and status_code in details."""
        normalizer = ExceptionNormalizer()
        exc = HTTPException(status_code=400, detail="Bad request")

        result = normalizer.normalize(exc, "anthropic")

        assert isinstance(result, InvalidRequestError)
        assert result.details.get("backend") == "anthropic"
        assert result.details.get("status_code") == 400

    def test_http_4xx_extracts_message_from_dict(self) -> None:
        """Should extract message from detail dict."""
        normalizer = ExceptionNormalizer()
        exc = HTTPException(status_code=400, detail={"message": "Invalid parameter"})

        result = normalizer.normalize(exc, "openai")

        assert isinstance(result, InvalidRequestError)
        assert "Invalid parameter" in result.message


class TestHTTP5xxTranslation:
    """Tests for HTTP 5xx to BackendError translation."""

    def test_http_500_translates_to_backend_error(self) -> None:
        """HTTP 500 should translate to BackendError."""
        normalizer = ExceptionNormalizer()
        exc = HTTPException(status_code=500, detail="Internal server error")

        result = normalizer.normalize(exc, "openai")

        assert isinstance(result, BackendError)

    def test_http_502_translates_to_backend_error(self) -> None:
        """HTTP 502 should translate to BackendError."""
        normalizer = ExceptionNormalizer()
        exc = HTTPException(status_code=502, detail="Bad gateway")

        result = normalizer.normalize(exc, "openai")

        assert isinstance(result, BackendError)

    def test_http_503_translates_to_backend_error(self) -> None:
        """HTTP 503 should translate to BackendError."""
        normalizer = ExceptionNormalizer()
        exc = HTTPException(status_code=503, detail="Service unavailable")

        result = normalizer.normalize(exc, "openai")

        assert isinstance(result, BackendError)

    def test_http_504_translates_to_backend_error(self) -> None:
        """HTTP 504 should translate to BackendError."""
        normalizer = ExceptionNormalizer()
        exc = HTTPException(status_code=504, detail="Gateway timeout")

        result = normalizer.normalize(exc, "openai")

        assert isinstance(result, BackendError)

    def test_http_5xx_includes_backend_name(self) -> None:
        """5xx errors should include backend_name."""
        normalizer = ExceptionNormalizer()
        exc = HTTPException(status_code=500, detail="Error")

        result = normalizer.normalize(exc, "gemini-oauth")

        assert isinstance(result, BackendError)
        assert result.backend_name == "gemini-oauth"

    def test_http_5xx_includes_status_code(self) -> None:
        """5xx errors should include status_code."""
        normalizer = ExceptionNormalizer()
        exc = HTTPException(status_code=503, detail="Error")

        result = normalizer.normalize(exc, "openai")

        assert isinstance(result, BackendError)
        assert result.status_code == 503


class TestPassthrough:
    """Tests for exception passthrough behavior."""

    def test_backend_error_passes_through(self) -> None:
        """BackendError should pass through unchanged."""
        normalizer = ExceptionNormalizer()
        exc = BackendError(message="Already backend error", backend_name="test")

        result = normalizer.normalize(exc, "openai")

        assert result is exc

    def test_rate_limit_error_passes_through(self) -> None:
        """RateLimitExceededError should pass through unchanged."""
        normalizer = ExceptionNormalizer()
        exc = RateLimitExceededError(message="Already rate limit error")

        result = normalizer.normalize(exc, "openai")

        assert result is exc

    def test_generic_exception_passes_through(self) -> None:
        """Generic exceptions should pass through unchanged."""
        normalizer = ExceptionNormalizer()
        exc = ValueError("Not an HTTP exception")

        result = normalizer.normalize(exc, "openai")

        assert result is exc

    def test_runtime_error_passes_through(self) -> None:
        """RuntimeError should pass through unchanged."""
        normalizer = ExceptionNormalizer()
        exc = RuntimeError("Runtime error")

        result = normalizer.normalize(exc, "openai")

        assert result is exc


class TestEquivalenceWithBackendService:
    """Tests verifying behavior equivalence with BackendService._normalize_provider_exception."""

    def test_equivalent_429_handling(self) -> None:
        """ExceptionNormalizer should match BackendService 429 handling."""
        normalizer = ExceptionNormalizer()

        # Test case matching BackendService behavior
        exc = HTTPException(
            status_code=429,
            detail={"error": {"message": "Rate limit exceeded"}},
        )
        exc.headers = {"Retry-After": "10"}

        result = normalizer.normalize(exc, "gemini")

        assert isinstance(result, RateLimitExceededError)
        assert "Rate limit exceeded" in result.message
        assert result.details.get("backend") == "gemini"
        assert result.reset_at is not None

    def test_equivalent_4xx_handling(self) -> None:
        """ExceptionNormalizer should match BackendService 4xx handling."""
        normalizer = ExceptionNormalizer()

        exc = HTTPException(
            status_code=400,
            detail={"message": "Invalid model specified"},
        )

        result = normalizer.normalize(exc, "openai")

        assert isinstance(result, InvalidRequestError)
        assert "Invalid model specified" in result.message
        assert result.details.get("backend") == "openai"
        assert result.details.get("status_code") == 400

    def test_equivalent_5xx_handling(self) -> None:
        """ExceptionNormalizer should match BackendService 5xx handling."""
        normalizer = ExceptionNormalizer()

        exc = HTTPException(
            status_code=502,
            detail="Upstream server error",
        )

        result = normalizer.normalize(exc, "anthropic")

        assert isinstance(result, BackendError)
        assert "Upstream server error" in result.message
        assert result.backend_name == "anthropic"
        assert result.status_code == 502
