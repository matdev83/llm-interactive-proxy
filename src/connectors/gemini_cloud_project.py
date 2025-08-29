"""
Gemini Cloud Project connector that uses OAuth authentication with user-specified GCP projects

This connector implements authentication for Google Cloud Project ID-based access, allowing
users to leverage their own GCP projects with Gemini Code Assist Standard/Enterprise subscriptions.

Unlike the personal OAuth connector (which uses free-tier with managed projects), this connector:
1. Requires a user-specified GCP project ID
2. Uses standard-tier for onboarding (NOT free-tier)
3. MUST include cloudaicompanionProject field in ALL API requests
4. Bills usage to the user's GCP project
5. Provides access to higher quotas and enterprise features

=== CRITICAL IMPLEMENTATION NOTES ===

1. PROJECT REQUIREMENTS:
   - User MUST have a valid Google Cloud Project with billing enabled
   - Cloud AI Companion API must be enabled on the project
   - User must have appropriate IAM permissions (roles/cloudaicompanion.user)

2. TIER SELECTION (OPPOSITE OF PERSONAL OAUTH):
   - MUST use "standard-tier" or "enterprise-tier"
   - NEVER falls back to "free-tier"
   - Requires userDefinedCloudaicompanionProject=true

3. ONBOARDING DIFFERENCES:
   - MUST include "cloudaicompanionProject" field in onboarding request
   - The field value MUST be the user's actual GCP project ID
   - Without this field, onboarding to standard-tier will fail

4. API REQUEST DIFFERENCES:
   - ALL requests must include the user's project ID
   - Project field in requests: user's GCP project (not "default" or managed ID)

5. BILLING & QUOTAS:
   - All API usage is billed to the user's GCP project
   - Subject to the project's quotas and rate limits
   - Can be monitored in GCP Console under APIs & Services

This implementation is designed for production use with proper GCP project setup,
as opposed to the personal OAuth backend which is for development/testing.
"""

# mypy: disable-error-code="no-untyped-call,no-untyped-def,no-any-return,has-type,var-annotated"
import asyncio
import json
import logging
import os
import time
from collections.abc import AsyncGenerator
from pathlib import Path
from typing import Any

import google.auth
import google.auth.transport.requests
import google.oauth2.credentials
import google.oauth2.service_account
import httpx
from fastapi import HTTPException
from google.auth.exceptions import RefreshError

from src.core.common.exceptions import AuthenticationError, BackendError
from src.core.config.app_config import AppConfig
from src.core.domain.responses import (
    ProcessedResponse,
    ResponseEnvelope,
    StreamingResponseEnvelope,
)
from src.core.services.backend_registry import backend_registry

from .gemini import GeminiBackend


