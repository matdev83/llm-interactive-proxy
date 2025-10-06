r"""
OpenAI OAuth connector that uses ChatGPT/Codex auth.json tokens instead of API keys.

This backend reads a local `auth.json` file (created by Codex CLI via ChatGPT login)
and uses `tokens.access_token` as the bearer for OpenAI API requests. If the file
also contains `OPENAI_API_KEY`, that is used as a fallback.

Default credential file locations (first that exists is used):
- Windows: %USERPROFILE%\.codex\auth.json
- Cross-platform: ~/.codex/auth.json

Configuration:
- `openai_oauth_path`: optional directory that contains `auth.json` (overrides defaults)
- `openai_api_base_url`: optional base URL override (default: https://api.openai.com/v1)
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import threading
import time
from pathlib import Path
from typing import TYPE_CHECKING, Any

import httpx
from fastapi import HTTPException
from watchdog.events import FileSystemEventHandler
from watchdog.observers import Observer

if TYPE_CHECKING:
    from watchdog.observers.api import BaseObserver

from src.connectors.openai import OpenAIConnector
from src.core.common.exceptions import AuthenticationError
from src.core.config.app_config import AppConfig
from src.core.services.backend_registry import backend_registry
from src.core.services.translation_service import TranslationService

logger = logging.getLogger(__name__)


class OpenAICredentialsFileHandler(FileSystemEventHandler):
    """File watcher handler for OpenAI OAuth credentials."""

    def __init__(self, connector: OpenAIOAuthConnector) -> None:
        super().__init__()
        self.connector = connector

    def on_modified(self, event) -> None:  # type: ignore[no-untyped-def]
        """Handle file modification events."""
        if not event.is_directory:
            # Compare paths using Path objects to handle Windows/Unix differences
            try:
                event_path = Path(event.src_path).resolve()
                auth_path = (
                    self.connector._auth_path.resolve()
                    if self.connector._auth_path
                    else None
                )

                if auth_path and event_path == auth_path:
                    logger.debug(
                        "OpenAI OAuth credentials file changed, scheduling reload"
                    )
                    self.connector._schedule_credentials_reload()
            except Exception as e:
                logger.error(f"Error processing file modification event: {e}")


class OpenAIOAuthConnector(OpenAIConnector):
    backend_type: str = "openai-oauth"

    def __init__(
        self,
        client: httpx.AsyncClient,
        config: AppConfig,
        response_processor: Any | None = None,
        translation_service: TranslationService | None = None,
    ) -> None:
        # Use explicit keywords to avoid argument order issues
        super().__init__(
            client=client,
            config=config,
            translation_service=translation_service,
            response_processor=response_processor,
        )
        self.name = "openai-oauth"
        self._oauth_dir_override: Path | None = None
        self._auth_path: Path | None = None
        self._last_modified: float = 0.0
        self.is_functional: bool = False

        # Stale token handling pattern attributes
        # Use BaseObserver for type checking to ensure stop/join are recognized by mypy
        self._file_observer: BaseObserver | None = None
        self._credential_validation_errors: list[str] = []
        self._initialization_failed: bool = False
        self._last_validation_time: float = 0.0
        self._pending_reload_task: asyncio.Future[None] | None = None
        self._auth_credentials: dict[str, Any] | None = None
        self._event_loop: asyncio.AbstractEventLoop | None = None
        self._reload_task_lock = threading.Lock()
        self._reload_scheduling_in_progress = False

        # Health checks are unnecessary for OAuth bearer flow in tests; disable by default
        import contextlib

        with contextlib.suppress(Exception):
            self.disable_health_check()

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
        logger.error(f"OpenAI OAuth initialization failed: {'; '.join(errors)}")

    def _degrade(self, errors: list[str]) -> None:
        """Mark backend as degraded due to runtime validation failures."""
        self.is_functional = False
        self._credential_validation_errors = errors
        logger.warning(f"OpenAI OAuth backend degraded: {'; '.join(errors)}")

    def _recover(self) -> None:
        """Mark backend as recovered after successful validation."""
        self.is_functional = True
        self._credential_validation_errors = []
        self._last_validation_time = time.time()
        logger.info("OpenAI OAuth backend recovered")

    # -----------------------------
    # Validation methods (stale token handling pattern)
    # -----------------------------
    def _validate_credentials_file_exists(self) -> tuple[bool, list[str]]:
        """Validate that credentials file exists and is readable."""
        errors = []

        auth_path = self._discover_auth_path()
        if auth_path is None:
            errors.append("OAuth credentials file not found in any default location")
            return False, errors

        if not auth_path.exists():
            errors.append(f"OAuth credentials file does not exist: {auth_path}")
            return False, errors

        if not auth_path.is_file():
            errors.append(f"OAuth credentials path is not a file: {auth_path}")
            return False, errors

        try:
            with open(auth_path, encoding="utf-8") as f:
                json.load(f)
        except json.JSONDecodeError as e:
            errors.append(f"OAuth credentials file contains invalid JSON: {e}")
            return False, errors
        except PermissionError:
            errors.append(f"No permission to read OAuth credentials file: {auth_path}")
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

        # Check for tokens.access_token or OPENAI_API_KEY
        access_token = None
        tokens = credentials.get("tokens")
        if isinstance(tokens, dict):
            tok = tokens.get("access_token")
            if isinstance(tok, str) and tok.strip():
                access_token = tok

        api_key = credentials.get("OPENAI_API_KEY")
        if not access_token and not (isinstance(api_key, str) and api_key.strip()):
            errors.append(
                "OAuth credentials missing required 'tokens.access_token' or 'OPENAI_API_KEY' field"
            )
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

        if self._auth_credentials is not None:
            ok, struct_errors = self._validate_credentials_structure(
                self._auth_credentials
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
        if self._auth_path is None or self._file_observer is not None:
            return

        try:
            self._file_observer = Observer()
            handler = OpenAICredentialsFileHandler(self)
            watch_dir = self._auth_path.parent
            self._file_observer.schedule(handler, str(watch_dir), recursive=False)
            self._file_observer.start()
            logger.debug(
                f"Started watching OpenAI OAuth credentials directory: {watch_dir}"
            )
        except Exception as e:
            logger.warning(
                f"Failed to start file watching for OpenAI OAuth credentials: {e}"
            )

    def _stop_file_watching(self) -> None:
        """Stop watching the credentials file for changes."""
        if self._file_observer is not None:
            try:
                self._file_observer.stop()
                self._file_observer.join(timeout=1.0)
            except Exception as e:
                logger.debug(f"Error stopping OpenAI OAuth file watcher: {e}")
            finally:
                self._file_observer = None

    def _schedule_credentials_reload(self) -> None:
        """Schedule an asynchronous reload of credentials.

        This method is called when the file system watcher detects a change to the
        auth.json file. It forces a reload of credentials bypassing the cache
        to ensure the latest token is loaded even if the file timestamp didn't change.
        """
        with self._reload_task_lock:
            if (
                self._pending_reload_task is not None
                and not self._pending_reload_task.done()
            ):
                return
            if self._reload_scheduling_in_progress:
                return
            self._reload_scheduling_in_progress = True

        async def reload_task() -> None:
            try:
                logger.debug("Reloading OpenAI OAuth credentials due to file change")
                # Use force_reload=True to bypass cache
                try:
                    loaded = await self._load_auth(force_reload=True)
                except TypeError:
                    loaded = await self._load_auth()
                if loaded:
                    if self._auth_credentials is not None:
                        ok, errors = self._validate_credentials_structure(
                            self._auth_credentials
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
                logger.error(f"Error during OpenAI OAuth credentials reload: {e}")
                self._degrade([f"Credentials reload failed: {e}"])

        loop = self._event_loop
        if loop is None:
            try:
                loop = asyncio.get_running_loop()
            except RuntimeError:
                logger.warning(
                    "Cannot schedule credentials reload: no running event loop available."
                )
                with self._reload_task_lock:
                    self._reload_scheduling_in_progress = False
                return
            self._event_loop = loop

        if loop.is_closed():
            logger.warning("Cannot schedule credentials reload: event loop is closed.")
            with self._reload_task_lock:
                self._reload_scheduling_in_progress = False
            return

        def _clear(_: asyncio.Future[Any]) -> None:
            with self._reload_task_lock:
                self._pending_reload_task = None
                self._reload_scheduling_in_progress = False

        def _assign_task(task: asyncio.Future[None]) -> None:
            task.add_done_callback(_clear)
            with self._reload_task_lock:
                self._pending_reload_task = task
                self._reload_scheduling_in_progress = False

        try:
            try:
                running_loop = asyncio.get_running_loop()
            except RuntimeError:
                running_loop = None

            if running_loop is loop:
                task = loop.create_task(reload_task())
                _assign_task(task)
                return

            def schedule_task() -> None:
                try:
                    task = loop.create_task(reload_task())
                    _assign_task(task)
                except Exception as exc:
                    logger.warning(
                        "Failed to schedule OpenAI OAuth credentials reload: %s", exc
                    )
                    with self._reload_task_lock:
                        self._reload_scheduling_in_progress = False

            loop.call_soon_threadsafe(schedule_task)
        except RuntimeError as exc:
            logger.warning(
                "Failed to schedule OpenAI OAuth credentials reload: %s", exc
            )
            with self._reload_task_lock:
                self._reload_scheduling_in_progress = False

    def _default_auth_paths(self) -> list[Path]:
        paths: list[Path] = []
        userprofile = os.getenv("USERPROFILE")
        if userprofile:
            paths.append(Path(userprofile) / ".codex" / "auth.json")
        # Cross-platform default
        paths.append(Path.home() / ".codex" / "auth.json")
        return paths

    def _discover_auth_path(self) -> Path | None:
        if self._oauth_dir_override is not None:
            return self._oauth_dir_override / "auth.json"
        for p in self._default_auth_paths():
            if p.exists():
                return p
        return None

    async def _load_auth(self, force_reload: bool = False) -> bool:
        """Load OAuth credentials from auth.json file.

        Args:
            force_reload: If True, bypass cache and force reload from file even if timestamp unchanged

        Returns:
            bool: True if credentials loaded successfully, False otherwise
        """
        auth_path = self._discover_auth_path()
        if auth_path is None:
            logger.warning("OpenAI OAuth auth.json not found in default locations")
            return False

        self._auth_path = auth_path
        try:
            # Check if file has been modified since last load (unless force_reload is True)
            if not force_reload:
                try:
                    mtime = auth_path.stat().st_mtime
                    if mtime == self._last_modified and self.api_key:
                        logger.debug(
                            "OpenAI OAuth credentials file not modified, using cached."
                        )
                        return True
                except OSError:
                    pass

            # Update last modified time
            try:
                mtime = auth_path.stat().st_mtime
                self._last_modified = mtime
            except OSError:
                pass

            with open(auth_path, encoding="utf-8") as f:
                data: dict[str, Any] = json.load(f)

            token: str | None = None
            # Prefer ChatGPT OAuth access token
            tokens = data.get("tokens")
            if isinstance(tokens, dict):
                tok = tokens.get("access_token")
                if isinstance(tok, str) and tok:
                    token = tok
            # Fallback to OPENAI_API_KEY if present
            if not token:
                api_key = data.get("OPENAI_API_KEY")
                if isinstance(api_key, str) and api_key:
                    token = api_key

            if not token:
                logger.warning(
                    "OpenAI OAuth auth.json missing tokens.access_token and OPENAI_API_KEY"
                )
                return False

            # Set as API key for parent header logic
            self.api_key = token
            # Store credentials for validation
            self._auth_credentials = data
            log_msg = "Successfully loaded OpenAI OAuth credentials"
            if force_reload:
                log_msg += " (force reload)"
            logger.info(log_msg + ".")
            return True
        except json.JSONDecodeError as e:
            logger.error("Malformed auth.json for OpenAI OAuth: %s", e, exc_info=True)
            return False
        except Exception as e:
            logger.error(
                "Failed to load OpenAI OAuth credentials: %s", e, exc_info=True
            )
            return False

    async def initialize(self, **kwargs: Any) -> None:  # type: ignore[override]
        """Initialize backend with enhanced validation using stale token handling pattern."""
        logger.info("Initializing OpenAI OAuth backend with enhanced validation.")

        try:
            self._event_loop = asyncio.get_running_loop()
        except RuntimeError:
            self._event_loop = None

        # Allow base URL override
        base = kwargs.get("openai_api_base_url") or kwargs.get("api_base_url")
        if isinstance(base, str) and base:
            self.api_base_url = base

        # Optional directory override for auth.json
        dir_override = kwargs.get("openai_oauth_path")
        if isinstance(dir_override, str) and dir_override:
            self._oauth_dir_override = Path(dir_override)

        # 1) File exists + readable + parseable
        ok, errors = self._validate_credentials_file_exists()
        if not ok:
            self._fail_init(errors)
            return

        # 2) Load credentials into memory
        if not await self._load_auth():
            self._fail_init(["Failed to load credentials despite validation passing"])
            return

        # 3) Structure validation
        if self._auth_credentials is not None:
            ok, errors = self._validate_credentials_structure(self._auth_credentials)
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

        # Optionally prefetch models (non-fatal if it fails)
        import contextlib

        with contextlib.suppress(Exception):
            await self.list_models()

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
                    "error": "openai_oauth_credentials_invalid",
                    "message": f"OpenAI OAuth credentials validation failed: {'; '.join(errors)}",
                    "details": {
                        "backend": self.name,
                        "validation_errors": errors,
                        "suggestion": "Please check your OAuth credentials file and ensure it contains valid tokens.access_token or OPENAI_API_KEY",
                    },
                },
            )

        # Ensure we have a token loaded just before the call
        if not await self._load_auth():
            self._degrade(["Failed to load OAuth credentials"])
            raise HTTPException(
                status_code=502,
                detail={
                    "error": "openai_oauth_credentials_unavailable",
                    "message": "No valid OpenAI OAuth credentials available",
                    "details": {
                        "backend": self.name,
                        "suggestion": "Run codex login or set openai_oauth_path to the directory containing auth.json",
                    },
                },
            )

        # Delegate to parent with our token
        try:
            result = await super().chat_completions(
                request_data=request_data,
                processed_messages=processed_messages,
                effective_model=effective_model,
                identity=identity,
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

    def __del__(self) -> None:
        """Cleanup file watcher on destruction."""
        self._stop_file_watching()


backend_registry.register_backend("openai-oauth", OpenAIOAuthConnector)
