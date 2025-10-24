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

    async def _discover_project_id(self, auth_session: Any) -> str:
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
        # This follows getOnboardTier logic from gemini-cli
        current_tier = load_data.get("currentTier")
        if current_tier:
            # User already has a tier, but no project ID
            if initial_project_id:
                self._project_id = initial_project_id
                return str(self._project_id)
            else:
                raise BackendError(
                    message="This account requires setting the GOOGLE_CLOUD_PROJECT or GOOGLE_CLOUD_PROJECT_ID env var. See https://goo.gle/gemini-cli-auth-docs#workspace-gca",
                    code="project_id_required",
                )

        # No current tier, need to onboard with paid tier
        # Find default tier from allowed tiers (following gemini-cli logic)
        tier_to_use = None
        allowed_tiers = load_data.get("allowedTiers", [])
        for tier in allowed_tiers:
            if tier.get("isDefault"):
                tier_to_use = tier
                break

        if not tier_to_use:
            # Default to standard-tier (paid) if no default found
            tier_to_use = {"id": "standard-tier"}

        # Step 3: Perform onboarding with the paid tier
        # For paid tiers, we include the cloudaicompanionProject field
        onboard_request = {
            "tierId": tier_to_use["id"],
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
