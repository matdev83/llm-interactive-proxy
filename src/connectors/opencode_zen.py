"""
OpenCode Zen backend connector.

Connects to OpenCode's Zen gateway using OAuth credentials stored by the opencode CLI.
Credentials are read from the auth.json file created by 'opencode auth login'.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import sys
import time
from collections.abc import AsyncGenerator
from pathlib import Path
from typing import TYPE_CHECKING, Any

import httpx
from fastapi import HTTPException

from src.connectors.openai import OpenAIConnector
from src.core.common.exceptions import AuthenticationError, BackendError
from src.core.config.app_config import AppConfig
from src.core.domain.responses import ResponseEnvelope, StreamingResponseEnvelope
from src.core.interfaces.configuration_interface import IAppIdentityConfig
from src.core.interfaces.model_bases import DomainModel, InternalDTO
from src.core.security.loop_prevention import ensure_loop_guard_header
from src.core.services.backend_registry import backend_registry

if TYPE_CHECKING:
    from src.core.services.translation_service import TranslationService

logger = logging.getLogger(__name__)

OPENCODE_ZEN_VENDOR_PREFIX = "opencode-zen"
TOKEN_EXPIRY_BUFFER_SECONDS = 60.0


class OpencodeZenConnector(OpenAIConnector):
    """Connector that routes requests through OpenCode's Zen gateway.

    This connector reads OAuth credentials from the opencode CLI's auth.json file
    and uses them to authenticate with the Zen gateway API.
    """

    backend_type: str = "opencode-zen"
    VENDOR_PREFIX: str = "opencode-zen"

    def __init__(
        self,
        client: httpx.AsyncClient,
        config: AppConfig,
        translation_service: TranslationService | None = None,
    ) -> None:
        super().__init__(client, config, translation_service=translation_service)
        self.name = "opencode-zen"
        self._default_endpoint = "https://api.gateway.opencode.ai/v1"
        self.is_functional = False
        self._oauth_credentials: dict[str, Any] | None = None
        self._credentials_path: Path | None = None
        self._last_modified: float = 0
        self._token_lock = asyncio.Lock()
        self._credential_validation_errors: list[str] = []
        self._provider_key = "opencode"

    def _get_default_credentials_path(self) -> Path:
        """Determine the credentials file path in an OS-agnostic way.

        Platform-specific behavior:
        - Windows: %LOCALAPPDATA%\\opencode\\auth.json, fallback to ~/.local/share/opencode/auth.json
        - Linux: $XDG_DATA_HOME/opencode/auth.json or ~/.local/share/opencode/auth.json
        - macOS: $XDG_DATA_HOME/opencode/auth.json or ~/.local/share/opencode/auth.json

        Returns:
            Path object pointing to the credentials file
        """
        if sys.platform == "win32" or os.name == "nt":
            localappdata = os.environ.get("LOCALAPPDATA")

            paths_to_check = []
            if localappdata:
                paths_to_check.append(Path(localappdata) / "opencode" / "auth.json")

            # Add unix-style XDG fallback for tools running in mixed environments on Windows
            paths_to_check.append(
                Path.home() / ".local" / "share" / "opencode" / "auth.json"
            )

            # Return the first one that exists
            for path in paths_to_check:
                if path.exists():
                    return path

            # If none exist, return the primary preferred path (LOCALAPPDATA) if available,
            # otherwise fallback to home-based structure for consistency in error reporting.
            return (
                paths_to_check[0]
                if paths_to_check
                else Path.home() / "AppData" / "Local" / "opencode" / "auth.json"
            )

        xdg_data_home = os.environ.get("XDG_DATA_HOME")
        if xdg_data_home:
            return Path(xdg_data_home) / "opencode" / "auth.json"

        return Path.home() / ".local" / "share" / "opencode" / "auth.json"

    async def _load_oauth_credentials(self) -> bool:
        """Load OAuth credentials from auth.json file.

        Returns:
            True if credentials were loaded successfully, False otherwise.
        """
        try:
            if not self._credentials_path or not self._credentials_path.exists():
                logger.warning(
                    "OpenCode credentials not found at %s",
                    self._credentials_path,
                )
                return False

            try:
                current_mtime = self._credentials_path.stat().st_mtime
                if current_mtime == self._last_modified and self._oauth_credentials:
                    logger.debug(
                        "OpenCode credentials file not modified, using cached."
                    )
                    return True
                self._last_modified = current_mtime
            except OSError:
                pass

            with open(self._credentials_path, encoding="utf-8") as f:
                all_credentials = json.load(f)

            provider_creds = all_credentials.get(self._provider_key)
            if not provider_creds:
                logger.warning(
                    "No '%s' provider found in auth.json", self._provider_key
                )
                return False

            auth_type = provider_creds.get("type")
            if auth_type == "oauth":
                required_fields = ["access", "refresh", "expires"]
                for field in required_fields:
                    if field not in provider_creds:
                        logger.warning(
                            "Missing field '%s' in OpenCode credentials", field
                        )
                        return False
            elif auth_type == "api":
                if "key" not in provider_creds:
                    logger.warning("Missing 'key' field in OpenCode API credentials")
                    return False
                # Map API key to access token structure for uniform handling
                provider_creds["access"] = provider_creds["key"]
                # API keys don't expire
                provider_creds["expires"] = None
            else:
                logger.warning(
                    "OpenCode credentials type '%s' is not supported", auth_type
                )
                return False

            self._oauth_credentials = provider_creds
            logger.info(
                "Successfully loaded OpenCode credentials (type: %s)", auth_type
            )
            return True

        except json.JSONDecodeError as e:
            logger.error("Invalid JSON in OpenCode credentials: %s", e)
            return False
        except Exception as e:
            logger.error("Error loading OpenCode credentials: %s", e)
            return False

    def _is_token_expired(
        self, buffer_seconds: float = TOKEN_EXPIRY_BUFFER_SECONDS
    ) -> bool:
        """Check if the current access token is expired or within buffer window.

        Args:
            buffer_seconds: Time buffer before actual expiry to consider token expired.

        Returns:
            True if token is expired or will expire within buffer, False otherwise.
        """
        if not self._oauth_credentials:
            return True

        expires = self._oauth_credentials.get("expires")
        if not isinstance(expires, int | float):
            return False

        if expires > 1e12:
            expires = expires / 1000.0

        return time.time() >= (expires - buffer_seconds)

    def get_headers(self, identity: IAppIdentityConfig | None = None) -> dict[str, str]:
        """Override to use OAuth access token for authentication.

        Args:
            identity: Optional app identity config (unused for this connector).

        Returns:
            Headers dict with Authorization, Content-Type, and Accept.

        Raises:
            AuthenticationError: If no valid access token is available.
        """
        if not self._oauth_credentials or not self._oauth_credentials.get("access"):
            raise AuthenticationError(
                message="No valid OpenCode OAuth access token available. "
                "Please run 'opencode auth login' to authenticate.",
                details={"backend": "opencode-zen"},
            )

        headers = {
            "Authorization": f"Bearer {self._oauth_credentials['access'].strip()}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }

        return ensure_loop_guard_header(headers)

    async def _perform_health_check(self) -> bool:
        """Validate credentials without making API calls.

        Returns:
            True if credentials are valid, False otherwise.
        """
        try:
            if not self._oauth_credentials:
                logger.warning("Health check failed - no OAuth credentials available")
                return False

            if not self._oauth_credentials.get("access"):
                logger.warning("Health check failed - no access token in credentials")
                return False

            if not self._oauth_credentials.get("refresh"):
                logger.warning("Health check failed - no refresh token in credentials")
                return False

            if self._is_token_expired(buffer_seconds=0):
                logger.warning("Health check failed - token is expired")
                return False

            logger.info(
                "OpenCode Zen health check passed - credentials are valid and not expired"
            )
            self._health_checked = True
            return True

        except Exception as e:
            logger.error("OpenCode Zen health check failed - unexpected error: %s", e)
            return False

    async def initialize(self, **kwargs: Any) -> None:
        """Initialize backend with credential loading and validation.

        Args:
            **kwargs: Optional configuration:
                - credentials_path: Custom path to auth.json
                - api_base_url: Custom API endpoint URL
                - enable_file_watching: Whether to watch for credential changes
        """
        logger.info("Initializing OpenCode Zen backend...")

        self._credential_validation_errors = []
        self.is_functional = False

        custom_path = kwargs.get("credentials_path") or os.getenv("OPENCODE_AUTH_PATH")
        self._credentials_path = (
            Path(custom_path).expanduser()
            if custom_path
            else self._get_default_credentials_path()
        )

        if not await self._load_oauth_credentials():
            self._credential_validation_errors.append(
                f"Failed to load credentials from {self._credentials_path}. "
                "Run 'opencode auth login' to authenticate."
            )
            return

        if self._is_token_expired(buffer_seconds=0):
            logger.warning("OpenCode OAuth token is expired")
            self._credential_validation_errors.append("OAuth token is expired")

        self.api_base_url = kwargs.get("api_base_url", self._default_endpoint)

        self.available_models = await self._fetch_available_models()

        self.is_functional = True
        logger.info(
            "OpenCode Zen backend initialized with %d models",
            len(self.available_models),
        )

    async def _fetch_available_models(self) -> list[str]:
        """Fetch available models from the backend API.

        Falls back to hardcoded list if API fetch fails.
        """
        try:
            headers = self.get_headers()
            url = f"{self.api_base_url}/models"

            logger.debug("Fetching available models from %s", url)
            response = await self.client.get(url, headers=headers, timeout=10.0)

            if response.status_code == 200:
                data = response.json()
                models = []
                # Handle standard OpenAI format: {"data": [{"id": "model-id", ...}]}
                if (
                    isinstance(data, dict)
                    and "data" in data
                    and isinstance(data["data"], list)
                ):
                    for model in data["data"]:
                        if isinstance(model, dict) and "id" in model:
                            models.append(model["id"])

                if models:
                    logger.info(
                        "Successfully fetched %d models from OpenCode API", len(models)
                    )
                    return models

            logger.warning(
                "Failed to fetch models from API (status: %s), using defaults. Response: %s",
                response.status_code,
                response.text[:200],
            )

        except Exception as e:
            logger.warning(
                "Error fetching models from API: %s, using defaults", e, exc_info=True
            )

        # Default fallback models
        return [
            "claude-opus-4-5",
            "claude-sonnet-4-5",
            "gpt-5.1",
            "gpt-5.1-codex",
            "gemini-3-pro",
        ]

    async def get_available_models_async(self) -> list[str]:
        """Async version of get_available_models to allow fetching from API if needed."""
        if not self.available_models:
            self.available_models = await self._fetch_available_models()

        return self.get_available_models()

    def get_available_models(self) -> list[str]:
        """Return available models with vendor prefix for unified model routing.

        Returns:
            List of available model names with 'opencode-zen:' vendor prefix.
        """
        if not self.is_functional:
            return []
        # Use ':' as separator per requirements, overriding standard '/' behavior
        return [f"{self.VENDOR_PREFIX}:{m}" for m in (self.available_models or [])]

    def get_validation_errors(self) -> list[str]:
        """Get the current list of credential validation errors.

        Returns:
            List of validation error messages.
        """
        return self._credential_validation_errors.copy()

    def is_backend_functional(self) -> bool:
        """Check if the backend is functional and ready to handle requests.

        Returns:
            True if backend is functional, False otherwise.
        """
        return self.is_functional and len(self._credential_validation_errors) == 0

    async def stream_completion(self, request: Any) -> AsyncGenerator[Any, None]:
        """Yield raw streaming chunks from the backend with 401 retry logic."""
        try:
            async for chunk in super().stream_completion(request):
                yield chunk
        except (HTTPException, AuthenticationError) as e:
            is_401 = False
            if (
                isinstance(e, HTTPException)
                and e.status_code == 401
                or isinstance(e, AuthenticationError)
            ):
                is_401 = True

            if is_401:
                token = (
                    self._oauth_credentials.get("access", "")
                    if self._oauth_credentials
                    else ""
                )
                masked_token = (
                    f"{token[:4]}...{token[-4:]}" if len(token) > 8 else "masked"
                )
                logger.warning(
                    f"Received 401 from OpenCode Zen backend during streaming. "
                    f"Token used: {masked_token}. "
                    "Reloading credentials and retrying..."
                )
                if await self._load_oauth_credentials():
                    # Retry the stream
                    async for chunk in super().stream_completion(request):
                        yield chunk
                else:
                    raise AuthenticationError(
                        "Failed to refresh credentials after 401 in stream"
                    ) from e
            else:
                raise e

    async def chat_completions(
        self,
        request_data: DomainModel | InternalDTO | dict[str, Any],
        processed_messages: list[Any],
        effective_model: str,
        identity: IAppIdentityConfig | None = None,
        **kwargs: Any,
    ) -> ResponseEnvelope | StreamingResponseEnvelope:
        """Handle chat completions with credential validation.

        Args:
            request_data: The chat request data.
            processed_messages: Pre-processed message list.
            effective_model: The model to use (may include vendor prefix).
            identity: Optional app identity config.
            **kwargs: Additional arguments passed to parent.

        Returns:
            Response envelope (streaming or non-streaming).

        Raises:
            BackendError: If backend is not functional.
            AuthenticationError: If credentials are invalid or expired.
        """
        if not self.is_functional:
            errors = (
                "; ".join(self._credential_validation_errors)
                or "Backend not initialized"
            )
            raise BackendError(
                message=f"OpenCode Zen backend is not functional: {errors}",
                backend_name="opencode-zen",
            )

        if self._is_token_expired():
            logger.info("Token expired, reloading credentials...")
            if not await self._load_oauth_credentials():
                raise AuthenticationError(
                    message="Failed to reload OpenCode credentials after token expiry",
                    details={"backend": "opencode-zen"},
                )
            if self._is_token_expired(buffer_seconds=0):
                raise AuthenticationError(
                    message="OpenCode OAuth token is expired. "
                    "Please run 'opencode auth login' to re-authenticate.",
                    details={"backend": "opencode-zen"},
                )

        model_name = effective_model
        if model_name.startswith("opencode-zen:"):
            model_name = model_name[len("opencode-zen:") :]
        elif model_name.startswith("opencode-zen/"):
            # Fallback for backward compatibility or accidental slash usage
            model_name = model_name[len("opencode-zen/") :]

        # Update request_data with the stripped model name to ensure it propagates to streaming logic
        # which might extract the model from request_data directly
        if hasattr(request_data, "model_copy") and callable(request_data.model_copy):
            # It's a Pydantic model, create a copy with updated field
            request_data = request_data.model_copy(update={"model": model_name})
        elif isinstance(request_data, dict):
            # It's a dict, update in place (or copy if preferred, but in-place is standard for dicts here)
            request_data["model"] = model_name

        try:
            return await super().chat_completions(
                request_data=request_data,
                processed_messages=processed_messages,
                effective_model=model_name,
                identity=identity,
                **kwargs,
            )
        except (HTTPException, AuthenticationError) as e:
            is_401 = False
            if (
                isinstance(e, HTTPException)
                and e.status_code == 401
                or isinstance(e, AuthenticationError)
            ):
                is_401 = True

            if is_401:
                logger.warning(
                    "Received 401 from OpenCode Zen backend. Reloading credentials and retrying..."
                )
                # Reload credentials (force check)
                if await self._load_oauth_credentials():
                    # Retry once
                    return await super().chat_completions(
                        request_data=request_data,
                        processed_messages=processed_messages,
                        effective_model=model_name,
                        identity=identity,
                        **kwargs,
                    )
                else:
                    raise AuthenticationError(
                        "Failed to refresh credentials after 401"
                    ) from e

            # Re-raise other errors
            raise e


backend_registry.register_backend("opencode-zen", OpencodeZenConnector)
