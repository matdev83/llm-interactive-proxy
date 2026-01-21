"""
GeminiOAuthAutoConnector implementation.

Backend connector with self-managed OAuth tokens.
(Stub - to be implemented in Task 9)
"""

from typing import Any

import httpx

from src.connectors.gemini_oauth_auto.models import StoredAccount


class GeminiOAuthAutoConnector:
    """Gemini OAuth Auto-Connector.

    Self-contained OAuth2 authentication without external dependencies.
    Stub implementation - will extend GeminiOAuthBaseConnector in Task 9.
    """

    backend_type: str = "gemini-oauth-auto"

    def __init__(
        self,
        client: httpx.AsyncClient | None = None,
        config: Any = None,
        translation_service: Any = None,
        name: str | None = None,
    ) -> None:
        """Initialize connector.

        Args:
            client: httpx.AsyncClient for HTTP requests
            config: Application configuration
            translation_service: Translation service (from base class)
            name: Optional backend name
        """
        self._client = client
        self._config = config
        self._name = name
        self._current_account: StoredAccount | None = None
        self._initialized = False

    async def initialize(self, **kwargs: Any) -> None:
        """Initialize connector with local account storage."""
        raise NotImplementedError("To be implemented in Task 9")

    def is_backend_functional(self) -> bool:
        """Check if connector has valid accounts."""
        return False  # Stub


# Registration will be added in Task 9 when extending GeminiOAuthBaseConnector
