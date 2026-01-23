"""
GeminiOAuthAutoConnector implementation.

Backend connector with self-managed OAuth tokens and multi-account support.
"""

import asyncio
import logging
from typing import Any

import httpx

from src.connectors.gemini_oauth_auto.account_selector import AccountSelectorService
from src.connectors.gemini_oauth_auto.token_refresh import TokenRefreshService
from src.connectors.gemini_oauth_auto.token_storage import TokenStorageService
from src.connectors.gemini_oauth_base import GeminiOAuthBaseConnector
from src.core.config.app_config import AppConfig
from src.core.services.backend_registry import backend_registry
from src.core.services.translation_service import TranslationService

logger = logging.getLogger(__name__)


class GeminiOAuthAutoConnector(GeminiOAuthBaseConnector):
    """Gemini OAuth Auto-Connector.

    Self-contained OAuth2 authentication with multi-account support and
    automatic rotation on quota exhaustion.
    """

    backend_type: str = "gemini-oauth-auto"

    def __init__(
        self,
        client: httpx.AsyncClient,
        config: AppConfig,
        translation_service: TranslationService,
        name: str = "gemini-oauth-auto",
    ) -> None:
        """Initialize Gemini OAuth Auto-Connector."""
        super().__init__(client, config, translation_service, name)

        # Initialize self-managed services
        self._token_storage = TokenStorageService()
        self._token_refresh = TokenRefreshService(
            storage=self._token_storage, http_client=client
        )
        self._account_selector = AccountSelectorService(
            storage=self._token_storage, refresh_service=self._token_refresh
        )

    @property
    def _oauth_credentials(self) -> dict[str, Any] | None:
        """Get current OAuth credentials from the selected account."""
        account = self._account_selector.get_current_account()
        if account:
            return account.to_credentials_dict()
        return None

    @_oauth_credentials.setter
    def _oauth_credentials(self, value: dict[str, Any] | None) -> None:
        """Setter for backward compatibility, currently no-op for auto-connector."""

    async def initialize(self, **kwargs: Any) -> None:
        """Initialize connector and load accounts."""
        logger.info("Initializing Gemini OAuth Auto backend: %s", self.name)

        # Set the API base URL for Google Code Assist API
        self.gemini_api_base_url = kwargs.get(
            "gemini_api_base_url", "https://cloudcode-pa.googleapis.com"
        )
        self.api_url = self.gemini_api_base_url

        # Load accounts via selector
        await self._account_selector.reload_accounts()

        # Select first account
        account = await self._account_selector.get_next_account()

        if account:
            self.is_functional = True
            logger.info(
                "Gemini OAuth Auto backend initialized with %d accounts",
                self._account_selector.get_available_count(),
            )
        else:
            logger.warning("Gemini OAuth Auto backend initialized with NO valid accounts")
            self.is_functional = False

        # We skip super().initialize() because it tries to use
        # GeminiCredentialCoordinator which we are bypassing.
        # But we still need model discovery if we are functional.
        if self.is_functional:
            await self._ensure_models_loaded()

    async def _refresh_token_if_needed(self, *, force_reload: bool = False) -> bool:
        """Ensure a valid access token is available.

        For auto-connector, we use account rotation and refresh.
        """
        if force_reload:
            await self._account_selector.reload_accounts()

        account = self._account_selector.get_current_account()
        if not account or account.is_expired():
            account = await self._account_selector.get_next_account()

        return account is not None

    async def _load_oauth_credentials(
        self, force_reload: bool = False, silent: bool = False
    ) -> bool:
        """Bypass base class credential loading."""
        return False

    def _start_file_watching(self) -> None:
        """Bypass base class file watching (we manage our own storage)."""

    def is_backend_functional(self) -> bool:
        """Check if backend is functional and ready to handle requests.

        This overrides the base class logic to combine account-based availability
        with circuit breaker / endpoint health states.
        """
        # 1. Circuit breaker / Auth checks
        if not getattr(self, "_endpoint_healthy", True):
            return False
        if not getattr(self, "_auth_valid", True):
            return False

        # 2. Account-specific availability check
        return self._is_backend_functional_internal()

    def _is_backend_functional_internal(self) -> bool:
        """Internal check for account availability."""
        return self.is_functional and self._account_selector.get_available_count() > 0

    def get_validation_errors(self) -> list[str]:
        """Get the current list of validation/health errors.

        Includes account count information for diagnostics.
        """
        # We don't call super().get_validation_errors() because GeminiBaseConnector
        # implementation of it is too narrow (only returns _credential_validation_errors).
        # We want to include LLMBackend's health info + our account info.
        
        errors: list[str] = []

        # 1. Auth/Endpoint errors from LLMBackend
        if not getattr(self, "_auth_valid", True):
            reason = getattr(self, "_last_health_change_reason", "Authentication failed")
            errors.append(f"Credentials invalid: {reason}")
        elif not getattr(self, "_endpoint_healthy", True):
            reason = getattr(self, "_last_health_change_reason", "unknown reason")
            errors.append(f"API endpoint unhealthy: {reason}")

        # 2. Account errors
        available_count = self._account_selector.get_available_count()
        if available_count == 0:
            errors.append("No valid OAuth accounts available in storage")
        elif not self.is_functional:
            errors.append("Backend initialization failed or marked unusable")

        return errors

    async def _discover_project_id(self, auth_session: Any = None) -> str:
        """Discover project ID - returns 'default' for auto-connector."""
        return "default"

    def _mark_backend_unusable(self, *, reason: str = "quota_exceeded") -> None:
        """Override to handle quota exhaustion via account rotation."""
        if reason == "quota_exceeded":
            logger.warning("Quota exceeded for account, triggering rotation")
            # Schedule rotation task and keep reference to prevent GC
            task = asyncio.create_task(self._account_selector.rotate_on_quota())
            self._background_tasks.add(task)
            task.add_done_callback(self._background_tasks.discard)
        else:
            super()._mark_backend_unusable(reason=reason)


# Register backend
backend_registry.register_backend("gemini-oauth-auto", GeminiOAuthAutoConnector)

