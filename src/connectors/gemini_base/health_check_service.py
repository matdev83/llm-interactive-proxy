"""
Health check service for Gemini OAuth connectors.

This module provides GeminiHealthCheckService which performs first-use health checks
with existing endpoints and records health-checked state without altering connector
health semantics.
"""

import logging

import httpx

from src.connectors.gemini_base.interfaces import (
    ICredentialCoordinator,
    IEndpointConfig,
    IHealthCheckService,
)
from src.core.common.exceptions import AuthenticationError, BackendError

logger = logging.getLogger(__name__)


class GeminiHealthCheckService(IHealthCheckService):
    """Service for health check and readiness gating.

    This service performs first-use health checks with existing endpoints
    and records health-checked state without altering connector health semantics.

    Preconditions: Credentials are valid or have been refreshed.
    Postconditions: Health check state is updated.
    Invariants: A failed health check does not invalidate valid credentials.
    """

    def __init__(
        self,
        credential_coordinator: ICredentialCoordinator,
        endpoint_config: IEndpointConfig,
        http_client: httpx.AsyncClient,
        backend_name: str = "gemini-oauth",
        disable_health_checks: bool = False,
    ) -> None:
        """Initialize the health check service.

        Args:
            credential_coordinator: Coordinator for credential access and refresh.
            endpoint_config: Configuration for API endpoints.
            http_client: HTTP client for API requests.
            backend_name: Name of the backend for logging context.
            disable_health_checks: If True, skip health checks entirely.
        """
        self._credential_coordinator = credential_coordinator
        self._endpoint_config = endpoint_config
        self._http_client = http_client
        self._backend_name = backend_name
        self._disable_health_checks = disable_health_checks
        self._health_checked: bool = disable_health_checks

    async def ensure_healthy(self) -> None:
        """Perform first use health check if needed.

        This method performs a health check on first use and caches the result.
        Subsequent calls are no-ops if already checked.

        Raises:
            BackendError: If health check fails critically (e.g., auth failure).
        """
        if self._health_checked:
            return

        if self._disable_health_checks:
            logger.debug(f"Health checks disabled for {self._backend_name}")
            self._health_checked = True
            return

        logger.info(
            f"Performing first-use health check for {self._backend_name} backend"
        )

        # Refresh token if needed before health check
        refreshed = await self._credential_coordinator.refresh_if_needed()
        if not refreshed:
            raise BackendError(
                message=f"Failed to refresh OAuth token during health check for {self._backend_name}",
                backend_name=self._backend_name,
            )

        # Perform health check (non-blocking - we only fail on token issues)
        healthy = await self._perform_health_check()
        if not healthy:
            logger.warning(
                f"Health check did not pass for {self._backend_name}, but continuing with valid OAuth credentials. "
                "The backend will be tested when the first real request is made."
            )
        # Mark as checked regardless - we have valid credentials
        self._health_checked = True
        logger.info(
            f"Backend health check completed for {self._backend_name} - ready for use"
        )

    async def _perform_health_check(self) -> bool:
        """Perform a health check by testing API connectivity.

        This method tests actual API connectivity by making a simple request to verify
        the OAuth token works and the service is accessible.

        Uses the fetchAvailableModels endpoint which is supported by all Code Assist API
        variants (standard and sandbox).

        Returns:
            bool: True if health check passes, False otherwise
        """
        try:
            # Ensure credentials are available
            credentials = self._credential_coordinator.credentials
            if not credentials or not credentials.access_token:
                logger.warning(
                    f"Health check failed for {self._backend_name} - no access token available"
                )
                return False

            # Get base URL and headers from endpoint config
            base_url = self._endpoint_config.get_base_url().rstrip("/")
            headers = self._endpoint_config.get_api_headers(credentials.to_dict())

            # Use fetchAvailableModels endpoint for health check
            # This endpoint is supported by all Code Assist API variants
            fetch_models_url = f"{base_url}/v1internal:fetchAvailableModels"
            try:
                response = await self._http_client.get(
                    fetch_models_url, headers=headers, timeout=10.0
                )
            except httpx.TimeoutException as te:
                logger.error(
                    f"Health check timeout calling {fetch_models_url} for {self._backend_name}: {te}",
                    exc_info=True,
                )
                return False
            except httpx.RequestError as rexc:
                logger.error(
                    f"Health check connection error calling {fetch_models_url} for {self._backend_name}: {rexc}",
                    exc_info=True,
                )
                return False

            if response.status_code == 200:
                logger.info(
                    f"Health check passed for {self._backend_name} - API connectivity verified via fetchAvailableModels"
                )
                return True

            # Fallback: use loadCodeAssist which is reliable on Code Assist API
            load_url = f"{base_url}/v1internal:loadCodeAssist"
            payload = {
                "metadata": {
                    "ideType": "IDE_UNSPECIFIED",
                    "platform": "PLATFORM_UNSPECIFIED",
                    "pluginType": "GEMINI",
                }
            }
            try:
                response = await self._http_client.post(
                    load_url, headers=headers, json=payload, timeout=10.0
                )
            except httpx.TimeoutException as te:
                logger.error(
                    f"Health check timeout calling {load_url} for {self._backend_name}: {te}",
                    exc_info=True,
                )
                return False
            except httpx.RequestError as rexc:
                logger.error(
                    f"Health check connection error calling {load_url} for {self._backend_name}: {rexc}",
                    exc_info=True,
                )
                return False

            if response.status_code == 200:
                logger.info(
                    f"Health check passed for {self._backend_name} via loadCodeAssist"
                )
                return True

            logger.warning(
                f"Health check failed for {self._backend_name} - API returned status {response.status_code}"
            )
            return False

        except AuthenticationError as e:
            logger.error(
                f"Health check failed for {self._backend_name} - authentication error: {e}",
                exc_info=True,
            )
            return False
        except BackendError as e:
            logger.error(
                f"Health check failed for {self._backend_name} - backend error: {e}",
                exc_info=True,
            )
            return False
        except Exception as e:
            logger.error(
                f"Health check failed for {self._backend_name} - unexpected error: {e}",
                exc_info=True,
            )
            return False
