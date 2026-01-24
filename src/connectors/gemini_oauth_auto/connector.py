"""
GeminiOAuthAutoConnector implementation.

Backend connector with self-managed OAuth tokens and multi-account support.
"""

import asyncio
import contextlib
import logging
import os
from typing import Any, cast

import httpx
from fastapi import HTTPException

from src.connectors.contracts import ConnectorChatCompletionsRequest
from src.connectors.gemini_base.models import GeminiOAuthCredentials
from src.connectors.gemini_oauth_auto.account_selector import AccountSelectorService
from src.connectors.gemini_oauth_auto.token_refresh import TokenRefreshService
from src.connectors.gemini_oauth_auto.token_storage import TokenStorageService
from src.connectors.gemini_oauth_base import GeminiOAuthBaseConnector
from src.core.config.app_config import AppConfig
from src.core.domain.responses import ResponseEnvelope, StreamingResponseEnvelope
from src.core.services.backend_registry import backend_registry
from src.core.services.translation_service import TranslationService

logger = logging.getLogger(__name__)

# Enable internal/debug-only backends automatically when running under tests.
_DEBUG_OVERRIDE_DEFAULT = os.environ.get(
    "ENABLE_INTERNAL_BACKENDS_FOR_TESTS", "1"
).lower() not in {"0", "false", "no"}


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
        self._enable_gemini_oauth_auto_backend_debugging_override = (
            _DEBUG_OVERRIDE_DEFAULT
        )



    def _sync_selected_account_to_base(self) -> None:
        """Sync the currently-selected account into the gemini_base credential coordinator.

        The refactored Gemini stack (model registry, health checks) reads credentials
        from `self._credential_coordinator.credentials`. `gemini-oauth-auto` manages
        its own token storage/rotation, so we must keep that coordinator in sync.
        """
        coordinator = getattr(self, "_credential_coordinator", None)
        if coordinator is None:
            return

        account = self._account_selector.get_current_account()
        if not account:
            # Clear coordinator credentials so downstream services fail fast.
            with contextlib.suppress(Exception):
                coordinator._credentials = None  # type: ignore[attr-defined]
            return

        try:
            creds_dict = account.to_credentials_dict()
            coordinator._credentials = GeminiOAuthCredentials.from_dict(creds_dict)  # type: ignore[attr-defined]
        except Exception:
            logger.warning(
                "Failed to sync OAuth auto account into credential coordinator",
                exc_info=True,
            )

    @staticmethod
    def _parse_accounts_allowlist(value: Any) -> set[str] | None:
        """Parse config `extra.accounts` value.

        Accepts:
        - 'all' (default) -> None (no filtering)
        - list[str] -> set[str]
        - comma-separated string -> set[str]
        """
        if value is None:
            return None
        if isinstance(value, str):
            if value.strip().lower() == "all":
                return None
            parts = [p.strip() for p in value.split(",") if p.strip()]
            return set(parts) if parts else None
        if isinstance(value, list | tuple | set):
            parts = [str(p).strip() for p in value if str(p).strip()]
            return set(parts) if parts else None
        return None

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
        backend_config = getattr(self.config.backends, "gemini_oauth_auto", None)
        extras = backend_config.extra if backend_config else {}

        current = self._enable_gemini_oauth_auto_backend_debugging_override
        self._enable_gemini_oauth_auto_backend_debugging_override = (
            kwargs.get("enable_gemini_oauth_auto_backend_debugging_override")
            if "enable_gemini_oauth_auto_backend_debugging_override" in kwargs
            else extras.get(
                "enable_gemini_oauth_auto_backend_debugging_override", current
            )
        )

        logger.info("Initializing Gemini OAuth Auto backend: %s", self.name)

        # Set the API base URL for Google Code Assist API
        self.gemini_api_base_url = kwargs.get(
            "gemini_api_base_url", "https://cloudcode-pa.googleapis.com"
        )
        self.api_url = self.gemini_api_base_url

        # Apply gemini-oauth-auto specific configuration
        storage_path = extras.get("storage_path")
        refresh_buffer_seconds = extras.get("refresh_buffer_seconds")
        accounts_allowlist = self._parse_accounts_allowlist(extras.get("accounts"))

        refresh_buffer_ms: int | None = None
        if refresh_buffer_seconds is not None:
            with contextlib.suppress(TypeError, ValueError):
                refresh_buffer_ms = int(float(refresh_buffer_seconds) * 1000)

        # Rebuild internal services with configured storage path / selection options.
        # Tests may replace these services after construction, so we only rebuild
        # when a storage_path is explicitly provided.
        if storage_path:
            self._token_storage = TokenStorageService(storage_path=storage_path)
            self._token_refresh = TokenRefreshService(
                storage=self._token_storage,
                http_client=self.client,
            )

        # Always rebuild selector to apply allowlist / refresh buffer.
        self._account_selector = AccountSelectorService(
            storage=self._token_storage,
            refresh_service=self._token_refresh,
            refresh_buffer_ms=refresh_buffer_ms or 300_000,
            allowed_account_ids=accounts_allowlist,
        )

        # Load accounts via selector
        await self._account_selector.reload_accounts()

        # Select first account
        account = await self._account_selector.get_next_account()
        self._sync_selected_account_to_base()

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

        self._sync_selected_account_to_base()
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

    async def chat_completions(  # type: ignore[override]
        self,
        request: ConnectorChatCompletionsRequest,
    ) -> ResponseEnvelope | StreamingResponseEnvelope:
        """Handle chat completions with debugging flag validation.

        Raises:
            HTTPException: If the debugging override flag is not enabled.
        """

        if not self._enable_gemini_oauth_auto_backend_debugging_override:
            logger.warning(
                "Rejected request: Gemini OAuth Auto backend requires debugging override flag. "
                "To enable, use the --enable-gemini-oauth-auto-backend-debugging-override flag."
            )
            # Use 403 Forbidden for clearer semantic meaning
            raise HTTPException(
                status_code=403,
                detail=(
                    "Forbidden: This backend is reserved for internal development and debugging purposes only. "
                    "Use --enable-gemini-oauth-auto-backend-debugging-override to bypass this check."
                ),
            )

        # Unpack canonical request to match legacy connector signature
        # We need to ensure the effective model has the backend prefix stripped
        # before passing it to the base class, which only knows about gemini-oauth-plan prefix.
        effective_model = request.effective_model
        prefix = f"{self.backend_type}:"
        if effective_model.startswith(prefix):
            effective_model = effective_model[len(prefix) :]

        return await super().chat_completions(
            request_data=request.request,
            processed_messages=list(request.processed_messages),
            effective_model=effective_model,
            identity=request.identity,
            cancellation_token=request.cancellation_token,
            cancellation_coordinator=request.cancellation_coordinator,
            # Pass any extra options (provider-specific) as kwargs
            **cast(dict[str, Any], request.options),
        )

    async def _rotate_and_sync(self) -> None:
        """Rotate to next account and sync credentials into gemini_base."""
        await self._account_selector.rotate_on_quota()
        self._sync_selected_account_to_base()

    def _mark_backend_unusable(self, *, reason: str = "quota_exceeded") -> None:
        """Override to handle quota exhaustion via account rotation."""
        if reason == "quota_exceeded":
            logger.warning("Quota exceeded for account, triggering rotation")
            # Schedule rotation task and keep reference to prevent GC
            task = asyncio.create_task(self._rotate_and_sync())
            self._background_tasks.add(task)
            task.add_done_callback(self._background_tasks.discard)
        else:
            super()._mark_backend_unusable(reason=reason)


# Register backend
backend_registry.register_backend("gemini-oauth-auto", GeminiOAuthAutoConnector)

