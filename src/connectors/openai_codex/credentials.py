"""Credential management for OpenAI Codex connector.

This module provides CredentialManager and CredentialWatcher services
for loading, validating, refreshing, and watching credential files.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import os
import tempfile
import threading
from collections.abc import Callable
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Any, cast

import httpx
from watchdog.events import FileSystemEventHandler
from watchdog.observers import Observer

from src.connectors.openai_codex.interfaces import ICredentialManager

if TYPE_CHECKING:
    from watchdog.observers.api import BaseObserver

logger = logging.getLogger(__name__)


class OpenAICredentialsFileHandler(FileSystemEventHandler):
    """File watcher handler for OpenAI Codex credentials."""

    def __init__(self, target: Any) -> None:
        super().__init__()
        self._target = target

    @staticmethod
    def _resolve_schedule_callback(target: Any) -> Callable[[], None] | None:
        """Resolve the callback used to schedule credential reloads."""
        watcher = getattr(target, "_watcher", None)
        if watcher is not None and hasattr(watcher, "schedule_reload"):
            callback = watcher.schedule_reload
            if callable(callback):
                return cast(Callable[[], None], callback)
            return None
        if hasattr(target, "_schedule_credentials_reload"):
            callback = target._schedule_credentials_reload
            if callable(callback):
                return cast(Callable[[], None], callback)
            return None
        return None

    def on_modified(self, event: Any) -> None:
        """Handle file modification events."""
        if not event.is_directory and isinstance(event.src_path, str):
            # Compare paths using Path objects to handle Windows/Unix differences
            try:
                event_path = Path(event.src_path).resolve()
                auth_path = getattr(self._target, "_auth_path", None)
                auth_path = auth_path.resolve() if isinstance(auth_path, Path) else None

                if auth_path and event_path == auth_path:
                    logger.debug(
                        "OpenAI Codex credentials file changed, scheduling reload"
                    )
                    schedule_reload = self._resolve_schedule_callback(self._target)
                    if schedule_reload is not None:
                        schedule_reload()
            except Exception as e:
                logger.error(
                    f"Error processing file modification event: {e}", exc_info=True
                )


class CredentialWatcher:
    """Manages file watching for credential changes with debounce."""

    def __init__(self, credential_manager: CredentialManager) -> None:
        """Initialize the credential watcher.

        Args:
            credential_manager: The CredentialManager instance to notify on changes
        """
        self._credential_manager = credential_manager
        self._observer: BaseObserver | None = None
        self._reload_scheduling_event = threading.Event()
        self._reload_task_lock = threading.Lock()
        self._pending_reload_task: asyncio.Future[None] | None = None
        self._event_loop: asyncio.AbstractEventLoop | None = None

    def start(self, auth_path: Path) -> None:
        """Start watching the credentials file for changes.

        Args:
            auth_path: Path to the auth.json file to watch
        """
        if self._observer is not None:
            return

        try:
            self._observer = Observer()
            handler = OpenAICredentialsFileHandler(self._credential_manager)
            watch_dir = auth_path.parent
            self._observer.schedule(handler, str(watch_dir), recursive=False)
            self._observer.start()
            logger.debug(
                f"Started watching OpenAI Codex credentials directory: {watch_dir}"
            )
        except Exception as e:
            logger.warning(
                f"Failed to start file watching for OpenAI Codex credentials: {e}"
            )

    def stop(self) -> None:
        """Stop watching the credentials file."""
        if self._observer is not None:
            try:
                self._observer.stop()
                self._observer.join(timeout=1.0)
            except Exception as e:
                logger.debug(f"Error stopping OpenAI Codex file watcher: {e}")
            finally:
                self._observer = None

    def is_running(self) -> bool:
        """Return True if the file watcher is active."""
        return self._observer is not None and self._observer.is_alive()

    async def cancel_pending_reload(self) -> None:
        """Cancel any pending reload task."""
        with self._reload_task_lock:
            if (
                self._pending_reload_task is not None
                and not self._pending_reload_task.done()
            ):
                self._pending_reload_task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await self._pending_reload_task
                self._pending_reload_task = None
        self._reload_scheduling_event.clear()

    def schedule_reload(self) -> None:
        """Schedule an asynchronous reload of credentials with debounce.

        This method ensures only one reload task per change window by using
        event gating and task tracking. Called when file watcher detects changes.
        """
        # Use threading.Event for thread-safe coordination
        if self._reload_scheduling_event.is_set():
            # Reload already in progress
            return

        with self._reload_task_lock:
            if (
                self._pending_reload_task is not None
                and not self._pending_reload_task.done()
            ):
                return
            self._reload_scheduling_event.set()

        async def reload_task() -> None:
            try:
                logger.debug("Reloading OpenAI Codex credentials due to file change")
                # Use force_reload=True to bypass cache
                loaded = await self._credential_manager._load_auth(force_reload=True)
                if loaded:
                    if self._credential_manager._auth_credentials is not None:
                        ok, errors = (
                            self._credential_manager._validate_credentials_structure(
                                self._credential_manager._auth_credentials
                            )
                        )
                        if not ok:
                            logger.warning(
                                f"Credential structure validation failed after reload: {'; '.join(errors)}"
                            )
                else:
                    logger.warning("Failed to reload credentials from file")
            except Exception as e:
                logger.error(f"Error during OpenAI Codex credentials reload: {e}")

        loop = self._event_loop
        if loop is None:
            try:
                loop = asyncio.get_running_loop()
            except RuntimeError:
                logger.warning(
                    "Cannot schedule credentials reload: no running event loop available."
                )
                self._reload_scheduling_event.clear()
                return
            self._event_loop = loop

        if loop.is_closed():
            logger.warning("Cannot schedule credentials reload: event loop is closed.")
            self._reload_scheduling_event.clear()
            return

        def _clear(_: asyncio.Future[Any]) -> None:
            with self._reload_task_lock:
                self._pending_reload_task = None
            self._reload_scheduling_event.clear()

        def _assign_task(task: asyncio.Future[None]) -> None:
            task.add_done_callback(_clear)
            with self._reload_task_lock:
                self._pending_reload_task = task

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
                        "Failed to schedule OpenAI Codex credentials reload: %s", exc
                    )
                    self._reload_scheduling_event.clear()

            loop.call_soon_threadsafe(schedule_task)
        except RuntimeError as exc:
            logger.warning(
                "Failed to schedule OpenAI Codex credentials reload: %s", exc
            )
            self._reload_scheduling_event.clear()


class CredentialManager(ICredentialManager):
    """Manages credential loading, validation, refresh, and file watching.

    Note: Health tracking (e.g., _recover/_degrade methods) is the responsibility
    of the connector, not this service. This service focuses solely on credential
    lifecycle management. The connector can observe credential state changes
    and update its health status accordingly.
    """

    def __init__(self, http_client: httpx.AsyncClient) -> None:
        """Initialize the credential manager.

        Args:
            http_client: HTTP client for OAuth token refresh API calls
        """
        self._http_client = http_client
        self._auth_path: Path | None = None
        self._auth_credentials: dict[str, Any] | None = None
        self._last_modified: float = 0.0
        self._token_refresh_lock = asyncio.Lock()
        self._event_loop: asyncio.AbstractEventLoop | None = None
        self._oauth_dir_override: Path | None = None
        self._watcher = CredentialWatcher(self)

    def _default_auth_paths(self) -> list[Path]:
        """Return list of default auth.json paths to check."""
        paths: list[Path] = []
        userprofile = os.getenv("USERPROFILE")
        if userprofile:
            paths.append(Path(userprofile) / ".codex" / "auth.json")
        # Cross-platform default
        paths.append(Path.home() / ".codex" / "auth.json")
        return paths

    def _discover_auth_path(self) -> Path | None:
        """Discover the auth.json file path.

        Returns:
            Path to auth.json if found, None otherwise
        """
        # If auth_path was directly set (e.g., from initialize parameter), use it
        if self._auth_path is not None and self._auth_path.exists():
            return self._auth_path

        if self._oauth_dir_override is not None:
            candidate = self._oauth_dir_override / "auth.json"
            if candidate.exists():
                return candidate

        for p in self._default_auth_paths():
            if p.exists():
                return p
        return None

    async def _load_auth(self, force_reload: bool = False) -> bool:
        """Load OAuth credentials from auth.json file.

        Args:
            force_reload: If True, bypass cache and force reload from file

        Returns:
            True if credentials loaded successfully, False otherwise
        """
        auth_path = self._discover_auth_path()
        if auth_path is None:
            logger.warning("OpenAI Codex auth.json not found in default locations")
            return False

        self._auth_path = auth_path
        try:
            # Check if file has been modified since last load (unless force_reload is True)
            if not force_reload:
                try:
                    mtime = auth_path.stat().st_mtime
                    if mtime == self._last_modified and self.get_access_token():
                        logger.debug(
                            "OpenAI Codex credentials file not modified, using cached."
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

            # Store credentials for validation
            self._auth_credentials = data
            log_msg = "Successfully loaded OpenAI Codex credentials"
            if force_reload:
                log_msg += " (force reload)"
            logger.info(log_msg + ".")
            return True
        except json.JSONDecodeError as e:
            logger.error("Malformed auth.json for OpenAI Codex: %s", e, exc_info=True)
            return False
        except Exception as e:
            logger.error(
                "Failed to load OpenAI Codex credentials: %s", e, exc_info=True
            )
            return False

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

    async def initialize(self, auth_path: Path | None = None) -> None:
        """Load initial credentials and start watcher.

        Args:
            auth_path: Optional path to auth.json file (if None, will discover default)
        """
        try:
            self._event_loop = asyncio.get_running_loop()
        except RuntimeError:
            self._event_loop = None

        # Set directory override if provided (auth_path is a file, so use parent)
        if auth_path is not None:
            if auth_path.is_file():
                # Direct file path provided
                self._auth_path = auth_path
            else:
                # Directory path provided, look for auth.json inside
                self._oauth_dir_override = auth_path

        # 1) File exists + readable + parseable
        ok, errors = self._validate_credentials_file_exists()
        if not ok:
            logger.error(f"Credential validation failed: {'; '.join(errors)}")
            return

        # 2) Load credentials into memory
        if not await self._load_auth():
            logger.error("Failed to load credentials despite validation passing")
            return

        # 3) Structure validation
        if self._auth_credentials is not None:
            ok, errors = self._validate_credentials_structure(self._auth_credentials)
            if not ok:
                logger.error(
                    f"Credential structure validation failed: {'; '.join(errors)}"
                )
                return
        else:
            logger.error("OAuth credentials are None after loading")
            return

        # 4) Start file watching
        if self._auth_path is not None:
            # Store event loop reference in watcher for reload scheduling
            self._watcher._event_loop = self._event_loop
            self._watcher.start(self._auth_path)
        logger.info("Credentials initialized successfully.")

    async def refresh_access_token(self) -> bool:
        """Refresh the access token in a concurrency-safe manner.

        Returns:
            True if refresh succeeded, False otherwise
        """
        async with self._token_refresh_lock:
            logger.info(
                "Attempting to refresh OpenAI Codex access token after authentication failure."
            )
            # CRITICAL: Always reload credentials inside the lock to avoid race conditions
            # This ensures stale tokens aren't used by parallel coroutines
            await self._load_auth(force_reload=True)
            if not self._auth_credentials:
                logger.warning(
                    "Cannot refresh OpenAI Codex token: credentials not loaded."
                )
                return False

            tokens = self._auth_credentials.get("tokens")
            if not isinstance(tokens, dict):
                logger.warning(
                    "Cannot refresh OpenAI Codex token: tokens payload missing in auth.json."
                )
                return False

            refresh_token = tokens.get("refresh_token")
            if not isinstance(refresh_token, str) or not refresh_token:
                logger.warning(
                    "Cannot refresh OpenAI Codex token: refresh_token not present in auth.json."
                )
                return False

            payload = {
                "client_id": "app_EMoamEEZ73f0CkXaXp7hrann",
                "grant_type": "refresh_token",
                "refresh_token": refresh_token,
                "scope": "openid profile email",
            }

            try:
                response = await self._http_client.post(
                    "https://auth.openai.com/oauth/token",
                    json=payload,
                    headers={"Content-Type": "application/json"},
                    timeout=15.0,
                )
            except httpx.HTTPError as exc:
                logger.warning("Failed to refresh OpenAI Codex token: %s", exc)
                return False

            if response.status_code >= 400:
                body = response.text
                logger.warning(
                    "OpenAI Codex token refresh failed with status %s: %s",
                    response.status_code,
                    body,
                )
                return False

            try:
                token_response = response.json()
            except Exception as exc:
                logger.warning("Failed to parse OAuth token refresh response: %s", exc)
                return False

            access_token = token_response.get("access_token")
            new_refresh_token = token_response.get("refresh_token") or refresh_token
            id_token = token_response.get("id_token")
            if not isinstance(access_token, str) or not access_token:
                logger.warning("OAuth token refresh response missing access_token.")
                return False

            updated_credentials = deepcopy(self._auth_credentials)
            updated_tokens = updated_credentials.setdefault("tokens", {})
            updated_tokens["access_token"] = access_token
            updated_tokens["refresh_token"] = new_refresh_token
            if isinstance(id_token, str) and id_token:
                updated_tokens["id_token"] = id_token
            if isinstance(self._auth_path, Path):
                updated_credentials["last_refresh"] = datetime.now(
                    timezone.utc
                ).isoformat()

                # Use atomic write pattern to prevent file corruption
                try:
                    # Create temp file in same directory for atomic os.replace()
                    temp_fd, temp_path = tempfile.mkstemp(
                        dir=self._auth_path.parent,
                        prefix=".auth_",
                        suffix=".json.tmp",
                        text=True,
                    )
                    try:
                        with os.fdopen(temp_fd, "w", encoding="utf-8") as f:
                            json.dump(updated_credentials, f, indent=2)
                            f.write("\n")
                            f.flush()
                            os.fsync(f.fileno())  # Ensure written to disk
                        # Atomic replacement (cross-platform)
                        os.replace(temp_path, self._auth_path)
                    except Exception:
                        # Clean up temp file on error
                        with contextlib.suppress(Exception):
                            os.unlink(temp_path)
                        raise
                except Exception as exc:
                    logger.warning(
                        "Failed to persist refreshed OAuth credentials: %s", exc
                    )
                    return False
            else:
                logger.warning(
                    "Cannot persist refreshed OAuth credentials: auth path unknown."
                )
                return False

            self._auth_credentials = updated_credentials
            await self._load_auth(force_reload=True)
            logger.info("Successfully refreshed OpenAI Codex access token.")
            return True

    def get_access_token(self) -> str | None:
        """Return current access token if available.

        Returns:
            Access token string or None if not available
        """
        if self._auth_credentials is None:
            return None

        # Prefer ChatGPT OAuth access token
        tokens = self._auth_credentials.get("tokens")
        if isinstance(tokens, dict):
            tok = tokens.get("access_token")
            if isinstance(tok, str) and tok:
                return tok

        # Fallback to OPENAI_API_KEY if present
        api_key = self._auth_credentials.get("OPENAI_API_KEY")
        if isinstance(api_key, str) and api_key:
            return api_key

        return None

    def get_account_id(self) -> str | None:
        """Return the ChatGPT account_id from cached credentials when available.

        Returns:
            Account ID or None
        """
        if self._auth_credentials is None:
            return None

        if isinstance(self._auth_credentials, dict):
            tokens = self._auth_credentials.get("tokens")
            if isinstance(tokens, dict):
                account_id = tokens.get("account_id")
                if isinstance(account_id, str) and account_id.strip():
                    return account_id
        return None

    async def shutdown(self) -> None:
        """Stop the file watcher and release resources.

        This method ensures clean shutdown by:
        - Stopping the credential file watcher
        - Cancelling any pending reload tasks
        - Releasing concurrency locks

        Safe to call multiple times; subsequent calls are no-ops.
        """
        self._watcher.stop()
        await self._watcher.cancel_pending_reload()

    def is_watcher_running(self) -> bool:
        """Return True if the credential file watcher is active.

        Returns:
            True if watcher is running, False otherwise
        """
        return self._watcher.is_running()
