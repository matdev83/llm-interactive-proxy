"""
Qwen OAuth connector that uses OAuth tokens from qwen-code CLI
"""

import asyncio
import json
import logging
import secrets
from pathlib import Path
from typing import (
    TYPE_CHECKING,
    Any,  # Added cast
    cast,
)

import httpx
from fastapi import HTTPException

from src.core.adapters.api_adapters import legacy_to_domain_chat_request
from src.core.common.exceptions import (
    AuthenticationError,
    BackendError,
    ServiceUnavailableError,
)
from src.core.domain.chat import ChatRequest
from src.core.domain.responses import ResponseEnvelope, StreamingResponseEnvelope
from src.core.interfaces.model_bases import DomainModel, InternalDTO
from src.core.services.backend_registry import backend_registry

from .openai import OpenAIConnector

if TYPE_CHECKING:
    # No legacy ChatCompletionRequest here; connectors should use domain ChatRequest
    pass

logger = logging.getLogger(__name__)


class QwenOAuthConnector(OpenAIConnector):
    """Connector that uses OAuth tokens from qwen-code CLI.

    This is a specialized OpenAI-compatible connector that uses OAuth tokens
    instead of API keys for authentication.
    """

    backend_type: str = "qwen-oauth"

    def __init__(self, client: httpx.AsyncClient) -> None:
        super().__init__(client)
        self.name = "qwen-oauth"
        self._default_endpoint = "https://dashscope.aliyuncs.com/compatible-mode/v1"
        self.api_base_url = self._default_endpoint
        self.is_functional = False
        self._oauth_credentials: dict[str, Any] | None = None

    def get_headers(self) -> dict[str, str]:
        """Override to use OAuth access token instead of API key."""
        access_token = self._get_access_token()
        if not access_token:
            raise HTTPException(
                status_code=401,
                detail="No valid Qwen OAuth access token available. Please authenticate using qwen-code CLI.",
            )
        return {
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }

    async def initialize(self, **kwargs: Any) -> None:
        """Initialize backend by loading OAuth credentials.

        This overrides the parent class method to load OAuth credentials from a file
        instead of requiring an API key to be passed in.
        """
        logger.info("Initializing Qwen OAuth backend")

        # Load OAuth credentials from qwen-code CLI
        if await self._load_oauth_credentials():
            # Set the actual models available via Qwen OAuth API
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
                f"Qwen OAuth backend initialized with {len(self.available_models)} models"
            )
        else:
            logger.warning("Failed to load Qwen OAuth credentials")
            self.is_functional = False

    async def _load_oauth_credentials(self) -> bool:
        """Load OAuth credentials from qwen-code CLI storage"""
        try:
            # Path where qwen-code stores OAuth credentials
            home_dir = Path.home()
            creds_path = home_dir / ".qwen" / "oauth_creds.json"

            if not creds_path.exists():
                logger.warning(f"Qwen OAuth credentials not found at {creds_path}")
                return False

            with open(creds_path, encoding="utf-8") as f:
                self._oauth_credentials = json.load(f)

            # Validate required fields
            if self._oauth_credentials and not self._oauth_credentials.get(
                "access_token"
            ):
                logger.warning("No access token found in Qwen OAuth credentials")
                return False

            # Update the API base URL from the OAuth credentials
            self.api_base_url = self._get_endpoint_url()

            logger.info("Successfully loaded Qwen OAuth credentials")
            return True

        except Exception as e:
            logger.error(f"Error loading Qwen OAuth credentials: {e}")
            return False

    def _get_access_token(self) -> str | None:
        """Get the current access token"""
        if not self._oauth_credentials:
            return None
        return self._oauth_credentials.get("access_token")

    def _get_endpoint_url(self) -> str:
        """Get the API endpoint URL"""
        if not self._oauth_credentials:
            return self._default_endpoint

        # Use resource_url from OAuth response if available
        resource_url = self._oauth_credentials.get("resource_url")
        if resource_url:
            # Ensure it has proper protocol
            if not resource_url.startswith(("http://", "https://")):
                resource_url = f"https://{resource_url}"

            # Ensure it ends with /v1
            if not resource_url.endswith("/v1"):
                resource_url = resource_url.rstrip("/") + "/v1"
            return resource_url

        return self._default_endpoint

    def _is_token_expired(self) -> bool:
        """Check if the current token is expired"""
        if not self._oauth_credentials:
            return True

        expiry_date = self._oauth_credentials.get("expiry_date")
        if not expiry_date:
            return False  # No expiry date, assume valid

        # Add 30 second buffer (expiry_date is in milliseconds, current time in seconds)
        import time

        current_time_ms = time.time() * 1000
        is_expired = current_time_ms >= (expiry_date - 30000)
        logger.info(
            f"Token expiry check: current_time_ms={current_time_ms}, expiry_date={expiry_date}, is_expired={is_expired}"
        )
        return bool(is_expired)

    async def _refresh_token_if_needed(self) -> bool:
        """Refresh the access token if needed"""
        is_expired = self._is_token_expired()
        logger.info(f"Token expired check: {is_expired}")
        if not is_expired:
            return True

        refresh_token = (
            self._oauth_credentials.get("refresh_token")
            if self._oauth_credentials
            else None
        )
        if not refresh_token:
            logger.warning("No refresh token available for Qwen OAuth")
            return False

        logger.info("Attempting to refresh Qwen OAuth token...")

        try:
            # Refresh token using Qwen OAuth API
            refresh_data = {
                "grant_type": "refresh_token",
                "refresh_token": refresh_token,
                "client_id": "f0304373b74a44d2b584a3fb70ca9e56",  # Qwen OAuth client ID
            }

            headers = {
                "Content-Type": "application/x-www-form-urlencoded",
                "Accept": "application/json",
            }

            # Convert to URL-encoded form data
            form_data = "&".join(f"{k}={v}" for k, v in refresh_data.items())

            response = await self.client.post(
                "https://chat.qwen.ai/api/v1/oauth2/token",
                content=form_data,
                headers=headers,
            )

            if response.status_code != 200:
                logger.error(
                    f"Token refresh failed: {response.status_code} {response.text}"
                )
                return False

            token_data = response.json()

            # Update credentials
            import time

            if self._oauth_credentials is None:
                self._oauth_credentials = {}
            self._oauth_credentials.update(
                {
                    "access_token": token_data["access_token"],
                    "token_type": token_data.get("token_type", "Bearer"),
                    "expiry_date": int(
                        time.time() * 1000 + token_data.get("expires_in", 3600) * 1000
                    ),
                }
            )

            # Update refresh token if provided
            if "refresh_token" in token_data:
                self._oauth_credentials["refresh_token"] = token_data["refresh_token"]

            # Update resource URL if provided
            if "resource_url" in token_data:
                self._oauth_credentials["resource_url"] = token_data["resource_url"]
                # Update the API base URL
                self.api_base_url = self._get_endpoint_url()

            # Save updated credentials back to file
            await self._save_oauth_credentials()  # type: ignore

            logger.info("Successfully refreshed Qwen OAuth token")
            return True

        except Exception as e:
            logger.error(f"Error refreshing Qwen OAuth token: {e}")
            return False

    async def _save_oauth_credentials(self) -> None:
        """Save OAuth credentials to the qwen-code CLI storage location"""
        try:
            # Path where qwen-code stores OAuth credentials
            home_dir = Path.home()
            creds_dir = home_dir / ".qwen"
            creds_path = creds_dir / "oauth_creds.json"

            # Create directory if it doesn't exist
            creds_dir.mkdir(parents=True, exist_ok=True)

            # Save credentials to file
            with open(creds_path, "w", encoding="utf-8") as f:
                json.dump(self._oauth_credentials, f, indent=2)

            logger.info(f"Saved Qwen OAuth credentials to {creds_path}")

        except Exception as e:
            logger.error(f"Error saving Qwen OAuth credentials: {e}")
            # Don't raise the exception as this is part of token refresh flow

    def get_available_models(self) -> list[str]:
        """Return available Qwen models if functional"""
        return self.available_models if self.is_functional else []

    async def chat_completions(
        self,
        request_data: DomainModel | InternalDTO | dict[str, Any],
        processed_messages: list[Any],
        effective_model: str,
        **kwargs: Any,
    ) -> ResponseEnvelope | StreamingResponseEnvelope:
        # Normalize incoming request to ChatRequest
        request_data = legacy_to_domain_chat_request(request_data)
        request_data = cast(ChatRequest, request_data)
        """Handle chat completions using Qwen OAuth API.

        This overrides the parent class method to handle OAuth token refresh
        before making API requests.
        """
        try:
            # Refresh token if needed
            if not await self._refresh_token_if_needed():
                raise HTTPException(
                    status_code=401,
                    detail="Failed to refresh Qwen OAuth token. Please re-authenticate using qwen-code CLI.",
                )

            # Use the effective model (strip qwen-oauth: prefix if present)
            model_name = effective_model
            if model_name.startswith("qwen-oauth:"):
                model_name = model_name[11:]  # Remove "qwen-oauth:" prefix

            # Create a modified request_data with the correct model name.
            # Use model_copy(update=...) to avoid mutating frozen ValueObject instances.
            try:
                modified_request = request_data.model_copy(update={"model": model_name})
            except Exception:
                # Fallback: build a new ChatRequest dict
                modified_request = ChatRequest(
                    model=model_name,
                    messages=request_data.messages,
                    temperature=getattr(request_data, "temperature", None),
                    top_p=getattr(request_data, "top_p", None),
                    max_tokens=getattr(request_data, "max_tokens", None),
                    stream=getattr(request_data, "stream", None),
                    tools=getattr(request_data, "tools", None),
                    tool_choice=getattr(request_data, "tool_choice", None),
                    session_id=getattr(request_data, "session_id", None),
                    extra_body=getattr(request_data, "extra_body", None),
                )

            # Call the parent class method to handle the actual API request
            return await super().chat_completions(
                request_data=modified_request,
                processed_messages=processed_messages,
                effective_model=model_name,
                **kwargs,
            )

        except HTTPException:
            # Re-raise HTTP exceptions directly
            raise
        except (AuthenticationError, BackendError, ServiceUnavailableError):
            # Re-raise domain exceptions
            raise
        except Exception as e:
            # Convert other exceptions to BackendError
            logger.error(f"Error in Qwen OAuth chat_completions: {e}")

            # Create a response payload envelope as callers/tests expect
            payload = {
                "id": f"chatcmpl-qwen-{secrets.token_hex(8)}",
                "object": "chat.completion",
                "created": int(asyncio.get_event_loop().time()),
                "model": effective_model,
                "choices": [
                    {
                        "index": 0,
                        "message": {"role": "assistant", "content": f"Error: {e!s}"},
                        "finish_reason": "stop",
                    }
                ],
                "usage": {
                    "prompt_tokens": 0,
                    "completion_tokens": 0,
                    "total_tokens": 0,
                },
            }
            return ResponseEnvelope(
                content=payload, headers={"content-type": "application/json"}
            )


backend_registry.register_backend("qwen-oauth", QwenOAuthConnector)
