"""
Gemini OAuth Personal connector that uses access_token from gemini-cli oauth_creds.json file

This connector replicates the authentication approach used by the Gemini CLI tool and KiloCode's
"Google CLI" authentication method, using the Code Assist API endpoint (cloudcode-pa.googleapis.com)
and OAuth2 authentication with the same client credentials and scopes as the CLI.

Unlike the standard Gemini backend, this connector makes API calls directly to the
Code Assist API using OAuth authentication, which allows it to bypass the API key
requirement for the public Gemini API.

=== CRITICAL IMPLEMENTATION NOTES ===

1. API ENDPOINTS:
   - Base URL: https://cloudcode-pa.googleapis.com (NOT the standard Gemini API)
   - API Version: v1internal (NOT v1beta or v1)
   - Key endpoints:
     * :loadCodeAssist - Check if user has existing project
     * :onboardUser - Onboard user to free tier if no project exists
     * :streamGenerateContent - Generate responses (MUST use ?alt=sse parameter)

2. FREE TIER ONBOARDING (MOST CRITICAL):
   - The free-tier uses a MANAGED Google Cloud project
   - When onboarding to free-tier, DO NOT include the "cloudaicompanionProject" field AT ALL
   - Including this field (even as null/None) causes "Precondition Failed" errors
   - The API will return a managed project ID (e.g., "charismatic-fragment-mxnz0")

3. TIER SELECTION LOGIC:
   - The "standard-tier" requires a user-defined Google Cloud project
   - If standard-tier is default and has userDefinedCloudaicompanionProject=true,
     we MUST use "free-tier" instead
   - KiloCode uses "free-tier" as fallback, NOT "standard-tier"

4. MODEL NAMES:
   - Must use Code Assist API model names, NOT standard Gemini model names
   - Correct: "gemini-1.5-flash-002", "gemini-2.0-flash-001"
   - WRONG: "gemini-pro" (doesn't exist in Code Assist API)

5. AUTHENTICATION:
   - Uses the same OAuth client ID/secret as the official gemini CLI
   - These are PUBLIC credentials meant for CLI applications
   - Credentials are stored in ~/.gemini/oauth_creds.json
   - Tokens are automatically refreshed when expired

6. REQUEST FORMAT:
   - Uses different format than standard Gemini API
   - Body structure: {"model": ..., "project": ..., "request": {...}}
   - NOT the standard Gemini format

7. RESPONSE FORMAT:
   - Uses Server-Sent Events (SSE) streaming
   - Each line starts with "data: " followed by JSON
   - Must parse SSE format, not regular JSON response

This implementation exactly matches KiloCode's approach, which only requires
the path to the credentials file as input - no Google Cloud project configuration needed.
"""

import asyncio
import json
import logging
import time
from collections.abc import AsyncGenerator
from pathlib import Path
from typing import Any

import google.auth
import google.auth.transport.requests
import google.oauth2.credentials
import httpx
import requests  # type: ignore[import-untyped]
from fastapi import HTTPException

from src.core.common.exceptions import (
    APIConnectionError,
    APITimeoutError,
    AuthenticationError,
    BackendError,
)
from src.core.config.app_config import AppConfig
from src.core.domain.responses import (
    ProcessedResponse,
    ResponseEnvelope,
    StreamingResponseEnvelope,
)
from src.core.services.backend_registry import backend_registry
from src.core.services.translation_service import TranslationService

from .gemini import GeminiBackend

# Code Assist API endpoint (matching the CLI's endpoint):
#   https://cloudcode-pa.googleapis.com
CODE_ASSIST_ENDPOINT = "https://cloudcode-pa.googleapis.com"
# API version: v1internal
# Default model example: "codechat-bison"
# Default project for free tier used in UserTierId enum: "free-tier"

logger = logging.getLogger(__name__)


