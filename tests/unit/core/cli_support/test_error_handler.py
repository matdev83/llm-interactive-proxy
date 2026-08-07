"""Unit tests for ErrorHandler.

Tests that ErrorHandler classifies errors, formats user-friendly messages,
and provides actionable guidance for different error types.

Requirements satisfied:
- 5.1: ErrorHandler formats user-friendly messages with actionable guidance
- 5.2: OAuth token expiration provides specific re-authentication instructions
- 5.3: API key errors list required environment variables
- 5.4: Unknown errors provide generic troubleshooting guidance
- 5.5: Error messages write to stderr with consistent formatting
- 8.3: ErrorHandler accepts injectable output stream for testing
- 9.1: Unit tests for ErrorHandler

Test-Driven Development (TDD):
- These tests are written FIRST (RED phase)
- Implementation will follow to make tests pass (GREEN phase)
"""

from __future__ import annotations

import io
from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from src.core.cli_support.error_handler import ErrorHandler

# =============================================================================
# Test Fixtures
# =============================================================================


@pytest.fixture
def error_handler() -> ErrorHandler:
    """Create an ErrorHandler instance with default stderr."""
    from src.core.cli_support.error_handler import ErrorHandler

    return ErrorHandler()


@pytest.fixture
def error_handler_with_output() -> tuple[ErrorHandler, io.StringIO]:
    """Create an ErrorHandler with injectable output stream for testing."""
    from src.core.cli_support.error_handler import ErrorHandler

    output = io.StringIO()
    handler = ErrorHandler(output=output)
    return handler, output


# =============================================================================
# Basic ErrorHandler Tests
# =============================================================================


class TestErrorHandlerBasic:
    """Tests for basic ErrorHandler functionality."""

    def test_error_handler_exists(self) -> None:
        """ErrorHandler class can be imported."""
        from src.core.cli_support.error_handler import ErrorHandler

        assert ErrorHandler is not None

    def test_error_handler_has_handle_build_error_method(
        self, error_handler: ErrorHandler
    ) -> None:
        """ErrorHandler has handle_build_error method."""
        assert hasattr(error_handler, "handle_build_error")
        assert callable(error_handler.handle_build_error)

    def test_error_handler_has_classify_error_method(
        self, error_handler: ErrorHandler
    ) -> None:
        """ErrorHandler has classify_error method."""
        assert hasattr(error_handler, "classify_error")
        assert callable(error_handler.classify_error)

    def test_error_handler_accepts_output_stream(self) -> None:
        """ErrorHandler accepts injectable output stream in constructor."""
        from src.core.cli_support.error_handler import ErrorHandler

        output = io.StringIO()
        handler = ErrorHandler(output=output)
        assert handler is not None

    def test_error_handler_default_output_is_stderr(self) -> None:
        """ErrorHandler defaults to stderr when no output is provided."""
        import sys

        from src.core.cli_support.error_handler import ErrorHandler

        handler = ErrorHandler()
        # Handler should have internal _output attribute pointing to stderr
        assert hasattr(handler, "_output")
        assert handler._output is sys.stderr


# =============================================================================
# ErrorType Enum Tests
# =============================================================================


class TestErrorType:
    """Tests for ErrorType enumeration."""

    def test_error_type_exists(self) -> None:
        """ErrorType enum can be imported."""
        from src.core.cli_support.error_handler import ErrorType

        assert ErrorType is not None

    def test_error_type_has_oauth_expired(self) -> None:
        """ErrorType has OAUTH_EXPIRED value."""
        from src.core.cli_support.error_handler import ErrorType

        assert hasattr(ErrorType, "OAUTH_EXPIRED")
        assert ErrorType.OAUTH_EXPIRED.value == "oauth_expired"

    def test_error_type_has_oauth_missing(self) -> None:
        """ErrorType has OAUTH_MISSING value."""
        from src.core.cli_support.error_handler import ErrorType

        assert hasattr(ErrorType, "OAUTH_MISSING")
        assert ErrorType.OAUTH_MISSING.value == "oauth_missing"

    def test_error_type_has_oauth_invalid(self) -> None:
        """ErrorType has OAUTH_INVALID value."""
        from src.core.cli_support.error_handler import ErrorType

        assert hasattr(ErrorType, "OAUTH_INVALID")
        assert ErrorType.OAUTH_INVALID.value == "oauth_invalid"

    def test_error_type_has_api_key_missing(self) -> None:
        """ErrorType has API_KEY_MISSING value."""
        from src.core.cli_support.error_handler import ErrorType

        assert hasattr(ErrorType, "API_KEY_MISSING")
        assert ErrorType.API_KEY_MISSING.value == "api_key_missing"

    def test_error_type_has_backend_unavailable(self) -> None:
        """ErrorType has BACKEND_UNAVAILABLE value."""
        from src.core.cli_support.error_handler import ErrorType

        assert hasattr(ErrorType, "BACKEND_UNAVAILABLE")
        assert ErrorType.BACKEND_UNAVAILABLE.value == "backend_unavailable"

    def test_error_type_has_port_in_use(self) -> None:
        """ErrorType has PORT_IN_USE value."""
        from src.core.cli_support.error_handler import ErrorType

        assert hasattr(ErrorType, "PORT_IN_USE")
        assert ErrorType.PORT_IN_USE.value == "port_in_use"

    def test_error_type_has_unknown(self) -> None:
        """ErrorType has UNKNOWN value."""
        from src.core.cli_support.error_handler import ErrorType

        assert hasattr(ErrorType, "UNKNOWN")
        assert ErrorType.UNKNOWN.value == "unknown"


