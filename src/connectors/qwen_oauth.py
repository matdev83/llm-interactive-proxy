"""
Qwen OAuth connector that uses refresh_token from qwen-cli oauth_creds.json file
"""

import asyncio
import contextlib
import json
import logging
import time
from concurrent.futures import Future
from pathlib import Path
from typing import TYPE_CHECKING, Any

import httpx
from fastapi import HTTPException
from watchdog.events import FileSystemEventHandler
from watchdog.observers import Observer

if TYPE_CHECKING:
    from watchdog.observers.api import BaseObserver

from src.core.adapters.api_adapters import dict_to_domain_chat_request
from src.core.common.exceptions import (
    AuthenticationError,
    BackendError,
    ServiceUnavailableError,
)
from src.core.config.app_config import AppConfig
from src.core.domain.responses import ResponseEnvelope, StreamingResponseEnvelope
from src.core.interfaces.configuration_interface import IAppIdentityConfig
from src.core.interfaces.model_bases import DomainModel, InternalDTO
from src.core.security.loop_prevention import ensure_loop_guard_header
from src.core.services.backend_registry import backend_registry

from .openai import OpenAIConnector

if TYPE_CHECKING:
    pass

    # No legacy ChatCompletionRequest here; connectors should use domain ChatRequest

logger = logging.getLogger(__name__)


class QwenCredentialsFileHandler(FileSystemEventHandler):
    """File system event handler for monitoring OAuth credentials file changes."""

    def __init__(self, connector: "QwenOAuthConnector"):
        """Initialize the file handler with reference to the connector.

        Args:
            connector: The QwenOAuthConnector instance to notify of file changes
        """
        super().__init__()
        self.connector = connector

    def on_modified(self, event):
        """Handle file modification events."""
        if not event.is_directory and event.src_path == str(
            self.connector._credentials_path
        ):
            if logger.isEnabledFor(logging.INFO):
                logger.info(f"OAuth credentials file modified: {event.src_path}")
            self.connector._schedule_credentials_reload()


