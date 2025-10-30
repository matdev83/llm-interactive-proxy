"""
Qwen OAuth connector that uses refresh_token from qwen-cli oauth_creds.json file
"""

import asyncio
import contextlib
import json
import logging
import shutil
import subprocess
import time
from concurrent.futures import Future
from pathlib import Path
from typing import TYPE_CHECKING, Any

import httpx
from fastapi import HTTPException

if TYPE_CHECKING:
    from watchdog.observers.api import BaseObserver

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
    from src.core.services.translation_service import TranslationService

    # No legacy ChatCompletionRequest here; connectors should use domain ChatRequest

logger = logging.getLogger(__name__)


TOKEN_EXPIRY_BUFFER_SECONDS = 30.0
CLI_REFRESH_THRESHOLD_SECONDS = 120.0
CLI_REFRESH_COOLDOWN_SECONDS = 30.0
TOKEN_REFRESH_MAX_WAIT_SECONDS = 30.0
TOKEN_REFRESH_POLL_INTERVAL_SECONDS = 1.0
CLI_REFRESH_COMMAND = [
    "qwen",
    "chat",
    "--model",
    "qwen-turbo",
    "--prompt",
    "Hi. What's up?",
]


def _create_file_handler(connector: "QwenOAuthConnector"):
    """Create a file handler that inherits from FileSystemEventHandler."""
    from watchdog.events import FileSystemEventHandler

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
                logger.info(f"OAuth credentials file modified: {event.src_path}")
                self.connector._schedule_credentials_reload()

    return QwenCredentialsFileHandler(connector)


