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
import uuid
from collections.abc import AsyncGenerator
from pathlib import Path
from typing import TYPE_CHECKING, Any

import google.auth
import google.auth.transport.requests
import google.oauth2.credentials
import google.oauth2.service_account
import httpx
import requests  # type: ignore[import-untyped]
from fastapi import HTTPException
from google.auth.exceptions import RefreshError
from watchdog.events import FileSystemEventHandler
from watchdog.observers import Observer

if TYPE_CHECKING:
    from watchdog.observers.api import BaseObserver

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
        except (ValueError, KeyError, TypeError):
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
# Code Assist API version: v1internal (documented for clarity)

# Scopes for Code Assist API (used with Google ADC)
CODE_ASSIST_SCOPES: list[str] = [
    "https://www.googleapis.com/auth/cloud-platform",
    "https://www.googleapis.com/auth/userinfo.email",
    "https://www.googleapis.com/auth/userinfo.profile",
]

# Tier IDs for standard and enterprise
STANDARD_TIER_ID = "standard-tier"
ENTERPRISE_TIER_ID = "enterprise-tier"

# Timeout configuration for streaming requests
# Connection timeout: time to establish connection
DEFAULT_CONNECTION_TIMEOUT = 60.0
# Read timeout: time between chunks during streaming (much longer for large responses)
DEFAULT_READ_TIMEOUT = 300.0  # 5 minutes to handle large file reads and long responses

logger = logging.getLogger(__name__)


class GeminiCredentialsFileHandler(FileSystemEventHandler):
    """File system event handler for monitoring OAuth credentials file changes."""

    def __init__(self, connector: "GeminiCloudProjectConnector"):
        """Initialize the file handler with reference to the connector.

        Args:
            connector: The GeminiCloudProjectConnector instance to notify of file changes
        """
        super().__init__()
        self.connector = connector

    def on_modified(self, event):
        """Handle file modification events."""
        if not event.is_directory and event.src_path == str(
            self.connector._credentials_path
        ):
            if logger.isEnabledFor(logging.INFO):
                logger.info(f"Credentials file modified: {event.src_path}")
            # Schedule credential reload in the connector's event loop
            task = asyncio.create_task(self.connector._handle_credentials_file_change())
            # Store reference to prevent task from being garbage collected
            self.connector._pending_reload_task = task


