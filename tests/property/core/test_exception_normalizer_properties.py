"""Property-based tests for ExceptionNormalizer.

Validates:
- Property 13: Exception Translation (Requirements 12.1, 12.4)

Feature: backend-service-refactoring
"""

from __future__ import annotations

import time

from hypothesis import given, settings
from hypothesis import strategies as st
from starlette.exceptions import HTTPException

# Strategy for generating valid HTTP status codes
http_4xx_codes = st.integers(min_value=400, max_value=499).filter(lambda x: x != 429)
http_5xx_codes = st.integers(min_value=500, max_value=599)


# Strategy for generating error messages
error_messages = st.text(
    min_size=1,
    max_size=200,
    alphabet=st.characters(
        whitelist_categories=("L", "N", "P", "S", "Z"),
        whitelist_characters=" ",
    ),
)


# Strategy for generating backend types
backend_types = st.sampled_from(
    [
        "openai",
        "anthropic",
        "gemini",
        "gemini-oauth",
        "azure",
        "local",
    ]
)


# Strategy for generating retry-after values
retry_after_values = st.one_of(
    st.none(),
    st.integers(min_value=1, max_value=3600),
    st.floats(min_value=0.1, max_value=3600.0, allow_nan=False, allow_infinity=False),
)


class TestExceptionTranslationProperty:
    """Property 13: Exception Translation (Requirements 12.1, 12.4).

    For any provider exception, the normalizer SHALL translate it to
    the appropriate domain exception type based on HTTP status codes.
    """

    @given(
        backend_type=backend_types,
        message=error_messages,
    )
    @settings(max_examples=50, deadline=None)
    def test_http_429_translates_to_rate_limit_error(
        self, backend_type: str, message: str
    ) -> None:
        """HTTP 429 exceptions should be translated to RateLimitExceededError.

        Validates Requirements 12.1: Translate HTTPException 429 to RateLimitExceededError
        """
        from src.core.common.exceptions import RateLimitExceededError
        from src.core.services.exception_normalizer import ExceptionNormalizer

        normalizer = ExceptionNormalizer()

        # Create HTTP 429 exception
        exc = HTTPException(status_code=429, detail={"message": message})

        result = normalizer.normalize(exc, backend_type)

        assert isinstance(result, RateLimitExceededError)
        assert backend_type in str(result.details.get("backend", ""))

    @given(
        backend_type=backend_types,
        message=error_messages,
        retry_after=retry_after_values,
    )
    @settings(max_examples=50, deadline=None)
    def test_http_429_preserves_retry_after_header(
        self, backend_type: str, message: str, retry_after: float | int | None
    ) -> None:
        """HTTP 429 should preserve Retry-After header in reset_at.

        Validates Requirements 12.4: Preserve retry-after headers in rate limit errors
        """
        from src.core.common.exceptions import RateLimitExceededError
        from src.core.services.exception_normalizer import ExceptionNormalizer

        normalizer = ExceptionNormalizer()

        # Create HTTP 429 exception with headers
        exc = HTTPException(status_code=429, detail={"message": message})
        if retry_after is not None:
            exc.headers = {"Retry-After": str(retry_after)}

        before_time = time.time()
        result = normalizer.normalize(exc, backend_type)
        after_time = time.time()

        assert isinstance(result, RateLimitExceededError)

        if retry_after is not None:
            # reset_at should be approximately now + retry_after
            assert result.reset_at is not None
            expected_min = before_time + float(retry_after)
            expected_max = after_time + float(retry_after)
            assert expected_min <= result.reset_at <= expected_max + 1

    @given(
        backend_type=backend_types,
        status_code=http_4xx_codes,
        message=error_messages,
    )
    @settings(max_examples=50, deadline=None)
    def test_http_4xx_translates_to_invalid_request_error(
        self, backend_type: str, status_code: int, message: str
    ) -> None:
        """HTTP 4xx (non-429) exceptions should be translated to InvalidRequestError.

        Validates Requirements 12.2: Translate HTTPException 4xx to InvalidRequestError
        """
        from src.core.common.exceptions import InvalidRequestError
        from src.core.services.exception_normalizer import ExceptionNormalizer

        normalizer = ExceptionNormalizer()

        exc = HTTPException(status_code=status_code, detail={"message": message})

        result = normalizer.normalize(exc, backend_type)

        assert isinstance(result, InvalidRequestError)
        assert result.details.get("backend") == backend_type
        assert result.details.get("status_code") == status_code

    @given(
        backend_type=backend_types,
        status_code=http_5xx_codes,
        message=error_messages,
    )
    @settings(max_examples=50, deadline=None)
    def test_http_5xx_translates_to_backend_error(
        self, backend_type: str, status_code: int, message: str
    ) -> None:
        """HTTP 5xx exceptions should be translated to BackendError.

        Validates Requirements 12.3: Translate HTTPException 5xx to BackendError
        """
        from src.core.common.exceptions import BackendError
        from src.core.services.exception_normalizer import ExceptionNormalizer

        normalizer = ExceptionNormalizer()

        exc = HTTPException(status_code=status_code, detail={"message": message})

        result = normalizer.normalize(exc, backend_type)

        assert isinstance(result, BackendError)
        assert result.backend_name == backend_type
        assert result.status_code == status_code

    @given(
        backend_type=backend_types,
        message=error_messages,
    )
    @settings(max_examples=50, deadline=None)
    def test_already_normalized_exceptions_pass_through(
        self, backend_type: str, message: str
    ) -> None:
        """Already-normalized domain exceptions should pass through unchanged.

        Validates idempotency of normalization.
        """
        from src.core.common.exceptions import (
            BackendError,
            RateLimitExceededError,
        )
        from src.core.services.exception_normalizer import ExceptionNormalizer

        normalizer = ExceptionNormalizer()

        # Test RateLimitExceededError passthrough
        rate_exc = RateLimitExceededError(message=message)
        result = normalizer.normalize(rate_exc, backend_type)
        assert result is rate_exc

        # Test BackendError passthrough
        backend_exc = BackendError(message=message, backend_name=backend_type)
        result = normalizer.normalize(backend_exc, backend_type)
        assert result is backend_exc

    @given(
        backend_type=backend_types,
        message=error_messages,
    )
    @settings(max_examples=50, deadline=None)
    def test_generic_exceptions_pass_through(
        self, backend_type: str, message: str
    ) -> None:
        """Non-HTTP exceptions should pass through unchanged.

        Validates that only HTTP exceptions are translated.
        """
        from src.core.services.exception_normalizer import ExceptionNormalizer

        normalizer = ExceptionNormalizer()

        exc = ValueError(message)

        result = normalizer.normalize(exc, backend_type)

        assert result is exc
        assert isinstance(result, ValueError)