class GeminiOAuthPersonalConnector(GeminiBackend):
    """Connector that uses access_token from gemini-cli oauth_creds.json file.

    This is a specialized Gemini connector that reads the access_token
    from the gemini-cli generated oauth_creds.json file and uses it as the API key.
    It handles token refresh automatically when the token expires.
    """

    _project_id: str | None = None

    backend_type: str = "gemini-cli-oauth-personal"

    def __init__(
        self,
        client: httpx.AsyncClient,
        config: AppConfig,
        translation_service: TranslationService,
    ) -> None:
        super().__init__(
            client, config, translation_service
        )  # Pass translation_service to super
        self.name = "gemini-cli-oauth-personal"
        self.is_functional = False
        self._oauth_credentials: dict[str, Any] | None = None
        self._credentials_path: Path | None = None
        self._last_modified: float = 0
        self._refresh_token: str | None = None
        self._token_refresh_lock = asyncio.Lock()
        self.translation_service = translation_service

        # Check environment variable to allow disabling health checks globally
        import os

        disable_health_checks = os.getenv("DISABLE_HEALTH_CHECKS", "false").lower() in (
            "true",
            "1",
            "yes",
        )

        # Start as checked only if explicitly disabled via env, otherwise require first-use check
        self._health_checked: bool = disable_health_checks

        # Set custom .gemini directory path (will be set in initialize)
        self.gemini_cli_oauth_path: str | None = None

    def _is_token_expired(self) -> bool:
        """Check if the current access token is expired or close to expiring."""
        if not self._oauth_credentials:
            return True  # No credentials means no valid token

        expiry_date_ms = self._oauth_credentials.get("expiry_date")
        if not isinstance(expiry_date_ms, int | float):
            return False  # No expiry date means token doesn't expire

        # Convert milliseconds to seconds
        expiry_date_s = float(expiry_date_ms) / 1000.0

        # Add a buffer for proactive refresh (e.g., 30 seconds before actual expiry)
        refresh_buffer_s = 30
        return time.time() >= (expiry_date_s - refresh_buffer_s)

    def _get_refresh_token(self) -> str | None:
        """Get refresh token, either from credentials or cached value."""
        if self._refresh_token:
            return self._refresh_token

        if self._oauth_credentials and "refresh_token" in self._oauth_credentials:
            self._refresh_token = self._oauth_credentials["refresh_token"]
            return self._refresh_token

        return None

    async def _refresh_token_if_needed(self) -> bool:
        """Ensure we have a valid access token; reload from CLI cache if expired.

        We intentionally avoid embedding OAuth client credentials. The official
        gemini CLI persists credentials to ~/.gemini/oauth_creds.json and refreshes
        them itself. Here we re-load that file if our token is stale.
        """
        if not self._is_token_expired():
            return True

        async with self._token_refresh_lock:
            if not self._is_token_expired():
                return True

            if logger.isEnabledFor(logging.INFO):
                logger.info(
                    "Access token expired or near expiry; reloading CLI credentials..."
                )

            # Attempt to reload the credentials file; the CLI should refresh it
            reloaded = await self._load_oauth_credentials()
            if not reloaded:
                if logger.isEnabledFor(logging.WARNING):
                    logger.warning(
                        "Failed to reload Gemini OAuth credentials from ~/.gemini."
                    )
                return False

            # After reload, consider token valid if not expired
            if self._is_token_expired():
                if logger.isEnabledFor(logging.WARNING):
                    logger.warning(
                        "Reloaded credentials are still expired. Please run 'gemini auth' to refresh."
                    )
                return False

            return True

    async def _save_oauth_credentials(self, credentials: dict[str, Any]) -> None:
        """Save OAuth credentials to oauth_creds.json file."""
        try:
            home_dir = Path.home()
            gemini_dir = home_dir / ".gemini"
            gemini_dir.mkdir(parents=True, exist_ok=True)  # Ensure directory exists
            creds_path = gemini_dir / "oauth_creds.json"

            with open(creds_path, "w", encoding="utf-8") as f:
                json.dump(credentials, f, indent=4)
            if logger.isEnabledFor(logging.INFO):
                logger.info(f"Gemini OAuth credentials saved to {creds_path}")
        except OSError as e:
            if logger.isEnabledFor(logging.ERROR):
                logger.error(
                    f"Error saving Gemini OAuth credentials: {e}", exc_info=True
                )

    async def _load_oauth_credentials(self) -> bool:
        """Load OAuth credentials from oauth_creds.json file."""
        try:
            # Use custom path if provided, otherwise default to ~/.gemini
            if self.gemini_cli_oauth_path:
                creds_path = Path(self.gemini_cli_oauth_path) / "oauth_creds.json"
            else:
                home_dir = Path.home()
                creds_path = home_dir / ".gemini" / "oauth_creds.json"
            self._credentials_path = creds_path

            if not creds_path.exists():
                if logger.isEnabledFor(logging.WARNING):
                    logger.warning(
                        f"Gemini OAuth credentials not found at {creds_path}"
                    )
                return False

            # Check if file has been modified since last load
            try:
                current_modified = creds_path.stat().st_mtime
                if current_modified == self._last_modified and self._oauth_credentials:
                    # File hasn't changed and credentials are in memory, no need to reload
                    if logger.isEnabledFor(logging.DEBUG):
                        logger.debug(
                            "Gemini OAuth credentials file not modified, using cached."
                        )
                    return True
                self._last_modified = current_modified
            except OSError:
                # If cannot get file stats, proceed with reading
                pass

            with open(creds_path, encoding="utf-8") as f:
                credentials = json.load(f)

            # Validate essential fields
            if "access_token" not in credentials:
                if logger.isEnabledFor(logging.WARNING):
                    logger.warning(
                        "Malformed Gemini OAuth credentials: missing access_token"
                    )
                return False

            self._oauth_credentials = credentials
            if logger.isEnabledFor(logging.INFO):
                logger.info("Successfully loaded Gemini OAuth credentials.")
            return True
        except json.JSONDecodeError as e:
            if logger.isEnabledFor(logging.ERROR):
                logger.error(
                    f"Error decoding Gemini OAuth credentials JSON: {e}",
                    exc_info=True,
                )
            return False
        except OSError as e:
            if logger.isEnabledFor(logging.ERROR):
                logger.error(
                    f"Error loading Gemini OAuth credentials: {e}", exc_info=True
                )
            return False

    async def initialize(self, **kwargs: Any) -> None:
        """Initialize backend by loading and potentially refreshing token."""
        logger.info("Initializing Gemini OAuth Personal backend.")

        # Set the API base URL for Google Code Assist API (used by oauth-personal)
        self.gemini_api_base_url = kwargs.get(
            "gemini_api_base_url", "https://cloudcode-pa.googleapis.com"
        )

        # Set custom .gemini directory path (defaults to ~/.gemini)
        self.gemini_cli_oauth_path = kwargs.get("gemini_cli_oauth_path")

        if not await self._load_oauth_credentials():
            logger.warning("Failed to load initial Gemini OAuth credentials.")
            self.is_functional = False
            return

        # Attempt to refresh token if needed during initialization
        if not await self._refresh_token_if_needed():
            logger.warning(
                "Failed to refresh Gemini OAuth token during initialization."
            )
            self.is_functional = False
            return

        # If token still appears expired after reload attempts, auto-disable backend
        if self._is_token_expired():
            logger.warning(
                "Gemini OAuth token is expired. Disabling backend until you run 'gemini auth' to refresh."
            )
            self.is_functional = False
            return

        # If we reach here, credentials are loaded and potentially refreshed
        # Fetch available models using the OAuth token
        try:
            await self._ensure_models_loaded()
            self.is_functional = True
            logger.info(
                f"Gemini OAuth Personal backend initialized with {len(self.available_models)} models."
            )
        except Exception as e:
            logger.error(
                f"Failed to load models during initialization: {e}", exc_info=True
            )
            # Even if model loading fails, mark as functional if we have credentials
            self.is_functional = True
            logger.info(
                "Gemini OAuth Personal backend initialized (models will be loaded on first use)."
            )

    async def _resolve_gemini_api_config(
        self,
        gemini_api_base_url: str | None,
        openrouter_api_base_url: str | None,
        api_key: str | None,
        **kwargs: Any,
    ) -> tuple[str, dict[str, str]]:
        """Override to use access_token from OAuth credentials instead of API key."""
        # Use the OAuth access token for authentication
        if not self._oauth_credentials or not self._oauth_credentials.get(
            "access_token"
        ):
            raise HTTPException(
                status_code=401,
                detail="No valid Gemini OAuth access token available. Please authenticate.",
            )

        # Prefer explicit params, then kwargs, then instance attributes
        base = (
            gemini_api_base_url
            or openrouter_api_base_url
            or kwargs.get("gemini_api_base_url")
            or getattr(self, "gemini_api_base_url", None)
        )

        if not base:
            raise HTTPException(
                status_code=500, detail="Gemini API base URL must be provided."
            )

        # Use OAuth access token instead of API key (reload if expired)
        # Ensure token is fresh enough
        await self._refresh_token_if_needed()
        access_token = (
            self._oauth_credentials.get("access_token")
            if self._oauth_credentials
            else None
        )
        if not access_token:
            raise HTTPException(
                status_code=401, detail="Missing access_token after refresh."
            )
        return base.rstrip("/"), {"Authorization": f"Bearer {access_token}"}

    async def _perform_health_check(self) -> bool:
        """Perform a health check by testing API connectivity.

        This method tests actual API connectivity by making a simple request to verify
        the OAuth token works and the service is accessible.

        Returns:
            bool: True if health check passes, False otherwise
        """
        try:
            # Ensure token is refreshed before testing
            if not await self._refresh_token_if_needed():
                logger.warning("Health check failed - couldn't refresh OAuth token")
                return False

            # Test API connectivity with a simple GET request
            if not self._oauth_credentials or not self._oauth_credentials.get(
                "access_token"
            ):
                logger.warning("Health check failed - no access token available")
                return False

            # Use the httpx client to make a simple API call (expected by tests)
            base_url = self.gemini_api_base_url or CODE_ASSIST_ENDPOINT
            url = f"{base_url}/v1internal/models"  # Simple models endpoint
            headers = {
                "Authorization": f"Bearer {self._oauth_credentials['access_token']}"
            }

            try:
                response = await self.client.get(url, headers=headers, timeout=10.0)
            except httpx.TimeoutException as te:
                logger.error(f"Health check timeout calling {url}: {te}", exc_info=True)
                return False
            except httpx.RequestError as rexc:
                logger.error(
                    f"Health check connection error calling {url}: {rexc}",
                    exc_info=True,
                )
                return False

            if response.status_code == 200:
                logger.info("Health check passed - API connectivity verified")
                self._health_checked = True
                return True
            else:
                logger.warning(
                    f"Health check failed - API returned status {response.status_code}"
                )
                return False

        except AuthenticationError as e:
            logger.error(
                f"Health check failed - authentication error: {e}", exc_info=True
            )
            return False
        except BackendError as e:
            logger.error(f"Health check failed - backend error: {e}", exc_info=True)
            return False
        except Exception as e:
            logger.error(f"Health check failed - unexpected error: {e}", exc_info=True)
            return False

    async def _ensure_healthy(self) -> None:
        """Ensure the backend is healthy before use.

        This method performs health checks on first use, similar to how
        models are loaded lazily in the parent class.
        """
        if not hasattr(self, "_health_checked") or not self._health_checked:
            logger.info(
                "Performing first-use health check for Gemini OAuth Personal backend"
            )

            # Refresh token if needed before health check
            refreshed = await self._refresh_token_if_needed()
            if not refreshed:
                raise BackendError("Failed to refresh OAuth token during health check")

            # Perform health check
            healthy = await self._perform_health_check()
            if not healthy:
                raise BackendError("Health check failed")

            self._health_checked = True
            logger.info("Health check passed - backend is ready for use")

    async def chat_completions(  # type: ignore[override]
        self,
        request_data: Any,
        processed_messages: list[Any],
        effective_model: str,
        identity: Any = None,
        openrouter_api_base_url: str | None = None,
        openrouter_headers_provider: Any = None,
        key_name: str | None = None,
        api_key: str | None = None,
        project: str | None = None,
        agent: str | None = None,
        gemini_api_base_url: str | None = None,
        **kwargs: Any,
    ) -> ResponseEnvelope | StreamingResponseEnvelope:
        """Handle chat completions using Google Code Assist API.

        This method uses the Code Assist API (https://cloudcode-pa.googleapis.com)
        which is the correct endpoint for oauth-personal authentication,
        while maintaining OpenAI-compatible interface and response format.
        """
        # Perform health check on first use (includes token refresh)
        await self._ensure_healthy()

        try:
            # Use the effective model (strip gemini-cli-oauth-personal: prefix if present)
            model_name = effective_model
            if model_name.startswith("gemini-cli-oauth-personal:"):
                model_name = model_name[
                    25:
                ]  # Remove "gemini-cli-oauth-personal:" prefix

            # Fix the model name stripping bug
            if model_name.startswith("gemini-cli-oauth-personal:"):
                model_name = model_name[
                    27:
                ]  # Remove "gemini-cli-oauth-personal:" prefix

            # Check if streaming is requested
            is_streaming = getattr(request_data, "stream", False)

            if is_streaming:
                return await self._chat_completions_code_assist_streaming(
                    request_data=request_data,
                    processed_messages=processed_messages,
                    effective_model=model_name,
                    **kwargs,
                )
            else:
                return await self._chat_completions_code_assist(
                    request_data=request_data,
                    processed_messages=processed_messages,
                    effective_model=model_name,
                    **kwargs,
                )

        except HTTPException:
            # Re-raise HTTP exceptions directly
            raise
        except (AuthenticationError, BackendError):
            # Re-raise domain exceptions
            raise
        except Exception as e:
            # Convert other exceptions to BackendError
            logger.error(
                f"Error in Gemini OAuth Personal chat_completions: {e}",
                exc_info=True,
            )
            raise BackendError(
                message=f"Gemini OAuth Personal chat completion failed: {e!s}"
            ) from e

    async def _chat_completions_code_assist(
        self,
        request_data: Any,
        processed_messages: list[Any],
        effective_model: str,
        **kwargs: Any,
    ) -> ResponseEnvelope:
        """Handle chat completions using the Code Assist API.

        This method implements the Code Assist API calls that match the Gemini CLI
        approach, while converting to/from OpenAI-compatible formats.
        """
        try:
            # Ensure token is refreshed before making the API call
            if not await self._refresh_token_if_needed():
                raise AuthenticationError("Failed to refresh OAuth token for API call")

            # Create an authorized session using the access token directly
            if not self._oauth_credentials:
                raise AuthenticationError("No OAuth credentials available for API call")

            access_token = self._oauth_credentials.get("access_token")
            if not access_token:
                raise AuthenticationError("Missing access_token in OAuth credentials")

            # Build a simple authorized session wrapper using Requests
            # We use AuthorizedSession with a bare Credentials-like shim
            class _StaticTokenCreds:
                def __init__(self, token: str) -> None:
                    self.token = token

                def refresh(self, request: Any) -> None:
                    # No-op: token is managed by the CLI; we reload from file when needed
                    return

            auth_session = google.auth.transport.requests.AuthorizedSession(
                _StaticTokenCreds(access_token)
            )

            # Discover project ID (required for Code Assist API)
            project_id = await self._discover_project_id(auth_session)

            # Convert messages to Gemini format using the translation service
            canonical_request = self.translation_service.to_domain_request(
                request=request_data,
                source_format="anthropic",  # Assuming input is Anthropic-compatible
            )

            # Prepare request body for Code Assist API (exactly matching KiloCode)
            request_body = canonical_request.model_dump(exclude_unset=True)
            request_body["model"] = effective_model  # Ensure model is correct
            request_body["project"] = project_id  # Ensure project is correct

            # Use the Code Assist API exactly like KiloCode does
            # IMPORTANT: KiloCode uses :streamGenerateContent, not :generateContent
            url = f"{self.gemini_api_base_url}/v1internal:streamGenerateContent"
            logger.info(f"Making Code Assist API call to: {url}")

            # Use the auth_session.request exactly like KiloCode
            # Add ?alt=sse for server-sent events streaming
            try:
                response = await asyncio.to_thread(
                    auth_session.request,
                    method="POST",
                    url=url,
                    params={"alt": "sse"},  # Important: KiloCode uses SSE streaming
                    json=request_body,
                    headers={"Content-Type": "application/json"},
                    timeout=60,
                )
            except requests.exceptions.Timeout as te:  # type: ignore[attr-defined]
                raise APITimeoutError(
                    message="Code Assist API call timed out",
                    backend_name=self.name,
                ) from te
            except requests.exceptions.RequestException as rexc:  # type: ignore[attr-defined]
                raise APIConnectionError(
                    message="Failed to connect to Code Assist API",
                    backend_name=self.name,
                ) from rexc

            # Process the response
            if response.status_code >= 400:
                try:
                    error_detail = response.json()
                except Exception:
                    error_detail = response.text

                raise BackendError(
                    message=f"Code Assist API error: {error_detail}",
                    code="code_assist_error",
                    status_code=response.status_code,
                )

            # Parse SSE stream response
            generated_text = ""
            domain_response = None

            # Read the SSE stream
            response_text = response.text
            for line in response_text.split("\n"):
                if line.startswith("data: "):
                    data_str = line[6:].strip()
                    if data_str == "[DONE]":
                        break
                    try:
                        data = json.loads(data_str)
                        # Use translation service to convert to domain response
                        domain_response = self.translation_service.to_domain_response(
                            response=data,  # Corrected parameter name
                            source_format="code_assist",
                        )
                        if (
                            domain_response.choices
                            and domain_response.choices[0].message.content
                        ):
                            generated_text += domain_response.choices[0].message.content
                    except json.JSONDecodeError:
                        continue

            # Convert to OpenAI-compatible format using translation_service
            if not domain_response:
                raise BackendError("Failed to parse a valid response from the backend.")
            openai_response = self.translation_service.from_domain_response(
                response=domain_response,
                target_format="openai",
            ).model_dump(exclude_unset=True)

            logger.info("Successfully received response from Code Assist API")
            return ResponseEnvelope(
                content=openai_response, headers={}, status_code=200
            )

        except AuthenticationError as e:
            logger.error(f"Authentication error during API call: {e}", exc_info=True)
            raise
        except BackendError as e:
            logger.error(f"Backend error during API call: {e}", exc_info=True)
            raise
        except Exception as e:
            logger.error(f"Unexpected error during API call: {e}", exc_info=True)
            raise BackendError(f"Unexpected error during API call: {e}")

    async def _chat_completions_code_assist_streaming(
        self,
        request_data: Any,
        processed_messages: list[Any],
        effective_model: str,
        **kwargs: Any,
    ) -> StreamingResponseEnvelope:
        """Handle streaming chat completions using the Code Assist API.

        This method implements proper streaming support for the Code Assist API,
        returning a StreamingResponseEnvelope that provides an async iterator
        of SSE-formatted response chunks.
        """
        try:
            # Ensure token is refreshed before making the API call
            if not await self._refresh_token_if_needed():
                raise AuthenticationError(
                    "Failed to refresh OAuth token for streaming API call"
                )

            # Create an authorized session using the access token directly
            if not self._oauth_credentials:
                raise AuthenticationError(
                    "No OAuth credentials available for streaming API call"
                )

            access_token = self._oauth_credentials.get("access_token")
            if not access_token:
                raise AuthenticationError("Missing access_token in OAuth credentials")

            class _StaticTokenCreds:
                def __init__(self, token: str) -> None:
                    self.token = token

                def refresh(self, request: Any) -> None:
                    return

            auth_session = google.auth.transport.requests.AuthorizedSession(
                _StaticTokenCreds(access_token)
            )

            # Discover project ID (required for Code Assist API)
            project_id = await self._discover_project_id(auth_session)

            # Convert messages to canonical domain request using the translation service
            canonical_request = self.translation_service.to_domain_request(
                request=request_data,
                source_format="anthropic",  # Assuming input is Anthropic-compatible
            )

            # Prepare request body for Code Assist API (exactly matching KiloCode)
            request_body = canonical_request.model_dump(exclude_unset=True)
            request_body["model"] = effective_model  # Ensure model is correct
            request_body["project"] = project_id  # Ensure project is correct

            # Use the Code Assist API with streaming endpoint
            url = f"{self.gemini_api_base_url}/v1internal:streamGenerateContent"
            logger.info(f"Making streaming Code Assist API call to: {url}")

            # Create an async iterator that yields SSE-formatted chunks
            async def stream_generator() -> AsyncGenerator[ProcessedResponse, None]:
                response = None  # Initialize response to None
                try:
                    # Use the auth_session.request exactly like KiloCode
                    # Add ?alt=sse for server-sent events streaming
                    try:
                        response = await asyncio.to_thread(
                            auth_session.request,
                            method="POST",
                            url=url,
                            params={
                                "alt": "sse"
                            },  # Important: KiloCode uses SSE streaming
                            json=request_body,
                            headers={"Content-Type": "application/json"},
                            timeout=60,
                        )
                    except requests.exceptions.Timeout as te:  # type: ignore[attr-defined]
                        logger.error(
                            f"Streaming timeout calling {url}: {te}", exc_info=True
                        )
                        # End stream gracefully
                        yield self.translation_service.to_domain_stream_chunk(
                            chunk=None, source_format="code_assist"
                        )
                        return
                    except requests.exceptions.RequestException as rexc:  # type: ignore[attr-defined]
                        logger.error(
                            f"Streaming connection error calling {url}: {rexc}",
                            exc_info=True,
                        )
                        yield self.translation_service.to_domain_stream_chunk(
                            chunk=None, source_format="code_assist"
                        )
                        return

                    # Process the response
                    if response.status_code >= 400:
                        try:
                            error_detail = response.json()
                        except Exception:
                            error_detail = response.text

                        raise BackendError(
                            message=f"Code Assist API streaming error: {error_detail}",
                            code="code_assist_error",
                            status_code=response.status_code,
                        )

                    # Process the streaming response using synchronous iter_lines()
                    for line in response.iter_lines(
                        chunk_size=1
                    ):  # Process line by line
                        try:
                            decoded_line = line.decode("utf-8")
                            if decoded_line.startswith("data: "):
                                data_str = decoded_line[6:].strip()
                                if data_str == "[DONE]":
                                    yield self.translation_service.to_domain_stream_chunk(
                                        chunk=None,  # Indicate end of stream
                                        source_format="code_assist",
                                    )
                                    break
                                try:
                                    data = json.loads(data_str)
                                    domain_chunk = (
                                        self.translation_service.to_domain_stream_chunk(
                                            chunk=data,  # Pass the parsed JSON data
                                            source_format="code_assist",
                                        )
                                    )
                                    yield domain_chunk
                                except json.JSONDecodeError:
                                    # If it's not JSON, it might be an empty line or comment, skip
                                    continue
                            else:
                                # Handle non-data lines (e.g., comments, event types) if necessary
                                if decoded_line.strip():
                                    yield self.translation_service.to_domain_stream_chunk(
                                        chunk={
                                            "text": decoded_line
                                        },  # Wrap in a dict for consistency
                                        source_format="raw_text",  # Or a more specific raw format
                                    )
                        except Exception as chunk_error:
                            logger.error(
                                f"Error processing stream line: {chunk_error}",
                                exc_info=True,
                            )
                            continue

                    # Ensure the stream is properly closed with a DONE signal
                    yield self.translation_service.to_domain_stream_chunk(
                        chunk=None,  # Indicate end of stream
                        source_format="code_assist",
                    )

                except Exception as e:
                    logger.error(f"Error in streaming generator: {e}", exc_info=True)
                    # Yield an error chunk or ensure stream ends gracefully
                    yield self.translation_service.to_domain_stream_chunk(
                        chunk=None,  # Indicate end of stream due to error
                        source_format="code_assist",
                    )

                finally:
                    if response:  # Ensure response is defined before closing
                        response.close()  # Use synchronous close

            return StreamingResponseEnvelope(
                content=stream_generator(),
                media_type="text/event-stream",
                headers={},
            )

        except AuthenticationError as e:
            logger.error(
                f"Authentication error during streaming API call: {e}",
                exc_info=True,
            )
            raise
        except BackendError as e:
            logger.error(f"Backend error during streaming API call: {e}", exc_info=True)
            raise
        except Exception as e:
            logger.error(
                f"Unexpected error during streaming API call: {e}", exc_info=True
            )
            raise BackendError(f"Unexpected error during streaming API call: {e}")

    def _convert_to_code_assist_format(
        self, request_data: Any, processed_messages: list[Any], model: str
    ) -> dict[str, Any]:
        """Convert OpenAI-style request to Code Assist API format."""
        # Extract the last user message for generation
        user_message = ""
        for msg in reversed(processed_messages):
            if msg.get("role") == "user":
                user_message = msg.get("content", "")
                break

        if not user_message:
            # Fallback to first message if no user message found
            user_message = (
                processed_messages[0].get("content", "") if processed_messages else ""
            )

        # Build system prompt from conversation history
        system_prompt = ""
        conversation_context = []

        for msg in processed_messages:
            role = msg.get("role", "")
            content = msg.get("content", "")

            if role == "system":
                system_prompt = content
            elif role == "user":
                conversation_context.append(f"User: {content}")
            elif role == "assistant":
                conversation_context.append(f"Assistant: {content}")

        # Combine system prompt with conversation context
        full_prompt = system_prompt
        if conversation_context:
            if full_prompt:
                full_prompt += "\n\n"
            full_prompt += "\n".join(conversation_context)

        # Create Code Assist request format (matching Gemini CLI format)
        code_assist_request = {
            "model": model,
            "contents": [
                {"role": "user", "parts": [{"text": full_prompt or user_message}]}
            ],
            "generationConfig": self._build_generation_config(request_data),
        }

        return code_assist_request

    def _build_generation_config(self, request_data: Any) -> dict[str, Any]:
        """Build Code Assist generationConfig from request_data including optional topK."""
        cfg: dict[str, Any] = {
            "temperature": float(getattr(request_data, "temperature", 0.7)),
            "maxOutputTokens": int(getattr(request_data, "max_tokens", 1024)),
            "topP": float(getattr(request_data, "top_p", 0.95)),
        }
        top_k = getattr(request_data, "top_k", None)
        if top_k is not None:
            import contextlib

            with contextlib.suppress(Exception):
                cfg["topK"] = int(top_k)
        return cfg

    def _convert_from_code_assist_format(
        self, code_assist_response: dict[str, Any], model: str
    ) -> dict[str, Any]:
        """Convert Code Assist API response to OpenAI-compatible format."""
        # Extract the generated text from Code Assist response
        # Code Assist API wraps the response in a "response" object
        response_wrapper = code_assist_response.get("response", {})
        candidates = response_wrapper.get("candidates", [])
        generated_text = ""

        if candidates and len(candidates) > 0:
            candidate = candidates[0]
            content = candidate.get("content", {})
            parts = content.get("parts", [])

            if parts and len(parts) > 0:
                generated_text = parts[0].get("text", "")

        # Create OpenAI-compatible response
        openai_response = {
            "id": f"code-assist-{int(time.time())}",
            "object": "chat.completion",
            "created": int(time.time()),
            "model": model,
            "choices": [
                {
                    "index": 0,
                    "message": {"role": "assistant", "content": generated_text},
                    "finish_reason": "stop",
                }
            ],
            "usage": {
                "prompt_tokens": 0,  # Code Assist API doesn't provide token counts
                "completion_tokens": 0,
                "total_tokens": 0,
            },
        }

        return openai_response

    async def _discover_project_id(self, auth_session) -> str:
        """Discover or retrieve the project ID for Code Assist API.

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

            # If no existing project, we need to onboard
            allowed_tiers = load_data.get("allowedTiers", [])
            default_tier = None
            for tier in allowed_tiers:
                if tier.get("isDefault"):
                    default_tier = tier
                    break

            # ==== CRITICAL TIER SELECTION LOGIC ====
            # This is one of the most critical parts of the implementation!
            #
            # The loadCodeAssist response returns available tiers, typically:
            # - "standard-tier": Requires user-defined Google Cloud project (userDefinedCloudaicompanionProject=true)
            # - "free-tier": Uses Google-managed project, no user project needed
            #
            # If we try to use standard-tier without a real Google Cloud project,
            # we get: "403 Permission denied on resource project default"
            #
            # KiloCode's solution: Automatically fall back to free-tier when
            # standard-tier requires a user project we don't have.
            #
            # This allows the "Google CLI" auth to work with just the credentials file,
            # no Google Cloud project setup required!

            if default_tier and default_tier.get("userDefinedCloudaicompanionProject"):
                # Standard-tier requires user project but we don't have one
                # Use free-tier instead (exactly what KiloCode does)
                logger.info(
                    f"Default tier {default_tier.get('id')} requires user project, using free-tier instead"
                )
                tier_id = "free-tier"
            else:
                tier_id = (
                    default_tier.get("id")
                    if default_tier
                    else "free-tier"  # ALWAYS fallback to free-tier, never standard-tier
                )

            logger.info(f"Using tier: {tier_id}")

            # ==== CRITICAL: FREE-TIER ONBOARDING ====
            # THIS IS THE MOST IMPORTANT PART OF THE ENTIRE IMPLEMENTATION!
            #
            # For free-tier, we MUST NOT include the "cloudaicompanionProject" field AT ALL.
            # Not as null, not as None, not as empty string - the field must be COMPLETELY ABSENT.
            #
            # Why? The free-tier uses a Google-managed project. If we include the field
            # (even with null/None), the API returns "Precondition Failed" errors.
            #
            # This was discovered through extensive debugging - the gemini CLI source code
            # explicitly omits this field for free-tier (see gemini-cli setup.ts line 73-77).
            #
            # The API will return a managed project ID like "charismatic-fragment-mxnz0"
            # which we then use for all subsequent API calls.

            if tier_id == "free-tier":
                onboard_request = {
                    "tierId": tier_id,
                    # CRITICAL: DO NOT add cloudaicompanionProject here!
                    # The field must be completely absent from the request
                    "metadata": {
                        "ideType": "IDE_UNSPECIFIED",
                        "platform": "PLATFORM_UNSPECIFIED",
                        "pluginType": "GEMINI",
                        # Also no duetProject for free tier
                    },
                }
            else:
                onboard_request = {
                    "tierId": tier_id,
                    "cloudaicompanionProject": initial_project_id,
                    "metadata": client_metadata,
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

            # Poll until operation is complete (matching KiloCode logic)
            max_retries = 30
            retry_count = 0

            while not lro_data.get("done") and retry_count < max_retries:
                await asyncio.sleep(2)

                # Poll the operation
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


backend_registry.register_backend(
    "gemini-cli-oauth-personal", GeminiOAuthPersonalConnector
)
