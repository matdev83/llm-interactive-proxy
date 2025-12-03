"""
Exception classes for SSO authentication.

This module defines custom exceptions for SSO authentication errors,
providing clear error handling and reporting.
"""

from src.core.common.exceptions import LLMProxyError


class SSOException(LLMProxyError):  # noqa: N818
    """Base exception for SSO authentication errors."""

    def __init__(
        self,
        message: str,
        details: dict | None = None,
        original_error: Exception | None = None,
    ):
        """
        Initialize SSO exception.

        Args:
            message: Human-readable error message
            details: Additional error context
            original_error: Original exception if wrapping another error
        """
        super().__init__(message, details or {})
        self.original_error = original_error


class AuthenticationError(SSOException):
    """Exception raised when SSO authentication fails."""


class AuthorizationError(SSOException):
    """Exception raised when authorization fails after successful SSO."""


class ConfigurationError(SSOException):
    """Exception raised when SSO configuration is invalid."""


class TokenError(SSOException):
    """Exception raised for token-related errors."""


class RateLimitError(SSOException):
    """Exception raised when rate limit is exceeded."""

    def __init__(
        self,
        message: str,
        retry_after: int,
        details: dict | None = None,
    ):
        """
        Initialize rate limit exception.

        Args:
            message: Human-readable error message
            retry_after: Seconds until retry is allowed
            details: Additional error context
        """
        super().__init__(message, details)
        self.retry_after = retry_after
