"""Credential management for OpenAI Codex connector.

This module provides CredentialManager and CredentialWatcher services
for loading, validating, refreshing, and watching credential files.
"""

from __future__ import annotations

import asyncio
import base64
import contextlib
import json
import logging
import os
import tempfile
import threading
import time
from collections.abc import Callable
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Any, cast

import httpx
from watchdog.events import FileSystemEventHandler
from watchdog.observers import Observer

from src.connectors.openai_codex.interfaces import ICredentialManager
from src.core.domain.validation import ValidationResult

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
                # Get auth_path - try target first, then credential manager
                auth_path = None
                # Try to get _auth_path from target (property or attribute)
                try:
                    auth_path_attr = getattr(self._target, "_auth_path", None)
                    if isinstance(auth_path_attr, Path):
                        auth_path = auth_path_attr.resolve()
                except (AttributeError, OSError) as exc:
                    logger.debug(
                        "Could not resolve auth_path from target: %s",
                        exc,
                        exc_info=True,
                    )

                # Fallback: get from credential manager if target doesn't have it
                if auth_path is None and hasattr(self._target, "_credential_manager"):
                    try:
                        cred_mgr = getattr(self._target, "_credential_manager", None)
                        if cred_mgr is not None:
                            auth_path_attr = getattr(cred_mgr, "_auth_path", None)
                            if isinstance(auth_path_attr, Path):
                                auth_path = auth_path_attr.resolve()
                    except (AttributeError, OSError) as exc:
                        logger.debug(
                            "Could not resolve auth_path from credential manager: %s",
                            exc,
                            exc_info=True,
                        )

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
        self._shutdown_requested = False

    def request_shutdown(self) -> None:
        """Prevent future reload scheduling during teardown."""
        self._shutdown_requested = True

    def set_event_loop(self, loop: asyncio.AbstractEventLoop | None) -> None:
        """Set the event loop used to schedule async reload tasks."""
        self._event_loop = loop

    def start(self, auth_path: Path) -> None:
        """Start watching the credentials file for changes.

        Args:
            auth_path: Path to the auth.json file to watch
        """
        if self._observer is not None:
            return

        try:
            self._observer = Observer()
            self._observer.daemon = True
            handler = OpenAICredentialsFileHandler(self._credential_manager)
            watch_dir = auth_path.parent
            self._observer.schedule(handler, str(watch_dir), recursive=False)
            self._observer.start()
            if logger.isEnabledFor(logging.DEBUG):
                logger.debug(
                    "Started watching OpenAI Codex credentials directory: %s", watch_dir
                )
        except Exception as e:
            if logger.isEnabledFor(logging.WARNING):
                logger.warning(
                    "Failed to start file watching for OpenAI Codex credentials: %s",
                    e,
                    exc_info=True,
                )

    def stop(self) -> None:
        """Stop watching the credentials file."""
        self._shutdown_requested = True

        if self._observer is not None:
            try:
                observer = self._observer
                self._observer = None

                observer.stop()
                observer_thread = cast(threading.Thread, observer)
                if observer_thread is not threading.current_thread():
                    observer_thread.join(timeout=5.0)
                if observer_thread.is_alive() and logger.isEnabledFor(logging.WARNING):
                    logger.warning(
                        "OpenAI Codex credentials file watcher did not terminate cleanly."
                    )
            except Exception as e:
                if logger.isEnabledFor(logging.DEBUG):
                    logger.debug("Error stopping OpenAI Codex file watcher: %s", e)
            finally:
                self._observer = None

    def is_running(self) -> bool:
        """Return True if the file watcher is active."""
        return self._observer is not None and self._observer.is_alive()

    async def cancel_pending_reload(self) -> None:
        """Cancel any pending reload task."""
        pending_task: asyncio.Future[None] | None = None
        with self._reload_task_lock:
            if (
                self._pending_reload_task is not None
                and not self._pending_reload_task.done()
            ):
                pending_task = self._pending_reload_task
                pending_task.cancel()

        if pending_task is not None:
            with contextlib.suppress(asyncio.CancelledError, RuntimeError):
                await pending_task
            with self._reload_task_lock:
                if self._pending_reload_task is pending_task:
                    self._pending_reload_task = None
        self._reload_scheduling_event.clear()

    def schedule_reload(self) -> None:
        """Schedule an asynchronous reload of credentials with debounce.

        This method ensures only one reload task per change window by using
        event gating and task tracking. Called when file watcher detects changes.
        """
        if self._shutdown_requested:
            return

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
                if logger.isEnabledFor(logging.DEBUG):
                    logger.debug(
                        "Reloading OpenAI Codex credentials due to file change"
                    )
                # Use public interface to reload credentials
                loaded = await self._credential_manager.reload_credentials(force=True)
                if loaded:
                    res = self._credential_manager.validate_current_credentials()
                    if not res and logger.isEnabledFor(logging.WARNING):
                        logger.warning(
                            "Credential structure validation failed after reload: %s",
                            "; ".join(res.errors),
                        )

                else:
                    if logger.isEnabledFor(logging.WARNING):
                        logger.warning(
                            "Failed to reload credentials from file",
                            exc_info=True,
                        )
            except Exception as e:
                logger.error(
                    f"Error during OpenAI Codex credentials reload: {e}", exc_info=True
                )

        loop = self._event_loop
        if loop is None:
            try:
                loop = asyncio.get_running_loop()
            except RuntimeError:
                if logger.isEnabledFor(logging.WARNING):
                    logger.warning(
                        "Cannot schedule credentials reload: no running event loop available.",
                        exc_info=True,
                    )
                self._reload_scheduling_event.clear()
                return
            self._event_loop = loop

        if loop.is_closed():
            if logger.isEnabledFor(logging.WARNING):
                logger.warning(
                    "Cannot schedule credentials reload: event loop is closed."
                )
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
                        "Failed to schedule OpenAI Codex credentials reload: %s",
                        exc,
                        exc_info=True,
                    )
                    self._reload_scheduling_event.clear()

            loop.call_soon_threadsafe(schedule_task)
        except RuntimeError as exc:
            logger.warning(
                "Failed to schedule OpenAI Codex credentials reload: %s",
                exc,
                exc_info=True,
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

            def _get_mtime() -> float:
                return auth_path.stat().st_mtime

            def _load_file() -> dict[str, Any]:
                with open(auth_path, encoding="utf-8") as f:
                    return cast(dict[str, Any], json.load(f))

            # Check if file has been modified since last load (unless force_reload is True)
            if not force_reload:
                try:
                    mtime = await asyncio.to_thread(_get_mtime)
                    if mtime == self._last_modified and self.get_access_token():
                        logger.debug(
                            "OpenAI Codex credentials file not modified, using cached."
                        )
                        return True
                except OSError as e:
                    # Failed to stat file - log for debugging and proceed with load
                    if logger.isEnabledFor(logging.DEBUG):
                        logger.debug(
                            "Failed to stat OpenAI Codex credentials file for modification time: %s",
                            e,
                            exc_info=True,
                        )

            # Update last modified time
            try:
                mtime = await asyncio.to_thread(_get_mtime)
                self._last_modified = mtime
            except OSError as e:
                # Failed to stat file - log for debugging and proceed with load
                if logger.isEnabledFor(logging.DEBUG):
                    logger.debug(
                        "Failed to stat OpenAI Codex credentials file for modification time: %s",
                        e,
                        exc_info=True,
                    )

            data: dict[str, Any] = await asyncio.to_thread(_load_file)

            # Store credentials for validation
            self._auth_credentials = data
            log_msg = "Successfully loaded OpenAI Codex credentials"
            if force_reload:
                log_msg += " (force reload)"
            if logger.isEnabledFor(logging.INFO):
                logger.info("%s.", log_msg)
            return True
        except json.JSONDecodeError as e:
            logger.error("Malformed auth.json for OpenAI Codex: %s", e, exc_info=True)
            return False
        except Exception as e:
            logger.error(
                "Failed to load OpenAI Codex credentials: %s", e, exc_info=True
            )
            return False

    def _validate_credentials_file_exists(self) -> ValidationResult:
        """Validate that credentials file exists and is readable."""
        auth_path = self._discover_auth_path()
        if auth_path is None:
            return ValidationResult.failure(
                "OAuth credentials file not found in any default location"
            )

        if not auth_path.exists():
            return ValidationResult.failure(
                f"OAuth credentials file does not exist: {auth_path}"
            )

        if not auth_path.is_file():
            return ValidationResult.failure(
                f"OAuth credentials path is not a file: {auth_path}"
            )

        try:
            with open(auth_path, encoding="utf-8") as f:
                json.load(f)
        except json.JSONDecodeError as e:
            return ValidationResult.failure(
                f"OAuth credentials file contains invalid JSON: {e}"
            )
        except PermissionError:
            return ValidationResult.failure(
                f"No permission to read OAuth credentials file: {auth_path}"
            )
        except Exception as e:
            return ValidationResult.failure(
                f"Error reading OAuth credentials file: {e}"
            )

        return ValidationResult.success()

    def _robust_replace(
        self, src: str, dst: str, retries: int = 5, delay: float = 0.1
    ) -> None:
        """Attempt to replace a file with retries to handle Windows file locking.

        Args:
            src: Source file path to rename from
            dst: Destination file path to rename to
            retries: Number of retry attempts
            delay: Delay between retries in seconds

        Raises:
            PermissionError: If all retries fail
        """
        for i in range(retries):
            try:
                os.replace(src, dst)
                return
            except PermissionError:
                if i < retries - 1:
                    time.sleep(delay)
                else:
                    raise

    def _validate_credentials_structure(
        self, credentials: dict[str, Any]
    ) -> ValidationResult:
        """Validate OAuth credentials structure and content."""
        # Check for tokens.access_token or OPENAI_API_KEY
        access_token = None
        tokens = credentials.get("tokens")
        if isinstance(tokens, dict):
            tok = tokens.get("access_token")
            if isinstance(tok, str) and tok.strip():
                access_token = tok

        api_key = credentials.get("OPENAI_API_KEY")
        if not access_token and not (isinstance(api_key, str) and api_key.strip()):
            return ValidationResult.failure(
                "OAuth credentials missing required 'tokens.access_token' or 'OPENAI_API_KEY' field"
            )

        return ValidationResult.success()

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
        res_file = self._validate_credentials_file_exists()
        if not res_file:
            logger.error(f"Credential validation failed: {'; '.join(res_file.errors)}")
            return

        # 2) Load credentials into memory
        if not await self._load_auth():
            logger.error("Failed to load credentials despite validation passing")
            return

        # 3) Structure validation
        if self._auth_credentials is not None:
            res_struct = self._validate_credentials_structure(self._auth_credentials)
            if not res_struct:
                logger.error(
                    f"Credential structure validation failed: {'; '.join(res_struct.errors)}"
                )
                return
        else:
            logger.error("OAuth credentials are None after loading")
            return

        # 4) Start file watching
        if self._auth_path is not None:
            # Store event loop reference in watcher for reload scheduling
            self._watcher.set_event_loop(self._event_loop)
            self._watcher.start(self._auth_path)
        logger.info("Credentials initialized successfully.")

    async def shutdown(self) -> None:
        """Stop the credential file watcher and cancel pending reload work."""
        self._watcher.request_shutdown()
        self._watcher.stop()
        await self._watcher.cancel_pending_reload()

    def is_watcher_running(self) -> bool:
        """Return True if the credential file watcher is active."""
        return self._watcher.is_running()

    async def reload_credentials(self, force: bool = False) -> bool:
        """Reload credentials from disk.

        Args:
            force: If True, bypass cache and force reload based on file mtime.

        Returns:
            True when credentials were loaded successfully.
        """
        return await self._load_auth(force_reload=force)

    def _persist_credentials_sync(
        self, credentials: dict[str, Any], auth_path: Path
    ) -> None:
        """Persist credentials to disk synchronously."""
        # Create temp file in same directory for atomic os.replace()
        temp_fd, temp_path = tempfile.mkstemp(
            dir=auth_path.parent,
            prefix=".auth_",
            suffix=".json.tmp",
            text=True,
        )
        try:
            with os.fdopen(temp_fd, "w", encoding="utf-8") as f:
                json.dump(credentials, f, indent=2)
                f.write("\n")
                f.flush()
                os.fsync(f.fileno())  # Ensure written to disk
            # Atomic replacement (cross-platform) with retry for Windows
            self._robust_replace(temp_path, str(auth_path))
        except (OSError, PermissionError, TypeError, ValueError) as exc:
            # Log file I/O and serialization errors with context before cleanup
            logger.error(
                "Failed to persist credentials to %s: %s",
                auth_path,
                exc,
                exc_info=True,
            )
            # Clean up temp file on error
            with contextlib.suppress(Exception):
                os.unlink(temp_path)
            raise
        except Exception as exc:
            # Catch-all for any other unexpected errors
            logger.error(
                "Unexpected error persisting credentials to %s: %s",
                auth_path,
                exc,
                exc_info=True,
            )
            # Clean up temp file on error
            with contextlib.suppress(Exception):
                os.unlink(temp_path)
            raise

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
                logger.warning(
                    "Failed to refresh OpenAI Codex token: %s", exc, exc_info=True
                )
                return False

            if response.status_code >= 400:
                body = response.text
                # Truncate body to avoid leaking excessive info or filling logs
                safe_body = body[:200] + "..." if len(body) > 200 else body
                logger.warning(
                    "OpenAI Codex token refresh failed with status %s: %s",
                    response.status_code,
                    safe_body,
                )
                return False

            try:
                token_response = response.json()
            except Exception as exc:
                logger.warning(
                    "Failed to parse OAuth token refresh response: %s",
                    exc,
                    exc_info=True,
                )
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
                    # Run file operations in a thread pool to avoid blocking the event loop
                    loop = asyncio.get_running_loop()
                    await loop.run_in_executor(
                        None,
                        self._persist_credentials_sync,
                        updated_credentials,
                        self._auth_path,
                    )
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

    def validate_current_credentials(self) -> ValidationResult:
        """Validate currently loaded credentials structure.

        This method validates the credentials that are currently in memory,
        without reloading from file. Useful for checking credentials after
        a reload operation.

        Returns:
            ValidationResult with success/error status. If no credentials
            are loaded, returns a failure result.
        """
        if self._auth_credentials is None:
            return ValidationResult.failure("No credentials loaded")
        return self._validate_credentials_structure(self._auth_credentials)

    def get_account_id(self) -> str | None:
        """Return ChatGPT account ID from loaded credentials.

        Returns:
            Account ID string or None if not available
        """
        if self._auth_credentials is None:
            return None

        # Account ID is typically stored in top-level 'account_id' field
        account_id = self._auth_credentials.get("account_id")
        if isinstance(account_id, str) and account_id:
            return account_id

        # Also check nested 'user' object for account_id
        user = self._auth_credentials.get("user")
        if isinstance(user, dict):
            nested_account_id = user.get("account_id")
            if isinstance(nested_account_id, str) and nested_account_id:
                return nested_account_id

        # Fallback: extract ChatGPT account id from the OAuth access token JWT.
        # Codex CLI/OpenCode plugins rely on the `chatgpt-account-id` header derived from:
        # payload["https://api.openai.com/auth"]["chatgpt_account_id"].
        access_token = self.get_access_token()
        if isinstance(access_token, str) and access_token:
            token_account_id = _extract_chatgpt_account_id_from_jwt(access_token)
            if isinstance(token_account_id, str) and token_account_id:
                return token_account_id

        return None


def _extract_chatgpt_account_id_from_jwt(token: str) -> str | None:
    """Best-effort decode of ChatGPT account id from an access token JWT.

    This does NOT verify the token signature; it is used only to extract the
    `chatgpt_account_id` claim for the required `chatgpt-account-id` header.
    """
    try:
        parts = token.split(".")
        if len(parts) < 2:
            return None
        payload_b64 = parts[1]
        padded = payload_b64 + "=" * (-len(payload_b64) % 4)
        payload_bytes = base64.urlsafe_b64decode(padded.encode("ascii"))
        payload = json.loads(payload_bytes.decode("utf-8", errors="replace"))
        if not isinstance(payload, dict):
            return None
        auth_claim = payload.get("https://api.openai.com/auth")
        if not isinstance(auth_claim, dict):
            return None
        account_id = auth_claim.get("chatgpt_account_id")
        return account_id if isinstance(account_id, str) and account_id else None
    except Exception:
        return None
