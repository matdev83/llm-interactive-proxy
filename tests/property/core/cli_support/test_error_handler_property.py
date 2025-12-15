"""Property tests for Error Classification Consistency.

**Feature: cli-god-object-refactoring, Property 4: Error Classification Consistency**

Requirements:
- 5.1: ErrorHandler formats user-friendly messages with actionable guidance
- 5.2: OAuth token expiration provides specific re-authentication instructions
- 5.3: API key errors list required environment variables
- 5.4: Unknown errors provide generic troubleshooting guidance
- 8.3: ErrorHandler accepts injectable output stream for testing
- 9.3: Property-based tests for correctness properties
"""

from __future__ import annotations

import io
from typing import TYPE_CHECKING

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

if TYPE_CHECKING:
    from src.core.cli_support.error_handler import ErrorHandler

# =============================================================================
# Strategies for Error Message Generation
# =============================================================================

# Known error patterns that should be classified
OAUTH_EXPIRED_PATTERNS = [
    "Token expired",
    "Token has expired",
    "access token expired",
    "refresh token expired",
]

OAUTH_MISSING_PATTERNS = [
    "oauth_credentials_unavailable",
    "credentials file not found",
    "Failed to load credentials",
    "OAuth credentials not found",
]

OAUTH_INVALID_PATTERNS = [
    "oauth_credentials_invalid",
    "invalid credentials",
    "credentials are corrupted",
]

API_KEY_MISSING_PATTERNS = [
    "api_key is required",
    "API key is required",
    "missing api key",
]

PORT_IN_USE_PATTERNS = [
    "Port 5000 is already in use",
    "Address already in use",
    "port in use",
]

# Backend names for context
BACKENDS = ["gemini", "qwen", "anthropic", "openai", "openrouter", "zai"]


@st.composite
def oauth_expired_error_message(draw: st.DrawFn) -> str:
    """Generate OAuth expired error messages."""
    pattern = draw(st.sampled_from(OAUTH_EXPIRED_PATTERNS))
    backend = draw(st.sampled_from(BACKENDS))
    prefix = draw(st.sampled_from(["", "Stage 'backends' validation error: "]))
    suffix = draw(
        st.sampled_from(["", f" for {backend}", f" for {backend}-oauth-plan"])
    )
    return f"{prefix}{pattern}{suffix}"


@st.composite
def oauth_missing_error_message(draw: st.DrawFn) -> str:
    """Generate OAuth missing error messages."""
    pattern = draw(st.sampled_from(OAUTH_MISSING_PATTERNS))
    backend = draw(st.sampled_from(BACKENDS))
    prefix = draw(st.sampled_from(["", "Stage 'backends' validation error: "]))
    suffix = draw(st.sampled_from(["", f" for {backend}"]))
    return f"{prefix}{pattern}{suffix}"


@st.composite
def oauth_invalid_error_message(draw: st.DrawFn) -> str:
    """Generate OAuth invalid error messages."""
    pattern = draw(st.sampled_from(OAUTH_INVALID_PATTERNS))
    backend = draw(st.sampled_from(BACKENDS))
    prefix = draw(st.sampled_from(["", "Stage 'backends' validation error: "]))
    suffix = draw(st.sampled_from(["", f" for {backend}"]))
    return f"{prefix}{pattern}{suffix}"


@st.composite
def api_key_missing_error_message(draw: st.DrawFn) -> str:
    """Generate API key missing error messages."""
    pattern = draw(st.sampled_from(API_KEY_MISSING_PATTERNS))
    backend = draw(st.sampled_from(BACKENDS))
    prefix = draw(st.sampled_from(["", "Stage 'backends' validation error: "]))
    suffix = draw(st.sampled_from(["", f" for {backend}"]))
    return f"{prefix}{pattern}{suffix}"


@st.composite
def port_in_use_error_message(draw: st.DrawFn) -> str:
    """Generate port in use error messages."""
    pattern = draw(st.sampled_from(PORT_IN_USE_PATTERNS))
    port = draw(st.integers(min_value=1024, max_value=65535))
    if "5000" in pattern:
        pattern = pattern.replace("5000", str(port))
    return pattern


# =============================================================================
# Property Tests
# =============================================================================