# Gemini CLI OAuth configuration loader (reads from ~/.gemini or env)
def _load_gemini_oauth_client_config() -> tuple[str, str | None, list[str]]:
    """Load OAuth client config from ~/.gemini files or environment.

    Order of precedence:
    1) ~/.gemini/oauth_client.json (fields: client_id, client_secret, scopes)
    2) ~/.gemini/config.json (same fields if present)
    3) Environment variables: GEMINI_CLI_CLIENT_ID, GEMINI_CLI_CLIENT_SECRET, GEMINI_CLI_OAUTH_SCOPES

    Returns:
        (client_id, client_secret, scopes)
    """
    home_dir = Path.home()
    candidates = [
        home_dir / ".gemini" / "oauth_client.json",
        home_dir / ".gemini" / "config.json",
    ]

    for path in candidates:
        try:
            if path.exists():
                with open(path, encoding="utf-8") as f:
                    data = json.load(f)
                client_id = data.get("client_id") or data.get("clientId")
                client_secret = data.get("client_secret") or data.get("clientSecret")
                scopes_val = data.get("scopes") or data.get("oauth_scopes")
                loaded_scopes: list[str] = []
                if isinstance(scopes_val, list):
                    loaded_scopes = [str(s) for s in scopes_val]
                elif isinstance(scopes_val, str):
                    loaded_scopes = [
                        s.strip() for s in scopes_val.split(",") if s.strip()
                    ]
                if client_id:
                    return (
                        str(client_id),
                        (str(client_secret) if client_secret else None),
                        (
                            loaded_scopes
                            if loaded_scopes
                            else [
                                "https://www.googleapis.com/auth/cloud-platform",
                                "https://www.googleapis.com/auth/userinfo.email",
                                "https://www.googleapis.com/auth/userinfo.profile",
                            ]
                        ),
                    )
        except Exception:
            # Ignore parsing errors and continue to next source
            pass

    env_client_id = os.getenv("GEMINI_CLI_CLIENT_ID")
    env_client_secret = os.getenv("GEMINI_CLI_CLIENT_SECRET")
    env_scopes = os.getenv("GEMINI_CLI_OAUTH_SCOPES")
    default_scopes: list[str] = [
        "https://www.googleapis.com/auth/cloud-platform",
        "https://www.googleapis.com/auth/userinfo.email",
        "https://www.googleapis.com/auth/userinfo.profile",
    ]
    resolved_scopes: list[str] = default_scopes
    if env_scopes:
        resolved_scopes = [s.strip() for s in env_scopes.split(",") if s.strip()]

    if env_client_id:
        return env_client_id, env_client_secret, resolved_scopes

    # As a last resort, raise a clear error to avoid embedding any client credentials in source
    raise AuthenticationError(
        "Gemini OAuth client configuration not found. Set GEMINI_CLI_CLIENT_ID (and optional GEMINI_CLI_CLIENT_SECRET) "
        "or provide ~/.gemini/oauth_client.json with client_id/client_secret/scopes."
    )


# Code Assist API endpoint (same as personal OAuth)
CODE_ASSIST_ENDPOINT = "https://cloudcode-pa.googleapis.com"
CODE_ASSIST_API_VERSION = "v1internal"

# Scopes for Code Assist API (used with Google ADC)
CODE_ASSIST_SCOPES: list[str] = [
    "https://www.googleapis.com/auth/cloud-platform",
    "https://www.googleapis.com/auth/userinfo.email",
    "https://www.googleapis.com/auth/userinfo.profile",
]

# Tier IDs for standard and enterprise
STANDARD_TIER_ID = "standard-tier"
ENTERPRISE_TIER_ID = "enterprise-tier"

logger = logging.getLogger(__name__)