# =============================================================================
# Error Classification Tests
# =============================================================================


class TestErrorClassification:
    """Tests for error classification logic."""

    def test_classify_oauth_expired(self, error_handler: ErrorHandler) -> None:
        """classify_error returns OAUTH_EXPIRED for expired token errors."""
        from src.core.cli_support.error_handler import ErrorType

        error_msg = "Stage 'backends' validation error: Token expired"
        result = error_handler.classify_error(error_msg)
        assert result == ErrorType.OAUTH_EXPIRED

    def test_classify_oauth_missing(self, error_handler: ErrorHandler) -> None:
        """classify_error returns OAUTH_MISSING for missing OAuth credentials."""
        from src.core.cli_support.error_handler import ErrorType

        error_msg = "Stage 'backends' validation error: oauth_credentials_unavailable for anthropic"
        result = error_handler.classify_error(error_msg)
        assert result == ErrorType.OAUTH_MISSING

    def test_classify_oauth_invalid(self, error_handler: ErrorHandler) -> None:
        """classify_error returns OAUTH_INVALID for invalid OAuth credentials."""
        from src.core.cli_support.error_handler import ErrorType

        error_msg = (
            "Stage 'backends' validation error: oauth_credentials_invalid for gemini"
        )
        result = error_handler.classify_error(error_msg)
        assert result == ErrorType.OAUTH_INVALID

    def test_classify_oauth_credentials_file_not_found(
        self, error_handler: ErrorHandler
    ) -> None:
        """classify_error returns OAUTH_MISSING for credentials file not found."""
        from src.core.cli_support.error_handler import ErrorType

        error_msg = "Failed to load credentials: credentials file not found"
        result = error_handler.classify_error(error_msg)
        assert result == ErrorType.OAUTH_MISSING

    def test_classify_api_key_missing(self, error_handler: ErrorHandler) -> None:
        """classify_error returns API_KEY_MISSING for missing API key errors."""
        from src.core.cli_support.error_handler import ErrorType

        error_msg = (
            "Stage 'backends' validation error: api_key is required for openrouter"
        )
        result = error_handler.classify_error(error_msg)
        assert result == ErrorType.API_KEY_MISSING

    def test_classify_backend_unavailable(self, error_handler: ErrorHandler) -> None:
        """classify_error returns BACKEND_UNAVAILABLE for generic backend errors."""
        from src.core.cli_support.error_handler import ErrorType

        error_msg = "Stage 'backends' validation error: no valid backends found"
        result = error_handler.classify_error(error_msg)
        assert result == ErrorType.BACKEND_UNAVAILABLE

    def test_classify_unknown_error(self, error_handler: ErrorHandler) -> None:
        """classify_error returns UNKNOWN for unrecognized errors."""
        from src.core.cli_support.error_handler import ErrorType

        error_msg = "Something completely unexpected happened"
        result = error_handler.classify_error(error_msg)
        assert result == ErrorType.UNKNOWN

    def test_classify_port_in_use(self, error_handler: ErrorHandler) -> None:
        """classify_error returns PORT_IN_USE for port in use errors."""
        from src.core.cli_support.error_handler import ErrorType

        error_msg = "Port 5000 is already in use"
        result = error_handler.classify_error(error_msg)
        assert result == ErrorType.PORT_IN_USE


# =============================================================================
# Message Formatting Tests
# =============================================================================


