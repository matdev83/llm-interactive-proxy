"""
Gemini OAuth Personal connector for paid plans.

This connector uses the access_token from the gemini-cli oauth_creds.json file
and is intended for users with a paid Google One subscription.
"""

import asyncio
import logging
from typing import Any

import httpx

from src.core.common.exceptions import BackendError
from src.core.config.app_config import AppConfig
from src.core.services.backend_registry import backend_registry
from src.core.services.translation_service import TranslationService

from .gemini_oauth_base import GeminiOAuthBaseConnector

logger = logging.getLogger(__name__)


class GeminiOAuthPlanConnector(GeminiOAuthBaseConnector):
    """
    Connector that uses access_token from gemini-cli oauth_creds.json file for paid plans.
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
        super().__init__(
            client,
            config,
            translation_service,
            name=name or self.backend_type,
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
