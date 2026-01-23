"""
Gemini OAuth Free Tier connector.

This connector uses the free-tier onboarding process for the Google Code Assist API,
which does not require a user-provided Google Cloud project.

This connector uses the Strategy Pattern with the following strategies:
- FileCredentialProvider: Loads credentials from ~/.gemini/oauth_creds.json
- StandardCodeAssistEndpoint: Uses cloudcode-pa.googleapis.com
- StandardRequestBodyBuilder: Standard user_prompt_id format
- FreeTierProjectDiscovery: Free tier onboarding flow
- FallbackModelDiscovery: Returns hardcoded model list (API doesn't expose fetchAvailableModels)
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
from src.connectors.gemini_base.config import DEFAULT_AVAILABLE_MODELS
from src.connectors.gemini_base.model_discovery import FallbackModelDiscovery
from src.connectors.gemini_base.project_discovery import FreeTierProjectDiscovery
from src.connectors.gemini_base.request_builders import StandardRequestBodyBuilder
from src.connectors.gemini_base.response_processors import NoOpResponsePostProcessor
from src.connectors.gemini_oauth_base import GeminiOAuthBaseConnector
from src.core.common.exceptions import BackendError
from src.core.config.app_config import AppConfig
from src.core.domain.responses import ResponseEnvelope, StreamingResponseEnvelope
from src.core.domain.session_key import SessionKey
from src.core.interfaces.configuration_interface import IAppIdentityConfig
from src.core.interfaces.model_bases import DomainModel, InternalDTO
from src.core.services.backend_registry import backend_registry
from src.core.services.translation_service import TranslationService

logger = logging.getLogger(__name__)

# Enable internal/debug-only backends automatically when running under tests.
_DEBUG_OVERRIDE_DEFAULT = os.environ.get(
    "ENABLE_INTERNAL_BACKENDS_FOR_TESTS", "1"
).lower() not in {"0", "false", "no"}


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
        # Initialize with appropriate strategies for free tier
        super().__init__(
            client,
            config,
            translation_service,
            name=name or self.backend_type,
            # Strategy injection
            credential_provider=FileCredentialProvider(),
            endpoint_config=StandardCodeAssistEndpoint(),
            request_body_builder=StandardRequestBodyBuilder(),
            project_discovery=FreeTierProjectDiscovery(),
            model_discovery=FallbackModelDiscovery(models=DEFAULT_AVAILABLE_MODELS),
            response_post_processor=NoOpResponsePostProcessor(),
        )
        self._enable_gemini_oauth_free_backend_debugging_override = (
            _DEBUG_OVERRIDE_DEFAULT
        )

    async def initialize(self, **kwargs: Any) -> None:
        """Initialize the connector and check for debugging override flag."""
        backend_config = getattr(self.config.backends, "gemini_oauth_free", None)
        extras = backend_config.extra if backend_config else {}

        current = self._enable_gemini_oauth_free_backend_debugging_override
        self._enable_gemini_oauth_free_backend_debugging_override = (
            kwargs.get("enable_gemini_oauth_free_backend_debugging_override")
            if "enable_gemini_oauth_free_backend_debugging_override" in kwargs
            else extras.get(
                "enable_gemini_oauth_free_backend_debugging_override", current
            )
        )

        await super().initialize(**kwargs)

    async def chat_completions(  # type: ignore[override]
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
        if not self._enable_gemini_oauth_free_backend_debugging_override:
            logger.warning(
                "Rejected request: Gemini OAuth Free backend requires debugging override flag. "
                "To enable, use the --enable-gemini-oauth-free-backend-debugging-override flag."
            )
            raise HTTPException(
                status_code=403,
                detail=(
                    "Forbidden: This backend is reserved for internal development and debugging purposes only. "
                    "Use --enable-gemini-oauth-free-backend-debugging-override to bypass this check."
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
        Discover or retrieve the project ID for Code Assist API (Free Tier).

        This method implements the exact project discovery logic from KiloCode,
        which calls loadCodeAssist and potentially onboardUser endpoints.
        """
        # If we already have a project ID, return it
        if hasattr(self, "_project_id") and self._project_id:
            return str(self._project_id)

        if not auth_session:
            # Fallback to a simplified discovery or raise error if strictly required
            # For now, we can assume it's required and raise if missing
            logger.warning(
                "auth_session required for free-tier project discovery but missing"
            )
            # We might return a default to avoid crash if called without session (e.g. generic probe)
            return "default"

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
            if logger.isEnabledFor(logging.INFO):
                logger.info("Discovered project ID: %s", self._project_id)
            return str(self._project_id)

        except Exception as e:
            logger.error(f"Failed to discover project ID: {e}", exc_info=True)
            # Fall back to default
            self._project_id = initial_project_id
            return str(self._project_id)


backend_registry.register_backend("gemini-oauth-free", GeminiOAuthFreeConnector)