class TestMessageFormatting:
    """Tests for error message formatting."""

    def test_handle_build_error_writes_to_output(
        self, error_handler_with_output: tuple[ErrorHandler, io.StringIO]
    ) -> None:
        """handle_build_error writes message to output stream."""
        handler, output = error_handler_with_output
        handler.handle_build_error("Test error message")
        result = output.getvalue()
        assert len(result) > 0

    def test_handle_build_error_includes_header(
        self, error_handler_with_output: tuple[ErrorHandler, io.StringIO]
    ) -> None:
        """handle_build_error includes error header."""
        handler, output = error_handler_with_output
        handler.handle_build_error("Test error")
        result = output.getvalue()
        assert "ERROR: Failed to start LLM Interactive Proxy" in result

    def test_handle_build_error_includes_separator(
        self, error_handler_with_output: tuple[ErrorHandler, io.StringIO]
    ) -> None:
        """handle_build_error includes separators."""
        handler, output = error_handler_with_output
        handler.handle_build_error("Test error")
        result = output.getvalue()
        assert "=" * 60 in result

    def test_handle_build_error_includes_help_footer(
        self, error_handler_with_output: tuple[ErrorHandler, io.StringIO]
    ) -> None:
        """handle_build_error includes help footer."""
        handler, output = error_handler_with_output
        handler.handle_build_error("Test error")
        result = output.getvalue()
        assert "For more help" in result
        assert "documentation" in result.lower()


# =============================================================================
# OAuth Expired Message Tests (Requirement 5.2)
# =============================================================================


class TestOAuthExpiredMessages:
    """Tests for OAuth expired error messages."""

    def test_oauth_expired_includes_detected_issue(
        self, error_handler_with_output: tuple[ErrorHandler, io.StringIO]
    ) -> None:
        """OAuth expired errors include DETECTED ISSUE section."""
        handler, output = error_handler_with_output
        error_msg = "Stage 'backends' validation error: Token expired for gemini"
        handler.handle_build_error(error_msg)
        result = output.getvalue()
        assert "DETECTED ISSUE:" in result
        assert "OAuth token has expired" in result

    def test_oauth_expired_gemini_instructions(
        self, error_handler_with_output: tuple[ErrorHandler, io.StringIO]
    ) -> None:
        """OAuth expired for Gemini includes 'gemini auth' instructions."""
        handler, output = error_handler_with_output
        error_msg = (
            "Stage 'backends' validation error: Token expired for gemini-oauth-plan"
        )
        handler.handle_build_error(error_msg)
        result = output.getvalue()
        assert "gemini auth" in result

    def test_oauth_expired_qwen_instructions(
        self, error_handler_with_output: tuple[ErrorHandler, io.StringIO]
    ) -> None:
        """OAuth expired for Qwen includes 'qwen auth' instructions."""
        handler, output = error_handler_with_output
        error_msg = "Stage 'backends' validation error: Token expired for qwen-oauth"
        handler.handle_build_error(error_msg)
        result = output.getvalue()
        assert "qwen auth" in result


# =============================================================================
# OAuth Missing Message Tests (Requirement 5.2)
# =============================================================================


class TestOAuthMissingMessages:
    """Tests for OAuth missing credential messages."""

    def test_oauth_missing_anthropic_instructions(
        self, error_handler_with_output: tuple[ErrorHandler, io.StringIO]
    ) -> None:
        """OAuth missing for Anthropic-shaped errors points to the official API key path."""
        handler, output = error_handler_with_output
        error_msg = "Stage 'backends' validation error: oauth_credentials_unavailable for anthropic"
        handler.handle_build_error(error_msg)
        result = output.getvalue()
        assert "ANTHROPIC_API_KEY" in result
        assert "`anthropic`" in result or "anthropic" in result

    def test_oauth_missing_openai_instructions(
        self, error_handler_with_output: tuple[ErrorHandler, io.StringIO]
    ) -> None:
        """OAuth missing for OpenAI includes 'codex login' instructions."""
        handler, output = error_handler_with_output
        error_msg = "Stage 'backends' validation error: oauth_credentials_unavailable for openai"
        handler.handle_build_error(error_msg)
        result = output.getvalue()
        assert "codex login" in result


# =============================================================================
# API Key Missing Message Tests (Requirement 5.3)
# =============================================================================


