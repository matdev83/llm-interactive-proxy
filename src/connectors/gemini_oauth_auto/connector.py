"""
GeminiOAuthAutoConnector implementation.

Backend connector with self-managed OAuth tokens and multi-account support.
"""

import asyncio
import contextlib
import logging
import os
import time
from collections.abc import AsyncIterator
from datetime import datetime, timezone
from typing import Any, cast

import httpx
from fastapi import HTTPException

from src.connectors.contracts import ConnectorChatCompletionsRequest
from src.connectors.gemini_base.config import DEFAULT_AVAILABLE_MODELS
from src.connectors.gemini_base.model_discovery import FallbackModelDiscovery
from src.connectors.gemini_base.models import GeminiOAuthCredentials, TierScore
from src.connectors.gemini_oauth_auto.account_selector import AccountSelectorService
from src.connectors.gemini_oauth_auto.token_refresh import TokenRefreshService
from src.connectors.gemini_oauth_auto.token_storage import TokenStorageService
from src.connectors.gemini_oauth_base import GeminiOAuthBaseConnector
from src.core.common.exceptions import BackendError
from src.core.config.app_config import AppConfig
from src.core.domain.responses import ResponseEnvelope, StreamingResponseEnvelope
from src.core.interfaces.response_processor_interface import ProcessedResponse
from src.core.services.backend_registry import backend_registry
from src.core.services.notification_service import NotificationService
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

    prompt_limit_prefix_overrides: tuple[tuple[str, int], ...] = (
        ("gemini-2.5", 1_000_000),
        ("gemini-3", 1_000_000),
    )

    backend_type: str = "gemini-oauth-auto"

    _ACCOUNT_BLOCK_MARKERS: tuple[str, ...] = (
        "to continue, validate",
        "to continue, verify",
        "validate your account",
        "verify your account",
        "account is suspended",
        "account suspended",
        "account disabled",
        "account has been disabled",
        "account blocked",
        "account has been blocked",
        "suspicious activity",
        "verify it's you",
        "confirm your identity",
    )

    _STREAM_PRIME_TIMEOUT_SECONDS: float = 0.75

    @staticmethod
    def _is_project_not_found_error(error: BackendError) -> bool:
        status_code = getattr(error, "status_code", None)
        if status_code != 404:
            return False

        message = str(getattr(error, "message", "") or "")
        if message and "requested entity was not found" in message.lower():
            return True

        details = getattr(error, "details", None)
        if not isinstance(details, dict):
            return False

        inner = details.get("error")
        if not isinstance(inner, dict):
            return False

        status_val = inner.get("status")
        return isinstance(status_val, str) and status_val.upper() == "NOT_FOUND"

    async def _prime_streaming_response(
        self, envelope: StreamingResponseEnvelope
    ) -> StreamingResponseEnvelope:
        """Prime the streaming iterator to surface immediate failures.

        The Gemini Code Assist streaming stack may raise a BackendError before
        yielding any chunks (e.g., when the HTTP response is 404). Without a
        small prime, that failure only shows up later during response streaming,
        which prevents oauth-auto from failing over to another account.

        We do a best-effort, non-blocking prime:
        - If the first chunk/error is available quickly, surface it now.
        - If not, return immediately and stream normally.
        """
        iterator = envelope.content
        if iterator is None:
            return envelope

        async def _first_item() -> ProcessedResponse:
            return await anext(iterator)

        first_task: asyncio.Task[ProcessedResponse] = asyncio.create_task(_first_item())
        done, _pending = await asyncio.wait(
            {first_task}, timeout=self._STREAM_PRIME_TIMEOUT_SECONDS
        )

        async def _gen_prefetched() -> AsyncIterator[ProcessedResponse]:
            first = await first_task
            yield first
            async for item in iterator:
                yield item

        if first_task in done:
            first = await first_task

            async def _gen_now() -> AsyncIterator[ProcessedResponse]:
                yield first
                async for item in iterator:
                    yield item

            envelope.content = _gen_now()
            return envelope

        envelope.content = _gen_prefetched()
        return envelope

    def __init__(
        self,
        client: httpx.AsyncClient,
        config: AppConfig,
        translation_service: TranslationService,
        name: str = "gemini-oauth-auto",
    ) -> None:
        """Initialize Gemini OAuth Auto-Connector."""
        super().__init__(
            client,
            config,
            translation_service,
            name,
            # Use FallbackModelDiscovery to avoid hitting non-existent fetchAvailableModels API
            model_discovery=FallbackModelDiscovery(models=DEFAULT_AVAILABLE_MODELS),
        )

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
        # Track if initialize() has been called to preserve rotation on re-init
        self._is_initialized = False

    async def _handle_project_not_found(
        self, account: Any, error: BackendError
    ) -> None:
        if not account:
            return

        account_id = getattr(account, "account_id", "unknown")
        email = getattr(account, "email", None) or account_id
        project_id = getattr(account, "project_id", None)

        notification_service = getattr(
            self._account_selector, "notification_service", None
        )
        if notification_service:
            help_url = "https://support.google.com/googleapi/answer/7014113"
            message = (
                f"Gemini OAuth account '{email}' failed with a 404 from Code Assist "
                f"(project not found).\n\n"
                f"Current project_id: {project_id!r}\n\n"
                "This usually means the Cloud Project ID / Code Assist project is missing, "
                "incorrect, or not accessible for this account.\n\n"
                f"Backend message: {getattr(error, 'message', '')}\n\n"
                f"Help: {help_url}"
            )
            try:
                await notification_service.send_notification(
                    title="Gemini OAuth: Project not found",
                    message=message,
                    url=help_url,
                    url_label="View Help",
                )
                logger.info(
                    "Sent notification for account %s with project not found error",
                    account_id,
                )
            except Exception as exc:
                logger.debug("Failed to send project not found notification: %s", exc)

        await self._account_selector.mark_account_uninitialized(account_id)
        logger.warning(
            "Account %s removed from available accounts due to project not found (404). "
            "This is a runtime-only operation; storage files were not modified.",
            account_id,
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

    @classmethod
    def _is_account_blocked_message(
        cls,
        message: str | None,
        *,
        status_code: int | None = None,
        details: dict[str, Any] | None = None,
    ) -> bool:
        if status_code != 403:
            return False

        messages: list[str] = []
        if isinstance(message, str) and message.strip():
            messages.append(message)

        if isinstance(details, dict):
            direct_message = details.get("message")
            if isinstance(direct_message, str) and direct_message.strip():
                messages.append(direct_message)

            error_detail = details.get("error")
            if isinstance(error_detail, dict):
                error_message = error_detail.get("message")
                if isinstance(error_message, str) and error_message.strip():
                    messages.append(error_message)
            elif isinstance(error_detail, str) and error_detail.strip():
                messages.append(error_detail)

        for candidate in messages:
            normalized = candidate.lower()
            if any(marker in normalized for marker in cls._ACCOUNT_BLOCK_MARKERS):
                return True

        return False

    @classmethod
    def _is_account_blocked_error(cls, error: BackendError) -> bool:
        return cls._is_account_blocked_message(
            error.message,
            status_code=getattr(error, "status_code", None),
            details=getattr(error, "details", None),
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

    def get_thought_signature_namespace(self) -> str | None:
        """Return a namespace identifier for thought signature caching."""
        selector = getattr(self, "_account_selector", None)
        if selector is None:
            return None
        try:
            account = selector.get_current_account()
        except Exception:
            return None
        if not account or not getattr(account, "account_id", None):
            return None
        return f"{self.backend_type}:{account.account_id}"

    async def initialize(self, **kwargs: Any) -> None:
        """Initialize connector and load accounts."""
        backend_config = self.config.backends.get("gemini-oauth-auto")
        extras_dict = backend_config.extra if backend_config else {}

        from src.connectors.gemini_oauth_auto.models import GeminiOAuthAutoConfig

        try:
            auto_config = GeminiOAuthAutoConfig(**extras_dict)
        except Exception as e:
            logger.warning(
                "Invalid gemini-oauth-auto configuration, using defaults: %s", e
            )
            auto_config = GeminiOAuthAutoConfig()

        current = self._enable_gemini_oauth_auto_backend_debugging_override
        self._enable_gemini_oauth_auto_backend_debugging_override = (
            kwargs.get("enable_gemini_oauth_auto_backend_debugging_override")
            if "enable_gemini_oauth_auto_backend_debugging_override" in kwargs
            else extras_dict.get(
                "enable_gemini_oauth_auto_backend_debugging_override", current
            )
        )

        logger.info("Initializing Gemini OAuth Auto backend: %s", self.name)

        self.gemini_api_base_url = kwargs.get(
            "gemini_api_base_url", "https://cloudcode-pa.googleapis.com"
        )
        self.api_url = self.gemini_api_base_url

        storage_path = auto_config.storage_path
        refresh_buffer_seconds = auto_config.refresh_buffer_seconds
        accounts_allowlist = self._parse_accounts_allowlist(auto_config.accounts)
        selection_strategy = auto_config.selection_strategy
        session_affinity_ttl_seconds = auto_config.session_affinity_ttl_seconds
        session_affinity_max_entries = auto_config.session_affinity_max_entries
        session_affinity_max_wait_seconds = self.config.failure_handling.max_silent_wait

        refresh_buffer_ms = int(refresh_buffer_seconds * 1000)

        # Check if this is first initialization or re-initialization
        if not self._is_initialized:
            # First initialization - create services and select first account
            self._token_storage = TokenStorageService(storage_path=storage_path)
            self._token_refresh = TokenRefreshService(
                storage=self._token_storage,
                http_client=self.client,
            )

            # Initialize notification service
            notification_service = NotificationService(
                config=self.config.notifications,
                host=self.config.host,
            )

            self._account_selector = AccountSelectorService(
                storage=self._token_storage,
                refresh_service=self._token_refresh,
                refresh_buffer_ms=refresh_buffer_ms,
                allowed_account_ids=accounts_allowlist,
                selection_strategy=selection_strategy,
                session_affinity_ttl_seconds=session_affinity_ttl_seconds,
                session_affinity_max_entries=session_affinity_max_entries,
                session_affinity_max_wait_seconds=session_affinity_max_wait_seconds,
                notification_service=notification_service,
            )

            await self._account_selector.reload_accounts()
            account = await self._account_selector.get_next_account(session_id=None)
            self._is_initialized = True
        else:
            # Re-initialization - preserve rotation state but update configuration
            logger.debug(
                "Re-initializing connector - preserving rotation state (current_index=%d)",
                self._account_selector.rotation_index,
            )
            # Update configuration without resetting rotation
            self._account_selector.refresh_buffer_ms = refresh_buffer_ms
            self._account_selector.allowed_account_ids = accounts_allowlist
            self._account_selector.selection_strategy = selection_strategy
            self._account_selector.session_affinity_ttl_seconds = (
                session_affinity_ttl_seconds
            )
            self._account_selector.session_affinity_max_entries = (
                session_affinity_max_entries
            )
            self._account_selector.session_affinity_max_wait_seconds = (
                session_affinity_max_wait_seconds
            )
            # Update notification service based on current config
            self._account_selector.notification_service = NotificationService(
                config=self.config.notifications,
                host=self.config.host,
            )
            await self._account_selector.reload_accounts()
            # Use current account if available, otherwise get next
            account = self._account_selector.get_current_account()
            if not account:
                account = await self._account_selector.get_next_account(session_id=None)
        self._sync_selected_account_to_base()

        if account:
            self.is_functional = True
            logger.info(
                "Gemini OAuth Auto backend initialized with %d accounts (strategy: %s)",
                self._account_selector.get_available_count(),
                selection_strategy,
            )
        else:
            logger.warning(
                "Gemini OAuth Auto backend initialized with NO valid accounts"
            )
            self.is_functional = False

        if self.is_functional:
            await self._ensure_models_loaded()

    async def _refresh_token_if_needed(
        self,
        *,
        force_reload: bool = False,
        session_id: str | None = None,
        retry_after_seconds: float | None = None,
    ) -> bool:
        """Ensure a valid access token is available.

        For auto-connector, we use account rotation and refresh.

        For round-robin strategy, rotates accounts before each request.
        For other strategies, only rotates when account expires or is missing.

        When force_reload=True (typically from rate limit retry), performs account
        rotation to switch to a different account that may not be rate-limited.

        Raises:
            AuthenticationError: When no account is available due to rate limiting
                or other account availability issues. This provides better error
                messages than the generic "Failed to refresh OAuth token" error.
        """
        if force_reload:
            # force_reload=True is called by streaming executor on 429 rate limits
            # Rotate to next account to avoid rate limit on current account
            old_account = self._account_selector.get_current_account()
            total_accounts = self._account_selector.total_count

            logger.info(
                "Rate limit detected, attempting account rotation (current: %s, total accounts: %d)",
                old_account.account_id if old_account else "none",
                total_accounts,
            )

            new_account = await self._account_selector.rotate_on_quota(
                session_id=session_id, retry_after_seconds=retry_after_seconds
            )

            if (
                new_account
                and old_account
                and new_account.account_id != old_account.account_id
            ):
                # Calculate when the old (rate-limited) account will be available again
                if retry_after_seconds:
                    available_at = datetime.fromtimestamp(
                        time.time() + retry_after_seconds, tz=timezone.utc
                    )
                    available_info = f"available at {available_at.strftime('%Y-%m-%d %H:%M:%S')} ({retry_after_seconds:.0f}s)"
                else:
                    available_info = "available time unknown"

                logger.info(
                    "Successfully rotated from account %s to %s (reason: rate limit, %s)",
                    old_account.account_id,
                    new_account.account_id,
                    available_info,
                )
                self._sync_selected_account_to_base()
                return True  # Rotation succeeded
            else:
                # No rotation happened (single account or all accounts exhausted)
                if not new_account:
                    logger.warning(
                        "Account rotation failed: no account available after rotation"
                    )
                    # Check if all accounts are rate-limited for better error message
                    available_count = self._account_selector.get_available_count()
                    if available_count == 0:
                        from src.core.common.exceptions import AuthenticationError

                        raise AuthenticationError(
                            "All OAuth accounts are currently unavailable "
                            "(likely all accounts are rate-limited)"
                        )
                elif not old_account:
                    logger.warning("Account rotation skipped: no current account")
                else:
                    logger.warning(
                        "Account rotation returned same account (likely all %d accounts are rate-limited)",
                        total_accounts,
                    )
                await self._account_selector.reload_accounts()
                self._sync_selected_account_to_base()
                return False

        if self._account_selector.selection_strategy == "session-affinity":
            account = await self._account_selector.get_next_account(
                session_id=session_id
            )
            self._sync_selected_account_to_base()
            if account is None:
                # Check if all accounts are rate-limited
                available_count = self._account_selector.get_available_count()
                if available_count == 0:
                    from src.core.common.exceptions import AuthenticationError

                    raise AuthenticationError(
                        "All OAuth accounts are currently unavailable "
                        "(likely all accounts are rate-limited)"
                    )
                return False
            return True

        account = self._account_selector.get_current_account()

        # For round-robin strategy, we only rotate if account is missing or expired.
        # Rotation between requests is handled in chat_completions entry point.
        should_rotate = False
        if not account or account.is_expired():
            should_rotate = True

        if should_rotate:
            account = await self._account_selector.get_next_account(
                session_id=session_id
            )

        self._sync_selected_account_to_base()

        if account is None:
            # Check if all accounts are rate-limited
            available_count = self._account_selector.get_available_count()
            if available_count == 0:
                from src.core.common.exceptions import AuthenticationError

                raise AuthenticationError(
                    "All OAuth accounts are currently unavailable "
                    "(likely all accounts are rate-limited)"
                )
            return False

        return True

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

    async def _validate_runtime_credentials(self) -> bool:
        """Validate credentials at runtime.

        Overrides base class to use auto-connector's functional state.
        """
        return self.is_backend_functional()

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
            reason = getattr(
                self, "_last_health_change_reason", "Authentication failed"
            )
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

    def _get_cached_project_id(self, current_account: Any) -> str | None:
        """Check for existing project ID in the current account's credentials."""
        if (
            current_account
            and current_account.project_id
            and current_account.project_id != "default"
        ):
            if logger.isEnabledFor(logging.INFO):
                logger.info(
                    "Using cached project ID from account: %s",
                    current_account.project_id,
                )
            return str(current_account.project_id)
        return None

    def _extract_project_id_from_response(
        self, data: dict[str, Any], top_key: str = "cloudaicompanionProject"
    ) -> str | None:
        """Extract project ID from a response dictionary (string or dict format)."""
        project_candidate = data.get(top_key)
        if isinstance(project_candidate, dict):
            project_candidate = project_candidate.get("id")

        project_id = str(project_candidate) if project_candidate else None
        return project_id if project_id and project_id != "default" else None

    async def _update_account_project(self, account: Any, project_id: str) -> None:
        """Update account storage with discovered project ID."""
        if not account:
            return

        updated_account = account.model_copy(
            update={
                "project_id": project_id,
                "updated_at": datetime.now(timezone.utc).isoformat(),
            }
        )
        await self._token_storage.save_account(updated_account)
        self._account_selector.update_account(updated_account)
        self._sync_selected_account_to_base()

    def _get_tier_score(self, tier: dict[str, Any]) -> TierScore:
        """Calculate score for a tier to find the best one for onboarding."""

        def _tier_id(t: dict[str, Any]) -> str:
            return str(t.get("id") or t.get("tierId") or "").lower()

        def _context_tokens(t: dict[str, Any]) -> int:
            for key in (
                "maxContextTokens",
                "contextTokenLimit",
                "contextWindowTokens",
                "tokenLimit",
                "maxContextWindow",
            ):
                value = t.get(key)
                if isinstance(value, int | float):
                    return int(value)
            return 0

        tid = _tier_id(tier)
        is_paid = int(
            tid
            in {
                "paid-tier",
                "google-one-tier",
                "googleone-tier",
                "googleone",
                "duet-ai-pro",
                "standard-tier",
            }
        )

        tokens = _context_tokens(tier)
        if is_paid and tokens == 0:
            tokens = 1_000_000

        return TierScore(
            is_paid=is_paid,
            context_tokens=tokens,
            is_default=int(bool(tier.get("isDefault"))),
        )

    async def _handle_missing_project_id(self, account: Any) -> None:
        """Handle case when project ID cannot be determined for an account.

        Sends a desktop notification to inform the user about the missing
        Cloud Project ID setup and removes the account from in-memory list.

        Args:
            account: The account that lacks a Cloud Project ID.
        """
        if not account:
            return

        account_id = getattr(account, "account_id", "unknown")
        email = getattr(account, "email", None) or account_id

        # Send desktop notification
        notification_service = getattr(
            self._account_selector, "notification_service", None
        )
        if notification_service:
            help_url = "https://support.google.com/googleapi/answer/7014113"
            message = (
                f"Google account '{email}' requires prior setup of a Cloud Project ID.\n\n"
                f"Please configure a Google Cloud Project for this account before using it.\n\n"
                f"Help: {help_url}"
            )
            try:
                await notification_service.send_notification(
                    title="Gemini OAuth: Cloud Project ID Required",
                    message=message,
                    url=help_url,
                    url_label="View Help",
                )
                logger.info(
                    "Sent notification for account %s missing Cloud Project ID",
                    account_id,
                )
            except Exception as e:
                logger.debug("Failed to send project ID notification: %s", e)

        # Remove account from in-memory list (mark as blocked)
        # This is a runtime-only operation - storage files are not touched
        await self._account_selector.mark_account_uninitialized(account_id)
        logger.warning(
            "Account %s removed from available accounts due to missing Cloud Project ID. "
            "This is a runtime-only operation; storage files were not modified.",
            account_id,
        )

    async def _discover_project_id(self, auth_session: Any = None) -> str:
        """
        Discover or retrieve the project ID for Code Assist API.

        This implementation follows the same pattern as gemini-oauth-free and
        gemini-oauth-plan connectors:
        1. Check if project ID is in current account's credentials
        2. Call loadCodeAssist to discover existing project
        3. If no project found, onboard with free-tier and poll for completion

        If project ID cannot be determined, the account will be marked as
        uninitialized and removed from the in-memory available accounts list.
        """
        # Get current account
        current_account = self._account_selector.get_current_account()

        # Check for cached project ID
        cached_id = self._get_cached_project_id(current_account)
        if cached_id:
            return cached_id

        if not auth_session:
            logger.warning("auth_session missing for project discovery, using fallback")
            if current_account:
                await self._handle_missing_project_id(current_account)
            return "default"

        # Get initial project ID from current account if available
        initial_project_id = current_account.project_id if current_account else None
        if initial_project_id == "default":
            initial_project_id = None

        fallback_project_id = initial_project_id or "default"

        try:
            # Step 1: Call loadCodeAssist to discover existing project ID
            client_metadata = {
                "ideType": "IDE_UNSPECIFIED",
                "platform": "PLATFORM_UNSPECIFIED",
                "pluginType": "GEMINI",
                "duetProject": initial_project_id,
            }
            load_request: dict[str, Any] = {"metadata": client_metadata}
            if initial_project_id:
                load_request["cloudaicompanionProject"] = initial_project_id

            load_url = f"{self.gemini_api_base_url}/v1internal:loadCodeAssist"
            load_response = await asyncio.to_thread(
                auth_session.request,
                method="POST",
                url=load_url,
                json=load_request,
                headers={"Content-Type": "application/json"},
                timeout=30.0,
            )

            if load_response.status_code != 200:
                raise BackendError(f"LoadCodeAssist failed: {load_response.text}")

            load_data = load_response.json()

            # Check cloudaicompanionProject and currentTier for existing project ID
            project_candidate = self._extract_project_id_from_response(load_data)

            # If not in top level, check currentTier
            if not project_candidate:
                current_tier_data = load_data.get("currentTier")
                if isinstance(current_tier_data, dict):
                    project_candidate = self._extract_project_id_from_response(
                        current_tier_data
                    )

            if project_candidate:
                if logger.isEnabledFor(logging.INFO):
                    logger.info(
                        "Discovered project ID from loadCodeAssist: %s",
                        project_candidate,
                    )
                await self._update_account_project(current_account, project_candidate)
                return project_candidate

            # Step 2: Determine which tier to use for onboarding
            allowed_tiers = [
                t for t in load_data.get("allowedTiers", []) if isinstance(t, dict)
            ]
            if isinstance(load_data.get("currentTier"), dict):
                allowed_tiers.append(load_data["currentTier"])

            tier_to_use = (
                max(allowed_tiers, key=self._get_tier_score)
                if allowed_tiers
                else {"id": "free-tier"}
            )
            selected_tier_id = (
                tier_to_use.get("id") or tier_to_use.get("tierId") or "free-tier"
            )

            # Step 3: Perform onboarding
            onboard_url = f"{self.gemini_api_base_url}/v1internal:onboardUser"
            max_retries, retry_count = 30, 0
            onboarding_completed_with_default = False

            while retry_count < max_retries:
                # Prepare onboarding request
                is_paid_tier = selected_tier_id != "free-tier"
                if is_paid_tier:
                    onboard_request = {
                        "tierId": selected_tier_id,
                        "metadata": {
                            **client_metadata,
                            "duetProject": initial_project_id,
                        },
                    }
                    if initial_project_id:
                        onboard_request["cloudaicompanionProject"] = initial_project_id
                else:
                    onboard_request = {
                        "tierId": selected_tier_id,
                        "metadata": {
                            "ideType": "IDE_UNSPECIFIED",
                            "platform": "PLATFORM_UNSPECIFIED",
                            "pluginType": "GEMINI",
                        },
                    }

                lro_response = await asyncio.to_thread(
                    auth_session.request,
                    method="POST",
                    url=onboard_url,
                    json=onboard_request,
                    headers={"Content-Type": "application/json"},
                    timeout=30.0,
                )

                if lro_response.status_code != 200:
                    error_text = lro_response.text
                    if (
                        selected_tier_id == "free-tier"
                        and "FREE_TIER_USER_NOT_ELIGIBLE" in error_text
                    ):
                        selected_tier_id = "standard-tier"  # Retry with standard
                        continue
                    raise BackendError(f"OnboardUser failed: {error_text}")

                lro_data = lro_response.json()
                if lro_data.get("done"):
                    resp_data = lro_data.get("response", {})
                    discovered_project_id = self._extract_project_id_from_response(
                        resp_data
                    )

                    if discovered_project_id:
                        if logger.isEnabledFor(logging.INFO):
                            logger.info(
                                "Discovered project ID from onboarding: %s",
                                discovered_project_id,
                            )
                        await self._update_account_project(
                            current_account, discovered_project_id
                        )
                        return discovered_project_id

                    onboarding_completed_with_default = True
                    break

                retry_count += 1
                await asyncio.sleep(2)

            # Final check if onboarding returned default
            if onboarding_completed_with_default:
                load_response_retry = await asyncio.to_thread(
                    auth_session.request,
                    method="POST",
                    url=load_url,
                    json=load_request,
                    headers={"Content-Type": "application/json"},
                    timeout=30.0,
                )
                if load_response_retry.status_code == 200:
                    project_retry = self._extract_project_id_from_response(
                        load_response_retry.json()
                    )
                    if project_retry:
                        await self._update_account_project(
                            current_account, project_retry
                        )
                        return project_retry

            if retry_count >= max_retries and not onboarding_completed_with_default:
                raise BackendError(f"Onboarding timeout after {max_retries} retries")

        except Exception as exc:
            if logger.isEnabledFor(logging.WARNING):
                logger.warning(
                    "Project discovery failed, using fallback '%s': %s",
                    fallback_project_id,
                    exc,
                    exc_info=True,
                )
            # If we couldn't determine a project ID, mark account as uninitialized
            if fallback_project_id == "default" and current_account:
                await self._handle_missing_project_id(current_account)
            return str(fallback_project_id)

        # If we reach here with "default", project ID couldn't be determined
        if fallback_project_id == "default" and current_account:
            await self._handle_missing_project_id(current_account)
        return str(fallback_project_id)

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

        # For round-robin strategy, rotate account before each request to distribute load.
        # We do this here instead of _refresh_token_if_needed to ensure exactly one
        # rotation per request, even if _refresh_token_if_needed is called multiple times
        # (e.g. for health checks, request preparation, and actual execution).
        if self._account_selector.selection_strategy == "round-robin":
            logger.debug("Round-robin: rotating account before request")
            session_id = request.context.session_id if request.context else None
            await self._account_selector.get_next_account(session_id=session_id)
            self._sync_selected_account_to_base()

        if request.context is not None:
            account = self._account_selector.get_current_account()
            account_id = getattr(account, "account_id", None) if account else None
            if isinstance(account_id, str) and account_id:
                request.context.extensions["account_id"] = account_id

        session_id = request.context.session_id if request.context else None

        while True:
            try:
                result = await super().chat_completions(
                    request_data=request.request,
                    processed_messages=list(request.processed_messages),
                    effective_model=effective_model,
                    identity=request.identity,
                    context=request.context,
                    cancellation_token=request.cancellation_token,
                    cancellation_coordinator=request.cancellation_coordinator,
                    **cast(dict[str, Any], request.options),
                )
                if isinstance(result, StreamingResponseEnvelope) and result.content:
                    result = await self._prime_streaming_response(result)
                break  # Success
            except BackendError as e:
                current_account = self._account_selector.get_current_account()
                current_account_id = (
                    getattr(current_account, "account_id", None)
                    if current_account
                    else None
                )

                if self._is_project_not_found_error(e) and current_account:
                    await self._handle_project_not_found(current_account, e)
                    if self._account_selector.get_available_count() > 0:
                        await self._account_selector.get_next_account(
                            session_id=session_id
                        )
                        self._sync_selected_account_to_base()
                        logger.info(
                            "Project not found for account %s; retrying with next available account",
                            current_account_id,
                        )
                        continue

                if self._is_account_blocked_error(e):
                    await self._account_selector.mark_current_account_blocked(e.message)
                    self._sync_selected_account_to_base()
                    # Ensure AuthErrorHandler doesn't disable the entire auto-pool instance
                    e.__resilience_context__ = {"is_personal_backend": True}  # type: ignore[attr-defined]

                    # Try next account if available
                    if self._account_selector.get_available_count() > 0:
                        logger.info(
                            "Account blocked; retrying with next available account"
                        )
                        continue

                if getattr(e, "status_code", None) == 429 and not getattr(
                    cast(Any, e), "__rate_limit_recorded__", False
                ):
                    # Logic amplification: Avoid duplicate rate limit recording
                    with contextlib.suppress(AttributeError, TypeError):
                        cast(Any, e).__rate_limit_recorded__ = True
                    await self.record_rate_limit(
                        retry_after_seconds=self._extract_retry_after_seconds(e)
                    )
                if e.code == "quota_exceeded":
                    self._mark_backend_unusable(
                        reason="quota_exceeded",
                        retry_after_seconds=self._extract_retry_after_seconds(e),
                    )
                raise

        if isinstance(result, StreamingResponseEnvelope) and result.content:
            result.content = self._wrap_stream_for_rotation(result.content)

        account = self._account_selector.get_current_account()
        account_id = getattr(account, "account_id", None) if account else None
        if isinstance(account_id, str) and account_id:
            if result.metadata is None:
                result.metadata = {}
            result.metadata["account_id"] = account_id

        await self._account_selector.mark_current_account_used()

        return result

    async def _wrap_stream_for_rotation(
        self, stream: AsyncIterator[ProcessedResponse]
    ) -> AsyncIterator[ProcessedResponse]:
        """Wrap streaming responses to detect quota errors and trigger rotation."""
        async for chunk in stream:
            # Check for error in chunk metadata
            error_info = chunk.metadata.get("error") if chunk.metadata else None
            if isinstance(error_info, dict):
                error_type = str(error_info.get("type", "")).lower()
                error_code = error_info.get("code")
                error_msg = str(error_info.get("message", ""))
                if self._is_account_blocked_message(
                    error_msg,
                    status_code=error_code if isinstance(error_code, int) else None,
                    details=error_info,
                ):
                    logger.warning(
                        "Detected account block in stream, triggering rotation"
                    )
                    await self._account_selector.mark_current_account_blocked(error_msg)
                    self._sync_selected_account_to_base()
                elif error_type == "quota_exceeded" or error_code in (429, 503):
                    logger.warning(
                        "Detected quota error in stream, triggering rotation"
                    )
                    # Extract retry delay from chunk if available
                    retry_delay = error_info.get("retry_after")
                    if not isinstance(retry_delay, int | float):
                        retry_delay = None

                    self._mark_backend_unusable(
                        reason="quota_exceeded", retry_after_seconds=retry_delay
                    )

            yield chunk

    async def _rotate_and_sync(self, retry_after_seconds: float | None = None) -> None:
        """Rotate to next account and sync credentials into gemini_base."""
        await self._account_selector.rotate_on_quota(
            retry_after_seconds=retry_after_seconds
        )
        self._sync_selected_account_to_base()

    @staticmethod
    def _extract_retry_after_seconds(error: BackendError) -> float | None:
        details = getattr(error, "details", None)
        if not isinstance(details, dict):
            return None
        retry_after = details.get("retry_after")
        if isinstance(retry_after, int | float):
            return float(retry_after)
        return None

    async def record_rate_limit(self, *, retry_after_seconds: float | None) -> None:
        await self._account_selector.mark_current_account_rate_limited(
            retry_after_seconds
        )
        self._sync_selected_account_to_base()

    def _mark_backend_unusable(
        self,
        *,
        reason: str = "quota_exceeded",
        retry_after_seconds: float | None = None,
    ) -> None:
        """Override to handle quota exhaustion via account rotation."""
        if reason == "quota_exceeded":
            logger.warning("Quota exceeded for account, triggering rotation")
            # Schedule rotation task and keep reference to prevent GC
            task = asyncio.create_task(
                self._rotate_and_sync(retry_after_seconds=retry_after_seconds)
            )
            self._background_tasks.add(task)
            task.add_done_callback(self._background_tasks.discard)
        else:
            super()._mark_backend_unusable(reason=reason)


# Register backend
backend_registry.register_backend("gemini-oauth-auto", GeminiOAuthAutoConnector)
