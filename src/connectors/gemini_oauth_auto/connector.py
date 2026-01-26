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
                self._account_selector._rotation_index,
            )
            # Update configuration without resetting rotation
            self._account_selector._refresh_buffer_ms = refresh_buffer_ms
            self._account_selector._allowed_account_ids = accounts_allowlist
            self._account_selector._selection_strategy = selection_strategy
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
        """
        if force_reload:
            await self._account_selector.reload_accounts()

        account = self._account_selector.get_current_account()

        # For round-robin strategy, rotate before each request
        # For other strategies, only rotate if account is missing or expired
        should_rotate = False
        if not account or account.is_expired():
            should_rotate = True
        elif self._account_selector._selection_strategy == "round-robin":
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

        # Check for existing project ID in the current account's credentials
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

        if not auth_session:
            logger.warning(
                "auth_session required for project discovery but missing, using fallback"
            )
            return "default"

        # Get initial project ID from current account if available
        initial_project_id = current_account.project_id if current_account else None
        if initial_project_id == "default":
            initial_project_id = None

        fallback_project_id = initial_project_id or "default"

        # Prepare client metadata (matching other connectors)
        client_metadata = {
            "ideType": "IDE_UNSPECIFIED",
            "platform": "PLATFORM_UNSPECIFIED",
            "pluginType": "GEMINI",
            "duetProject": initial_project_id,
        }

        try:
            # Step 1: Call loadCodeAssist to discover existing project ID
            load_request: dict[str, Any] = {
                "metadata": client_metadata,
            }
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

            # Debug: log the full response to understand structure
            if logger.isEnabledFor(logging.DEBUG):
                logger.debug("loadCodeAssist response: %s", load_data)

            # Also check currentTier for project ID (accounts may already be onboarded)
            # For paid tiers, project ID might be in currentTier.cloudaicompanionProject
            current_tier_data = load_data.get("currentTier")
            if isinstance(current_tier_data, dict):
                tier_project = current_tier_data.get("cloudaicompanionProject")
                if tier_project:
                    # Extract project ID from currentTier (can be string or dict)
                    if isinstance(tier_project, dict):
                        tier_project = tier_project.get("id") or tier_project
                    tier_project = str(tier_project) if tier_project else None

                    # Use currentTier project ID if top-level doesn't have a valid one
                    top_level_project = load_data.get("cloudaicompanionProject")
                    if not top_level_project or (
                        isinstance(top_level_project, str)
                        and top_level_project == "default"
                    ):
                        if tier_project and tier_project != "default":
                            if logger.isEnabledFor(logging.INFO):
                                logger.info(
                                    "Found project ID in currentTier: %s", tier_project
                                )
                            load_data["cloudaicompanionProject"] = tier_project
                        elif logger.isEnabledFor(logging.DEBUG):
                            logger.debug(
                                "currentTier has project but it's invalid: %s",
                                tier_project,
                            )

            # Check if we already have a project ID from the response
            # loadCodeAssist can return project ID as string or dict
            project_candidate = load_data.get("cloudaicompanionProject")
            if project_candidate:
                # Handle both string and dict formats (matching gemini-oauth-free)
                if isinstance(project_candidate, dict):
                    project_candidate = project_candidate.get("id")
                # Convert to string
                project_candidate = (
                    str(project_candidate) if project_candidate else None
                )

                # Only use if it's a valid project ID (not None, not "default")
                if project_candidate and project_candidate != "default":
                    if logger.isEnabledFor(logging.INFO):
                        logger.info(
                            "Discovered project ID from loadCodeAssist: %s",
                            project_candidate,
                        )

                    # Save project_id to current account storage for future use
                    if current_account:
                        updated_account = current_account.model_copy(
                            update={
                                "project_id": project_candidate,
                                "updated_at": datetime.now(timezone.utc).isoformat(),
                            }
                        )
                        await self._token_storage.save_account(updated_account)
                        # Update account selector's current account reference
                        self._account_selector.update_account(updated_account)
                        self._sync_selected_account_to_base()

                    return str(project_candidate)
                elif logger.isEnabledFor(logging.DEBUG):
                    logger.debug(
                        "loadCodeAssist returned invalid project ID: %s",
                        project_candidate,
                    )

            # Check if account is already onboarded (currentTier exists)
            # If onboarded, we should be able to get project ID from currentTier
            if current_tier_data and isinstance(current_tier_data, dict):
                tier_id = current_tier_data.get("id") or current_tier_data.get("tierId")
                if tier_id:
                    if logger.isEnabledFor(logging.INFO):
                        logger.info(
                            "Account is already onboarded with tier: %s", tier_id
                        )
                    # If already onboarded but no project ID found, this is unusual
                    # Try to extract from currentTier more carefully
                    tier_project = current_tier_data.get("cloudaicompanionProject")
                    if tier_project:
                        if isinstance(tier_project, dict):
                            tier_project = tier_project.get("id")
                        tier_project = str(tier_project) if tier_project else None
                        if tier_project and tier_project != "default":
                            if logger.isEnabledFor(logging.INFO):
                                logger.info(
                                    "Extracted project ID from currentTier: %s",
                                    tier_project,
                                )
                            if current_account:
                                updated_account = current_account.model_copy(
                                    update={
                                        "project_id": tier_project,
                                        "updated_at": datetime.now(
                                            timezone.utc
                                        ).isoformat(),
                                    }
                                )
                                await self._token_storage.save_account(updated_account)
                                self._account_selector.update_account(updated_account)
                                self._sync_selected_account_to_base()
                            return str(tier_project)

                    # If account is already onboarded but we can't find project ID,
                    # check top-level cloudaicompanionProject again (might have been missed)
                    top_level_retry = load_data.get("cloudaicompanionProject")
                    if top_level_retry:
                        if isinstance(top_level_retry, dict):
                            top_level_retry = top_level_retry.get("id")
                        top_level_retry = (
                            str(top_level_retry) if top_level_retry else None
                        )
                        if top_level_retry and top_level_retry != "default":
                            if logger.isEnabledFor(logging.INFO):
                                logger.info(
                                    "Found project ID at top level for onboarded account: %s",
                                    top_level_retry,
                                )
                            if current_account:
                                updated_account = current_account.model_copy(
                                    update={
                                        "project_id": top_level_retry,
                                        "updated_at": datetime.now(
                                            timezone.utc
                                        ).isoformat(),
                                    }
                                )
                                await self._token_storage.save_account(updated_account)
                                self._account_selector.update_account(updated_account)
                                self._sync_selected_account_to_base()
                            return str(top_level_retry)

                    # Account is onboarded but project ID not found
                    # Continue to onboarding - it might reveal the project ID
                    if logger.isEnabledFor(logging.WARNING):
                        logger.warning(
                            "Account is onboarded with tier %s but project ID not found. "
                            "Will attempt onboarding to discover project ID.",
                            tier_id,
                        )

            # Step 2: Determine which tier to use for onboarding
            # Select the best tier from allowedTiers (similar to gemini-oauth-plan)
            allowed_tiers_raw = load_data.get("allowedTiers", [])
            allowed_tiers: list[dict[str, Any]] = [
                tier for tier in allowed_tiers_raw if isinstance(tier, dict)
            ]
            current_tier = load_data.get("currentTier")
            if isinstance(current_tier, dict):
                allowed_tiers.append(current_tier)

            def _tier_id(tier: dict[str, Any]) -> str:
                raw_id = tier.get("id") or tier.get("tierId")
                return str(raw_id or "").lower()

            def _context_tokens(tier: dict[str, Any]) -> int:
                for key in (
                    "maxContextTokens",
                    "contextTokenLimit",
                    "contextWindowTokens",
                    "tokenLimit",
                    "maxContextWindow",
                ):
                    value = tier.get(key)
                    if isinstance(value, int | float):
                        return int(value)
                return 0

            def _tier_score(tier: dict[str, Any]) -> TierScore:
                tier_id = _tier_id(tier)
                # Match gemini-oauth-plan: recognize paid tiers including AI Pro tiers
                is_paid = int(
                    tier_id
                    in {
                        "paid-tier",
                        "google-one-tier",
                        "googleone-tier",
                        "googleone",
                        "duet-ai-pro",
                        "standard-tier",  # Standard tier is also a paid tier for AI Pro
                    }
                )
                context_tokens = _context_tokens(tier)
                if is_paid and context_tokens == 0:
                    context_tokens = 1_000_000
                is_default = int(bool(tier.get("isDefault")))
                return TierScore(
                    is_paid=is_paid,
                    context_tokens=context_tokens,
                    is_default=is_default,
                )

            tier_to_use: dict[str, Any] | None = None
            if allowed_tiers:
                tier_to_use = max(allowed_tiers, key=_tier_score)

            if not tier_to_use:
                tier_to_use = {"id": "free-tier"}

            selected_tier_id = (
                tier_to_use.get("id") or tier_to_use.get("tierId") or "free-tier"
            )

            # Don't override the selected tier - if tier selection picked a paid tier,
            # use it (accounts with AI Pro should use paid tiers, not free-tier)

            if logger.isEnabledFor(logging.INFO):
                logger.info(
                    "Selected Code Assist tier '%s' (context_limit=%s)",
                    selected_tier_id,
                    _context_tokens(tier_to_use),
                )

            # Step 3: Perform onboarding with the selected tier
            # For free-tier, we MUST NOT include cloudaicompanionProject field
            # For paid tiers (including standard-tier for AI Pro), we include it if available
            is_paid_tier = selected_tier_id not in ("free-tier",)
            if is_paid_tier:
                # Paid tiers (standard-tier, paid-tier, google-one-tier, etc.) require cloudaicompanionProject
                onboard_request: dict[str, Any] = {
                    "tierId": selected_tier_id,
                    "metadata": {
                        **client_metadata,
                        "duetProject": initial_project_id,
                    },
                }
                if initial_project_id:
                    onboard_request["cloudaicompanionProject"] = initial_project_id
            else:
                # Free-tier must NOT include cloudaicompanionProject
                onboard_request = {
                    "tierId": selected_tier_id,
                    "metadata": {
                        "ideType": "IDE_UNSPECIFIED",
                        "platform": "PLATFORM_UNSPECIFIED",
                        "pluginType": "GEMINI",
                    },
                }

            # Call onboardUser
            onboard_url = f"{self.gemini_api_base_url}/v1internal:onboardUser"
            max_retries = 30
            retry_count = 0
            onboarding_completed_with_default = False

            while retry_count < max_retries:
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
                    # Check if this is a free-tier eligibility error
                    if (
                        selected_tier_id == "free-tier"
                        and "FREE_TIER_USER_NOT_ELIGIBLE" in error_text
                    ):
                        # Account is not eligible for free-tier, try standard-tier or paid-tier
                        if logger.isEnabledFor(logging.INFO):
                            logger.info(
                                "Account not eligible for free-tier, trying standard-tier instead"
                            )
                        # Update request to use standard-tier
                        selected_tier_id = "standard-tier"
                        onboard_request = {
                            "tierId": selected_tier_id,
                            "metadata": {
                                **client_metadata,
                                "duetProject": initial_project_id,
                            },
                        }
                        if initial_project_id:
                            onboard_request["cloudaicompanionProject"] = (
                                initial_project_id
                            )

                        # Retry with standard-tier (will be handled in next iteration)
                        lro_response = await asyncio.to_thread(
                            auth_session.request,
                            method="POST",
                            url=onboard_url,
                            json=onboard_request,
                            headers={"Content-Type": "application/json"},
                            timeout=30.0,
                        )
                        if lro_response.status_code != 200:
                            raise BackendError(
                                f"OnboardUser failed: {lro_response.text}"
                            )
                    else:
                        raise BackendError(f"OnboardUser failed: {error_text}")

                lro_data = lro_response.json()
                if logger.isEnabledFor(logging.DEBUG):
                    logger.debug("onboardUser response: %s", lro_data)

                # Check if onboarding is complete
                if lro_data.get("done"):
                    response_data = lro_data.get("response", {})
                    cloudai_project = response_data.get("cloudaicompanionProject", {})
                    # Extract project ID - match gemini-oauth-free logic
                    # cloudaicompanionProject can be a dict with "id" field or a string
                    if isinstance(cloudai_project, dict):
                        discovered_project_id = cloudai_project.get(
                            "id", initial_project_id
                        )
                    elif isinstance(cloudai_project, str):
                        discovered_project_id = cloudai_project
                    else:
                        # Fallback: try to get project ID from response directly
                        discovered_project_id = (
                            response_data.get("cloudaicompanionProject")
                            or initial_project_id
                        )

                    # Convert to string and validate
                    discovered_project_id = (
                        str(discovered_project_id) if discovered_project_id else None
                    )

                    # Only use discovered project ID if it's valid (not None, not "default")
                    if discovered_project_id and discovered_project_id != "default":
                        if logger.isEnabledFor(logging.INFO):
                            logger.info(
                                "Discovered project ID from onboarding: %s",
                                discovered_project_id,
                            )

                        # Save project_id to current account storage for future use
                        if current_account:
                            updated_account = current_account.model_copy(
                                update={
                                    "project_id": discovered_project_id,
                                    "updated_at": datetime.now(
                                        timezone.utc
                                    ).isoformat(),
                                }
                            )
                            await self._token_storage.save_account(updated_account)
                            # Update account selector's current account reference
                            self._account_selector.update_account(updated_account)
                            self._sync_selected_account_to_base()

                        return str(discovered_project_id)
                    else:
                        # If we got "default", operation is done but project ID is invalid
                        # This may indicate the account is already onboarded with a different project
                        logger.warning(
                            "Onboarding completed but returned 'default' as project ID. "
                            "This may indicate the account is already onboarded. "
                            "Checking loadCodeAssist again for existing project..."
                        )
                        onboarding_completed_with_default = True
                        # Break out of polling loop - operation is done
                        break

                # Not done yet, wait and retry
                retry_count += 1
                await asyncio.sleep(2)

            # If onboarding completed but returned "default", try loadCodeAssist again
            # The account might already be onboarded and we need to get the real project ID
            if onboarding_completed_with_default:
                if logger.isEnabledFor(logging.INFO):
                    logger.info(
                        "Re-checking loadCodeAssist for project ID after onboarding returned 'default'"
                    )
                # Call loadCodeAssist again - it should now return the actual project ID
                load_response_retry = await asyncio.to_thread(
                    auth_session.request,
                    method="POST",
                    url=load_url,
                    json=load_request,
                    headers={"Content-Type": "application/json"},
                    timeout=30.0,
                )
                if load_response_retry.status_code == 200:
                    load_data_retry = load_response_retry.json()
                    project_retry = load_data_retry.get("cloudaicompanionProject")
                    if project_retry:
                        if isinstance(project_retry, dict):
                            project_retry = project_retry.get("id")
                        project_retry = str(project_retry) if project_retry else None
                        if project_retry and project_retry != "default":
                            if logger.isEnabledFor(logging.INFO):
                                logger.info(
                                    "Found project ID from loadCodeAssist retry: %s",
                                    project_retry,
                                )
                            if current_account:
                                updated_account = current_account.model_copy(
                                    update={
                                        "project_id": project_retry,
                                        "updated_at": datetime.now(
                                            timezone.utc
                                        ).isoformat(),
                                    }
                                )
                                await self._token_storage.save_account(updated_account)
                                self._account_selector.update_account(updated_account)
                                self._sync_selected_account_to_base()
                            return str(project_retry)

            # Timeout - onboarding didn't complete (or completed with invalid project ID)
            if retry_count >= max_retries and not onboarding_completed_with_default:
                raise BackendError(
                    f"Onboarding timeout after {max_retries} retries - operation did not complete"
                )

        except Exception as exc:
            if logger.isEnabledFor(logging.WARNING):
                logger.warning(
                    "Project discovery failed, using fallback project '%s': %s",
                    fallback_project_id,
                    exc,
                    exc_info=True,
                )
            # Fall back to default
            return str(fallback_project_id)

        # Final fallback
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
        except BackendError as e:
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
                if error_type == "quota_exceeded" or error_code in (429, 503):
                    logger.warning(
                        "Detected quota error in stream, triggering rotation"
                    )
                    self._mark_backend_unusable(reason="quota_exceeded")

            yield chunk

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