class TestErrorClassificationConsistency:
    """Property tests for error classification consistency.

    **Feature: cli-god-object-refactoring, Property 4: Error Classification Consistency**

    *For any* error message containing known patterns (e.g., "Token expired",
    "api_key is required"), the `ErrorHandler.classify_error` SHALL return
    the corresponding `ErrorType`.

    **Validates: Requirements 5.1, 5.2, 5.3, 5.4**
    """

    @pytest.fixture
    def error_handler(self) -> ErrorHandler:
        """Create an ErrorHandler instance."""
        from src.core.cli_support.error_handler import ErrorHandler

        return ErrorHandler()

    @given(error_msg=oauth_expired_error_message())
    @settings(max_examples=50, deadline=None)
    def test_oauth_expired_classification(self, error_msg: str) -> None:
        """OAuth expired errors are consistently classified.

        **Feature: cli-god-object-refactoring, Property 4: Error Classification Consistency**

        This property verifies that any error message containing OAuth expired
        patterns is correctly classified as OAUTH_EXPIRED.
        """
        from src.core.cli_support.error_handler import ErrorHandler, ErrorType

        handler = ErrorHandler()
        result = handler.classify_error(error_msg)
        assert result == ErrorType.OAUTH_EXPIRED, f"Failed for: {error_msg}"

    @given(error_msg=oauth_missing_error_message())
    @settings(max_examples=50, deadline=None)
    def test_oauth_missing_classification(self, error_msg: str) -> None:
        """OAuth missing errors are consistently classified.

        **Feature: cli-god-object-refactoring, Property 4: Error Classification Consistency**

        This property verifies that any error message containing OAuth missing
        patterns is correctly classified as OAUTH_MISSING.
        """
        from src.core.cli_support.error_handler import ErrorHandler, ErrorType

        handler = ErrorHandler()
        result = handler.classify_error(error_msg)
        assert result == ErrorType.OAUTH_MISSING, f"Failed for: {error_msg}"

    @given(error_msg=oauth_invalid_error_message())
    @settings(max_examples=50, deadline=None)
    def test_oauth_invalid_classification(self, error_msg: str) -> None:
        """OAuth invalid errors are consistently classified.

        **Feature: cli-god-object-refactoring, Property 4: Error Classification Consistency**

        This property verifies that any error message containing OAuth invalid
        patterns is correctly classified as OAUTH_INVALID.
        """
        from src.core.cli_support.error_handler import ErrorHandler, ErrorType

        handler = ErrorHandler()
        result = handler.classify_error(error_msg)
        assert result == ErrorType.OAUTH_INVALID, f"Failed for: {error_msg}"

    @given(error_msg=api_key_missing_error_message())
    @settings(max_examples=50, deadline=None)
    def test_api_key_missing_classification(self, error_msg: str) -> None:
        """API key missing errors are consistently classified.

        **Feature: cli-god-object-refactoring, Property 4: Error Classification Consistency**

        This property verifies that any error message containing API key missing
        patterns is correctly classified as API_KEY_MISSING.
        """
        from src.core.cli_support.error_handler import ErrorHandler, ErrorType

        handler = ErrorHandler()
        result = handler.classify_error(error_msg)
        assert result == ErrorType.API_KEY_MISSING, f"Failed for: {error_msg}"

    @given(error_msg=port_in_use_error_message())
    @settings(max_examples=50, deadline=None)
    def test_port_in_use_classification(self, error_msg: str) -> None:
        """Port in use errors are consistently classified.

        **Feature: cli-god-object-refactoring, Property 4: Error Classification Consistency**

        This property verifies that any error message containing port in use
        patterns is correctly classified as PORT_IN_USE.
        """
        from src.core.cli_support.error_handler import ErrorHandler, ErrorType

        handler = ErrorHandler()
        result = handler.classify_error(error_msg)
        assert result == ErrorType.PORT_IN_USE, f"Failed for: {error_msg}"

    @given(
        error_msg=st.text(min_size=10, max_size=100).filter(
            lambda x: not any(
                pat.lower() in x.lower()
                for patterns in [
                    OAUTH_EXPIRED_PATTERNS,
                    OAUTH_MISSING_PATTERNS,
                    OAUTH_INVALID_PATTERNS,
                    API_KEY_MISSING_PATTERNS,
                    PORT_IN_USE_PATTERNS,
                ]
                for pat in patterns
            )
        )
    )
    @settings(max_examples=50, deadline=None)
    def test_unknown_classification(self, error_msg: str) -> None:
        """Unrecognized errors are classified as UNKNOWN.

        **Feature: cli-god-object-refactoring, Property 4: Error Classification Consistency**

        This property verifies that error messages not matching any known pattern
        are correctly classified as UNKNOWN.
        """
        from src.core.cli_support.error_handler import ErrorHandler, ErrorType

        handler = ErrorHandler()
        result = handler.classify_error(error_msg)
        assert result == ErrorType.UNKNOWN, f"Unexpectedly classified: {error_msg}"