class GeminiCloudProjectConnector(GeminiBackend):
    """Connector that uses OAuth authentication with user-specified GCP project.

    This connector requires a valid Google Cloud Project ID and uses OAuth2
    authentication to access Gemini Code Assist API with standard/enterprise tier features.
    All usage is billed to the specified GCP project.
    """

    backend_type: str = "gemini-cli-cloud-project"

    def __init__(
        self,
        client: httpx.AsyncClient,
        config: AppConfig,
        translation_service: TranslationService,
        **kwargs: Any,
    ) -> None:  # Modified
        super().__init__(client, config, translation_service)
        self.translation_service = translation_service
        self.name = "gemini-cli-cloud-project"
        self.is_functional = False
        self._oauth_credentials: dict[str, Any] | None = None
        self._credentials_path: Path | None = None
        self._last_modified: float = 0
        self._refresh_token: str | None = None
        self._token_refresh_lock = asyncio.Lock()
        # Use BaseObserver for type checking to ensure stop/join are recognized by mypy
        self._file_observer: BaseObserver | None = None
        self._credential_validation_errors: list[str] = []
        self._initialization_failed = False
        self._last_validation_time = 0.0
        self._pending_reload_task: asyncio.Task | None = None

        # GCP Project ID is REQUIRED for this backend (CLI uses GOOGLE_CLOUD_PROJECT)
        self.gcp_project_id = (
            kwargs.get("gcp_project_id")
            or os.getenv("GOOGLE_CLOUD_PROJECT")
            or os.getenv("GCP_PROJECT_ID")
        )
        if not self.gcp_project_id:
            if logger.isEnabledFor(logging.WARNING):
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
                if time.time() >= float(expiry) / 1000.0:
                    errors.append("Token expired")

        return len(errors) == 0, errors

    def _validate_credentials_file_exists(self) -> tuple[bool, list[str]]:
        """Validate that the OAuth credentials file exists and is readable.

        Returns:
            Tuple of (is_valid, list_of_errors)
        """
        errors = []

        if self.credentials_path:
            creds_path = Path(self.credentials_path)
            if creds_path.is_dir():
                creds_path = creds_path / "oauth_creds.json"
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

    def _start_file_watching(self) -> None:
        """Start watching the credentials file for changes."""
        if not self._credentials_path or self._file_observer:
            return

        try:
            event_handler = GeminiCredentialsFileHandler(self)
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
        """Handle credentials file change event."""
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

            # Attempt to reload
            if await self._load_oauth_credentials():
                self._recover()
                if logger.isEnabledFor(logging.INFO):
                    logger.info("Successfully reloaded credentials from updated file")
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

        if self._is_token_expired():
            if logger.isEnabledFor(logging.INFO):
                logger.info(
                    "Access token expired during runtime, attempting to reload credentials..."
                )

            if await self._load_oauth_credentials():
                if self._is_token_expired():
                    self._degrade(["Token expired and no valid replacement found"])
                    if logger.isEnabledFor(logging.WARNING):
                        logger.warning(
                            "Reloaded token is still expired, marking backend as non-functional"
                        )
                    return False
                self._recover()
                if logger.isEnabledFor(logging.INFO):
                    logger.info("Successfully reloaded valid credentials")
                return True
            self._degrade(["Failed to reload expired credentials"])
            if logger.isEnabledFor(logging.ERROR):
                logger.error(
                    "Failed to reload credentials, marking backend as non-functional"
                )
            return False

        return self.is_backend_functional()

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
                if logger.isEnabledFor(logging.INFO):
                    logger.info("Using service account credentials from %s", sa_path)
                return google.auth.transport.requests.AuthorizedSession(credentials)
            except Exception as e:
                if logger.isEnabledFor(logging.WARNING):
                    logger.warning(
                        "Failed to load service account credentials from %s: %s",
                        sa_path,
                        e,
                        exc_info=True,
                    )

        # Fall back to ADC (supports gcloud ADC, workload identity, etc.)
        credentials, adc_project = google.auth.default(scopes=CODE_ASSIST_SCOPES)
        if adc_project and not self.gcp_project_id:
            # If ADC provided a project and user didn't specify, adopt it
            self.gcp_project_id = adc_project
        if logger.isEnabledFor(logging.INFO):
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

            if logger.isEnabledFor(logging.INFO):
                logger.info(
                    "Access token expired or near expiry, attempting to refresh..."
                )

            if not self._oauth_credentials:
                if logger.isEnabledFor(logging.WARNING):
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

                if logger.isEnabledFor(logging.INFO):
                    logger.info(
                        "Successfully refreshed OAuth token for GCP project access."
                    )
                return True

            except RefreshError as e:
                if logger.isEnabledFor(logging.ERROR):
                    logger.error(f"Google Auth token refresh error: {e}")
                return False
            except Exception as e:
                if logger.isEnabledFor(logging.ERROR):
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
            if logger.isEnabledFor(logging.INFO):
                logger.info(f"OAuth credentials saved to {creds_path}")
        except Exception as e:
            if logger.isEnabledFor(logging.ERROR):
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
                if logger.isEnabledFor(logging.WARNING):
                    logger.warning(f"OAuth credentials not found at {creds_path}")
                return False

            try:
                current_modified = creds_path.stat().st_mtime
                if current_modified == self._last_modified and self._oauth_credentials:
                    if logger.isEnabledFor(logging.DEBUG):
                        logger.debug(
                            "OAuth credentials file not modified, using cached."
                        )
                    return True
                self._last_modified = current_modified
            except OSError:
                pass

            with open(creds_path, encoding="utf-8") as f:
                credentials = json.load(f)

            if "access_token" not in credentials:
                if logger.isEnabledFor(logging.WARNING):
                    logger.warning("Malformed OAuth credentials: missing access_token")
                return False

            self._oauth_credentials = credentials
            if logger.isEnabledFor(logging.INFO):
                logger.info("Successfully loaded OAuth credentials.")
            return True
        except json.JSONDecodeError as e:
            if logger.isEnabledFor(logging.ERROR):
                logger.error(f"Error decoding OAuth credentials JSON: {e}")
            return False
        except Exception as e:
            if logger.isEnabledFor(logging.ERROR):
                logger.error(f"Error loading OAuth credentials: {e}")
            return False

    async def initialize(self, **kwargs: Any) -> None:
        """Initialize backend with enhanced validation following the stale token handling pattern."""
        if logger.isEnabledFor(logging.INFO):
            logger.info(
                f"Initializing Gemini Cloud Project backend with enhanced validation for project: {self.gcp_project_id}"
            )

        # Ensure we have a project ID
        if not self.gcp_project_id:
            self._fail_init(["GCP Project ID is required for cloud-project backend"])
            if logger.isEnabledFor(logging.ERROR):
                logger.error("GCP Project ID is required for cloud-project backend")
            return

        # Set the API base URL for Google Code Assist API
        self.gemini_api_base_url = kwargs.get(
            "gemini_api_base_url", CODE_ASSIST_ENDPOINT
        )

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
            self._fail_init(["Failed to refresh expired token during initialization"])
            return

        # 5) Validate project access
        try:
            await self._validate_project_access()
        except Exception as e:
            self._fail_init([f"Failed to validate project access: {e}"])
            return

        # 6) Load models (non-fatal)
        try:
            await self._ensure_models_loaded()
        except Exception as e:
            if logger.isEnabledFor(logging.WARNING):
                logger.warning(
                    f"Failed to load models during initialization: {e}", exc_info=True
                )
            # Continue with initialization even if model loading fails

        # 7) Start file watching and mark functional
        self._start_file_watching()
        self.is_functional = True
        self._last_validation_time = time.time()

        if logger.isEnabledFor(logging.INFO):
            logger.info(
                f"Gemini Cloud Project backend initialized successfully with {len(self.available_models)} models "
                f"for project: {self.gcp_project_id}"
            )

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
                timeout=30,
            )

            if load_response.status_code == 403:
                raise AuthenticationError(
                    f"Permission denied for project {self.gcp_project_id}. "
                    f"Ensure Cloud AI Companion API is enabled and you have necessary permissions."
                )
            elif load_response.status_code != 200:
                raise BackendError(f"Project validation failed: {load_response.text}")

            if logger.isEnabledFor(logging.INFO):
                logger.info(
                    f"Successfully validated access to project: {self.gcp_project_id}"
                )
        except Exception as e:
            if logger.isEnabledFor(logging.ERROR):
                logger.error(f"Failed to validate project access: {e}", exc_info=True)
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
                if logger.isEnabledFor(logging.WARNING):
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
            try:
                response = await self.client.get(url, headers=headers, timeout=10.0)
            except httpx.TimeoutException as te:
                if logger.isEnabledFor(logging.ERROR):
                    logger.error(
                        f"Health check timeout calling {url}: {te}", exc_info=True
                    )
                return False
            except httpx.RequestError as rexc:
                if logger.isEnabledFor(logging.ERROR):
                    logger.error(
                        f"Health check connection error calling {url}: {rexc}",
                        exc_info=True,
                    )
                return False

            if response.status_code == 200:
                if logger.isEnabledFor(logging.INFO):
                    logger.info("Health check passed - API connectivity verified")
                self._health_checked = True
                return True
            else:
                if logger.isEnabledFor(logging.WARNING):
                    logger.warning(
                        f"Health check failed - API returned status {response.status_code}"
                    )
                return False

        except Exception as e:
            if logger.isEnabledFor(logging.ERROR):
                logger.error(
                    f"Health check failed - unexpected error: {e}", exc_info=True
                )
            return False

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

    async def _ensure_healthy(self) -> None:
        """Ensure the backend is healthy before use."""
        if not hasattr(self, "_health_checked") or not self._health_checked:
            if logger.isEnabledFor(logging.INFO):
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
            if logger.isEnabledFor(logging.INFO):
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
            if logger.isEnabledFor(logging.ERROR):
                logger.error(
                    f"Error in Gemini Cloud Project chat_completions: {e}",
                    exc_info=True,
                )
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

            # request_data is expected to be a CanonicalChatRequest already
            # (the frontend controller converts from frontend-specific format to domain format)
            # Backends should ONLY convert FROM domain TO backend-specific format
            canonical_request = request_data

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

            # Prepare request body with USER'S project ID
            request_body = {
                "model": effective_model,
                "project": project_id,  # User's GCP project
                "user_prompt_id": self._generate_user_prompt_id(request_data),
                "request": code_assist_request,
            }

            url = f"{self.gemini_api_base_url}/v1internal:streamGenerateContent"
            if logger.isEnabledFor(logging.INFO):
                logger.info(f"Making Code Assist API call with project {project_id}")

            # Use tuple for (connect_timeout, read_timeout) to handle large responses
            try:
                response = await asyncio.to_thread(
                    auth_session.request,
                    method="POST",
                    url=url,
                    params={"alt": "sse"},
                    json=request_body,
                    headers={"Content-Type": "application/json"},
                    timeout=(DEFAULT_CONNECTION_TIMEOUT, DEFAULT_READ_TIMEOUT),
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
            domain_response = None

            response_text = response.text
            for line in response_text.split("\n"):
                if line.startswith("data: "):
                    data_str = line[6:].strip()
                    if data_str == "[DONE]":
                        break
                    try:
                        data = json.loads(data_str)
                        domain_response = self.translation_service.to_domain_response(
                            response=data,
                            source_format="code_assist",
                        )
                        if (
                            domain_response.choices
                            and domain_response.choices[0].message.content
                        ):
                            generated_text += domain_response.choices[0].message.content
                    except json.JSONDecodeError:
                        continue

            # Convert to OpenAI-compatible format using the translation service
            if not domain_response:
                raise BackendError("Failed to parse a valid response from the backend.")
            openai_response = self.translation_service.from_domain_response(
                response=domain_response,
                target_format="openai",
            ).model_dump(exclude_unset=True)

            if logger.isEnabledFor(logging.INFO):
                logger.info(
                    f"Successfully received response from Code Assist API for project {project_id}"
                )
            return ResponseEnvelope(
                content=openai_response, headers={}, status_code=200
            )

        except (AuthenticationError, BackendError):
            raise
        except Exception as e:
            if logger.isEnabledFor(logging.ERROR):
                logger.error(f"Unexpected error during API call: {e}", exc_info=True)
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

            # request_data is expected to be a CanonicalChatRequest already
            # (the frontend controller converts from frontend-specific format to domain format)
            # Backends should ONLY convert FROM domain TO backend-specific format
            canonical_request = request_data

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

            # Prepare request body with USER'S project ID
            request_body = {
                "model": effective_model,
                "project": project_id,
                "user_prompt_id": self._generate_user_prompt_id(request_data),
                "request": code_assist_request,
            }

            url = f"{self.gemini_api_base_url}/v1internal:streamGenerateContent"
            if logger.isEnabledFor(logging.INFO):
                logger.info(
                    f"Making streaming Code Assist API call with project {project_id}"
                )

            async def stream_generator() -> AsyncGenerator[ProcessedResponse, None]:
                response = None
                try:
                    # Use tuple for (connect_timeout, read_timeout) to allow longer streaming
                    # CRITICAL: Add stream=True to enable real-time streaming
                    try:
                        response = await asyncio.to_thread(
                            auth_session.request,
                            method="POST",
                            url=url,
                            params={"alt": "sse"},
                            json=request_body,
                            headers={"Content-Type": "application/json"},
                            timeout=(DEFAULT_CONNECTION_TIMEOUT, DEFAULT_READ_TIMEOUT),
                            stream=True,  # Enable streaming mode for real-time data
                        )
                    except requests.exceptions.Timeout as te:  # type: ignore[attr-defined]
                        if logger.isEnabledFor(logging.ERROR):
                            logger.error(
                                f"Streaming timeout calling {url}: {te}", exc_info=True
                            )
                        yield self.translation_service.to_domain_stream_chunk(
                            chunk=None, source_format="code_assist"
                        )
                        return
                    except requests.exceptions.RequestException as rexc:  # type: ignore[attr-defined]
                        if logger.isEnabledFor(logging.ERROR):
                            logger.error(
                                f"Streaming connection error calling {url}: {rexc}",
                                exc_info=True,
                            )
                        yield self.translation_service.to_domain_stream_chunk(
                            chunk=None, source_format="code_assist"
                        )
                        return

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

                    # Process the streaming response using iter_content for real-time streaming
                    # Use iter_content instead of iter_lines to avoid buffering complete lines
                    line_buffer = ""
                    for chunk in response.iter_content(
                        chunk_size=1, decode_unicode=False
                    ):  # Read byte-by-byte for real-time streaming
                        try:
                            # Decode chunk to string
                            char = chunk.decode("utf-8")
                            line_buffer += char

                            # Check if we have a complete line (ends with \n)
                            if char == "\n":
                                decoded_line = line_buffer.rstrip("\r\n")
                                line_buffer = ""  # Reset buffer for next line

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
                                        domain_chunk = self.translation_service.to_domain_stream_chunk(
                                            chunk=data,  # Pass the parsed JSON data
                                            source_format="code_assist",
                                        )
                                        yield domain_chunk
                                    except json.JSONDecodeError:
                                        # If it's not JSON, it might be an empty line or comment, skip
                                        continue
                                elif decoded_line.strip():
                                    # Handle non-data lines (e.g., comments, event types) if necessary
                                    yield self.translation_service.to_domain_stream_chunk(
                                        chunk={
                                            "text": decoded_line
                                        },  # Wrap in a dict for consistency
                                        source_format="raw_text",  # Or a more specific raw format
                                    )
                        except UnicodeDecodeError:
                            # Skip invalid UTF-8 bytes
                            continue
                        except Exception as chunk_error:
                            if logger.isEnabledFor(logging.ERROR):
                                logger.error(
                                    f"Error processing stream chunk: {chunk_error}",
                                    exc_info=True,
                                )
                            continue

                    # Ensure the stream is properly closed with a DONE signal
                    yield self.translation_service.to_domain_stream_chunk(
                        chunk=None,  # Indicate end of stream
                        source_format="code_assist",
                    )

                except Exception as e:
                    if logger.isEnabledFor(logging.ERROR):
                        logger.error(f"Error in streaming generator: {e}")
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

        except (AuthenticationError, BackendError):
            raise
        except Exception as e:
            if logger.isEnabledFor(logging.ERROR):
                logger.error(
                    f"Unexpected error during streaming API call: {e}", exc_info=True
                )
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
            if logger.isEnabledFor(logging.INFO):
                logger.info(
                    f"Project {self._onboarded_project_id} is already onboarded"
                )
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

        if confirmed_project_id != self.gcp_project_id and logger.isEnabledFor(
            logging.WARNING
        ):
            logger.warning(
                f"Project ID mismatch: expected {self.gcp_project_id}, got {confirmed_project_id}"
            )

        self._onboarded_project_id = confirmed_project_id
        if logger.isEnabledFor(logging.INFO):
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

    def __del__(self):
        """Cleanup file watcher on destruction."""
        self._stop_file_watching()


backend_registry.register_backend(
    "gemini-cli-cloud-project", GeminiCloudProjectConnector
)
