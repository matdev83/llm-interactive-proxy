"""
Qwen OAuth connector that uses refresh_token from qwen-cli oauth_creds.json file
"""

import asyncio
import json
import logging
import time
from collections.abc import AsyncGenerator
from pathlib import Path
from typing import TYPE_CHECKING, Any

import httpx
from fastapi import HTTPException

from src.core.adapters.api_adapters import legacy_to_domain_chat_request
from src.core.common.exceptions import (
    AuthenticationError,
    BackendError,
    ServiceUnavailableError,
)
from src.core.config.app_config import AppConfig
from src.core.domain.responses import ResponseEnvelope, StreamingResponseEnvelope
from src.core.interfaces.model_bases import DomainModel, InternalDTO
from src.core.services.backend_registry import backend_registry

from .openai import OpenAIConnector

if TYPE_CHECKING:
    from src.core.domain.configuration.app_identity_config import IAppIdentityConfig

    # No legacy ChatCompletionRequest here; connectors should use domain ChatRequest

logger = logging.getLogger(__name__)


class QwenOAuthConnector(OpenAIConnector):
    """Connector that uses refresh_token from qwen-cli oauth_creds.json file.

    This is a specialized OpenAI-compatible connector that reads the refresh_token
    from the qwen-cli generated oauth_creds.json file and uses it as the API key.
    """

    backend_type: str = "qwen-oauth"

    def __init__(
        self, client: httpx.AsyncClient, config: AppConfig
    ) -> None:  # Modified
        super().__init__(client, config)  # Modified
        self.name = "qwen-oauth"
        self._default_endpoint = "https://dashscope.aliyuncs.com/compatible-mode/v1"
        self.api_base_url = self._default_endpoint
        self.is_functional = False
        self._oauth_credentials: dict[str, Any] | None = None
        self._credentials_path: Path | None = None
        self._last_modified: float = 0
        self._refresh_token: str | None = None
        self._token_refresh_lock = asyncio.Lock()  # Ensure only one refresh at a time

    def _is_token_expired(self) -> bool:
        """Check if the current access token is expired or close to expiring."""
        if not self._oauth_credentials:
            return True  # No credentials means no valid token

        expiry_date_ms = self._oauth_credentials.get("expiry_date")
        if not isinstance(expiry_date_ms, int | float):
            return False  # No expiry date means token doesn't expire

        # Convert milliseconds to seconds
        expiry_date_s = float(expiry_date_ms) / 1000.0

        # Convert milliseconds to seconds
        expiry_date_s = expiry_date_ms / 1000

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
        """Refresh the access token if it's expired or close to expiring."""
        if not self._is_token_expired():
            return True  # No refresh needed

        async with self._token_refresh_lock:
            # Re-check after acquiring lock in case another coroutine refreshed it
            if not self._is_token_expired():
                return True

            logger.info("Access token expired or near expiry, attempting to refresh...")

            refresh_token = (
                self._oauth_credentials.get("refresh_token")
                if self._oauth_credentials
                else None
            )
            if not refresh_token:
                logger.warning("No refresh token available to perform refresh.")
                return False

            token_url = "https://chat.qwen.ai/api/v1/oauth2/token"  # Qwen's OAuth token endpoint
            headers = {"Content-Type": "application/x-www-form-urlencoded"}
            data = {
                "grant_type": "refresh_token",
                "refresh_token": refresh_token,
            }

            try:
                response = await self.client.post(token_url, headers=headers, data=data)
                response.raise_for_status()  # Raise an exception for HTTP errors (4xx or 5xx)
                new_credentials = response.json()

                # Ensure _oauth_credentials is a dictionary before updating
                if self._oauth_credentials is None:
                    self._oauth_credentials = {}
                self._oauth_credentials.update(new_credentials)
                self._oauth_credentials["expiry_date"] = (
                    int(time.time() * 1000)
                    + new_credentials.get("expires_in", 3600) * 1000
                )  # Convert to ms

                # Update API base URL if resource_url is provided
                resource_url = new_credentials.get("resource_url")
                if resource_url:
                    self.api_base_url = f"https://{resource_url}/v1"
                    logger.info(f"Qwen API base URL updated to: {self.api_base_url}")

                # Save updated credentials
                await self._save_oauth_credentials(self._oauth_credentials)

                logger.info("Successfully refreshed Qwen OAuth token.")
                return True

            except httpx.HTTPStatusError as e:
                logger.error(
                    f"HTTP error during token refresh: {e.response.status_code} - {e.response.text}"
                )
                return False
            except httpx.RequestError as e:
                logger.error(f"Network error during token refresh: {e}")
                return False
            except json.JSONDecodeError as e:
                logger.error(f"Malformed JSON response during token refresh: {e}")
                return False
            except Exception as e:
                logger.error(f"An unexpected error occurred during token refresh: {e}")
                return False

    async def _save_oauth_credentials(self, credentials: dict[str, Any]) -> None:
        """Save OAuth credentials to oauth_creds.json file."""
        try:
            home_dir = Path.home()
            qwen_dir = home_dir / ".qwen"
            qwen_dir.mkdir(parents=True, exist_ok=True)  # Ensure directory exists
            creds_path = qwen_dir / "oauth_creds.json"

            with open(creds_path, "w", encoding="utf-8") as f:
                json.dump(credentials, f, indent=4)
            logger.info(f"Qwen OAuth credentials saved to {creds_path}")
        except Exception as e:
            logger.error(f"Error saving Qwen OAuth credentials: {e}")

    async def _load_oauth_credentials(self) -> bool:
        """Load OAuth credentials from oauth_creds.json file."""
        try:
            home_dir = Path.home()
            creds_path = home_dir / ".qwen" / "oauth_creds.json"
            self._credentials_path = creds_path

            if not creds_path.exists():
                logger.warning(f"Qwen OAuth credentials not found at {creds_path}")
                return False

            # Check if file has been modified since last load
            try:
                current_modified = creds_path.stat().st_mtime
                if current_modified == self._last_modified and self._oauth_credentials:
                    # File hasn't changed and credentials are in memory, no need to reload
                    logger.debug(
                        "Qwen OAuth credentials file not modified, using cached."
                    )
                    return True
                self._last_modified = current_modified
            except OSError:
                # If cannot get file stats, proceed with reading
                pass

            with open(creds_path, encoding="utf-8") as f:
                credentials = json.load(f)

            # Validate essential fields
            if "access_token" not in credentials or "refresh_token" not in credentials:
                logger.warning(
                    "Malformed Qwen OAuth credentials: missing access_token or refresh_token"
                )
                return False

            self._oauth_credentials = credentials

            # Update API base URL if resource_url is provided
            resource_url = credentials.get("resource_url")
            if resource_url:
                self.api_base_url = f"https://{resource_url}/v1"
                logger.info(f"Qwen API base URL set to: {self.api_base_url}")

            logger.info("Successfully loaded Qwen OAuth credentials.")
            return True
        except json.JSONDecodeError as e:
            logger.error(f"Error decoding Qwen OAuth credentials JSON: {e}")
            return False
        except Exception as e:
            logger.error(f"Error loading Qwen OAuth credentials: {e}")
            return False

    def get_headers(self) -> dict[str, str]:
        """Override to use access_token from loaded credentials."""
        if not self._oauth_credentials or not self._oauth_credentials.get(
            "access_token"
        ):
            raise HTTPException(
                status_code=401,
                detail="No valid Qwen OAuth access token available. Please authenticate.",
            )
        return {
            "Authorization": f"Bearer {self._oauth_credentials['access_token']}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }

    async def _perform_health_check(self) -> bool:
        """Override parent health check to use Qwen-specific API endpoint."""
        try:
            # Use the Qwen API endpoint instead of OpenAI's
            if not self._oauth_credentials or not self._oauth_credentials.get(
                "access_token"
            ):
                logger.warning("Health check failed - no access token available")
                return False

            headers = self.get_headers()
            base_url = self._get_endpoint_url()
            url = f"{base_url}/models"

            response = await self.client.get(url, headers=headers)

            if response.status_code == 200:
                logger.info(
                    "Qwen OAuth health check passed - API connectivity verified"
                )
                self._health_checked = True
                return True
            else:
                logger.warning(
                    f"Qwen OAuth health check failed - API returned status {response.status_code}"
                )
                return False

        except Exception as e:
            logger.error(f"Qwen OAuth health check failed - unexpected error: {e}")
            return False

    async def initialize(self, **kwargs: Any) -> None:
        """Initialize backend by loading and potentially refreshing token."""
        logger.info("Initializing Qwen OAuth backend.")
        if not await self._load_oauth_credentials():
            logger.warning("Failed to load initial Qwen OAuth credentials.")
            self.is_functional = False
            return

        # Attempt to refresh token if needed during initialization
        if not await self._refresh_token_if_needed():
            logger.warning("Failed to refresh Qwen OAuth token during initialization.")
            self.is_functional = False
            return

        # If we reach here, credentials are loaded and potentially refreshed
        self.available_models = [
            "qwen3-coder-plus",  # Default model (confirmed working)
            "qwen3-coder-flash",  # Flash/fast model
            "qwen-turbo",  # Legacy names (may work)
            "qwen-plus",
            "qwen-max",
            "qwen2.5-72b-instruct",
            "qwen2.5-32b-instruct",
            "qwen2.5-14b-instruct",
            "qwen2.5-7b-instruct",
            "qwen2.5-3b-instruct",
            "qwen2.5-1.5b-instruct",
            "qwen2.5-0.5b-instruct",
        ]

        self.is_functional = True
        logger.info(
            f"Qwen OAuth backend initialized with {len(self.available_models)} models and health check enabled."
        )

    def _get_endpoint_url(self) -> str:
        """Get the API endpoint URL."""
        # Use resource_url from credentials if available, otherwise default
        if self._oauth_credentials and self._oauth_credentials.get("resource_url"):
            return f"https://{self._oauth_credentials['resource_url']}/v1"
        return self._default_endpoint

    def get_available_models(self) -> list[str]:
        """Return available Qwen models if functional."""
        return self.available_models if self.is_functional else []

    async def chat_completions(
        self,
        request_data: (
            DomainModel | InternalDTO | dict[str, Any]
        ),  # Revert to original type hint
        processed_messages: list[Any],
        effective_model: str,
        identity: "IAppIdentityConfig | None" = None,
        **kwargs: Any,
    ) -> ResponseEnvelope | StreamingResponseEnvelope:
        """Handle chat completions using Qwen OAuth API.

        This overrides the parent class method to ensure token is refreshed before API call.
        """
        # Ensure token is refreshed before making the API call
        if not await self._refresh_token_if_needed():
            raise HTTPException(
                status_code=401,
                detail="Failed to refresh Qwen OAuth token. Please re-authenticate.",
            )

        try:
            # Use the effective model (strip qwen-oauth: prefix if present)
            model_name = effective_model
            if model_name.startswith("qwen-oauth:"):
                model_name = model_name[11:]  # Remove "qwen-oauth:" prefix

            # Convert request_data to ChatRequest using the adapter
            chat_request = legacy_to_domain_chat_request(request_data)

            # Create a modified request_data with the correct model name.
            # Use model_copy(update=...) to avoid mutating frozen ValueObject instances.
            modified_request = chat_request.model_copy(update={"model": model_name})

            # Call the parent class method to handle the actual API request
            response_envelope = await super().chat_completions(
                request_data=modified_request,
                processed_messages=processed_messages,
                effective_model=model_name,
                **kwargs,
            )

            # If streaming, wrap the content with the JSON repair processor
            if (
                isinstance(response_envelope, StreamingResponseEnvelope)
                and self.config.session.json_repair_enabled
            ):
                from src.core.services.json_repair_service import JsonRepairService
                from src.core.services.streaming_json_repair_processor import (
                    StreamingJsonRepairProcessor,
                )

                json_repair_service = JsonRepairService()
                processor = StreamingJsonRepairProcessor(
                    repair_service=json_repair_service,
                    buffer_cap_bytes=self.config.session.json_repair_buffer_cap_bytes,
                    strict_mode=self.config.session.json_repair_strict_mode,
                )

                # Convert AsyncIterator[bytes] to AsyncGenerator[str, None]
                async def bytes_to_string_generator() -> AsyncGenerator[str, None]:
                    async for chunk in response_envelope.content:
                        yield chunk.decode("utf-8")

                # Store the processed stream and convert back to AsyncIterator[bytes]
                processed_content = processor.process_stream(
                    bytes_to_string_generator()
                )

                # Convert the processed string stream back to bytes
                async def string_to_bytes_generator() -> AsyncGenerator[bytes, None]:
                    async for chunk in processed_content:
                        yield chunk.encode("utf-8")

                response_envelope.content = string_to_bytes_generator()

            return response_envelope

        except HTTPException:
            # Re-raise HTTP exceptions directly
            raise
        except (AuthenticationError, BackendError, ServiceUnavailableError):
            # Re-raise domain exceptions
            raise
        except Exception as e:
            # Convert other exceptions to BackendError
            logger.error(f"Error in Qwen OAuth chat_completions: {e}")
            raise BackendError(
                message=f"Qwen OAuth chat completion failed: {e!s}"
            ) from e


backend_registry.register_backend("qwen-oauth", QwenOAuthConnector)
