"""
Google Auth adapter for Gemini OAuth connectors.

This module provides injectable wrappers around google.auth library
imports to avoid module-level singleton dependencies and enable testing.
"""

import logging
import threading
from functools import lru_cache
from typing import Any, Protocol, runtime_checkable

logger = logging.getLogger(__name__)


@runtime_checkable
class IGoogleAuthProvider(Protocol):
    """Interface for Google Auth library access."""

    def get_transport_requests(self) -> Any:
        """Get the google.auth.transport.requests module."""
        ...

    def get_auth_exceptions(self) -> Any:
        """Get the google.auth.exceptions module."""
        ...

    def create_authorized_session(self, credentials: Any) -> Any:
        """Create an AuthorizedSession with the given credentials."""
        ...


@lru_cache(maxsize=1)
def _get_google_transport_requests():
    """Lazily import google.auth transport to avoid heavy startup cost."""
    import google.auth.transport.requests as transport_requests  # type: ignore[import-untyped]

    return transport_requests


@lru_cache(maxsize=1)
def _get_google_auth_exceptions():
    """Lazily import google.auth exceptions."""
    import google.auth.exceptions as google_auth_exceptions  # type: ignore[import-untyped]

    return google_auth_exceptions


class GoogleAuthProvider:
    """Provider for Google Auth library access.

    This class wraps the google.auth imports and provides them
    through an injectable interface. It uses lru_cache internally
    to avoid repeated imports while keeping the imports lazy.
    """

    def get_transport_requests(self) -> Any:
        """Get the google.auth.transport.requests module.

        Returns:
            The google.auth.transport.requests module.
        """
        return _get_google_transport_requests()

    def get_auth_exceptions(self) -> Any:
        """Get the google.auth.exceptions module.

        Returns:
            The google.auth.exceptions module.
        """
        return _get_google_auth_exceptions()

    def create_authorized_session(self, credentials: Any) -> Any:
        """Create an AuthorizedSession with the given credentials.

        Args:
            credentials: Google auth credentials object.

        Returns:
            An AuthorizedSession instance.
        """
        transport_requests = self.get_transport_requests()
        return transport_requests.AuthorizedSession(credentials)

    def is_google_auth_error(self, exception: Exception) -> bool:
        """Check if an exception is a Google Auth error.

        Args:
            exception: The exception to check.

        Returns:
            True if it's a GoogleAuthError, False otherwise.
        """
        try:
            auth_exceptions = self.get_auth_exceptions()
            return isinstance(exception, auth_exceptions.GoogleAuthError)
        except Exception:
            return False


# Default instance for convenience
_default_provider: GoogleAuthProvider | None = None
_default_provider_lock = threading.Lock()


def get_default_google_auth_provider() -> GoogleAuthProvider:
    """Get the default Google Auth provider instance."""
    global _default_provider
    if _default_provider is None:
        with _default_provider_lock:
            if _default_provider is None:
                _default_provider = GoogleAuthProvider()
    return _default_provider


__all__ = [
    "GoogleAuthProvider",
    "IGoogleAuthProvider",
    "get_default_google_auth_provider",
]
