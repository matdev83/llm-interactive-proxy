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
import concurrent.futures
import contextlib
import json
import logging
import shutil
import subprocess
import time
import uuid
from collections.abc import AsyncGenerator
from pathlib import Path
from typing import TYPE_CHECKING, Any

import google.auth
import google.auth.transport.requests
import google.oauth2.credentials
import httpx
import requests  # type: ignore[import-untyped]
import tiktoken
from fastapi import HTTPException
from watchdog.events import FileSystemEventHandler
from watchdog.observers import Observer

from src.core.domain.chat import (
    CanonicalChatResponse,
    ChatCompletionChoice,
    ChatCompletionChoiceMessage,
)

if TYPE_CHECKING:
    from watchdog.observers.api import BaseObserver

from src.connectors.utils.gemini_request_counter import DailyRequestCounter
from src.core.common.exceptions import (
    APIConnectionError,
    APITimeoutError,
    AuthenticationError,
    BackendError,
    ServiceUnavailableError,
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


TOKEN_EXPIRY_BUFFER_SECONDS = 30.0
CLI_REFRESH_THRESHOLD_SECONDS = 120.0
CLI_REFRESH_COOLDOWN_SECONDS = 30.0
CLI_REFRESH_COMMAND = [
    "gemini",
    "-m",
    "gemini-2.5-flash",
    "-y",
    "-p",
    "Hi. What's up?",
]

# Timeout configuration for streaming requests
# Connection timeout: time to establish connection
DEFAULT_CONNECTION_TIMEOUT = 60.0
# Read timeout: time between chunks during streaming (much longer for large responses)
DEFAULT_READ_TIMEOUT = 300.0  # 5 minutes to handle large file reads and long responses


class GeminiPersonalCredentialsFileHandler(FileSystemEventHandler):
    """File system event handler for monitoring OAuth credentials file changes."""

    def __init__(self, connector: "GeminiOAuthPersonalConnector"):
        """Initialize the file handler with reference to the connector.

        Args:
            connector: The GeminiOAuthPersonalConnector instance to notify of file changes
        """
        super().__init__()
        self.connector = connector

    def on_modified(self, event):
        """Handle file modification events."""
        if not event.is_directory:
            # Compare paths using Path objects to handle Windows/Unix differences
            try:
                event_path = Path(event.src_path).resolve()
                credentials_path = (
                    self.connector._credentials_path.resolve()
                    if self.connector._credentials_path
                    else None
                )

                if credentials_path and event_path == credentials_path:
                    if logger.isEnabledFor(logging.INFO):
                        logger.info(f"Credentials file modified: {event.src_path}")

                    # Schedule credential reload in the connector's event loop in a thread-safe way
                    if self.connector._main_loop is not None:
                        try:
                            future = asyncio.run_coroutine_threadsafe(
                                self.connector._handle_credentials_file_change(),
                                self.connector._main_loop,
                            )
                            # Store reference to prevent task from being garbage collected
                            self.connector._pending_reload_task = future
                        except Exception as e:
                            if logger.isEnabledFor(logging.ERROR):
                                logger.error(
                                    f"Failed to schedule credentials reload: {e}"
                                )
                    else:
                        if logger.isEnabledFor(logging.WARNING):
                            logger.warning(
                                "No event loop available for credentials reload"
                            )
            except Exception as e:
                if logger.isEnabledFor(logging.ERROR):
                    logger.error(f"Error processing file modification event: {e}")


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
        # Use BaseObserver for type checking to ensure stop/join are recognized by mypy
        self._file_observer: BaseObserver | None = None
        self._credential_validation_errors: list[str] = []
        self._initialization_failed = False
        self._last_validation_time = 0.0
        self._pending_reload_task: asyncio.Task | concurrent.futures.Future | None = (
            None
        )
        self._last_cli_refresh_attempt = 0.0
        self._cli_refresh_process: subprocess.Popen[bytes] | None = None
        # Store reference to the main event loop for thread-safe operations
        self._main_loop: asyncio.AbstractEventLoop | None = None
        # Flag to track if quota has been exceeded
        self._quota_exceeded = False
        self._request_counter: DailyRequestCounter | None = None

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
        self._request_counter = DailyRequestCounter(
            persistence_path=Path("data/gemini_oauth_request_count.json"), limit=1000
        )

    def is_backend_functional(self) -> bool:
        """Check if backend is functional and ready to handle requests.

        Returns:
            bool: True if backend is functional, False otherwise
        """
        return (
            self.is_functional
            and not self._initialization_failed
            and len(self._credential_validation_errors) == 0
        )

    def get_validation_errors(self) -> list[str]:
        """Get the current list of credential validation errors.

        Returns:
            List of validation error messages
        """
        return self._credential_validation_errors.copy()

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

        # Required fields for OAuth credentials
        required_fields = ["access_token"]
        for field in required_fields:
            if field not in credentials:
                errors.append(f"Missing required field: {field}")
            elif not isinstance(credentials[field], str) or not credentials[field]:
                errors.append(f"Invalid {field}: must be a non-empty string")

        # Optional refresh token validation
        if "refresh_token" in credentials and (
            not isinstance(credentials["refresh_token"], str)
            or not credentials["refresh_token"]
        ):
            errors.append("Invalid refresh_token: must be a non-empty string")

        # Expiry validation (if present)
        if "expiry_date" in credentials:
            expiry = credentials["expiry_date"]
            if not isinstance(expiry, int | float):
                errors.append("Invalid expiry_date: must be a number (ms)")
            else:
                # Record expired status without failing validation; refresh logic handles it
                import datetime

                current_utc_s = datetime.datetime.now(datetime.timezone.utc).timestamp()
                if current_utc_s >= float(expiry) / 1000.0 and logger.isEnabledFor(
                    logging.INFO
                ):
                    logger.info(
                        "Loaded Gemini OAuth credentials appear expired; refresh will be triggered."
                    )

        return len(errors) == 0, errors

    def _validate_credentials_file_exists(self) -> tuple[bool, list[str]]:
        """Validate that the OAuth credentials file exists and is readable.

        Returns:
            Tuple of (is_valid, list_of_errors)
        """
        errors = []

        # Use custom path if provided, otherwise default to ~/.gemini
        if self.gemini_cli_oauth_path:
            creds_path = Path(self.gemini_cli_oauth_path) / "oauth_creds.json"
        else:
            home_dir = Path.home()
            creds_path = home_dir / ".gemini" / "oauth_creds.json"

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

    def _fail_init(self, errors: list[str]) -> None:
        """Mark initialization as failed with given errors."""
        self._credential_validation_errors = errors
        self._initialization_failed = True
        self.is_functional = False

    def _degrade(self, errors: list[str]) -> None:
        """Degrade backend functionality due to credential issues."""
        self._credential_validation_errors = errors
        self.is_functional = False

    def _recover(self) -> None:
        """Recover backend functionality after credential issues are resolved."""
        self._credential_validation_errors = []
        self.is_functional = True
        self._initialization_failed = False

    def _mark_backend_unusable(self) -> None:
        """Mark this backend as unusable by removing it from functional backends list.

        This method is called when quota exceeded errors are detected and the backend
        should no longer be used for requests.
        """
        # We don't have direct access to the DI container here; just mark ourselves unusable.
        self.is_functional = False
        self._quota_exceeded = True

        logger.error(
            "Backend %s marked as unusable due to quota exceeded. "
            "Manual intervention may be required to restore functionality.",
            self.name,
        )

    def _start_file_watching(self) -> None:
        """Start watching the credentials file for changes."""
        if not self._credentials_path or self._file_observer:
            return

        try:
            event_handler = GeminiPersonalCredentialsFileHandler(self)
            self._file_observer = Observer()
            # Watch the parent directory of the credentials file
            watch_dir = self._credentials_path.parent
            self._file_observer.schedule(event_handler, str(watch_dir), recursive=False)
            self._file_observer.start()
            if logger.isEnabledFor(logging.INFO):
                logger.info(
                    f"Started watching credentials file: {self._credentials_path}"
                )
        except Exception as e:
            if logger.isEnabledFor(logging.WARNING):
                logger.warning(f"Failed to start file watching: {e}")

    def _stop_file_watching(self) -> None:
        """Stop watching the credentials file."""
        observer = self._file_observer
        if observer:
            try:
                observer.stop()
                observer.join()
                self._file_observer = None
                if logger.isEnabledFor(logging.INFO):
                    logger.info("Stopped watching credentials file")
            except Exception as e:
                if logger.isEnabledFor(logging.WARNING):
                    logger.warning(f"Error stopping file watcher: {e}")

    async def _handle_credentials_file_change(self) -> None:
        """Handle credentials file change event.

        This method is called when the file system watcher detects a change to the
        oauth_creds.json file. It forces a reload of credentials bypassing the cache
        to ensure the latest token is loaded even if the file timestamp didn't change.
        """
        try:
            if logger.isEnabledFor(logging.INFO):
                logger.info("Handling credentials file change...")

            # Validate file first
            ok, errs = self._validate_credentials_file_exists()
            if not ok:
                self._degrade(errs)
                if logger.isEnabledFor(logging.WARNING):
                    logger.warning(
                        f"Updated credentials file is invalid: {'; '.join(errs)}"
                    )
                return

            # Attempt to reload with force_reload=True to bypass cache
            if await self._load_oauth_credentials(force_reload=True):
                refreshed = await self._refresh_token_if_needed()
                if refreshed:
                    self._recover()
                    if logger.isEnabledFor(logging.INFO):
                        logger.info(
                            "Successfully reloaded credentials from updated file"
                        )
                else:
                    self._degrade(
                        ["Credentials refreshed from file but token remains invalid"]
                    )
                    if logger.isEnabledFor(logging.WARNING):
                        logger.warning(
                            "Credentials file reload completed but token is still invalid"
                        )
            else:
                self._degrade(["Failed to reload credentials after file change"])
                if logger.isEnabledFor(logging.ERROR):
                    logger.error("Failed to reload credentials after file change")

        except Exception as e:
            self._degrade([f"Error handling credentials file change: {e}"])
            if logger.isEnabledFor(logging.ERROR):
                logger.error(
                    f"Error handling credentials file change: {e}", exc_info=True
                )

    async def _validate_runtime_credentials(self) -> bool:
        """Validate credentials at runtime with throttling.

        Returns:
            bool: True if credentials are valid, False otherwise
        """
        now = time.time()
        if now - self._last_validation_time < 30:
            return self.is_backend_functional()
        self._last_validation_time = now

        refreshed = await self._refresh_token_if_needed()
        if not refreshed:
            self._degrade(["Token expired and automatic refresh failed"])
            if logger.isEnabledFor(logging.WARNING):
                logger.warning(
                    "Token validation failed; automatic refresh did not produce a valid token."
                )
            return False

        if not self.is_backend_functional():
            self._recover()
        return True

    def _seconds_until_token_expiry(self) -> float | None:
        """Return seconds remaining before token expiry, or None if unknown."""
        if not self._oauth_credentials:
            return None

        expiry_value = self._oauth_credentials.get("expiry_date")
        if not isinstance(expiry_value, int | float):
            return None

        expiry_seconds = float(expiry_value) / 1000.0
        return expiry_seconds - time.time()

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
        """Launch gemini CLI command to refresh the OAuth token in background."""
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
            if logger.isEnabledFor(logging.INFO):
                logger.info("Triggered Gemini CLI background refresh process")
        except FileNotFoundError:
            self._last_cli_refresh_attempt = now
            if logger.isEnabledFor(logging.ERROR):
                logger.error(
                    "Gemini CLI binary not found; cannot refresh OAuth token automatically."
                )
        except Exception as exc:  # pragma: no cover - defensive logging
            self._last_cli_refresh_attempt = now
            if logger.isEnabledFor(logging.ERROR):
                logger.error(
                    "Failed to launch Gemini CLI for token refresh: %s",
                    exc,
                    exc_info=True,
                )

    async def _poll_for_new_token(self) -> bool:
        """Poll the credential file for an updated token after CLI refresh."""
        for _ in range(5):
            await asyncio.sleep(1)
            loaded = await self._load_oauth_credentials()
            if loaded and not self._is_token_expired():
                return True

        return not self._is_token_expired()

    def _get_refresh_token(self) -> str | None:
        """Get refresh token, either from credentials or cached value."""
        if self._refresh_token:
            return self._refresh_token

        if self._oauth_credentials and "refresh_token" in self._oauth_credentials:
            self._refresh_token = self._oauth_credentials["refresh_token"]
            return self._refresh_token

        return None

    async def _refresh_token_if_needed(self) -> bool:
        """Ensure a valid access token is available, refreshing when necessary."""
        if not self._oauth_credentials:
            await self._load_oauth_credentials()

        if not self._oauth_credentials:
            return False

        expired = self._is_token_expired()
        near_expiry = self._should_trigger_cli_refresh()

        if not expired and not near_expiry:
            return True

        async with self._token_refresh_lock:
            if not self._oauth_credentials:
                await self._load_oauth_credentials()

            if not self._oauth_credentials:
                return False

            expired = self._is_token_expired()
            near_expiry = self._should_trigger_cli_refresh()

            if not expired and near_expiry:
                self._launch_cli_refresh_process()
                return True

            if not expired:
                return True

            if logger.isEnabledFor(logging.INFO):
                logger.info(
                    "Access token expired; reloading credentials and invoking CLI refresh if needed."
                )

            reloaded = await self._load_oauth_credentials()
            if reloaded and not self._is_token_expired():
                if self._should_trigger_cli_refresh():
                    self._launch_cli_refresh_process()
                return True

            self._launch_cli_refresh_process()

            refreshed = await self._poll_for_new_token()
            if refreshed:
                return True

            if logger.isEnabledFor(logging.WARNING):
                logger.warning(
                    "Automatic Gemini CLI refresh did not produce a valid token in time."
                )
            return False

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

    async def _load_oauth_credentials(self, force_reload: bool = False) -> bool:
        """Load OAuth credentials from oauth_creds.json file.

        Args:
            force_reload: If True, bypass cache and force reload from file even if timestamp unchanged

        Returns:
            bool: True if credentials loaded successfully, False otherwise
        """
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

            # Check if file has been modified since last load (unless force_reload is True)
            if not force_reload:
                try:
                    current_modified = creds_path.stat().st_mtime
                    if (
                        current_modified == self._last_modified
                        and self._oauth_credentials
                    ):
                        # File hasn't changed and credentials are in memory, no need to reload
                        if logger.isEnabledFor(logging.DEBUG):
                            logger.debug(
                                "Gemini OAuth credentials file not modified, using cached."
                            )
                        return True
                except OSError:
                    # If cannot get file stats, proceed with reading
                    pass

            # Update last modified time
            try:
                current_modified = creds_path.stat().st_mtime
                self._last_modified = current_modified
            except OSError:
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
                log_msg = "Successfully loaded Gemini OAuth credentials"
                if force_reload:
                    log_msg += " (force reload)"
                logger.info(log_msg + ".")
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
        """Initialize backend with enhanced validation following the stale token handling pattern."""
        if logger.isEnabledFor(logging.INFO):
            logger.info(
                "Initializing Gemini OAuth Personal backend with enhanced validation."
            )

        # Capture the current event loop for thread-safe operations
        try:
            self._main_loop = asyncio.get_running_loop()
        except RuntimeError:
            # If no running loop, create a new one
            self._main_loop = asyncio.new_event_loop()
            asyncio.set_event_loop(self._main_loop)

        # Set the API base URL for Google Code Assist API (used by oauth-personal)
        self.gemini_api_base_url = kwargs.get(
            "gemini_api_base_url", "https://cloudcode-pa.googleapis.com"
        )

        # Set custom .gemini directory path (defaults to ~/.gemini)
        self.gemini_cli_oauth_path = kwargs.get("gemini_cli_oauth_path")

        # 1) Startup validation pipeline
        # First validate credentials file exists and is readable
        ok, errs = self._validate_credentials_file_exists()
        if not ok:
            self._fail_init(errs)
            return

        # 2) Load credentials into memory
        if not await self._load_oauth_credentials():
            self._fail_init(["Failed to load credentials despite validation passing"])
            return

        # 3) Structure validation
        if self._oauth_credentials is not None:
            ok, errs = self._validate_credentials_structure(self._oauth_credentials)
            if not ok:
                self._fail_init(errs)
                return
        else:
            self._fail_init(["OAuth credentials are None after loading"])
            return

        # 4) Refresh if needed
        if not await self._refresh_token_if_needed():
            pending_message = "OAuth token refresh pending; Gemini CLI background refresh was triggered."
            self._degrade([pending_message])
            self._start_file_watching()
            self._initialization_failed = False
            self._last_validation_time = time.time()
            if logger.isEnabledFor(logging.WARNING):
                logger.warning(
                    "Gemini OAuth Personal backend started with an expired token; "
                    "waiting for the Gemini CLI to refresh credentials."
                )
            return

        # 5) Load models (non-fatal)
        try:
            await self._ensure_models_loaded()
        except Exception as e:
            if logger.isEnabledFor(logging.WARNING):
                logger.warning(
                    f"Failed to load models during initialization: {e}", exc_info=True
                )
            # Continue with initialization even if model loading fails

        # 6) Start file watching and mark functional
        self._start_file_watching()
        self.is_functional = True
        self._last_validation_time = time.time()

        if logger.isEnabledFor(logging.INFO):
            logger.info(
                f"Gemini OAuth Personal backend initialized successfully with {len(self.available_models)} models."
            )

    async def _ensure_models_loaded(self) -> None:
        """Fetch models if not already cached - OAuth version.

        Note: The Code Assist API doesn't have a models list endpoint,
        so we use a hardcoded list of known models based on the official
        gemini-cli source code (as of 2025).
        """
        if not self.available_models and self._oauth_credentials:
            # Code Assist API doesn't have a /v1internal/models endpoint
            # Use a hardcoded list based on gemini-cli's tokenLimits.ts and models.ts
            self.available_models = [
                # Current generation (2.5 series) - DEFAULT models
                "gemini-2.5-pro",
                "gemini-2.5-flash",
                "gemini-2.5-flash-lite",
                # Preview models
                "gemini-2.5-pro-preview-05-06",
                "gemini-2.5-pro-preview-06-05",
                "gemini-2.5-flash-preview-05-20",
                # 2.0 series
                "gemini-2.0-flash",
                "gemini-2.0-flash-thinking-exp-1219",
                "gemini-2.0-flash-preview-image-generation",
                # 1.5 series
                "gemini-1.5-pro",
                "gemini-1.5-flash",
                # Embedding model
                "gemini-embedding-001",
            ]
            if logger.isEnabledFor(logging.INFO):
                logger.info(
                    f"Loaded {len(self.available_models)} known Code Assist models"
                )

    async def list_models(
        self, *, gemini_api_base_url: str, key_name: str, api_key: str
    ) -> dict[str, Any]:
        """List available models using OAuth authentication - ignores API key params."""
        if not self._oauth_credentials or not self._oauth_credentials.get(
            "access_token"
        ):
            raise HTTPException(
                status_code=401, detail="No OAuth access token available"
            )

        headers = {"Authorization": f"Bearer {self._oauth_credentials['access_token']}"}
        base_url = self.gemini_api_base_url or CODE_ASSIST_ENDPOINT
        url = f"{base_url}/v1internal/models"

        try:
            response = await self.client.get(url, headers=headers)
            if response.status_code >= 400:
                try:
                    error_detail = response.json()
                except Exception:
                    error_detail = response.text
                raise BackendError(
                    message=str(error_detail),
                    code="gemini_oauth_error",
                    status_code=response.status_code,
                    backend_name=self.backend_type,
                )
            result: dict[str, Any] = response.json()
            return result
        except httpx.TimeoutException as e:
            if logger.isEnabledFor(logging.ERROR):
                logger.error(
                    "Timeout connecting to Gemini OAuth API: %s", e, exc_info=True
                )
            raise ServiceUnavailableError(
                message=f"Timeout connecting to Gemini OAuth API ({e})"
            )
        except httpx.RequestError as e:
            if logger.isEnabledFor(logging.ERROR):
                logger.error(
                    "Request error connecting to Gemini OAuth API: %s", e, exc_info=True
                )
            raise ServiceUnavailableError(
                message=f"Could not connect to Gemini OAuth API ({e})"
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

            # Perform health check (non-blocking - we only fail on token issues)
            healthy = await self._perform_health_check()
            if not healthy:
                logger.warning(
                    "Health check did not pass, but continuing with valid OAuth credentials. "
                    "The backend will be tested when the first real request is made."
                )
            # Mark as checked regardless - we have valid credentials
            self._health_checked = True
            logger.info("Backend health check completed - ready for use")

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
        # Runtime validation with descriptive errors
        if not await self._validate_runtime_credentials():
            details = (
                "; ".join(self._credential_validation_errors)
                or "Backend is not functional"
            )
            raise HTTPException(
                status_code=502,
                detail=f"No valid credentials found for backend {self.name}: {details}",
            )

        if not await self._refresh_token_if_needed():
            raise HTTPException(
                status_code=502,
                detail=f"No valid credentials found for backend {self.name}: Failed to refresh expired token",
            )

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

            if self._request_counter:
                self._request_counter.increment()

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

                def before_request(
                    self, request: Any, method: str, url: str, headers: dict
                ) -> None:
                    """Apply the token to the authentication header."""
                    headers["Authorization"] = f"Bearer {self.token}"

                def refresh(self, request: Any) -> None:
                    # No-op: token is managed by the CLI; we reload from file when needed
                    return

            auth_session = google.auth.transport.requests.AuthorizedSession(
                _StaticTokenCreds(access_token)
            )

            # Discover project ID (required for Code Assist API)
            project_id = await self._discover_project_id(auth_session)

            # request_data is expected to be a CanonicalChatRequest already
            # (the frontend controller converts from frontend-specific format to domain format)
            # Backends should ONLY convert FROM domain TO backend-specific format
            canonical_request = request_data

            # Debug logging to trace message flow
            if logger.isEnabledFor(logging.DEBUG):
                message_count = (
                    len(canonical_request.messages)
                    if hasattr(canonical_request, "messages")
                    else 0
                )
                logger.debug(
                    f"Processing {message_count} messages for Gemini Code Assist API"
                )
                if message_count > 0 and hasattr(canonical_request, "messages"):
                    last_msg = canonical_request.messages[-1]
                    last_msg_preview = str(getattr(last_msg, "content", ""))[:100]
                    logger.debug(
                        f"Last message role={getattr(last_msg, 'role', 'unknown')}, content preview={last_msg_preview}"
                    )

            # Convert from canonical/domain format to Gemini API format
            gemini_request = self.translation_service.from_domain_to_gemini_request(
                canonical_request
            )

            # Code Assist API doesn't support 'system' role in contents array
            # Extract system messages and convert to systemInstruction with 'user' role
            system_instruction = None
            filtered_contents = []

            for content in gemini_request.get("contents", []):
                if content.get("role") == "system":
                    # Convert system message to systemInstruction with 'user' role
                    # (Code Assist API doesn't support 'system' role)
                    system_instruction = {
                        "role": "user",
                        "parts": content.get("parts", []),
                    }
                else:
                    filtered_contents.append(content)

            # Build the request for Code Assist API
            code_assist_request = {
                "contents": filtered_contents,
                "generationConfig": gemini_request.get("generationConfig", {}),
            }

            # Add systemInstruction if we found system messages
            if system_instruction:
                code_assist_request["systemInstruction"] = system_instruction

            # Add other fields if present
            if "tools" in gemini_request:
                code_assist_request["tools"] = gemini_request["tools"]
            if "toolConfig" in gemini_request:
                code_assist_request["toolConfig"] = gemini_request["toolConfig"]
            if "safetySettings" in gemini_request:
                code_assist_request["safetySettings"] = gemini_request["safetySettings"]

            # Prepare request body for Code Assist API
            request_body = {
                "model": effective_model,
                "project": project_id,
                "user_prompt_id": self._generate_user_prompt_id(request_data),
                "request": code_assist_request,
            }

            # Use the Code Assist API exactly like KiloCode does
            # IMPORTANT: KiloCode uses :streamGenerateContent, not :generateContent
            url = f"{self.gemini_api_base_url}/v1internal:streamGenerateContent"
            logger.info(f"Making Code Assist API call to: {url}")

            # Use the auth_session.request exactly like KiloCode
            # Add ?alt=sse for server-sent events streaming
            # Use tuple for (connect_timeout, read_timeout) to handle large responses
            try:
                response = await asyncio.to_thread(
                    auth_session.request,
                    method="POST",
                    url=url,
                    params={"alt": "sse"},  # Important: KiloCode uses SSE streaming
                    json=request_body,
                    headers={"Content-Type": "application/json"},
                    timeout=int(DEFAULT_CONNECTION_TIMEOUT),
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
            response_text = response.text
            for line in response_text.split("\n"):
                if line.startswith("data: "):
                    data_str = line[6:].strip()
                    if data_str == "[DONE]":
                        break
                    try:
                        data = json.loads(data_str)
                        # Extract content from the chunk
                        chunk_response = (
                            self.translation_service.to_domain_stream_chunk(
                                chunk=data,
                                source_format="code_assist",
                            )
                        )
                        if (
                            chunk_response
                            and chunk_response.get("choices")
                            and chunk_response["choices"][0]
                            .get("delta", {})
                            .get("content")
                        ):
                            generated_text += chunk_response["choices"][0]["delta"][
                                "content"
                            ]
                    except json.JSONDecodeError:
                        continue

            # Manually calculate token usage since the API doesn't provide it
            try:
                encoding = tiktoken.get_encoding("cl100k_base")

                # Reconstruct prompt text
                prompt_text_parts = []
                if code_assist_request.get("systemInstruction"):
                    for part in code_assist_request["systemInstruction"].get(
                        "parts", []
                    ):
                        if "text" in part:
                            prompt_text_parts.append(part["text"])

                for content in code_assist_request.get("contents", []):
                    for part in content.get("parts", []):
                        if "text" in part:
                            prompt_text_parts.append(part["text"])

                full_prompt = "\n".join(prompt_text_parts)

                prompt_tokens = len(encoding.encode(full_prompt))
                completion_tokens = len(encoding.encode(generated_text))
                total_tokens = prompt_tokens + completion_tokens
                usage = {
                    "prompt_tokens": prompt_tokens,
                    "completion_tokens": completion_tokens,
                    "total_tokens": total_tokens,
                }
            except Exception as e:
                logger.warning(f"Could not calculate token usage with tiktoken: {e}")
                usage = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}

            # Create a new CanonicalChatResponse with the full content and usage
            domain_response = CanonicalChatResponse(
                id=f"chatcmpl-code-assist-{int(time.time())}",
                object="chat.completion",
                created=int(time.time()),
                model=effective_model,
                choices=[
                    ChatCompletionChoice(
                        index=0,
                        message=ChatCompletionChoiceMessage(
                            role="assistant", content=generated_text
                        ),
                        finish_reason="stop",
                    )
                ],
                usage=usage,
            )

            # Convert to OpenAI-compatible format
            openai_response = self.translation_service.from_domain_to_openai_response(
                domain_response
            )

            logger.info(
                "Successfully received and processed response from Code Assist API"
            )
            return ResponseEnvelope(
                content=openai_response, headers={}, status_code=200, usage=usage
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

            if self._request_counter:
                self._request_counter.increment()

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

                def before_request(
                    self, request: Any, method: str, url: str, headers: dict
                ) -> None:
                    """Apply the token to the authentication header."""
                    headers["Authorization"] = f"Bearer {self.token}"

                def refresh(self, request: Any) -> None:
                    return

            auth_session = google.auth.transport.requests.AuthorizedSession(
                _StaticTokenCreds(access_token)
            )

            # Discover project ID (required for Code Assist API)
            project_id = await self._discover_project_id(auth_session)

            # request_data is expected to be a CanonicalChatRequest already
            # (the frontend controller converts from frontend-specific format to domain format)
            # Backends should ONLY convert FROM domain TO backend-specific format
            canonical_request = request_data

            # Debug logging to trace message flow (streaming)
            if logger.isEnabledFor(logging.DEBUG):
                message_count = (
                    len(canonical_request.messages)
                    if hasattr(canonical_request, "messages")
                    else 0
                )
                logger.debug(
                    f"[STREAMING] Processing {message_count} messages for Gemini Code Assist API"
                )
                if message_count > 0 and hasattr(canonical_request, "messages"):
                    last_msg = canonical_request.messages[-1]
                    last_msg_preview = str(getattr(last_msg, "content", ""))[:100]
                    logger.debug(
                        f"[STREAMING] Last message role={getattr(last_msg, 'role', 'unknown')}, content preview={last_msg_preview}"
                    )

            # Convert from canonical/domain format to Gemini API format
            gemini_request = self.translation_service.from_domain_to_gemini_request(
                canonical_request
            )

            # Code Assist API doesn't support 'system' role in contents array
            # Extract system messages and convert to systemInstruction with 'user' role
            system_instruction = None
            filtered_contents = []

            for content in gemini_request.get("contents", []):
                if content.get("role") == "system":
                    # Convert system message to systemInstruction with 'user' role
                    # (Code Assist API doesn't support 'system' role)
                    system_instruction = {
                        "role": "user",
                        "parts": content.get("parts", []),
                    }
                else:
                    filtered_contents.append(content)

            # Build the request for Code Assist API
            code_assist_request = {
                "contents": filtered_contents,
                "generationConfig": gemini_request.get("generationConfig", {}),
            }

            # Add systemInstruction if we found system messages
            if system_instruction:
                code_assist_request["systemInstruction"] = system_instruction

            # Add other fields if present
            if "tools" in gemini_request:
                code_assist_request["tools"] = gemini_request["tools"]
            if "toolConfig" in gemini_request:
                code_assist_request["toolConfig"] = gemini_request["toolConfig"]
            if "safetySettings" in gemini_request:
                code_assist_request["safetySettings"] = gemini_request["safetySettings"]

            # Prepare request body for Code Assist API
            request_body = {
                "model": effective_model,
                "project": project_id,
                "user_prompt_id": self._generate_user_prompt_id(request_data),
                "request": code_assist_request,
            }

            # Use the Code Assist API with streaming endpoint
            url = f"{self.gemini_api_base_url}/v1internal:streamGenerateContent"
            logger.info(f"Making streaming Code Assist API call to: {url}")

            # For token calculation
            encoding = tiktoken.get_encoding("cl100k_base")
            try:
                prompt_text_parts = []
                if code_assist_request.get("systemInstruction"):
                    for part in code_assist_request["systemInstruction"].get(
                        "parts", []
                    ):
                        if "text" in part:
                            prompt_text_parts.append(part["text"])
                for content in code_assist_request.get("contents", []):
                    for part in content.get("parts", []):
                        if "text" in part:
                            prompt_text_parts.append(part["text"])
                full_prompt = "\n".join(prompt_text_parts)
                prompt_tokens = len(encoding.encode(full_prompt))
            except Exception as e:
                logger.warning(f"Could not calculate prompt tokens with tiktoken: {e}")
                prompt_tokens = 0

            # Create an async iterator that yields SSE-formatted chunks
            async def stream_generator() -> AsyncGenerator[ProcessedResponse, None]:
                response = None
                generated_text = ""
                try:
                    try:
                        response = await asyncio.to_thread(
                            auth_session.request,
                            method="POST",
                            url=url,
                            params={"alt": "sse"},
                            json=request_body,
                            headers={"Content-Type": "application/json"},
                            timeout=int(DEFAULT_CONNECTION_TIMEOUT),
                            stream=True,
                        )
                    except requests.exceptions.Timeout as te:
                        logger.error(
                            f"Streaming timeout calling {url}: {te}", exc_info=True
                        )
                        yield ProcessedResponse(
                            content=self.translation_service.to_domain_stream_chunk(
                                chunk=None, source_format="code_assist"
                            )
                        )
                        return
                    except requests.exceptions.RequestException as rexc:
                        logger.error(
                            f"Streaming connection error calling {url}: {rexc}",
                            exc_info=True,
                        )
                        yield ProcessedResponse(
                            content=self.translation_service.to_domain_stream_chunk(
                                chunk=None, source_format="code_assist"
                            )
                        )
                        return

                    if response.status_code >= 400:
                        try:
                            error_detail = response.json()
                        except Exception:
                            error_detail = response.text
                        if (
                            response.status_code == 429
                            and isinstance(error_detail, dict)
                            and "Quota exceeded"
                            in error_detail.get("error", {}).get("message", "")
                        ):
                            self._mark_backend_unusable()
                            raise BackendError(
                                message=f"Gemini CLI OAuth quota exceeded: {error_detail}",
                                code="quota_exceeded",
                                status_code=response.status_code,
                            )
                        raise BackendError(
                            message=f"Code Assist API streaming error: {error_detail}",
                            code="code_assist_error",
                            status_code=response.status_code,
                        )

                    # Process streaming byte-by-byte for true real-time streaming
                    # Use a larger chunk_size for better performance (512 bytes is a good balance)
                    line_buffer = ""
                    done = False
                    for chunk in response.iter_content(
                        chunk_size=512, decode_unicode=False
                    ):
                        if done:
                            break
                        try:
                            # Decode the chunk and process character by character
                            chunk_str = chunk.decode("utf-8")
                            for char in chunk_str:
                                line_buffer += char
                                if char == "\n":
                                    decoded_line = line_buffer.rstrip("\r\n")
                                    line_buffer = ""
                                    if decoded_line.startswith("data: "):
                                        data_str = decoded_line[6:].strip()
                                        if data_str == "[DONE]":
                                            done = True
                                            break
                                        try:
                                            data = json.loads(data_str)
                                            domain_chunk = self.translation_service.to_domain_stream_chunk(
                                                chunk=data, source_format="code_assist"
                                            )
                                            # Accumulate generated text for usage calculation
                                            if (
                                                domain_chunk
                                                and domain_chunk.get("choices")
                                                and domain_chunk["choices"][0]
                                                .get("delta", {})
                                                .get("content")
                                            ):
                                                generated_text += domain_chunk[
                                                    "choices"
                                                ][0]["delta"]["content"]
                                            # Always yield the chunk, regardless of content
                                            yield ProcessedResponse(
                                                content=domain_chunk
                                            )
                                        except json.JSONDecodeError:
                                            continue
                        except UnicodeDecodeError:
                            # Skip invalid UTF-8 sequences
                            continue
                        except Exception as chunk_error:
                            logger.error(
                                f"Error processing stream chunk: {chunk_error}",
                                exc_info=True,
                            )
                            continue

                    # Calculate and yield usage
                    try:
                        completion_tokens = len(encoding.encode(generated_text))
                        usage = {
                            "prompt_tokens": prompt_tokens,
                            "completion_tokens": completion_tokens,
                            "total_tokens": prompt_tokens + completion_tokens,
                        }
                        usage_chunk = {
                            "id": f"chatcmpl-gemini-usage-{int(time.time())}",
                            "object": "chat.completion.chunk",
                            "created": int(time.time()),
                            "model": effective_model,
                            "choices": [],
                            "usage": usage,
                        }
                        yield ProcessedResponse(content=usage_chunk)
                    except Exception as e:
                        logger.warning(
                            f"Could not calculate completion tokens for streaming: {e}"
                        )

                    final_chunk = self.translation_service.to_domain_stream_chunk(
                        chunk=None, source_format="code_assist"
                    )
                    yield ProcessedResponse(content=final_chunk)

                except Exception as e:
                    logger.error(f"Error in streaming generator: {e}", exc_info=True)
                    error_chunk = self.translation_service.to_domain_stream_chunk(
                        chunk=None, source_format="code_assist"
                    )
                    yield ProcessedResponse(content=error_chunk)
                finally:
                    if response:
                        response.close()

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
            # For quota exceeded errors, don't log full stack trace to avoid console spam
            if "quota exceeded" in str(e).lower():
                logger.error(f"Backend error during streaming API call: {e}")
            else:
                logger.error(
                    f"Backend error during streaming API call: {e}", exc_info=True
                )
            raise
        except Exception as e:
            logger.error(
                f"Unexpected error during streaming API call: {e}", exc_info=True
            )
            raise BackendError(f"Unexpected error during streaming API call: {e}")

    def _generate_user_prompt_id(self, request_data: Any) -> str:
        """Generate a unique user_prompt_id for Code Assist requests."""
        session_hint: str | None = None
        extra_body = getattr(request_data, "extra_body", None)
        if isinstance(extra_body, dict):
            raw_session = extra_body.get("session_id") or extra_body.get(
                "user_prompt_id"
            )
            if raw_session is not None:
                session_hint = str(raw_session)

        base = "proxy"
        if session_hint:
            safe_session = "".join(
                c if c.isalnum() or c in "-._" else "-" for c in session_hint
            ).strip("-")
            if safe_session:
                base = f"{base}-{safe_session}"

        return f"{base}-{uuid.uuid4().hex}"

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

    def __del__(self):
        """Cleanup file watcher on destruction."""
        self._stop_file_watching()
        if self._cli_refresh_process and self._cli_refresh_process.poll() is None:
            with contextlib.suppress(Exception):
                self._cli_refresh_process.terminate()
        self._cli_refresh_process = None


backend_registry.register_backend(
    "gemini-cli-oauth-personal", GeminiOAuthPersonalConnector
)