class TestExceptionMessageExtraction:
    """Tests for extracting error messages from various response formats."""

    @given(
        backend_type=backend_types,
    )
    @settings(max_examples=20, deadline=None)
    def test_extracts_message_from_nested_error_block(self, backend_type: str) -> None:
        """Should extract message from nested error.message structure."""
        from src.core.common.exceptions import RateLimitExceededError
        from src.core.services.exception_normalizer import ExceptionNormalizer

        normalizer = ExceptionNormalizer()

        detail = {"error": {"message": "Nested error message"}}
        exc = HTTPException(status_code=429, detail=detail)

        result = normalizer.normalize(exc, backend_type)

        assert isinstance(result, RateLimitExceededError)
        assert "Nested error message" in result.message

    @given(
        backend_type=backend_types,
    )
    @settings(max_examples=20, deadline=None)
    def test_extracts_message_from_top_level_message(self, backend_type: str) -> None:
        """Should extract message from top-level message field."""
        from src.core.common.exceptions import RateLimitExceededError
        from src.core.services.exception_normalizer import ExceptionNormalizer

        normalizer = ExceptionNormalizer()

        detail = {"message": "Top level message"}
        exc = HTTPException(status_code=429, detail=detail)

        result = normalizer.normalize(exc, backend_type)

        assert isinstance(result, RateLimitExceededError)
        assert "Top level message" in result.message

    @given(
        backend_type=backend_types,
    )
    @settings(max_examples=20, deadline=None)
    def test_handles_string_detail(self, backend_type: str) -> None:
        """Should handle plain string detail."""
        from src.core.common.exceptions import RateLimitExceededError
        from src.core.services.exception_normalizer import ExceptionNormalizer

        normalizer = ExceptionNormalizer()

        exc = HTTPException(status_code=429, detail="Plain string error")

        result = normalizer.normalize(exc, backend_type)

        assert isinstance(result, RateLimitExceededError)
        assert "Plain string error" in result.message

    @given(
        backend_type=backend_types,
    )
    @settings(max_examples=20, deadline=None)
    def test_provides_default_message_when_none(self, backend_type: str) -> None:
        """Should provide default message when detail is None."""
        from src.core.common.exceptions import RateLimitExceededError
        from src.core.services.exception_normalizer import ExceptionNormalizer

        normalizer = ExceptionNormalizer()

        exc = HTTPException(status_code=429, detail=None)

        result = normalizer.normalize(exc, backend_type)

        assert isinstance(result, RateLimitExceededError)
        assert result.message  # Should have some default message
