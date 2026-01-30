"""
GeminiOAuthAutoConnector implementation.

Backend connector with self-managed OAuth tokens and multi-account support.
"""

import asyncio
import contextlib
import logging
import os
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

        refresh_buffer_ms = int(refresh_buffer_seconds * 1000)

        # Check if this is first initialization or re-initialization
        if not self._is_initialized:
            # First initialization - create services and select first account
            self._token_storage = TokenStorageService(storage_path=storage_path)
            self._token_refresh = TokenRefreshService(
                storage=self._token_storage,
                http_client=self.client,
            )

            self._account_selector = AccountSelectorService(
                storage=self._token_storage,
                refresh_service=self._token_refresh,
                refresh_buffer_ms=refresh_buffer_ms,
                allowed_account_ids=accounts_allowlist,
                selection_strategy=selection_strategy,
            )

            await self._account_selector.reload_accounts()
            account = await self._account_selector.get_next_account()
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
            await self._account_selector.reload_accounts()
            # Use current account if available, otherwise get next
            account = self._account_selector.get_current_account()
            if not account:
                account = await self._account_selector.get_next_account()
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

    async def _refresh_token_if_needed(self, *, force_reload: bool = False) -> bool:
        """Ensure a valid access token is available.

        For auto-connector, we use account rotation and refresh.

        For round-robin strategy, rotates accounts before each request.
        For other strategies, only rotates when account expires or is missing.

        When force_reload=True (typically from rate limit retry), performs account
        rotation to switch to a different account that may not be rate-limited.
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

            new_account = await self._account_selector.rotate_on_quota()

            if (
                new_account
                and old_account
                and new_account.account_id != old_account.account_id
            ):
                logger.info(
                    "Successfully rotated from account %s to %s",
                    old_account.account_id,
                    new_account.account_id,
                )
                self._sync_selected_account_to_base()
                return True  # Rotation succeeded
            else:
                # No rotation happened (single account or all accounts exhausted)
                if not new_account:
                    logger.warning(
                        "Account rotation failed: no account available after rotation"
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

        account = self._account_selector.get_current_account()

        # For round-robin strategy, rotate before each request
        # For other strategies, only rotate if account is missing or expired
        should_rotate = False
        if not account or account.is_expired():
            should_rotate = True
        elif self._account_selector.selection_strategy == "round-robin":
            # Round-robin: rotate before each request to distribute load
            should_rotate = True

        if should_rotate:
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

    async def _discover_project_id(self, auth_session: Any = None) -> str:
        """
        Discover or retrieve the project ID for Code Assist API.

        This implementation follows the same pattern as gemini-oauth-free and
        gemini-oauth-plan connectors:
        1. Check if project ID is in current account's credentials
        2. Call loadCodeAssist to discover existing project
        3. If no project found, onboard with free-tier and poll for completion
        """
        # Get current account
        current_account = self._account_selector.get_current_account()

        # Check for cached project ID
        cached_id = self._get_cached_project_id(current_account)
        if cached_id:
            return cached_id

        if not auth_session:
            logger.warning("auth_session missing for project discovery, using fallback")
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
            return str(fallback_project_id)

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

        while True:
            try:
                result = await super().chat_completions(
                    request_data=request.request,
                    processed_messages=list(request.processed_messages),
                    effective_model=effective_model,
                    identity=request.identity,
                    cancellation_token=request.cancellation_token,
                    cancellation_coordinator=request.cancellation_coordinator,
                    **cast(dict[str, Any], request.options),
                )
                break  # Success
            except BackendError as e:
                error_str = str(e)
                if "To continue, validate" in error_str:
                    await self._account_selector.mark_current_account_blocked(error_str)
                    self._sync_selected_account_to_base()
                    # Ensure AuthErrorHandler doesn't disable the entire auto-pool instance
                    setattr(e, "__resilience_context__", {"is_personal_backend": True})

                    # Try next account if available
                    if self._account_selector.get_available_count() > 0:
                        logger.info("Account blocked; retrying with next available account")
                        continue

                if getattr(e, "status_code", None) == 429:
                    await self.record_rate_limit(
                        retry_after_seconds=self._extract_retry_after_seconds(e)
                    )
                if e.code == "quota_exceeded":
                    self._mark_backend_unusable(reason="quota_exceeded")
                raise

        if isinstance(result, StreamingResponseEnvelope) and result.content:
            result.content = self._wrap_stream_for_rotation(result.content)

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
                if "To continue, validate" in error_msg:
                    logger.warning(
                        "Detected account block in stream, triggering rotation"
                    )
                    await self._account_selector.mark_current_account_blocked(error_msg)
                    self._sync_selected_account_to_base()
                elif error_type == "quota_exceeded" or error_code in (429, 503):
                    logger.warning(
                        "Detected quota error in stream, triggering rotation"
                    )
                    self._mark_backend_unusable(reason="quota_exceeded")

            yield chunk

    async def _rotate_and_sync(self) -> None:
        """Rotate to next account and sync credentials into gemini_base."""
        await self._account_selector.rotate_on_quota()
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
