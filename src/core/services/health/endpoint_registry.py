"""Endpoint registry for mapping API URLs to backend instances.

This module provides a registry that tracks:
- Unique API URLs used by backend connectors
- Which backend instances use each URL
- Health state for each unique URL
"""

from __future__ import annotations

import logging
import threading
from collections import defaultdict
from typing import TYPE_CHECKING
from urllib.parse import urlparse

from src.core.domain.health.endpoint_health_state import EndpointHealthState

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)


class EndpointRegistry:
    """Registry for tracking unique API endpoints and their backend instances.

    This registry maintains a mapping between unique API URLs and the backend
    connector instances that use them. It also manages health state for each
    unique URL.

    Thread-safe: All operations are protected by a lock.
    """

    def __init__(self) -> None:
        """Initialize the endpoint registry."""
        self._lock = threading.Lock()
        # Map: normalized URL -> set of backend instance names
        self._url_to_backends: dict[str, set[str]] = defaultdict(set)
        # Map: backend instance name -> normalized URL
        self._backend_to_url: dict[str, str] = {}
        # Map: normalized URL -> health state
        self._health_states: dict[str, EndpointHealthState] = {}

    def register_backend(
        self,
        backend_name: str,
        api_url: str,
    ) -> EndpointHealthState:
        """Register a backend instance with its API URL.

        Args:
            backend_name: Unique identifier for the backend instance (e.g., "openai.1").
            api_url: The API URL used by this backend.

        Returns:
            The EndpointHealthState for this URL (created if new).
        """
        normalized_url = self._normalize_url(api_url)

        with self._lock:
            # Track backend -> URL mapping
            old_url = self._backend_to_url.get(backend_name)
            if old_url and old_url != normalized_url:
                # Backend changed URL - remove from old URL's backend set
                self._url_to_backends[old_url].discard(backend_name)
                if not self._url_to_backends[old_url]:
                    # No more backends using this URL
                    del self._url_to_backends[old_url]
                    # Keep health state for now (could be re-registered)

            # Register new mapping
            self._backend_to_url[backend_name] = normalized_url
            self._url_to_backends[normalized_url].add(backend_name)

            # Create health state if new URL
            if normalized_url not in self._health_states:
                self._health_states[normalized_url] = EndpointHealthState(
                    api_url=normalized_url
                )
                if logger.isEnabledFor(logging.INFO):
                    logger.info(
                        "Registered new API endpoint for health checks: %s",
                        normalized_url,
                    )

            if logger.isEnabledFor(logging.DEBUG):
                logger.debug(
                    "Backend %s registered with URL %s (total backends for URL: %d)",
                    backend_name,
                    normalized_url,
                    len(self._url_to_backends[normalized_url]),
                )

            return self._health_states[normalized_url]

    def unregister_backend(self, backend_name: str) -> None:
        """Unregister a backend instance.

        Args:
            backend_name: The backend instance to unregister.
        """
        with self._lock:
            url = self._backend_to_url.pop(backend_name, None)
            if url:
                self._url_to_backends[url].discard(backend_name)
                if logger.isEnabledFor(logging.DEBUG):
                    logger.debug(
                        "Backend %s unregistered from URL %s",
                        backend_name,
                        url,
                    )

    def get_all_urls(self) -> list[str]:
        """Get all registered unique API URLs.

        Returns:
            List of normalized API URLs that have at least one backend.
        """
        with self._lock:
            return [
                url
                for url, backends in self._url_to_backends.items()
                if backends  # Only URLs with active backends
            ]

    def get_backends_for_url(self, api_url: str) -> set[str]:
        """Get all backend instance names using a specific URL.

        Args:
            api_url: The API URL to query.

        Returns:
            Set of backend instance names using this URL.
        """
        normalized_url = self._normalize_url(api_url)
        with self._lock:
            return set(self._url_to_backends.get(normalized_url, set()))

    def get_url_for_backend(self, backend_name: str) -> str | None:
        """Get the API URL used by a specific backend instance.

        Args:
            backend_name: The backend instance name.

        Returns:
            The normalized API URL, or None if not registered.
        """
        with self._lock:
            return self._backend_to_url.get(backend_name)

    def get_health_state(self, api_url: str) -> EndpointHealthState | None:
        """Get the health state for a specific API URL.

        Args:
            api_url: The API URL to query.

        Returns:
            The health state, or None if URL is not registered.
        """
        normalized_url = self._normalize_url(api_url)
        with self._lock:
            return self._health_states.get(normalized_url)

    def get_all_health_states(self) -> dict[str, EndpointHealthState]:
        """Get health states for all registered URLs.

        Returns:
            Dictionary mapping URLs to their health states.
        """
        with self._lock:
            return dict(self._health_states)

    def is_url_healthy(self, api_url: str) -> bool:
        """Check if a URL is considered healthy.

        Args:
            api_url: The API URL to check.

        Returns:
            True if healthy (or if URL is not registered, assumes healthy).
        """
        state = self.get_health_state(api_url)
        return state.is_healthy if state else True

    def is_backend_healthy(self, backend_name: str) -> bool:
        """Check if a backend's API URL is healthy.

        Args:
            backend_name: The backend instance name.

        Returns:
            True if the backend's URL is healthy (or if not registered).
        """
        url = self.get_url_for_backend(backend_name)
        if not url:
            return True  # Not registered, assume healthy
        return self.is_url_healthy(url)

    @staticmethod
    def _normalize_url(url: str) -> str:
        """Normalize a URL for consistent comparison.

        - Removes trailing slashes
        - Lowercases the scheme and host
        - Keeps port if non-default

        Args:
            url: The URL to normalize.

        Returns:
            Normalized URL string.
        """
        if not url:
            return ""

        parsed = urlparse(url)

        # Lowercase scheme and host
        scheme = parsed.scheme.lower() if parsed.scheme else "https"
        host = parsed.hostname.lower() if parsed.hostname else ""
        port = parsed.port

        # Reconstruct with optional port
        if port:
            # Only include port if non-default
            default_port = 443 if scheme == "https" else 80
            if port != default_port:
                netloc = f"{host}:{port}"
            else:
                netloc = host
        else:
            netloc = host

        # Remove trailing slashes from path
        path = parsed.path.rstrip("/") if parsed.path else ""

        # Reconstruct URL
        return f"{scheme}://{netloc}{path}"

    @staticmethod
    def extract_hostname(url: str) -> str:
        """Extract hostname from a URL for ping checks.

        Args:
            url: The URL to parse.

        Returns:
            The hostname portion of the URL.
        """
        parsed = urlparse(url)
        return parsed.hostname or url

    def clear(self) -> None:
        """Clear all registrations and health states."""
        with self._lock:
            self._url_to_backends.clear()
            self._backend_to_url.clear()
            self._health_states.clear()
            logger.info("Endpoint registry cleared")

    def __len__(self) -> int:
        """Return the number of unique registered URLs."""
        with self._lock:
            return len(
                [url for url, backends in self._url_to_backends.items() if backends]
            )

    def __repr__(self) -> str:
        """Return a string representation."""
        with self._lock:
            url_count = len(
                [url for url, backends in self._url_to_backends.items() if backends]
            )
            backend_count = len(self._backend_to_url)
        return f"<EndpointRegistry urls={url_count} backends={backend_count}>"