class TestApiKeyMissingMessages:
    """Tests for API key missing error messages."""

    def test_api_key_missing_lists_variables(
        self, error_handler_with_output: tuple[ErrorHandler, io.StringIO]
    ) -> None:
        """API key missing errors list required environment variables."""
        handler, output = error_handler_with_output
        error_msg = (
            "Stage 'backends' validation error: api_key is required for openrouter"
        )
        handler.handle_build_error(error_msg)
        result = output.getvalue()
        # Should mention setting environment variables
        assert "environment variable" in result.lower()

    def test_api_key_missing_includes_openrouter(
        self, error_handler_with_output: tuple[ErrorHandler, io.StringIO]
    ) -> None:
        """API key missing lists OPENROUTER_API_KEY."""
        handler, output = error_handler_with_output
        error_msg = "Stage 'backends' validation error: api_key is required"
        handler.handle_build_error(error_msg)
        result = output.getvalue()
        assert "OPENROUTER_API_KEY" in result

    def test_api_key_missing_includes_gemini(
        self, error_handler_with_output: tuple[ErrorHandler, io.StringIO]
    ) -> None:
        """API key missing lists GEMINI_API_KEY."""
        handler, output = error_handler_with_output
        error_msg = "Stage 'backends' validation error: api_key is required"
        handler.handle_build_error(error_msg)
        result = output.getvalue()
        assert "GEMINI_API_KEY" in result

    def test_api_key_missing_includes_anthropic(
        self, error_handler_with_output: tuple[ErrorHandler, io.StringIO]
    ) -> None:
        """API key missing lists ANTHROPIC_API_KEY."""
        handler, output = error_handler_with_output
        error_msg = "Stage 'backends' validation error: api_key is required"
        handler.handle_build_error(error_msg)
        result = output.getvalue()
        assert "ANTHROPIC_API_KEY" in result

    def test_api_key_missing_includes_zai(
        self, error_handler_with_output: tuple[ErrorHandler, io.StringIO]
    ) -> None:
        """API key missing lists ZAI_API_KEY."""
        handler, output = error_handler_with_output
        error_msg = "Stage 'backends' validation error: api_key is required"
        handler.handle_build_error(error_msg)
        result = output.getvalue()
        assert "ZAI_API_KEY" in result
        assert "ZAI_CODING_PLAN_API_KEY" in result

    def test_api_key_missing_suggests_oauth_alternatives(
        self, error_handler_with_output: tuple[ErrorHandler, io.StringIO]
    ) -> None:
        """API key missing suggests OAuth-based backend alternatives."""
        handler, output = error_handler_with_output
        error_msg = "Stage 'backends' validation error: api_key is required"
        handler.handle_build_error(error_msg)
        result = output.getvalue()
        assert "OAuth" in result


# =============================================================================
# Unknown Error Message Tests (Requirement 5.4)
# =============================================================================


class TestUnknownErrorMessages:
    """Tests for unknown error messages."""

    def test_unknown_error_includes_generic_guidance(
        self, error_handler_with_output: tuple[ErrorHandler, io.StringIO]
    ) -> None:
        """Unknown errors include generic troubleshooting guidance."""
        handler, output = error_handler_with_output
        error_msg = "Something completely unexpected happened"
        handler.handle_build_error(error_msg)
        result = output.getvalue()
        assert "logs" in result.lower() or "details" in result.lower()

    def test_unknown_error_includes_original_message(
        self, error_handler_with_output: tuple[ErrorHandler, io.StringIO]
    ) -> None:
        """Unknown errors include the original error message."""
        handler, output = error_handler_with_output
        error_msg = "Something completely unexpected happened"
        handler.handle_build_error(error_msg)
        result = output.getvalue()
        assert "unexpected" in result.lower()


# =============================================================================
# Consistent Formatting Tests (Requirement 5.5)
# =============================================================================


class TestConsistentFormatting:
    """Tests for consistent error message formatting."""

    def test_error_format_is_consistent(
        self, error_handler_with_output: tuple[ErrorHandler, io.StringIO]
    ) -> None:
        """Error message format is consistent across different error types."""
        handler, output = error_handler_with_output

        # Test multiple error types
        test_errors = [
            "Token expired",
            "api_key is required",
            "Something unexpected",
        ]

        for error_msg in test_errors:
            output.truncate(0)
            output.seek(0)
            handler.handle_build_error(
                f"Stage 'backends' validation error: {error_msg}"
            )
            result = output.getvalue()

            # All should have separator and header
            assert "=" * 60 in result
            assert "ERROR:" in result

    def test_error_format_starts_with_newline(
        self, error_handler_with_output: tuple[ErrorHandler, io.StringIO]
    ) -> None:
        """Error message starts with newline for visual separation."""
        handler, output = error_handler_with_output
        handler.handle_build_error("Test error")
        result = output.getvalue()
        assert result.startswith("\n")

    def test_error_format_ends_with_separator(
        self, error_handler_with_output: tuple[ErrorHandler, io.StringIO]
    ) -> None:
        """Error message ends with separator."""
        handler, output = error_handler_with_output
        handler.handle_build_error("Test error")
        result = output.getvalue()
        assert result.strip().endswith("=" * 60)


