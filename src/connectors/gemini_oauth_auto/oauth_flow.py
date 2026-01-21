"""
OAuthFlowService implementation.

Browser-based OAuth authorization flow for account registration.
(Stub - to be implemented in Task 7)
"""

import httpx

from src.connectors.gemini_oauth_auto.interfaces import ITokenStorage
from src.connectors.gemini_oauth_auto.models import StoredAccount


class OAuthFlowService:
    """OAuth flow service for browser-based authorization.

    Used by the management script, not the runtime connector.
    """

    def __init__(
        self,
        storage: ITokenStorage,
        http_client: httpx.AsyncClient | None = None,
    ) -> None:
        """Initialize OAuth flow service.

        Args:
            storage: Token storage service for persisting new accounts
            http_client: httpx.AsyncClient for HTTP requests
        """
        self._storage = storage
        self._http_client = http_client

    async def authorize(
        self,
        account_id: str | None = None,
        port: int | None = None,
        timeout: int = 120,
        open_browser: bool = True,
    ) -> StoredAccount:
        """Run OAuth authorization flow.

        Args:
            account_id: Custom account identifier (auto-generated if None)
            port: Fixed port for callback server (dynamic if None)
            timeout: Seconds to wait for authorization
            open_browser: Whether to auto-open browser

        Returns:
            StoredAccount with tokens and email

        Raises:
            OAuthError: On failure or timeout
        """
        raise NotImplementedError("To be implemented in Task 7")
