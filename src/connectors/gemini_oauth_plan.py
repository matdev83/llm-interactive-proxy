"""
Gemini OAuth Personal connector for paid plans.

This connector uses the access_token from the gemini-cli oauth_creds.json file
and is intended for users with a paid Google One subscription.

This connector uses the Strategy Pattern with the following strategies:
- FileCredentialProvider: Loads credentials from ~/.gemini/oauth_creds.json
- StandardCodeAssistEndpoint: Uses cloudcode-pa.googleapis.com
- StandardRequestBodyBuilder: Standard user_prompt_id format
- PaidTierProjectDiscovery: Paid tier onboarding flow
- ApiModelDiscovery: Uses fetchAvailableModels API
"""

import asyncio
import logging
import os
from collections.abc import Callable
from typing import Any

import httpx
from fastapi import HTTPException

from src.connectors.gemini_base.credential_providers import FileCredentialProvider
from src.connectors.gemini_base.endpoints import StandardCodeAssistEndpoint
from src.connectors.gemini_base.model_discovery import ApiModelDiscovery
from src.connectors.gemini_base.project_discovery import PaidTierProjectDiscovery
from src.connectors.gemini_base.request_builders import StandardRequestBodyBuilder
from src.connectors.gemini_base.response_processors import NoOpResponsePostProcessor
from src.core.common.exceptions import BackendError
from src.core.config.app_config import AppConfig
from src.core.domain.responses import ResponseEnvelope, StreamingResponseEnvelope
from src.core.domain.session_key import SessionKey
from src.core.interfaces.configuration_interface import IAppIdentityConfig
from src.core.interfaces.model_bases import DomainModel, InternalDTO
from src.core.services.backend_registry import backend_registry
from src.core.services.translation_service import TranslationService

from .gemini_oauth_base import GeminiOAuthBaseConnector

logger = logging.getLogger(__name__)

# Enable internal/debug-only backends automatically when running under tests.
_DEBUG_OVERRIDE_DEFAULT = os.environ.get(
    "ENABLE_INTERNAL_BACKENDS_FOR_TESTS", "1"
).lower() not in {"0", "false", "no"}