class QwenOAuthConnector(OpenAIConnector):
    """Connector that uses refresh_token from qwen-cli oauth_creds.json file.

    This is a specialized OpenAI-compatible connector that reads the refresh_token
    from the qwen-cli generated oauth_creds.json file and uses it as the API key.
    """

    backend_type: str = "qwen-oauth"

    def __init__(
        self,
        client: httpx.AsyncClient,
        config: AppConfig,
        translation_service: "TranslationService | None" = None,
    ) -> None:
        super().__init__(client, config, translation_service=translation_service)
        self.name = "qwen-oauth"
        self._default_endpoint = "https://portal.qwen.ai/v1"
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
        self._last_cli_refresh_attempt = 0.0
        self._cli_refresh_process: subprocess.Popen[bytes] | None = None
        self._main_loop: asyncio.AbstractEventLoop | None = None

    @property
    def api_base_url(self) -> str:
        """Return the Qwen API endpoint."""
        # Use resource_url from credentials if available, otherwise default
        if self._oauth_credentials and self._oauth_credentials.get("resource_url"):
            return f"https://{self._oauth_credentials['resource_url']}/v1"
        return self._default_endpoint

    @api_base_url.setter
    def api_base_url(self, value: str) -> None:
        """Setting the base URL is not supported for QwenOAuthConnector; it is derived dynamically."""
        logger.warning(
            "Attempt to set api_base_url on QwenOAuthConnector ignored. URL is derived from credentials."
        )

    def _is_token_expired(
        self, buffer_seconds: float = TOKEN_EXPIRY_BUFFER_SECONDS
    ) -> bool:
        """Check if the current access token is expired or within buffer window."""
        if not self._oauth_credentials:
            return True

        seconds_remaining = self._seconds_until_token_expiry()
        if seconds_remaining is None:
            return False

        return seconds_remaining <= buffer_seconds

    def _get_refresh_token(self) -> str | None:
        """Get refresh token, either from credentials or cached value."""
        if self._refresh_token:
            return self._refresh_token

        if self._oauth_credentials and "refresh_token" in self._oauth_credentials:
            self._refresh_token = self._oauth_credentials["refresh_token"]
            return self._refresh_token

        return None

    def _seconds_until_token_expiry(self) -> float | None:
        """Return seconds remaining before token expiry, or None if unknown."""
        if not self._oauth_credentials:
            return None

        expiry_value = self._oauth_credentials.get("expiry_date")
        if not isinstance(expiry_value, int | float):
            return None

        expiry_seconds = float(expiry_value) / 1000.0
        return expiry_seconds - time.time()

    def _should_trigger_cli_refresh(self) -> bool:
        """Determine whether we should proactively trigger CLI token refresh."""
        if not self._oauth_credentials:
            return True

        seconds_remaining = self._seconds_until_token_expiry()
        if seconds_remaining is None:
            return False

        if seconds_remaining > CLI_REFRESH_THRESHOLD_SECONDS:
            return False

        now = time.time()
        if (now - self._last_cli_refresh_attempt) < CLI_REFRESH_COOLDOWN_SECONDS:
            return False

        return not (
            self._cli_refresh_process and self._cli_refresh_process.poll() is None
        )

    def _launch_cli_refresh_process(self) -> None:
        """Launch qwen CLI command to refresh the OAuth token in background."""
        now = time.time()

        if (now - self._last_cli_refresh_attempt) < CLI_REFRESH_COOLDOWN_SECONDS:
            return

        if self._cli_refresh_process and self._cli_refresh_process.poll() is None:
            return

        try:
            command = list(CLI_REFRESH_COMMAND)
            executable = shutil.which(command[0])
            if executable:
                command[0] = executable
            else:
                raise FileNotFoundError(command[0])

            self._cli_refresh_process = subprocess.Popen(  # - intended CLI call
                command,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            self._last_cli_refresh_attempt = now
            logger.info("Triggered Qwen CLI background refresh process")
        except FileNotFoundError:
            self._last_cli_refresh_attempt = now
            logger.error(
                "Qwen CLI binary not found; cannot refresh OAuth token automatically."
            )
        except Exception as exc:  # pragma: no cover - defensive logging
            self._last_cli_refresh_attempt = now
            logger.error(
                "Failed to launch Qwen CLI for token refresh: %s",
                exc,
                exc_info=True,
            )

    async def _poll_for_new_token(self, max_wait_seconds: float | None = None) -> bool:
        """Poll the credential file for an updated token after CLI refresh."""
        if not self._is_token_expired():
            return True

        wait_window = (
            TOKEN_REFRESH_MAX_WAIT_SECONDS
            if max_wait_seconds is None
            else max_wait_seconds
        )
        if wait_window <= 0:
            return not self._is_token_expired()

        deadline = time.time() + wait_window
        attempts = 0

        while time.time() < deadline:
            remaining = deadline - time.time()
            sleep_for = min(TOKEN_REFRESH_POLL_INTERVAL_SECONDS, remaining)
            if sleep_for > 0:
                await asyncio.sleep(sleep_for)
            attempts += 1
            loaded = await self._load_oauth_credentials()
            if loaded and not self._is_token_expired():
                logger.debug(
                    "Qwen OAuth token refresh succeeded after %d poll attempts",
                    attempts,
                )
                return True

        loaded = await self._load_oauth_credentials()
        if loaded and not self._is_token_expired():
            logger.debug(
                "Qwen OAuth token refresh finalized after max wait window (%s seconds)",
                wait_window,
            )
            return True

        return not self._is_token_expired()

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
                logger.info("Successfully reloaded OAuth credentials from updated file")
                self._credential_validation_errors = []
                self.is_functional = True
                self._last_validation_time = time.time()
            else:
                logger.error("Failed to load updated OAuth credentials file")
                self.is_functional = False

        except Exception as e:
            logger.error(f"Error handling credentials file change: {e}")
            self.is_functional = False

    def _start_file_watching(self) -> None:
        """Start watching the OAuth credentials file for changes."""
        try:
            if self._credentials_path and self._credentials_path.exists():
                # Lazy import watchdog components
                from watchdog.observers import Observer

                self._file_observer = Observer()
                handler = _create_file_handler(self)
                # Watch the directory containing the credentials file
                watch_dir = self._credentials_path.parent
                self._file_observer.schedule(handler, str(watch_dir), recursive=False)
                self._file_observer.start()
                logger.info(
                    f"Started watching OAuth credentials file: {self._credentials_path}"
                )
        except Exception as e:
            logger.warning(f"Failed to start file watching for OAuth credentials: {e}")

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
        """Ensure a valid access token is available, refreshing when necessary."""
        if not self._oauth_credentials:
            await self._load_oauth_credentials()

        expired = self._is_token_expired()
        near_expiry = self._should_trigger_cli_refresh()

        if not expired and not near_expiry:
            return True

        async with self._token_refresh_lock:
            credentials_missing = not self._oauth_credentials
            if credentials_missing:
                await self._load_oauth_credentials()
                credentials_missing = not self._oauth_credentials

            if credentials_missing:
                # Without credentials we cannot assess expiry accurately; treat as expired to
                # leverage the existing CLI refresh pathway instead of failing immediately.
                expired = True
                near_expiry = True
            else:
                expired = self._is_token_expired()
                near_expiry = self._should_trigger_cli_refresh()

            # If token is not expired but nearing expiry, trigger CLI refresh in background
            if not expired and near_expiry:
                self._launch_cli_refresh_process()
                return True

            # If token is expired (or credentials missing), prefer CLI-based refresh first
            if expired:
                self._launch_cli_refresh_process()
                # Wait briefly for refreshed token to appear via credentials file
                if await self._poll_for_new_token():
                    # Ensure in-memory credentials are reloaded after successful poll
                    with contextlib.suppress(Exception):
                        await self._load_oauth_credentials()
                    return True
                return False
                # If CLI did not provide a new token, do not fall back to endpoint here.
                # Returning False aligns with tests and avoids unintended network calls.

            # Not expired and not near expiry covered above; default allow
            return True

    async def _refresh_token_via_endpoint(self) -> bool:
        """Attempt to refresh the access token using Qwen's OAuth endpoint.

        Returns:
            True if the token was refreshed and credentials updated; False otherwise.
        """
        refresh_token = self._get_refresh_token()
        if not refresh_token:
            return False

        url = "https://chat.qwen.ai/api/v1/oauth2/token"
        payload = {"grant_type": "refresh_token", "refresh_token": refresh_token}

        try:
            response = await self.client.post(url, json=payload)
        except httpx.RequestError:
            return False

        # Honor HTTP errors
        try:
            response.raise_for_status()
        except httpx.HTTPStatusError:
            return False

        # Parse JSON body
        try:
            data = response.json()
        except Exception:
            return False

        new_access_token = data.get("access_token")
        new_refresh_token = data.get("refresh_token") or refresh_token
        expires_in = data.get("expires_in")
        resource_url = data.get("resource_url")

        if not new_access_token or not isinstance(expires_in, int | float):
            return False

        # Compute new expiry timestamp in ms
        new_expiry_ms = int((time.time() + float(expires_in)) * 1000.0)

        # Update in-memory credentials without mutating on failure paths
        updated_credentials = dict(self._oauth_credentials or {})
        updated_credentials.update(
            {
                "access_token": str(new_access_token),
                "refresh_token": str(new_refresh_token),
                "expiry_date": new_expiry_ms,
            }
        )
        if resource_url:
            updated_credentials["resource_url"] = str(resource_url)

        # Apply updates
        self._oauth_credentials = updated_credentials
        # Update base URL if provided
        if resource_url:
            self.api_base_url = f"https://{resource_url}/v1"

        # Persist credentials best-effort
        with contextlib.suppress(Exception):
            await self._save_oauth_credentials(updated_credentials)

        return True

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

            # Use the DashScope API endpoint for all requests
            logger.info(
                f"Qwen OAuth credentials loaded. Using fixed API base URL: {self._default_endpoint}"
            )

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
        return ensure_loop_guard_header(
            {
                "Authorization": f"Bearer {self._oauth_credentials['access_token']}",
                "Content-Type": "application/json",
                "Accept": "application/json",
            }
        )

    async def _perform_health_check(self) -> bool:
        """Override parent health check to validate credentials without API calls."""
        try:
            # Check if we have valid OAuth credentials
            if not self._oauth_credentials:
                logger.warning("Health check failed - no OAuth credentials available")
                return False

            if not self._oauth_credentials.get("access_token"):
                logger.warning("Health check failed - no access token in credentials")
                return False

            if not self._oauth_credentials.get("refresh_token"):
                logger.warning("Health check failed - no refresh token in credentials")
                return False

            # Check if token is expired
            if self._is_token_expired():
                logger.warning("Health check failed - token is expired")
                return False

            # For portal.qwen.ai, the /models endpoint returns 404, but chat/completions work
            # So we'll validate credentials locally rather than making API calls
            logger.info(
                "Qwen OAuth health check passed - credentials are valid and not expired"
            )
            self._health_checked = True
            return True

        except Exception as e:
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
                # Tolerant startup behavior: degrade instead of outright failure
                pending_msg = (
                    "OAuth token refresh pending; background refresh was triggered"
                )
                logger.error(
                    "Failed to refresh expired OAuth token during initialization"
                )
                self._credential_validation_errors = [pending_msg]
                self._initialization_failed = False
                self.is_functional = False
                # Do not raise; allow app to start in degraded mode
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
        # Use the default Qwen API endpoint always, as the resource_url from credentials
        # may be incorrect for API calls (it's likely for portal access only)
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

    async def _handle_streaming_response(
        self,
        url: str,
        payload: dict[str, Any],
        headers: dict[str, str] | None,
        session_id: str,
        stream_format: str,
    ) -> Any:
        """Override parent to add chunk deduplication for Qwen API bug.

        The Qwen API sometimes sends duplicate SSE chunks with identical content,
        causing text repetition in the client (e.g., "NowNowNow" instead of "Now").
        This method wraps the parent's streaming response to deduplicate chunks.
        """
        import hashlib
        from collections import deque

        # Get the parent's streaming handle
        stream_handle = await super()._handle_streaming_response(
            url, payload, headers, session_id, stream_format
        )

        # Wrap the iterator with deduplication logic
        original_iterator = stream_handle.iterator

        async def deduplicated_iterator():
            """Deduplicate streaming chunks based on content hash."""
            # Track recent chunk hashes to detect duplicates
            # Use a sliding window of last N hashes to avoid memory growth
            recent_hashes: deque[str] = deque(maxlen=10)

            async for chunk in original_iterator:
                # Extract content for hashing
                content = chunk.content if hasattr(chunk, "content") else chunk

                # Compute hash of the chunk content
                if isinstance(content, dict):
                    # For dict chunks, hash the JSON representation
                    # Sort keys to ensure consistent hashing regardless of key order
                    import json

                    content_str = json.dumps(content, sort_keys=True)
                    chunk_hash = hashlib.md5(
                        content_str.encode(), usedforsecurity=False
                    ).hexdigest()
                elif isinstance(content, str):
                    chunk_hash = hashlib.md5(
                        content.encode(), usedforsecurity=False
                    ).hexdigest()
                elif isinstance(content, bytes):
                    chunk_hash = hashlib.md5(content, usedforsecurity=False).hexdigest()
                else:
                    chunk_hash = hashlib.md5(
                        str(content).encode(), usedforsecurity=False
                    ).hexdigest()

                # Check if this chunk is a duplicate of a recent chunk
                if chunk_hash in recent_hashes:
                    logger.debug(
                        f"Qwen OAuth: Skipping duplicate chunk (hash: {chunk_hash[:8]}...)"
                    )
                    continue

                # Add to recent hashes and yield the chunk
                recent_hashes.append(chunk_hash)
                yield chunk

        # Return a new handle with the deduplicated iterator
        from src.core.domain.responses import StreamingResponseHandle

        return StreamingResponseHandle(
            iterator=deduplicated_iterator(),
            cancel_callback=stream_handle.cancel_callback,
            headers=(
                stream_handle.headers if hasattr(stream_handle, "headers") else None
            ),
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
        # Ensure token is refreshed before making the API call
        if not await self._refresh_token_if_needed():
            raise HTTPException(
                status_code=401,
                detail="Failed to refresh Qwen OAuth token",
            )

        # Validate runtime credentials and backend functionality
        if not await self._validate_runtime_credentials():
            # Check if we have specific validation errors
            if self._credential_validation_errors:
                error_detail = f"No valid OAuth credentials found for backend qwen-oauth: {'; '.join(self._credential_validation_errors)}"
            else:
                error_detail = "No valid OAuth credentials found for backend qwen-oauth: Backend is not functional"

            raise HTTPException(
                status_code=502,
                detail=error_detail,
            )

        try:
            # Use the effective model and properly extract just the model name part
            # Strip any backend prefix (like "qwen-oauth:", "gemini-cli-oauth-personal:", etc.)
            model_name = effective_model
            if ":" in model_name:
                # Extract just the model name part after the last colon
                model_name = model_name.split(":")[-1]

            # Further clean up the model name to remove any prefixes like "models/"
            if model_name.startswith("models/"):
                model_name = model_name[7:]  # Remove "models/" prefix

            # Additional safety check: if the model name doesn't look like a Qwen model,
            # fall back to the default model to prevent API errors
            valid_qwen_models = {
                "qwen3-coder-plus",
                "qwen3-coder-flash",
                "qwen-turbo",
                "qwen-plus",
                "qwen-max",
                "qwen2.5-72b-instruct",
                "qwen2.5-32b-instruct",
                "qwen2.5-14b-instruct",
                "qwen2.5-7b-instruct",
                "qwen2.5-3b-instruct",
                "qwen2.5-1.5b-instruct",
                "qwen2.5-0.5b-instruct",
            }

            # If the model name is not in our valid list, try to map common names or default
            if model_name not in valid_qwen_models:
                # Map common model name patterns to Qwen equivalents
                if "qwen" in model_name.lower():
                    # If it contains qwen, it might be a valid qwen model
                    pass  # Allow it through
                elif "turbo" in model_name.lower():
                    model_name = "qwen-turbo"
                elif "plus" in model_name.lower():
                    model_name = "qwen-plus"
                elif "max" in model_name.lower():
                    model_name = "qwen-max"
                else:
                    # Default to a known working model
                    model_name = "qwen-turbo"
                    logger.warning(
                        f"Unknown model '{effective_model}' mapped to '{model_name}' for Qwen OAuth"
                    )

            # Call the parent class method directly - it will handle the model override correctly
            # The parent OpenAIConnector.chat_completions method uses the effective_model parameter
            # to override the model in the payload, so we don't need to modify request_data
            from src.connectors.openai import OpenAIConnector

            # DEBUG: Log what we're about to do
            original_model = (
                getattr(request_data, "model", "unknown")
                if hasattr(request_data, "model")
                else "unknown"
            )
            logger.info(
                f"QwenOAuth DEBUG: Calling parent with effective_model='{model_name}', original request_data model='{original_model}'"
            )

            response_envelope = await OpenAIConnector.chat_completions(
                self,
                request_data=request_data,  # Pass original request_data, let parent handle model override
                processed_messages=processed_messages,
                effective_model=model_name,  # Pass our validated/mapped model name
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
            logger.error(f"Error in Qwen OAuth chat_completions: {e}")
            raise BackendError(
                message=f"Qwen OAuth chat completion failed: {e!s}"
            ) from e

    def __del__(self) -> None:
        """Cleanup method to stop file watching when connector is destroyed."""
        with contextlib.suppress(Exception):
            self._stop_file_watching()


backend_registry.register_backend("qwen-oauth", QwenOAuthConnector)