# =============================================================================
# Specialized Formatter Tests
# =============================================================================


class TestSpecializedFormatters:
    """Tests for specialized message formatters."""

    def test_has_format_oauth_expired_message(
        self, error_handler: ErrorHandler
    ) -> None:
        """ErrorHandler has format_oauth_expired_message method."""
        assert hasattr(error_handler, "format_oauth_expired_message")
        assert callable(error_handler.format_oauth_expired_message)

    def test_has_format_api_key_missing_message(
        self, error_handler: ErrorHandler
    ) -> None:
        """ErrorHandler has format_api_key_missing_message method."""
        assert hasattr(error_handler, "format_api_key_missing_message")
        assert callable(error_handler.format_api_key_missing_message)

    def test_format_oauth_expired_returns_string(
        self, error_handler: ErrorHandler
    ) -> None:
        """format_oauth_expired_message returns a string."""
        result = error_handler.format_oauth_expired_message("Token expired for gemini")
        assert isinstance(result, str)
        assert len(result) > 0

    def test_format_api_key_missing_returns_string(
        self, error_handler: ErrorHandler
    ) -> None:
        """format_api_key_missing_message returns a string."""
        result = error_handler.format_api_key_missing_message()
        assert isinstance(result, str)
        assert len(result) > 0


# =============================================================================
# Backward Compatibility Tests
# =============================================================================


class TestBackwardCompatibility:
    """Tests for backward compatibility with existing _handle_application_build_error."""

    def test_same_output_structure_as_original(
        self, error_handler_with_output: tuple[ErrorHandler, io.StringIO]
    ) -> None:
        """ErrorHandler produces similar output structure as original function."""
        handler, output = error_handler_with_output

        # Use a message that would have been handled by original
        error_msg = "Stage 'backends' validation error: Token expired"
        handler.handle_build_error(error_msg)

        result = output.getvalue()

        # Original format elements that should be preserved
        assert "ERROR: Failed to start LLM Interactive Proxy" in result
        assert "=" * 60 in result
        assert "For more help" in result

    def test_oauth_expired_detection_same_as_original(
        self, error_handler: ErrorHandler
    ) -> None:
        """OAuth expired detection works same as original implementation."""
        from src.core.cli_support.error_handler import ErrorType

        # These patterns were detected in original _handle_application_build_error
        test_cases = [
            "Token expired",
            "Token has expired",
        ]

        for msg in test_cases:
            result = error_handler.classify_error(
                f"Stage 'backends' validation error: {msg}"
            )
            assert result == ErrorType.OAUTH_EXPIRED, f"Failed for: {msg}"

    def test_api_key_detection_same_as_original(
        self, error_handler: ErrorHandler
    ) -> None:
        """API key detection works same as original implementation."""
        from src.core.cli_support.error_handler import ErrorType

        result = error_handler.classify_error(
            "Stage 'backends' validation error: api_key is required"
        )
        assert result == ErrorType.API_KEY_MISSING


# =============================================================================
# Error Handler with Credentials File Missing Tests
# =============================================================================


class TestCredentialsFileMissing:
    """Tests for credentials file missing errors."""

    def test_credentials_file_missing_detected(
        self, error_handler: ErrorHandler
    ) -> None:
        """Credentials file missing errors are detected."""
        from src.core.cli_support.error_handler import ErrorType

        test_cases = [
            "Failed to load credentials: file not found",
            "credentials file not found",
            "Failed to load credentials from ~/.gemini/oauth_creds.json",
        ]

        for msg in test_cases:
            result = error_handler.classify_error(msg)
            assert result == ErrorType.OAUTH_MISSING, f"Failed for: {msg}"

    def test_credentials_file_missing_instructions(
        self, error_handler_with_output: tuple[ErrorHandler, io.StringIO]
    ) -> None:
        """Credentials file missing includes authentication instructions."""
        handler, output = error_handler_with_output
        handler.handle_build_error(
            "Failed to load credentials: credentials file not found"
        )
        result = output.getvalue()
        # Should include instructions for authenticating
        assert "auth" in result.lower()