class GeminiCloudProjectConnector(GeminiBackend):
    """Connector that uses OAuth authentication with user-specified GCP project.

    This connector requires a valid Google Cloud Project ID and uses OAuth2
    authentication to access Gemini Code Assist API with standard/enterprise tier features.
    All usage is billed to the specified GCP project.
    """

    backend_type: str = "gemini-cli-cloud-project"

    def __init__(
        self, client: httpx.AsyncClient, config: AppConfig, **kwargs: Any
    ) -> None:  # Modified
        super().__init__(client, config)  # Modified
        self.name = "gemini-cli-cloud-project"
        self.is_functional = False
        self._oauth_credentials: dict[str, Any] | None = None
        self._credentials_path: Path | None = None
        self._last_modified: float = 0
        self._refresh_token: str | None = None
        self._token_refresh_lock = asyncio.Lock()

        # GCP Project ID is REQUIRED for this backend (CLI uses GOOGLE_CLOUD_PROJECT)
        self.gcp_project_id = (
            kwargs.get("gcp_project_id")
            or os.getenv("GOOGLE_CLOUD_PROJECT")
            or os.getenv("GCP_PROJECT_ID")
        )
        if not self.gcp_project_id:
            logger.warning(
                "GCP Project ID not provided. This backend requires a valid Google Cloud "
                "Project ID with billing enabled and Cloud AI Companion API enabled."
            )
            self.is_functional = False

        # Optional: Allow custom credentials path
        self.credentials_path = kwargs.get("credentials_path") or os.getenv(
            "GEMINI_CREDENTIALS_PATH"
        )

        # Check if health checks should be disabled
        disable_health_checks = os.getenv("DISABLE_HEALTH_CHECKS", "false").lower() in (
            "true",
            "1",
            "yes",
        )
        self._health_checked: bool = disable_health_checks

    def _get_adc_authorized_session(
        self,
    ) -> google.auth.transport.requests.AuthorizedSession:
        """Create an AuthorizedSession using ADC, preferring service account file if provided.

        Resolution order:
        1) Explicit credentials_path (points to a service account JSON file)
        2) GOOGLE_APPLICATION_CREDENTIALS env var (service account JSON)
        3) Application Default Credentials (google.auth.default), supporting
           workload identity, user credentials, or gcloud auth application-default
        """
        # Prefer explicit service account file path
        sa_path: str | None = None
        if self.credentials_path:
            sa_path = str(self.credentials_path)
        else:
            sa_path = os.getenv("GOOGLE_APPLICATION_CREDENTIALS")

        if sa_path and Path(sa_path).exists():
            try:
                credentials = (
                    google.oauth2.service_account.Credentials.from_service_account_file(
                        sa_path, scopes=CODE_ASSIST_SCOPES
                    )
                )
                logger.info("Using service account credentials from %s", sa_path)
                return google.auth.transport.requests.AuthorizedSession(credentials)
            except Exception as e:
                logger.warning(
                    "Failed to load service account credentials from %s: %s", sa_path, e
                )

        # Fall back to ADC (supports gcloud ADC, workload identity, etc.)
        credentials, adc_project = google.auth.default(scopes=CODE_ASSIST_SCOPES)
        if adc_project and not self.gcp_project_id:
            # If ADC provided a project and user didn't specify, adopt it
            self.gcp_project_id = adc_project
        logger.info("Using Application Default Credentials for Code Assist API")
        return google.auth.transport.requests.AuthorizedSession(credentials)

    def _is_token_expired(self) -> bool:
        """Check if the current access token is expired or close to expiring."""
        if not self._oauth_credentials:
            return True

        expiry_date_ms = self._oauth_credentials.get("expiry_date")
        if not isinstance(expiry_date_ms, int | float):
            return False

        expiry_date_s = float(expiry_date_ms) / 1000.0
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
        """Refresh the access token if it's expired or close to expiring."""
        if not self._is_token_expired():
            return True

        async with self._token_refresh_lock:
            if not self._is_token_expired():
                return True

            logger.info("Access token expired or near expiry, attempting to refresh...")

            if not self._oauth_credentials:
                logger.warning("No OAuth credentials available for refresh.")
                return False

            try:
                creds_dict = dict(self._oauth_credentials)
                if "expiry_date" in creds_dict:
                    creds_dict["expiry"] = creds_dict.pop("expiry_date") / 1000

                credentials = google.oauth2.credentials.Credentials(
                    token=creds_dict.get("access_token"),
                    refresh_token=creds_dict.get("refresh_token"),
                    token_uri="https://oauth2.googleapis.com/token",
                    client_id=_load_gemini_oauth_client_config()[0],
                    client_secret=_load_gemini_oauth_client_config()[1],
                    scopes=_load_gemini_oauth_client_config()[2],
                )

                request = google.auth.transport.requests.Request()
                credentials.refresh(request)

                new_credentials = {
                    "access_token": credentials.token,
                    "refresh_token": credentials.refresh_token,
                    "token_type": "Bearer",
                    "expiry_date": (
                        int(credentials.expiry.timestamp() * 1000)
                        if credentials.expiry
                        else int(time.time() * 1000 + 3600 * 1000)
                    ),
                }

                self._oauth_credentials.update(new_credentials)
                await self._save_oauth_credentials(self._oauth_credentials)

                logger.info(
                    "Successfully refreshed OAuth token for GCP project access."
                )
                return True

            except RefreshError as e:
                logger.error(f"Google Auth token refresh error: {e}")
                return False
            except Exception as e:
                logger.error(f"Unexpected error during token refresh: {e}")
                return False

    async def _save_oauth_credentials(self, credentials: dict[str, Any]) -> None:
        """Save OAuth credentials to oauth_creds.json file."""
        try:
            if self.credentials_path:
                creds_path = Path(self.credentials_path)
                if creds_path.is_dir():
                    creds_path = creds_path / "oauth_creds.json"
            else:
                home_dir = Path.home()
                gemini_dir = home_dir / ".gemini"
                gemini_dir.mkdir(parents=True, exist_ok=True)
                creds_path = gemini_dir / "oauth_creds.json"

            with open(creds_path, "w", encoding="utf-8") as f:
                json.dump(credentials, f, indent=4)
            logger.info(f"OAuth credentials saved to {creds_path}")
        except Exception as e:
            logger.error(f"Error saving OAuth credentials: {e}")

    async def _load_oauth_credentials(self) -> bool:
        """Load OAuth credentials from oauth_creds.json file."""
        try:
            if self.credentials_path:
                creds_path = Path(self.credentials_path)
                if creds_path.is_dir():
                    creds_path = creds_path / "oauth_creds.json"
            else:
                home_dir = Path.home()
                creds_path = home_dir / ".gemini" / "oauth_creds.json"

            self._credentials_path = creds_path

            if not creds_path.exists():
                logger.warning(f"OAuth credentials not found at {creds_path}")
                return False

            try:
                current_modified = creds_path.stat().st_mtime
                if current_modified == self._last_modified and self._oauth_credentials:
                    logger.debug("OAuth credentials file not modified, using cached.")
                    return True
                self._last_modified = current_modified
            except OSError:
                pass

            with open(creds_path, encoding="utf-8") as f:
                credentials = json.load(f)

            if "access_token" not in credentials:
                logger.warning("Malformed OAuth credentials: missing access_token")
                return False

            self._oauth_credentials = credentials
            logger.info("Successfully loaded OAuth credentials.")
            return True
        except json.JSONDecodeError as e:
            logger.error(f"Error decoding OAuth credentials JSON: {e}")
            return False
        except Exception as e:
            logger.error(f"Error loading OAuth credentials: {e}")
            return False

    async def initialize(self, **kwargs: Any) -> None:
        """Initialize backend by loading credentials and validating project."""
        logger.info(
            f"Initializing Gemini Cloud Project backend with project: {self.gcp_project_id}"
        )

        # Ensure we have a project ID
        if not self.gcp_project_id:
            logger.error("GCP Project ID is required for cloud-project backend")
            self.is_functional = False
            return

        # Set the API base URL for Google Code Assist API
        self.gemini_api_base_url = kwargs.get(
            "gemini_api_base_url", CODE_ASSIST_ENDPOINT
        )

        # Using Google ADC; no need to load personal OAuth creds. Validate by making API calls below

        # Validate the project during initialization
        try:
            await self._validate_project_access()
            await self._ensure_models_loaded()
            self.is_functional = True
            logger.info(
                f"Gemini Cloud Project backend initialized with {len(self.available_models)} models "
                f"for project: {self.gcp_project_id}"
            )
        except Exception as e:
            logger.error(f"Failed to validate project or load models: {e}")
            self.is_functional = False

    async def _validate_project_access(self) -> None:
        """Validate that we can access the specified GCP project."""
        # Acquire ADC authorized session
        auth_session = self._get_adc_authorized_session()

        # Call loadCodeAssist with the user's project
        load_request = {
            "cloudaicompanionProject": self.gcp_project_id,
            "metadata": {
                "ideType": "IDE_UNSPECIFIED",
                "platform": "PLATFORM_UNSPECIFIED",
                "pluginType": "GEMINI",
                "duetProject": self.gcp_project_id,
            },
        }

        url = f"{self.gemini_api_base_url}/v1internal:loadCodeAssist"
        try:
            load_response = await asyncio.to_thread(
                auth_session.request,
                method="POST",
                url=url,
                json=load_request,
                headers={"Content-Type": "application/json"},
                timeout=30.0,
            )

            if load_response.status_code == 403:
                raise AuthenticationError(
                    f"Permission denied for project {self.gcp_project_id}. "
                    f"Ensure Cloud AI Companion API is enabled and you have necessary permissions."
                )
            elif load_response.status_code != 200:
                raise BackendError(f"Project validation failed: {load_response.text}")

            logger.info(
                f"Successfully validated access to project: {self.gcp_project_id}"
            )
        except Exception as e:
            logger.error(f"Failed to validate project access: {e}")
            raise

    async def _resolve_gemini_api_config(
        self,
        gemini_api_base_url: str | None,
        openrouter_api_base_url: str | None,
        api_key: str | None,
        **kwargs: Any,
    ) -> tuple[str, dict[str, str]]:
        """Override to use access_token from OAuth credentials."""
        if not self._oauth_credentials or not self._oauth_credentials.get(
            "access_token"
        ):
            raise HTTPException(
                status_code=401,
                detail="No valid OAuth access token available. Please authenticate.",
            )

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

        access_token = self._oauth_credentials["access_token"]
        return base.rstrip("/"), {"Authorization": f"Bearer {access_token}"}

    async def _perform_health_check(self) -> bool:
        """Perform a health check by testing API connectivity with project."""
        try:
            # With ADC, token handling is internal; proceed to simple request

            if not self.gcp_project_id:
                logger.warning("Health check failed - no GCP project ID specified")
                return False

            # Test with a simple API call
            base_url = self.gemini_api_base_url or CODE_ASSIST_ENDPOINT
            url = f"{base_url}/v1internal/models"
            # Use ADC session to make a simple GET (httpx client requires headers; fetch token)
            session = self._get_adc_authorized_session()
            request = google.auth.transport.requests.Request()
            # Refresh underlying credentials to ensure valid token
            session.credentials.refresh(request)  # type: ignore[attr-defined]
            headers = {"Authorization": f"Bearer {session.credentials.token}"}  # type: ignore[attr-defined]
            response = await self.client.get(url, headers=headers)

            if response.status_code == 200:
                logger.info("Health check passed - API connectivity verified")
                self._health_checked = True
                return True
            else:
                logger.warning(
                    f"Health check failed - API returned status {response.status_code}"
                )
                return False

        except Exception as e:
            logger.error(f"Health check failed - unexpected error: {e}")
            return False

    async def _ensure_healthy(self) -> None:
        """Ensure the backend is healthy before use."""
        if not hasattr(self, "_health_checked") or not self._health_checked:
            logger.info(
                "Performing first-use health check for Gemini Cloud Project backend"
            )

            refreshed = await self._refresh_token_if_needed()
            if not refreshed:
                raise BackendError("Failed to refresh OAuth token during health check")

            healthy = await self._perform_health_check()
            if not healthy:
                raise BackendError("Health check failed")

            self._health_checked = True
            logger.info("Health check passed - backend is ready for use")

    async def chat_completions(
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
        """Handle chat completions using Google Code Assist API with user's GCP project."""
        await self._ensure_healthy()

        try:
            # Use the effective model (strip prefix if present)
            model_name = effective_model
            if model_name.startswith("gemini-cli-cloud-project:"):
                model_name = model_name[25:]  # Remove prefix

            # Check if streaming is requested
            is_streaming = getattr(request_data, "stream", False)

            if is_streaming:
                return await self._chat_completions_streaming(
                    request_data=request_data,
                    processed_messages=processed_messages,
                    effective_model=model_name,
                    **kwargs,
                )
            else:
                return await self._chat_completions_standard(
                    request_data=request_data,
                    processed_messages=processed_messages,
                    effective_model=model_name,
                    **kwargs,
                )

        except HTTPException:
            raise
        except (AuthenticationError, BackendError):
            raise
        except Exception as e:
            logger.error(f"Error in Gemini Cloud Project chat_completions: {e}")
            raise BackendError(
                message=f"Gemini Cloud Project chat completion failed: {e!s}"
            ) from e

    async def _chat_completions_standard(
        self,
        request_data: Any,
        processed_messages: list[Any],
        effective_model: str,
        **kwargs: Any,
    ) -> ResponseEnvelope:
        """Handle non-streaming chat completions."""
        try:
            # Use ADC for API calls (matches gemini CLI behavior for project-id auth)
            auth_session = self._get_adc_authorized_session()

            # Ensure project is onboarded for standard-tier
            project_id = await self._ensure_project_onboarded(auth_session)

            # Convert messages to Gemini format
            contents = self._convert_messages_to_gemini_format(processed_messages)

            # Prepare request body with USER'S project ID
            request_body = {
                "model": effective_model,
                "project": project_id,  # User's GCP project
                "request": {
                    "contents": contents,
                    "generationConfig": self._build_generation_config(request_data),
                },
            }

            url = f"{self.gemini_api_base_url}/v1internal:streamGenerateContent"
            logger.info(f"Making Code Assist API call with project {project_id}")

            response = await asyncio.to_thread(
                auth_session.request,
                method="POST",
                url=url,
                params={"alt": "sse"},
                json=request_body,
                headers={"Content-Type": "application/json"},
                timeout=60.0,
            )

            if response.status_code >= 400:
                try:
                    error_detail = response.json()
                except Exception:
                    error_detail = response.text

                if response.status_code == 403:
                    raise BackendError(
                        message=f"Permission denied for project {project_id}. {error_detail}",
                        code="permission_denied",
                        status_code=403,
                    )
                raise BackendError(
                    message=f"Code Assist API error: {error_detail}",
                    code="code_assist_error",
                    status_code=response.status_code,
                )

            # Parse SSE stream response
            generated_text = ""
            usage_metadata = {}

            response_text = response.text
            for line in response_text.split("\n"):
                if line.startswith("data: "):
                    data_str = line[6:].strip()
                    if data_str == "[DONE]":
                        break
                    try:
                        data = json.loads(data_str)
                        response_data = data.get("response", data)

                        candidates = response_data.get("candidates", [])
                        if candidates:
                            content = candidates[0].get("content", {})
                            parts = content.get("parts", [])
                            for part in parts:
                                if isinstance(part, dict) and "text" in part:
                                    generated_text += part["text"]

                        if "usageMetadata" in response_data:
                            usage_metadata = response_data["usageMetadata"]
                    except json.JSONDecodeError:
                        continue

            # Convert to OpenAI-compatible format
            openai_response = {
                "id": f"gemini-cloud-{int(time.time())}",
                "object": "chat.completion",
                "created": int(time.time()),
                "model": effective_model,
                "choices": [
                    {
                        "index": 0,
                        "message": {"role": "assistant", "content": generated_text},
                        "finish_reason": "stop",
                    }
                ],
                "usage": {
                    "prompt_tokens": usage_metadata.get("promptTokenCount", 0),
                    "completion_tokens": usage_metadata.get("candidatesTokenCount", 0),
                    "total_tokens": usage_metadata.get("totalTokenCount", 0),
                },
            }

            logger.info(
                f"Successfully received response from Code Assist API for project {project_id}"
            )
            return ResponseEnvelope(
                content=openai_response, headers={}, status_code=200
            )

        except (AuthenticationError, BackendError):
            raise
        except Exception as e:
            logger.error(f"Unexpected error during API call: {e}")
            raise BackendError(f"Unexpected error during API call: {e}")

    async def _chat_completions_streaming(
        self,
        request_data: Any,
        processed_messages: list[Any],
        effective_model: str,
        **kwargs: Any,
    ) -> StreamingResponseEnvelope:
        """Handle streaming chat completions."""
        try:
            # Use ADC for streaming API calls
            auth_session = self._get_adc_authorized_session()

            # Ensure project is onboarded for standard-tier
            project_id = await self._ensure_project_onboarded(auth_session)

            # Convert messages to Gemini format
            contents = self._convert_messages_to_gemini_format(processed_messages)

            # Prepare request body with USER'S project ID
            request_body = {
                "model": effective_model,
                "project": project_id,
                "request": {
                    "contents": contents,
                    "generationConfig": self._build_generation_config(request_data),
                },
            }

            url = f"{self.gemini_api_base_url}/v1internal:streamGenerateContent"
            logger.info(
                f"Making streaming Code Assist API call with project {project_id}"
            )

            async def stream_generator() -> AsyncGenerator[ProcessedResponse, None]:
                try:
                    response = await asyncio.to_thread(
                        auth_session.request,
                        method="POST",
                        url=url,
                        params={"alt": "sse"},
                        json=request_body,
                        headers={"Content-Type": "application/json"},
                        timeout=60.0,
                    )

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

                    # Forward raw text stream; central pipeline will handle normalization/repairs
                    processed_stream = response.aiter_text()

                    async for chunk in processed_stream:
                        # If JSON repair is enabled, the processor yields repaired JSON strings
                        # or raw text. If disabled, it yields raw text.
                        # We need to ensure it's properly formatted as SSE.
                        if chunk.startswith(("data: ", "id: ", ":")):
                            # Already SSE formatted or a comment, yield directly
                            yield ProcessedResponse(content=chunk)
                        else:
                            # Assume it's a raw text chunk (either repaired JSON or non-JSON text)
                            # and format it as an SSE data event.
                            yield ProcessedResponse(content=f"data: {chunk}\n\n")

                    yield ProcessedResponse(content="data: [DONE]\n\n")

                except Exception as e:
                    logger.error(f"Error in streaming generator: {e}")
                    yield ProcessedResponse(content="data: [DONE]\n\n")

                finally:
                    await response.aclose()

            return StreamingResponseEnvelope(
                content=stream_generator(),
                media_type="text/event-stream",
                headers={},
            )

        except (AuthenticationError, BackendError):
            raise
        except Exception as e:
            logger.error(f"Unexpected error during streaming API call: {e}")
            raise BackendError(f"Unexpected error during streaming API call: {e}")

    def _build_generation_config(self, request_data: Any) -> dict[str, Any]:
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

    async def _ensure_project_onboarded(self, auth_session) -> str:
        """Ensure the user's GCP project is onboarded for standard-tier access."""
        if hasattr(self, "_onboarded_project_id"):
            return self._onboarded_project_id

        # Prepare metadata
        client_metadata = {
            "ideType": "IDE_UNSPECIFIED",
            "platform": "PLATFORM_UNSPECIFIED",
            "pluginType": "GEMINI",
            "duetProject": self.gcp_project_id,
        }

        # First, check if project is already onboarded
        load_request = {
            "cloudaicompanionProject": self.gcp_project_id,
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
            error_detail = load_response.text
            if "Permission denied" in error_detail:
                raise BackendError(
                    f"Permission denied for project {self.gcp_project_id}. "
                    "Ensure Cloud AI Companion API is enabled and you have necessary IAM permissions."
                )
            raise BackendError(f"LoadCodeAssist failed: {error_detail}")

        load_data = load_response.json()

        # Check if already onboarded
        if load_data.get("cloudaicompanionProject"):
            self._onboarded_project_id = load_data["cloudaicompanionProject"]
            logger.info(f"Project {self._onboarded_project_id} is already onboarded")
            return self._onboarded_project_id

        # Need to onboard to standard-tier
        allowed_tiers = load_data.get("allowedTiers", [])
        standard_tier = None

        for tier in allowed_tiers:
            if tier.get("id") == STANDARD_TIER_ID:
                standard_tier = tier
                break

        if not standard_tier:
            # Try enterprise tier as fallback
            for tier in allowed_tiers:
                if tier.get("id") == ENTERPRISE_TIER_ID:
                    standard_tier = tier
                    break

        if not standard_tier:
            raise BackendError(
                f"Neither standard-tier nor enterprise-tier available for project {self.gcp_project_id}"
            )

        # Verify tier supports user-defined projects
        if not standard_tier.get("userDefinedCloudaicompanionProject"):
            raise BackendError(
                f"Tier {standard_tier.get('id')} does not support user-defined projects. "
                "This may indicate a configuration issue with your GCP project."
            )

        # CRITICAL: Include cloudaicompanionProject for standard-tier
        onboard_request = {
            "tierId": standard_tier.get("id"),
            "cloudaicompanionProject": self.gcp_project_id,  # MUST include for standard
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
            error_detail = lro_response.text
            if "Permission denied" in error_detail:
                raise BackendError(
                    f"Permission denied for project {self.gcp_project_id}. "
                    "Ensure you have the necessary IAM permissions and billing is enabled."
                )
            raise BackendError(f"Onboarding failed: {error_detail}")

        lro_data = lro_response.json()

        # Poll until operation is complete
        lro_data = await self._poll_operation(
            auth_session, onboard_url, onboard_request
        )

        # Extract the project ID
        response_data = lro_data.get("response", {})
        cloudai_project = response_data.get("cloudaicompanionProject", {})
        confirmed_project_id = cloudai_project.get("id", self.gcp_project_id)

        if confirmed_project_id != self.gcp_project_id:
            logger.warning(
                f"Project ID mismatch: expected {self.gcp_project_id}, got {confirmed_project_id}"
            )

        self._onboarded_project_id = confirmed_project_id
        logger.info(
            f"Successfully onboarded project {self._onboarded_project_id} to {standard_tier.get('id')}"
        )
        return self._onboarded_project_id

    async def _poll_operation(
        self, auth_session, url: str, request_body: dict[str, Any]
    ) -> dict[str, Any]:
        """Poll a long-running operation until completion."""
        max_retries = 30
        retry_count = 0
        lro_data = {}

        while retry_count < max_retries:
            await asyncio.sleep(2)

            lro_response = await asyncio.to_thread(
                auth_session.request,
                method="POST",
                url=url,
                json=request_body,
                headers={"Content-Type": "application/json"},
                timeout=30.0,
            )

            if lro_response.status_code == 200:
                lro_data = lro_response.json()
                if lro_data.get("done"):
                    break

            retry_count += 1

        if not lro_data.get("done"):
            raise BackendError(
                "Operation timeout - did not complete within expected time"
            )

        return lro_data

    def _convert_messages_to_gemini_format(
        self, processed_messages: list[Any]
    ) -> list[dict]:
        """Convert processed messages to Gemini format."""
        contents = []

        for msg in processed_messages:
            role = (
                msg.get("role") if isinstance(msg, dict) else getattr(msg, "role", None)
            )
            content = (
                msg.get("content")
                if isinstance(msg, dict)
                else getattr(msg, "content", "")
            )

            if role and content:
                # Convert role mapping
                gemini_role = "user" if role == "user" else "model"
                contents.append(
                    {"role": gemini_role, "parts": [{"text": str(content)}]}
                )

        return contents

    def _convert_stream_chunk(self, data: dict[str, Any], model: str) -> dict[str, Any]:
        """Convert a Code Assist API streaming chunk to OpenAI format."""
        candidate = {}
        text = ""
        if data.get("candidates"):
            candidate = data["candidates"][0] or {}
            content = candidate.get("content", {})
            parts = content.get("parts", [])
            for part in parts:
                if isinstance(part, dict) and "text" in part:
                    text += part["text"]

        finish_reason = candidate.get("finishReason")
        return {
            "id": data.get("id", ""),
            "object": "chat.completion.chunk",
            "created": int(time.time()),
            "model": model,
            "choices": [
                {
                    "index": candidate.get("index", 0),
                    "delta": {"content": text},
                    "finish_reason": (
                        finish_reason.lower()
                        if isinstance(finish_reason, str)
                        else None
                    ),
                }
            ],
        }


backend_registry.register_backend(
    "gemini-cli-cloud-project", GeminiCloudProjectConnector
)
