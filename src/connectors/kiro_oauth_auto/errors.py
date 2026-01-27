"""Error types for Kiro OAuth auto-connector."""

from __future__ import annotations


class OAuthError(RuntimeError):
    """Raised when an OAuth flow fails."""


class TokenRefreshError(RuntimeError):
    """Raised when token refresh fails."""


class NoValidAccountsError(RuntimeError):
    """Raised when no usable accounts are available."""
