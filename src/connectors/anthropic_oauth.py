"""
Anthropic OAuth connector that uses a locally stored OAuth credential file
to obtain an access token and call Anthropic's Messages API without a user
configured API key.

This mirrors the pattern used by other oauth-based backends in this project
(e.g., Qwen OAuth, Gemini OAuth Personal):

- Loads credentials from a JSON file (default locations are probed; a custom
  directory may be provided via init kwarg `anthropic_oauth_path`).
- Expects an `access_token` field; falls back to `api_key` if present.
- Uses the token in the `x-api-key` header together with the standard
  `anthropic-version` header used by the base Anthropic backend.
- Refresh policy: we do not attempt protocol token refresh (no public endpoint);
  instead we reload the file on changes or when initialize is called.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
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

from src.connectors.anthropic import (
    ANTHROPIC_DEFAULT_BASE_URL,
    AnthropicBackend,
)
from src.core.common.exceptions import AuthenticationError
from src.core.config.app_config import AppConfig
from src.core.services.backend_registry import backend_registry
from src.core.services.translation_service import TranslationService

logger = logging.getLogger(__name__)


class AnthropicCredentialsFileHandler(FileSystemEventHandler):
    """File watcher handler for Anthropic OAuth credentials."""

    def __init__(self, connector: AnthropicOAuthBackend) -> None:
        super().__init__()
        self.connector = connector

    def on_modified(self, event) -> None:  # type: ignore[no-untyped-def]
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
                    logger.debug(
                        "Anthropic OAuth credentials file changed, scheduling reload"
                    )
                    self.connector._schedule_credentials_reload()
            except Exception as e:
                if logger.isEnabledFor(logging.ERROR):
                    logger.error(f"Error processing file modification event: {e}")


class AnthropicOAuthBackend(AnthropicBackend):
    """Connector that uses a locally stored OAuth token for Anthropic.

    The token is read from an oauth_creds.json file. By default, we probe a set of
    well-known directories; callers may override the directory via the
    `anthropic_oauth_path` initialization parameter.
    """

    backend_type: str = "anthropic-oauth"

    def __init__(
        self,
        client: httpx.AsyncClient,
        config: AppConfig,
        translation_service: TranslationService,
    ) -> None:
        super().__init__(client, config, translation_service)
        self.name = "anthropic-oauth"
        self.is_functional: bool = False
        self._oauth_credentials: dict[str, Any] | None = None
        self._credentials_path: Path | None = None
        self._last_modified: float = 0.0
        # Optional override for credential directory
        self._oauth_dir_override: Path | None = None

        # Stale token handling pattern attributes
        # Use BaseObserver for type checking to ensure stop/join are recognized by mypy
        self._file_observer: BaseObserver | None = None
        self._credential_validation_errors: list[str] = []
        self._initialization_failed: bool = False
        self._last_validation_time: float = 0.0
        self._pending_reload_task: asyncio.Task[None] | Future[None] | None = None
        self._event_loop: asyncio.AbstractEventLoop | None = None

    # -----------------------------
    # Health Tracking API (stale token handling pattern)
    # -----------------------------
    def is_backend_functional(self) -> bool:
        """Return True if the backend is functional and ready to serve requests."""
        return self.is_functional and not self._initialization_failed

    def get_validation_errors(self) -> list[str]:
        """Return list of validation errors encountered during initialization or runtime."""
        return self._credential_validation_errors.copy()

    def _fail_init(self, errors: list[str]) -> None:
        """Mark initialization as failed with given errors."""
        self._initialization_failed = True
        self.is_functional = False
        self._credential_validation_errors = errors
        logger.error(f"Anthropic OAuth initialization failed: {'; '.join(errors)}")

    def _degrade(self, errors: list[str]) -> None:
        """Mark backend as degraded due to runtime validation failures."""
        self.is_functional = False
        self._credential_validation_errors = errors
        logger.warning(f"Anthropic OAuth backend degraded: {'; '.join(errors)}")

    def _recover(self) -> None:
        """Mark backend as recovered after successful validation."""
        self.is_functional = True
        self._credential_validation_errors = []
        self._last_validation_time = time.time()
        logger.info("Anthropic OAuth backend recovered")

    # -----------------------------
    # Validation methods (stale token handling pattern)
    # -----------------------------
    def _validate_credentials_file_exists(self) -> tuple[bool, list[str]]:
        """Validate that credentials file exists and is readable."""
        errors = []

        creds_path = self._discover_credentials_path()
        if creds_path is None:
            errors.append("OAuth credentials file not found in any default location")
            return False, errors

        if not creds_path.exists():
            errors.append(f"OAuth credentials file does not exist: {creds_path}")
            return False, errors

        if not creds_path.is_file():
            errors.append(f"OAuth credentials path is not a file: {creds_path}")
            return False, errors

        try:
            with open(creds_path, encoding="utf-8") as f:
                json.load(f)
        except json.JSONDecodeError as e:
            errors.append(f"OAuth credentials file contains invalid JSON: {e}")
            return False, errors
        except PermissionError:
            errors.append(f"No permission to read OAuth credentials file: {creds_path}")
            return False, errors
        except Exception as e:
            errors.append(f"Error reading OAuth credentials file: {e}")
            return False, errors

        return True, errors

    def _validate_credentials_structure(
        self, credentials: dict[str, Any]
    ) -> tuple[bool, list[str]]:
        """Validate OAuth credentials structure and content."""
        errors = []

        if not isinstance(credentials, dict):
            errors.append("OAuth credentials must be a JSON object")
            return False, errors

        # Check for access_token or api_key
        access_token = credentials.get("access_token")
        api_key = credentials.get("api_key")

        if not access_token and not api_key:
            errors.append(
                "OAuth credentials missing required 'access_token' or 'api_key' field"
            )
            return False, errors

        token = access_token or api_key
        if not isinstance(token, str) or not token.strip():
            errors.append("OAuth credentials token must be a non-empty string")
            return False, errors

        return True, errors

    def _validate_runtime_credentials(self) -> tuple[bool, list[str]]:
        """Validate credentials at runtime with throttling."""
        # Simple throttling: only validate once per 30 seconds
        current_time = time.time()
        if current_time - self._last_validation_time < 30:
            return True, []

        # Validate file existence and structure
        ok, errors = self._validate_credentials_file_exists()
        if not ok:
            return False, errors

        if self._oauth_credentials is not None:
            ok, struct_errors = self._validate_credentials_structure(
                self._oauth_credentials
            )
            if not ok:
                errors.extend(struct_errors)
                return False, errors
        else:
            errors.append("OAuth credentials not loaded in memory")
            return False, errors

        self._last_validation_time = current_time
        return True, errors

    # -----------------------------
    # File watching methods (stale token handling pattern)
    # -----------------------------
    def _start_file_watching(self) -> None:
        """Start watching the credentials file for changes."""
        if self._credentials_path is None or self._file_observer is not None:
            return

        try:
            self._file_observer = Observer()
            handler = AnthropicCredentialsFileHandler(self)
            watch_dir = self._credentials_path.parent
            self._file_observer.schedule(handler, str(watch_dir), recursive=False)
            self._file_observer.start()
            logger.debug(
                f"Started watching Anthropic OAuth credentials directory: {watch_dir}"
            )
        except Exception as e:
            logger.warning(
                f"Failed to start file watching for Anthropic OAuth credentials: {e}"
            )

    def _stop_file_watching(self) -> None:
        """Stop watching the credentials file for changes."""
        if self._file_observer is not None:
            try:
                self._file_observer.stop()
                self._file_observer.join(timeout=1.0)
            except Exception as e:
                logger.debug(f"Error stopping Anthropic OAuth file watcher: {e}")
            finally:
                self._file_observer = None

    def _schedule_credentials_reload(self) -> None:
        """Schedule an asynchronous reload of credentials."""
        pending = self._pending_reload_task
        if pending is not None and not pending.done():
            return  # Already have a reload pending

        async def reload_task() -> None:
            """Reload credentials from file with force_reload to bypass cache."""
            try:
                logger.debug("Reloading Anthropic OAuth credentials due to file change")
                loaded = await self._load_oauth_credentials(force_reload=True)
                if loaded:
                    if self._oauth_credentials is not None:
                        ok, errors = self._validate_credentials_structure(
                            self._oauth_credentials
                        )
                        if ok:
                            self._recover()
                        else:
                            self._degrade(errors)
                    else:
                        self._degrade(
                            ["Failed to load credentials despite successful file read"]
                        )
                else:
                    self._degrade(["Failed to reload credentials from file"])
            except Exception as e:
                logger.error(f"Error during Anthropic OAuth credentials reload: {e}")
                self._degrade([f"Credentials reload failed: {e}"])

        try:
            current_loop = asyncio.get_running_loop()
        except RuntimeError:
            current_loop = None

        target_loop = None
        if current_loop and current_loop.is_running():
            target_loop = current_loop
        elif self._event_loop and self._event_loop.is_running():
            target_loop = self._event_loop

        if target_loop is None or target_loop.is_closed():
            if logger.isEnabledFor(logging.WARNING):
                logger.warning(
                    "Cannot schedule Anthropic OAuth credentials reload: no running event loop available."
                )
            return

        if target_loop is not self._event_loop:
            self._event_loop = target_loop

        def _clear(_: Any) -> None:
            self._pending_reload_task = None

        if target_loop is current_loop:
            task = target_loop.create_task(reload_task())
            task.add_done_callback(_clear)
            self._pending_reload_task = task
            return

        try:
            future = asyncio.run_coroutine_threadsafe(reload_task(), target_loop)
            future.add_done_callback(_clear)
            self._pending_reload_task = future
        except RuntimeError as exc:
            if logger.isEnabledFor(logging.WARNING):
                logger.warning(
                    "Failed to schedule Anthropic OAuth credentials reload: %s", exc
                )

    # -----------------------------
    # Credential loading utilities
    # -----------------------------
    def _default_oauth_dirs(self) -> list[Path]:
        """Return candidate directories that may contain oauth_creds.json.

        We probe several plausible locations so users can rely on auto-discovery
        (mirroring our other oauth connectors):
        - ~/.anthropic
        - ~/.claude
        - ~/.config/claude (Linux)
        - %APPDATA%/Claude (Windows)
        """
        home = Path.home()
        candidates: list[Path] = [home / ".anthropic", home / ".claude"]
        # Linux/XDG style
        candidates.append(home / ".config" / "claude")
        # Windows roaming AppData
        appdata = os.getenv("APPDATA")
        if appdata:
            candidates.append(Path(appdata) / "Claude")
        return candidates

    def _discover_credentials_path(self) -> Path | None:
        """Determine the oauth_creds.json path to use."""
        if self._oauth_dir_override is not None:
            return self._oauth_dir_override / "oauth_creds.json"

        for d in self._default_oauth_dirs():
            p = d / "oauth_creds.json"
            if p.exists():
                return p
        return None

    async def _load_oauth_credentials(self, force_reload: bool = False) -> bool:
        """Load OAuth credentials from oauth_creds.json if available.

        Args:
            force_reload: If True, bypass cache and force reload from file even if timestamp unchanged

        Returns:
            bool: True when credentials were successfully loaded (or cached and
            unchanged), False otherwise.
        """
        creds_path = self._discover_credentials_path()
        if creds_path is None:
            if logger.isEnabledFor(logging.WARNING):
                logger.warning(
                    "Anthropic OAuth credentials file not found in default paths"
                )
            return False

        self._credentials_path = creds_path

        try:
            # Short-circuit if unchanged and we have a cached value (unless force_reload is True)
            if not force_reload:
                try:
                    mtime = creds_path.stat().st_mtime
                    if (
                        mtime == self._last_modified
                        and self._oauth_credentials is not None
                    ):
                        return True
                except OSError:
                    # If we fail to stat, attempt to read anyway
                    pass

            # Update last modified time
            try:
                mtime = creds_path.stat().st_mtime
                self._last_modified = mtime
            except OSError:
                pass

            with open(creds_path, encoding="utf-8") as f:
                data: dict[str, Any] = json.load(f)

            # We expect an access_token (preferred) or api_key
            token: str | None = None
            if isinstance(data, dict):
                token = (
                    str(data.get("access_token"))
                    if data.get("access_token") is not None
                    else (
                        str(data.get("api_key"))
                        if data.get("api_key") is not None
                        else None
                    )
                )

            if not token:
                if logger.isEnabledFor(logging.WARNING):
                    logger.warning(
                        "Anthropic OAuth credentials missing access_token/api_key"
                    )
                return False

            self._oauth_credentials = data
            # Set api_key on the base class so parent logic can operate normally
            self.api_key = token
            self.key_name = self.backend_type

            log_msg = "Successfully loaded Anthropic OAuth credentials"
            if force_reload:
                log_msg += " (force reload)"
            if logger.isEnabledFor(logging.INFO):
                logger.info(log_msg + ".")
            return True

        except json.JSONDecodeError as e:
            if logger.isEnabledFor(logging.ERROR):
                logger.error(f"Malformed Anthropic OAuth credentials JSON: {e}")
            return False
        except Exception as e:
            if logger.isEnabledFor(logging.ERROR):
                logger.error(f"Error loading Anthropic OAuth credentials: {e}")
            return False

    # -----------------------------
    # LLMBackend API
    # -----------------------------
    async def initialize(self, **kwargs: Any) -> None:  # type: ignore[override]
        """Initialize backend with enhanced validation using stale token handling pattern."""
        logger.info("Initializing Anthropic OAuth backend with enhanced validation.")

        try:
            self._event_loop = asyncio.get_running_loop()
        except RuntimeError:
            self._event_loop = None

        # Allow overriding the oauth dir (directory containing oauth_creds.json)
        override = kwargs.get("anthropic_oauth_path")
        if isinstance(override, str) and override:
            self._oauth_dir_override = Path(override)

        # Base URL override or default
        self.anthropic_api_base_url = kwargs.get(
            "anthropic_api_base_url", ANTHROPIC_DEFAULT_BASE_URL
        )

        # 1) File exists + readable + parseable
        ok, errors = self._validate_credentials_file_exists()
        if not ok:
            self._fail_init(errors)
            return

        # 2) Load credentials into memory
        if not await self._load_oauth_credentials():
            self._fail_init(["Failed to load credentials despite validation passing"])
            return

        # 3) Structure validation
        if self._oauth_credentials is not None:
            ok, errors = self._validate_credentials_structure(self._oauth_credentials)
            if not ok:
                self._fail_init(errors)
                return
        else:
            self._fail_init(["OAuth credentials are None after loading"])
            return

        # 4) Start file watching and mark functional
        self._start_file_watching()
        self.is_functional = True
        self._last_validation_time = time.time()
        logger.info(f"Credentials file validation passed for {self.name}.")

        # Do not fetch models during init to avoid unnecessary outbound calls in tests;
        # they'll be lazily fetched on first use via _ensure_models_loaded in the parent.

    async def chat_completions(  # type: ignore[override]
        self,
        request_data: Any,
        processed_messages: list[Any],
        effective_model: str,
        identity: Any | None = None,
        **kwargs: Any,
    ):
        # Runtime validation with throttling
        ok, errors = self._validate_runtime_credentials()
        if not ok:
            self._degrade(errors)
            raise HTTPException(
                status_code=502,
                detail={
                    "error": "anthropic_oauth_credentials_invalid",
                    "message": f"Anthropic OAuth credentials validation failed: {'; '.join(errors)}",
                    "details": {
                        "backend": self.name,
                        "validation_errors": errors,
                        "suggestion": "Please check your OAuth credentials file and ensure it contains valid access_token or api_key",
                    },
                },
            )

        # Ensure we have a token loaded just before the call
        if not await self._load_oauth_credentials():
            self._degrade(["Failed to load OAuth credentials"])
            raise HTTPException(
                status_code=502,
                detail={
                    "error": "anthropic_oauth_credentials_unavailable",
                    "message": "No valid Anthropic OAuth credentials available",
                    "details": {
                        "backend": self.name,
                        "suggestion": "Please authenticate using Claude Code or provide a valid oauth_creds.json",
                    },
                },
            )

        # Delegate to parent with our token (set on self.api_key)
        try:
            result = await super().chat_completions(
                request_data=request_data,
                processed_messages=processed_messages,
                effective_model=effective_model,
                identity=identity,
                api_key=self.api_key,
                **kwargs,
            )
            # If we reach here, the call was successful - mark as recovered if we were degraded
            if not self.is_functional:
                self._recover()
            return result
        except Exception as e:
            # Check if it's an auth-related error and degrade accordingly
            if (
                isinstance(e, AuthenticationError | HTTPException)
                and hasattr(e, "status_code")
                and e.status_code in (401, 403)
            ):
                self._degrade([f"Authentication failed: {e!s}"])
            raise

    def get_available_models(self) -> list[str]:
        return super().get_available_models()

    def __del__(self) -> None:
        """Cleanup file watcher on destruction."""
        self._stop_file_watching()


# Register in backend registry
backend_registry.register_backend("anthropic-oauth", AnthropicOAuthBackend)
