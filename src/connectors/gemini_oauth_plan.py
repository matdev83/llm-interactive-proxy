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

        For the paid plan, we perform the onboarding process with the paid tier.
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

        # Perform onboarding for the paid tier
        # First, we need to select the paid tier
        tier_selection_request = {
            "userTierId": "paid-tier",
        }

        tier_selection_url = f"{self.gemini_api_base_url}/v1internal/userTier:select"
        response = await asyncio.to_thread(
            auth_session.post,
            tier_selection_url,
            json=tier_selection_request,
            headers={"Content-Type": "application/json"},
        )

        if response.status_code != 200:
            try:
                error_detail = response.json()
            except Exception:
                error_detail = response.text
            raise BackendError(
                message=f"Code Assist API tier selection error for paid tier: {error_detail}",
                code="code_assist_error",
                status_code=response.status_code,
            )

        # Now, perform the onboarding with the paid tier selected
        onboard_request = {
            "userTierId": "paid-tier",
            "cloudaicompanionProject": {
                # The name is not really used by the API, but is required in the request
                "name": "cloudaicompanionProject",
            },
        }

        onboard_url = f"{self.gemini_api_base_url}/v1internal/onboard"
        response = await asyncio.to_thread(
            auth_session.post,
            onboard_url,
            json=onboard_request,
            headers={"Content-Type": "application/json"},
        )

        if response.status_code == 200:
            response_data = response.json()
            project_id = response_data.get("projectId")
            if project_id:
                self._project_id = project_id
                # Optionally save the project ID back to the credentials file
                if self._oauth_credentials:
                    self._oauth_credentials["project_id"] = project_id
                    await self._save_oauth_credentials(self._oauth_credentials)
                return str(project_id)
            else:
                raise BackendError(
                    message="Failed to get project ID from onboarding response for paid tier.",
                    code="project_id_missing",
                    status_code=response.status_code,
                )
        else:
            try:
                error_detail = response.json()
            except Exception:
                error_detail = response.text
            raise BackendError(
                message=f"Code Assist API onboarding error for paid tier: {error_detail}",
                code="code_assist_error",
                status_code=response.status_code,
            )


backend_registry.register_backend("gemini-oauth-plan", GeminiOAuthPlanConnector)