class QwenOAuthConnector(OpenAIConnector):
    """Connector that uses refresh_token from qwen-cli oauth_creds.json file.

    This is a specialized OpenAI-compatible connector that reads the refresh_token
    from the qwen-cli generated oauth_creds.json file and uses it as the API key.
    """

    backend_type: str = "qwen-oauth"

    def __init__(
        self, client: httpx.AsyncClient, config: AppConfig
    ) -> None:  # Modified
        from src.core.services.translation_service import TranslationService

        super().__init__(client, config, translation_service=TranslationService())
        self.name = "qwen-oauth"
        self._default_endpoint = "https://dashscope.aliyuncs.com/compatible-mode/v1"
        self.api_base_url = self._default_endpoint
        self.is_functional = False
        self._oauth_credentials: dict[str, Any] | None = None
        self._credentials_path: Path | None = None
        self._last_modified: float = 0
        self._refresh_token: str | None = None
        self._token_refresh_lock = asyncio.Lock()  # Ensure only one refresh at a time
        self._file_observer: BaseObserver | None = None
        self._credential_validation_errors: list[str] = []
        self._initialization_failed = False
        self._last_validation_time = 0.0
        self._pending_reload_task: asyncio.Task[None] | Future[None] | None = None
        self._event_loop: asyncio.AbstractEventLoop | None = None

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

    def _validate_credentials_structure(
        self, credentials: dict[str, Any]
    ) -> tuple[bool, list[str]]:
        """Validate the structure and content of OAuth credentials.

        Args:
            credentials: The credentials dictionary to validate

        Returns:
            Tuple of (is_valid, list_of_errors)
        """
        errors = []

        # Check required fields
        required_fields = ["access_token", "refresh_token"]
        for field in required_fields:
            if field not in credentials:
                errors.append(f"Missing required field: {field}")
            elif not credentials[field] or not isinstance(credentials[field], str):
                errors.append(f"Invalid {field}: must be a non-empty string")

        # Check expiry date if present
        if "expiry_date" in credentials:
            expiry_date = credentials["expiry_date"]
            if not isinstance(expiry_date, int | float):
                errors.append(
                    "Invalid expiry_date: must be a number (timestamp in milliseconds)"
                )
            else:
                # Convert to seconds and check if expired
                expiry_date_s = float(expiry_date) / 1000.0
                current_time = time.time()
                if current_time >= expiry_date_s:
                    errors.append(
                        f"Token expired at {time.ctime(expiry_date_s)} (current time: {time.ctime(current_time)})"
                    )

        return len(errors) == 0, errors

    def _validate_credentials_file_exists(self) -> tuple[bool, list[str]]:
        """Validate that the OAuth credentials file exists and is readable.

        Returns:
            Tuple of (is_valid, list_of_errors)
        """
        errors = []

        home_dir = Path.home()
        creds_path = home_dir / ".qwen" / "oauth_creds.json"

        if not creds_path.exists():
            errors.append(f"OAuth credentials file not found at {creds_path}")
            return False, errors

        if not creds_path.is_file():
            errors.append(
                f"OAuth credentials path exists but is not a file: {creds_path}"
            )
            return False, errors

        try:
            with open(creds_path, encoding="utf-8") as f:
                credentials = json.load(f)

            # Validate the loaded credentials
            is_valid, validation_errors = self._validate_credentials_structure(
                credentials
            )
            errors.extend(validation_errors)

            return is_valid, errors

        except json.JSONDecodeError as e:
            errors.append(f"Invalid JSON in credentials file: {e}")
            return False, errors
        except PermissionError:
            errors.append(f"Permission denied reading credentials file: {creds_path}")
            return False, errors
        except Exception as e:
            errors.append(f"Unexpected error reading credentials file: {e}")
            return False, errors

    def get_validation_errors(self) -> list[str]:
        """Get the current list of credential validation errors.

        Returns:
            List of validation error messages
        """
        return self._credential_validation_errors.copy()

    def is_backend_functional(self) -> bool:
        """Check if the backend is functional and ready to handle requests.

        Returns:
            True if backend is functional, False otherwise
        """
        return (
            self.is_functional
            and not self._initialization_failed
            and len(self._credential_validation_errors) == 0
        )

    async def _handle_credentials_file_change(self) -> None:
        """Handle changes to the OAuth credentials file."""
        try:
            if logger.isEnabledFor(logging.INFO):
                logger.info(
                    "Detected OAuth credentials file change, attempting to reload..."
                )

            # Validate the file first
            is_valid, errors = self._validate_credentials_file_exists()

            if not is_valid:
                logger.warning(
                    f"Updated credentials file is invalid: {'; '.join(errors)}"
                )
                self._credential_validation_errors = errors
                self.is_functional = False
                return

            # File is valid, try to load it
            if await self._load_oauth_credentials():
                if logger.isEnabledFor(logging.INFO):
                    logger.info(
                        "Successfully reloaded OAuth credentials from updated file"
                    )
                self._credential_validation_errors = []
                self.is_functional = True
                self._last_validation_time = time.time()
            else:
                if logger.isEnabledFor(logging.ERROR):
                    logger.error("Failed to load updated OAuth credentials file")
                self.is_functional = False

        except Exception as e:
            if logger.isEnabledFor(logging.ERROR):
                logger.error(f"Error handling credentials file change: {e}")
            self.is_functional = False

    def _start_file_watching(self) -> None:
        """Start watching the OAuth credentials file for changes."""
        try:
            if self._credentials_path and self._credentials_path.exists():
                self._file_observer = Observer()
                handler = QwenCredentialsFileHandler(self)
                # Watch the directory containing the credentials file
                watch_dir = self._credentials_path.parent
                self._file_observer.schedule(handler, str(watch_dir), recursive=False)
                self._file_observer.start()
                if logger.isEnabledFor(logging.INFO):
                    logger.info(
                        f"Started watching OAuth credentials file: {self._credentials_path}"
                    )
        except Exception as e:
            if logger.isEnabledFor(logging.WARNING):
                logger.warning(
                    f"Failed to start file watching for OAuth credentials: {e}"
                )

    def _stop_file_watching(self) -> None:
        """Stop watching the OAuth credentials file."""
        if self._file_observer:
            try:
                self._file_observer.stop()
                # Only join if the thread has been started to avoid "cannot join thread before it is started" error
                if (
                    hasattr(self._file_observer, "is_alive")
                    and self._file_observer.is_alive()
                ):
                    self._file_observer.join(timeout=5.0)
                elif not hasattr(self._file_observer, "is_alive"):
                    # Fallback: always try to join if we can't check if it's alive
                    self._file_observer.join(timeout=5.0)
                logger.info("Stopped watching OAuth credentials file")
            except Exception as e:
                if logger.isEnabledFor(logging.WARNING):
                    logger.warning(f"Error stopping file watcher: {e}")
            finally:
                self._file_observer = None

    async def _validate_runtime_credentials(self) -> bool:
        """Validate credentials during runtime and handle expiry."""
        current_time = time.time()

        # Don't validate too frequently (every 30 seconds at most)
        if current_time - self._last_validation_time < 30:
            return self.is_backend_functional()

        self._last_validation_time = current_time

        # Check if token is expired
        if self._is_token_expired():
            if logger.isEnabledFor(logging.INFO):
                logger.info(
                    "Access token expired during runtime, attempting to reload credentials..."
                )

            # Try to reload credentials file first
            if await self._load_oauth_credentials():
                # Check if the reloaded token is still expired
                if self._is_token_expired():
                    logger.warning(
                        "Reloaded token is still expired, marking backend as non-functional"
                    )
                    self._credential_validation_errors = [
                        "Token expired and no valid replacement found"
                    ]
                    self.is_functional = False
                    return False
                else:
                    logger.info("Successfully reloaded valid credentials")
                    self._credential_validation_errors = []
                    self.is_functional = True
                    return True
            else:
                logger.error(
                    "Failed to reload credentials, marking backend as non-functional"
                )
                self._credential_validation_errors = [
                    "Failed to reload expired credentials"
                ]
                self.is_functional = False
                return False

        # Credentials are present and not expired; allow proceeding
        return True

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
                if logger.isEnabledFor(logging.ERROR):
                    logger.error(f"Network error during token refresh: {e}")
                return False
            except json.JSONDecodeError as e:
                if logger.isEnabledFor(logging.ERROR):
                    logger.error(f"Malformed JSON response during token refresh: {e}")
                return False
            except Exception as e:
                if logger.isEnabledFor(logging.ERROR):
                    logger.error(
                        f"An unexpected error occurred during token refresh: {e}"
                    )
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
            if logger.isEnabledFor(logging.ERROR):
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
            if logger.isEnabledFor(logging.ERROR):
                logger.error(f"Error decoding Qwen OAuth credentials JSON: {e}")
            return False
        except Exception as e:
            if logger.isEnabledFor(logging.ERROR):
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
        return ensure_loop_guard_header(
            {
            "Authorization": f"Bearer {self._oauth_credentials['access_token']}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }
        )

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
            if logger.isEnabledFor(logging.ERROR):
                logger.error(f"Qwen OAuth health check failed - unexpected error: {e}")
            return False

    async def initialize(self, **kwargs: Any) -> None:
        """Initialize backend with comprehensive validation and error handling."""
        logger.info("Initializing Qwen OAuth backend with enhanced validation...")

        # Reset state
        try:
            self._event_loop = asyncio.get_running_loop()
        except RuntimeError:
            self._event_loop = None
        self._initialization_failed = False
        self._credential_validation_errors = []
        self.is_functional = False

        try:
            # Step 1: Load credentials (tests will mock this; production path can still validate file later)
            logger.info("Step 1: Loading OAuth credentials...")
            if not await self._load_oauth_credentials():
                error_msg = (
                    "Failed to load OAuth credentials despite validation passing"
                )
                logger.error(error_msg)
                # Try to enrich error details from file validation (best-effort)
                is_valid, errors = self._validate_credentials_file_exists()
                self._credential_validation_errors = errors or [error_msg]
                self._initialization_failed = True
                self.is_functional = False
                return

            logger.info("OAuth credentials loaded successfully")

            # Step 3: Validate loaded credentials structure
            if self._oauth_credentials:
                is_valid, validation_errors = self._validate_credentials_structure(
                    self._oauth_credentials
                )
                if not is_valid:
                    logger.error(
                        f"Loaded credentials are invalid: {'; '.join(validation_errors)}"
                    )
                    self._credential_validation_errors = validation_errors
                    self._initialization_failed = True
                    self.is_functional = False
                    return

            # Step 4: Attempt token refresh if needed
            logger.info("Step 3: Checking token expiry and refreshing if needed...")
            if not await self._refresh_token_if_needed():
                error_msg = (
                    "Failed to refresh expired OAuth token during initialization"
                )
                logger.error(error_msg)
                self._credential_validation_errors = [error_msg]
                self._initialization_failed = True
                self.is_functional = False
                return

            logger.info("Token refresh check completed successfully")

            # Step 5: Set up available models
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

            # Step 6: Start file watching
            logger.info("Step 4: Starting OAuth credentials file monitoring...")
            self._start_file_watching()

            # Step 7: Mark as functional
            self.is_functional = True
            self._last_validation_time = time.time()
            logger.info(
                f"Qwen OAuth backend successfully initialized with {len(self.available_models)} models, "
                f"file monitoring enabled, and health check enabled."
            )

        except Exception as e:
            error_msg = (
                f"Unexpected error during Qwen OAuth backend initialization: {e}"
            )
            logger.error(error_msg)
            self._credential_validation_errors = [error_msg]
            self._initialization_failed = True
            self.is_functional = False

    def _get_endpoint_url(self) -> str:
        """Get the API endpoint URL."""
        # Use resource_url from credentials if available, otherwise default
        if self._oauth_credentials and self._oauth_credentials.get("resource_url"):
            return f"https://{self._oauth_credentials['resource_url']}/v1"
        return self._default_endpoint

    def get_available_models(self) -> list[str]:
        """Return available Qwen models if functional."""
        return self.available_models if self.is_functional else []

    def _schedule_credentials_reload(self) -> None:
        """Schedule a reload of OAuth credentials on the active event loop."""

        async def _reload() -> None:
            await self._handle_credentials_file_change()

        try:
            current_loop = asyncio.get_running_loop()
        except RuntimeError:
            current_loop = None

        target_loop = None
        if current_loop and current_loop.is_running():
            target_loop = current_loop
        elif self._event_loop and self._event_loop.is_running():
            target_loop = self._event_loop

        if target_loop is None:
            if logger.isEnabledFor(logging.WARNING):
                logger.warning(
                    "No running event loop available to schedule Qwen OAuth credential reload"
                )
            return

        if target_loop is current_loop:
            self._pending_reload_task = target_loop.create_task(_reload())
        else:
            self._pending_reload_task = asyncio.run_coroutine_threadsafe(
                _reload(), target_loop
            )

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

        This overrides the parent class method to ensure credentials are valid before API call.
        """
        # First, validate runtime credentials
        if not await self._validate_runtime_credentials():
            error_details = (
                "; ".join(self._credential_validation_errors)
                if self._credential_validation_errors
                else "Backend is not functional"
            )
            raise HTTPException(
                status_code=502,
                detail=f"No valid OAuth credentials found for backend qwen-oauth: {error_details}",
            )

        # Ensure token is refreshed before making the API call
        if not await self._refresh_token_if_needed():
            raise HTTPException(
                status_code=401,
                detail="Failed to refresh Qwen OAuth token",
            )

        try:
            # Use the effective model (strip qwen-oauth: prefix if present)
            model_name = effective_model
            if model_name.startswith("qwen-oauth:"):
                model_name = model_name[11:]  # Remove "qwen-oauth:" prefix

            # Convert request_data to ChatRequest using the adapter
            if not isinstance(request_data, dict):
                if hasattr(request_data, "model_dump"):
                    request_data = request_data.model_dump()
                else:
                    raise TypeError(
                        f"Unsupported request_data type: {type(request_data).__name__}"
                    )
            chat_request = dict_to_domain_chat_request(request_data)

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

            # If streaming, leave content as-is; central pipeline will handle repairs

            return response_envelope

        except HTTPException:
            # Re-raise HTTP exceptions directly
            raise
        except (AuthenticationError, BackendError, ServiceUnavailableError):
            # Re-raise domain exceptions
            raise
        except Exception as e:
            # Convert other exceptions to BackendError
            if logger.isEnabledFor(logging.ERROR):
                logger.error(f"Error in Qwen OAuth chat_completions: {e}")
            raise BackendError(
                message=f"Qwen OAuth chat completion failed: {e!s}"
            ) from e

    def __del__(self) -> None:
        """Cleanup method to stop file watching when connector is destroyed."""
        with contextlib.suppress(Exception):
            self._stop_file_watching()


backend_registry.register_backend("qwen-oauth", QwenOAuthConnector)