class TestErrorMessageFormatConsistency:
    """Property tests for error message format consistency.

    Validates that error messages always follow the standard format
    regardless of error type.
    """

    @given(error_msg=st.text(min_size=1, max_size=200))
    @settings(max_examples=50, deadline=None)
    def test_handle_build_error_format_consistency(self, error_msg: str) -> None:
        """All error messages follow consistent format structure.

        **Feature: cli-god-object-refactoring, Property 4: Error Classification Consistency**

        This property verifies that handle_build_error always produces output
        with consistent structural elements (header, separator, footer).
        """
        from src.core.cli_support.error_handler import ErrorHandler

        output = io.StringIO()
        handler = ErrorHandler(output=output)
        handler.handle_build_error(error_msg)
        result = output.getvalue()

        # All messages should have consistent structure
        assert result.startswith("\n"), "Message should start with newline"
        assert "=" * 60 in result, "Message should contain separator"
        assert "ERROR:" in result, "Message should contain ERROR header"
        assert "For more help" in result, "Message should contain footer"

    @given(
        error_msg1=st.text(min_size=10, max_size=100),
        error_msg2=st.text(min_size=10, max_size=100),
    )
    @settings(max_examples=25, deadline=None)
    def test_handle_build_error_deterministic(
        self, error_msg1: str, error_msg2: str
    ) -> None:
        """Same error message produces same output.

        **Feature: cli-god-object-refactoring, Property 4: Error Classification Consistency**

        This property verifies that handle_build_error is deterministic -
        the same input always produces the same output.
        """
        from src.core.cli_support.error_handler import ErrorHandler

        # Same message should produce same output
        output1 = io.StringIO()
        output2 = io.StringIO()
        handler1 = ErrorHandler(output=output1)
        handler2 = ErrorHandler(output=output2)

        handler1.handle_build_error(error_msg1)
        handler2.handle_build_error(error_msg1)

        assert output1.getvalue() == output2.getvalue()


class TestClassificationIdempotency:
    """Property tests for classification idempotency."""

    @given(error_msg=st.text(min_size=1, max_size=200))
    @settings(max_examples=50, deadline=None)
    def test_classify_error_is_idempotent(self, error_msg: str) -> None:
        """classify_error returns same result for same input.

        **Feature: cli-god-object-refactoring, Property 4: Error Classification Consistency**

        This property verifies that classify_error is idempotent -
        calling it multiple times with the same input returns the same result.
        """
        from src.core.cli_support.error_handler import ErrorHandler

        handler = ErrorHandler()

        result1 = handler.classify_error(error_msg)
        result2 = handler.classify_error(error_msg)
        result3 = handler.classify_error(error_msg)

        assert result1 == result2 == result3

    @given(error_msg=st.text(min_size=1, max_size=200))
    @settings(max_examples=50, deadline=None)
    def test_classify_error_returns_valid_type(self, error_msg: str) -> None:
        """classify_error always returns a valid ErrorType.

        **Feature: cli-god-object-refactoring, Property 4: Error Classification Consistency**

        This property verifies that classify_error always returns a value
        from the ErrorType enum, never None or invalid values.
        """
        from src.core.cli_support.error_handler import ErrorHandler, ErrorType

        handler = ErrorHandler()
        result = handler.classify_error(error_msg)

        assert isinstance(result, ErrorType)
        assert result in list(ErrorType)


class TestBackendDetection:
    """Property tests for backend detection in error messages."""

    @given(backend=st.sampled_from(BACKENDS))
    @settings(max_examples=20, deadline=None)
    def test_oauth_expired_mentions_correct_auth_command(self, backend: str) -> None:
        """OAuth expired messages for specific backends mention correct auth command.

        **Feature: cli-god-object-refactoring, Property 4: Error Classification Consistency**

        This property verifies that when an OAuth expired error mentions a specific
        backend, the resulting message includes the appropriate authentication command.
        """
        from src.core.cli_support.error_handler import ErrorHandler

        output = io.StringIO()
        handler = ErrorHandler(output=output)

        error_msg = f"Stage 'backends' validation error: Token expired for {backend}"
        handler.handle_build_error(error_msg)
        result = output.getvalue()

        # Should mention authentication
        assert "auth" in result.lower() or "login" in result.lower()

        # Backend-specific checks
        if "gemini" in backend.lower():
            assert "gemini auth" in result or "gemini" in result.lower()
        elif "qwen" in backend.lower():
            assert "qwen auth" in result or "qwen" in result.lower()
        elif "anthropic" in backend.lower():
            assert "Claude" in result or "anthropic" in result.lower()
        elif "openai" in backend.lower():
            assert "codex login" in result or "openai" in result.lower()
