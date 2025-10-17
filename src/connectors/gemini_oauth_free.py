"""
Gemini OAuth Free Tier connector.

This connector uses the free-tier onboarding process for the Google Code Assist API,
which does not require a user-provided Google Cloud project.
"""

import asyncio
import logging
from typing import Any

import httpx

from src.connectors.gemini_oauth_base import GeminiOAuthBaseConnector
from src.core.common.exceptions import BackendError
from src.core.config.app_config import AppConfig
from src.core.services.backend_registry import backend_registry
from src.core.services.translation_service import TranslationService

logger = logging.getLogger(__name__)


class GeminiOAuthFreeConnector(GeminiOAuthBaseConnector):
    """
    Connector for Gemini using OAuth with free-tier automatic project onboarding.
    """

    backend_type: str = "gemini-oauth-free"

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
        Discover or retrieve the project ID for Code Assist API (Free Tier).

        This method implements the exact project discovery logic from KiloCode,
        which calls loadCodeAssist and potentially onboardUser endpoints.
        """
        # If we already have a project ID, return it
        if hasattr(self, "_project_id") and self._project_id:
            return str(self._project_id)

        initial_project_id = "default"

        # Prepare client metadata (matching KiloCode exactly)
        client_metadata = {
            "ideType": "IDE_UNSPECIFIED",
            "platform": "PLATFORM_UNSPECIFIED",
            "pluginType": "GEMINI",
            "duetProject": initial_project_id,
        }

        try:
            # Call loadCodeAssist to discover the actual project ID
            load_request = {
                "cloudaicompanionProject": initial_project_id,
                "metadata": client_metadata,
            }

            url = f"{self.gemini_api_base_url}/v1internal:loadCodeAssist"
            load_response = await asyncio.to_thread(
                auth_session.request,
                method="POST",
                url=url,
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

            # For free-tier, we MUST NOT include the "cloudaicompanionProject" field AT ALL.
            onboard_request = {
                "tierId": "free-tier",
                "metadata": {
                    "ideType": "IDE_UNSPECIFIED",
                    "platform": "PLATFORM_UNSPECIFIED",
                    "pluginType": "GEMINI",
                },
            }

            # Call onboardUser
            onboard_url = f"{self.gemini_api_base_url}/v1internal:onboardUser"
            lro_response = await asyncio.to_thread(
                auth_session.request,
                method="POST",
                url=onboard_url,
                json=onboard_request,
                headers={"Content-Type": "application/json"},
                timeout=30.0,
            )

            if lro_response.status_code != 200:
                raise BackendError(f"OnboardUser failed: {lro_response.text}")

            lro_data = lro_response.json()

            # Poll until operation is complete
            max_retries = 30
            retry_count = 0
            while not lro_data.get("done") and retry_count < max_retries:
                await asyncio.sleep(2)
                lro_response = await asyncio.to_thread(
                    auth_session.request,
                    method="POST",
                    url=onboard_url,
                    json=onboard_request,
                    headers={"Content-Type": "application/json"},
                    timeout=30.0,
                )
                if lro_response.status_code == 200:
                    lro_data = lro_response.json()
                retry_count += 1

            if not lro_data.get("done"):
                raise BackendError("Onboarding timeout - operation did not complete")

            # Extract the discovered project ID
            response_data = lro_data.get("response", {})
            cloudai_project = response_data.get("cloudaicompanionProject", {})
            discovered_project_id = cloudai_project.get("id", initial_project_id)

            self._project_id = discovered_project_id
            logger.info(f"Discovered project ID: {self._project_id}")
            return str(self._project_id)

        except Exception as e:
            logger.error(f"Failed to discover project ID: {e}", exc_info=True)
            # Fall back to default
            self._project_id = initial_project_id
            return str(self._project_id)


backend_registry.register_backend("gemini-oauth-free", GeminiOAuthFreeConnector)