class GeminiOAuthPlanConnector(GeminiOAuthBaseConnector):
    """
    Connector that uses access_token from the gemini-cli oauth_creds.json file for paid plans.
    """

    prompt_limit_prefix_overrides: tuple[tuple[str, int], ...] = (
        ("gemini-2.5", 1_000_000),
        ("gemini-3", 1_000_000),
    )

    backend_type: str = "gemini-oauth-plan"

    def __init__(
        self,
        client: httpx.AsyncClient,
        config: AppConfig,
        translation_service: TranslationService,
        name: str | None = None,
    ) -> None:
        # Initialize with appropriate strategies for paid plan
        super().__init__(
            client,
            config,
            translation_service,
            name=name or self.backend_type,
            # Strategy injection (using defaults for standard behavior)
            credential_provider=FileCredentialProvider(),
            endpoint_config=StandardCodeAssistEndpoint(),
            request_body_builder=StandardRequestBodyBuilder(),
            project_discovery=PaidTierProjectDiscovery(),
            model_discovery=ApiModelDiscovery(),
            response_post_processor=NoOpResponsePostProcessor(),
        )
        self._enable_gemini_oauth_plan_backend_debugging_override = (
            _DEBUG_OVERRIDE_DEFAULT
        )

    async def initialize(self, **kwargs: Any) -> None:
        """Initialize the connector and check for debugging override flag."""
        backend_config = getattr(self.config.backends, "gemini_oauth_plan", None)
        extras = backend_config.extra if backend_config else {}

        current = self._enable_gemini_oauth_plan_backend_debugging_override
        self._enable_gemini_oauth_plan_backend_debugging_override = (
            kwargs.get("enable_gemini_oauth_plan_backend_debugging_override")
            if "enable_gemini_oauth_plan_backend_debugging_override" in kwargs
            else extras.get(
                "enable_gemini_oauth_plan_backend_debugging_override", current
            )
        )

        await super().initialize(**kwargs)

    async def chat_completions(
        self,
        request_data: DomainModel | InternalDTO | dict[str, Any],
        processed_messages: list[Any],
        effective_model: str,
        identity: IAppIdentityConfig | None = None,
        cancellation_token: SessionKey | None = None,
        cancellation_coordinator: (
            Any | None
        ) = None,  # ISessionCancellationCoordinator | None
        openrouter_api_base_url: str | None = None,
        openrouter_headers_provider: Callable[[Any, str], dict[str, str]] | None = None,
        key_name: str | None = None,
        api_key: str | None = None,
        project: str | None = None,
        agent: str | None = None,
        gemini_api_base_url: str | None = None,
        **kwargs: Any,
    ) -> ResponseEnvelope | StreamingResponseEnvelope:
        # Structural enforcement: check cancellation immediately if coordinator and token provided
        if cancellation_coordinator is not None and cancellation_token is not None:
            cancellation_coordinator.ensure_not_cancelled(cancellation_token)
        """Handle chat completions with debugging flag validation.

        Raises:
            HTTPException: If the debugging override flag is not enabled.
        """
        if not self._enable_gemini_oauth_plan_backend_debugging_override:
            logger.warning(
                "Rejected request: Gemini OAuth Plan backend requires debugging override flag. "
                "To enable, use the --enable-gemini-oauth-plan-backend-debugging-override flag."
            )
            raise HTTPException(
                status_code=403,
                detail=(
                    "Forbidden: This backend is reserved for internal development and debugging purposes only. "
                    "Use --enable-gemini-oauth-plan-backend-debugging-override to bypass this check."
                ),
            )

        return await super().chat_completions(
            request_data,
            processed_messages,
            effective_model,
            identity=identity,
            openrouter_api_base_url=openrouter_api_base_url,
            openrouter_headers_provider=openrouter_headers_provider,
            key_name=key_name,
            api_key=api_key,
            project=project,
            agent=agent,
            gemini_api_base_url=gemini_api_base_url,
            **kwargs,
        )

    async def _discover_project_id(self, auth_session: Any = None) -> str:
        """
        Discover or retrieve the project ID for the paid plan.

        This implementation follows the exact flow used by the official gemini-cli:
        1. Call loadCodeAssist to determine current tier and project
        2. If no current tier, call onboardUser with paid-tier parameters
        3. Poll the long-running operation until completion
        """
        # If we already have a project ID, return it
        if self._project_id:
            return str(self._project_id)

        # Check for existing project ID in the credentials file
        if self._oauth_credentials and "project_id" in self._oauth_credentials:
            project_id = self._oauth_credentials["project_id"]
            if project_id:
                self._project_id = project_id
                return str(project_id)

        if not auth_session:
            raise BackendError("auth_session required for project discovery")

        # Step 1: Call loadCodeAssist to discover current tier and project
        # This follows the exact implementation from gemini-cli setup.ts
        initial_project_id = (
            self._oauth_credentials.get("project_id")
            if self._oauth_credentials
            else None
        )

        # Prepare client metadata (matching gemini-cli exactly)
        client_metadata = {
            "ideType": "IDE_UNSPECIFIED",
            "platform": "PLATFORM_UNSPECIFIED",
            "pluginType": "GEMINI",
            "duetProject": initial_project_id,
        }

        load_request = {
            "cloudaicompanionProject": initial_project_id,
            "metadata": client_metadata,
        }

        load_url = f"{self.gemini_api_base_url}/v1internal:loadCodeAssist"
        load_response = await asyncio.to_thread(
            auth_session.post,
            load_url,
            json=load_request,
            headers={"Content-Type": "application/json"},
            timeout=30.0,
        )

        if load_response.status_code != 200:
            raise BackendError(f"LoadCodeAssist failed: {load_response.text}")

        load_data = load_response.json()

        # Check if we already have a project ID from the response
        if load_data.get("cloudaicompanionProject"):
            self._project_id = load_data["cloudaicompanionProject"]
            return str(self._project_id)

        # Step 2: Determine which tier to use for onboarding
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

        def _tier_score(tier: dict[str, Any]) -> tuple[int, int, int]:
            tier_id = _tier_id(tier)
            is_paid = int(tier_id in {"paid-tier", "google-one-tier", "googleone-tier"})
            context_tokens = _context_tokens(tier)
            if is_paid and context_tokens == 0:
                # Paid tier should always outrank tiers with unknown limits
                context_tokens = 1_000_000
            is_default = int(bool(tier.get("isDefault")))
            return (is_paid, context_tokens, is_default)

        tier_to_use: dict[str, Any] | None = None
        if allowed_tiers:
            tier_to_use = max(allowed_tiers, key=_tier_score)

        if not tier_to_use:
            tier_to_use = {"id": "paid-tier"}

        selected_tier_id = tier_to_use.get("id") or "paid-tier"
        logger.info(
            "Selected Code Assist tier '%s' (context_limit=%s)",
            selected_tier_id,
            _context_tokens(tier_to_use),
        )

        # Step 3: Perform onboarding with the paid tier
        # For paid tiers, we include the cloudaicompanionProject field
        onboard_request = {
            "tierId": selected_tier_id,
            "cloudaicompanionProject": initial_project_id,
            "metadata": {
                **client_metadata,
                "duetProject": initial_project_id,
            },
        }

        onboard_url = f"{self.gemini_api_base_url}/v1internal:onboardUser"

        # Step 4: Poll the long-running operation until completion
        # This follows the polling logic from gemini-cli setup.ts
        max_retries = 30
        retry_count = 0

        while retry_count < max_retries:
            lro_response = await asyncio.to_thread(
                auth_session.post,
                onboard_url,
                json=onboard_request,
                headers={"Content-Type": "application/json"},
                timeout=30.0,
            )

            if lro_response.status_code != 200:
                raise BackendError(f"OnboardUser failed: {lro_response.text}")

            lro_data = lro_response.json()

            if lro_data.get("done"):
                # Operation completed successfully
                response_data = lro_data.get("response", {})
                cloudai_project = response_data.get("cloudaicompanionProject", {})
                discovered_project_id = cloudai_project.get(
                    "id", initial_project_id or "default"
                )

                self._project_id = discovered_project_id
                logger.info(f"Discovered project ID: {self._project_id}")

                # Optionally save the project ID back to the credentials file
                if self._oauth_credentials:
                    self._oauth_credentials["project_id"] = discovered_project_id
                    await self._save_oauth_credentials(self._oauth_credentials)

                return str(self._project_id)

            # Operation not done yet, wait and retry
            await asyncio.sleep(2)
            retry_count += 1

        raise BackendError(
            message="Onboarding timeout - operation did not complete after maximum retries",
            code="onboarding_timeout",
        )


backend_registry.register_backend("gemini-oauth-plan", GeminiOAuthPlanConnector)
