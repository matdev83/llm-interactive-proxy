"""
Endpoint configuration strategies for Gemini OAuth connectors.

This module provides different endpoint configurations:
- StandardCodeAssistEndpoint: Standard cloudcode-pa.googleapis.com
- AntigravitySandboxEndpoint: Antigravity daily sandbox endpoint
"""

from typing import Any

# Standard Code Assist API endpoint
CODE_ASSIST_ENDPOINT = "https://cloudcode-pa.googleapis.com"

# Antigravity sandbox endpoint
ANTIGRAVITY_SANDBOX_ENDPOINT = "https://daily-cloudcode-pa.sandbox.googleapis.com"

# Antigravity-specific User-Agent
ANTIGRAVITY_USER_AGENT = "antigravity/1.11.5 windows/amd64"


class StandardCodeAssistEndpoint:
    """Endpoint configuration for standard Code Assist API.

    Used by gemini-oauth-plan and gemini-oauth-free backends.
    """

    def __init__(self, base_url: str | None = None) -> None:
        """Initialize the endpoint configuration.

        Args:
            base_url: Optional custom base URL override.
        """
        self._base_url = base_url or CODE_ASSIST_ENDPOINT

    def get_base_url(self) -> str:
        """Get the base URL for the API endpoint.

        Returns:
            The API base URL string.
        """
        return self._base_url

    def get_api_headers(self, credentials: dict[str, Any] | None) -> dict[str, str]:
        """Get headers for API requests (used with httpx client).

        Args:
            credentials: Optional credentials dictionary for Authorization header.

        Returns:
            Dictionary of HTTP headers.
        """
        headers: dict[str, str] = {}
        if credentials and credentials.get("access_token"):
            headers["Authorization"] = f"Bearer {credentials['access_token']}"
        headers["Content-Type"] = "application/json"
        return headers

    def get_session_headers(self) -> dict[str, str]:
        """Get headers for AuthorizedSession requests (used with requests library).

        Returns:
            Dictionary of HTTP headers (empty for standard endpoint).
        """
        return {}


class AntigravitySandboxEndpoint:
    """Endpoint configuration for Antigravity sandbox API.

    Used by gemini-oauth-antigravity backend.
    """

    def __init__(self, base_url: str | None = None) -> None:
        """Initialize the endpoint configuration.

        Args:
            base_url: Optional custom base URL override.
        """
        self._base_url = base_url or ANTIGRAVITY_SANDBOX_ENDPOINT

    def get_base_url(self) -> str:
        """Get the base URL for the API endpoint.

        Returns:
            The Antigravity sandbox API base URL string.
        """
        return self._base_url

    def get_api_headers(self, credentials: dict[str, Any] | None) -> dict[str, str]:
        """Get headers for API requests (used with httpx client).

        The Antigravity sandbox endpoint requires a specific User-Agent header.

        Args:
            credentials: Optional credentials dictionary for Authorization header.

        Returns:
            Dictionary of HTTP headers including Antigravity User-Agent.
        """
        headers: dict[str, str] = {}
        if credentials and credentials.get("access_token"):
            headers["Authorization"] = f"Bearer {credentials['access_token']}"
        headers["Content-Type"] = "application/json"
        headers["User-Agent"] = ANTIGRAVITY_USER_AGENT
        return headers

    def get_session_headers(self) -> dict[str, str]:
        """Get headers for AuthorizedSession requests (used with requests library).

        Returns:
            Dictionary of HTTP headers with Antigravity User-Agent.
        """
        return {"User-Agent": ANTIGRAVITY_USER_AGENT}


__all__ = [
    "ANTIGRAVITY_SANDBOX_ENDPOINT",
    "ANTIGRAVITY_USER_AGENT",
    "AntigravitySandboxEndpoint",
    "CODE_ASSIST_ENDPOINT",
    "StandardCodeAssistEndpoint",
]
