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
from collections.abc import Callable, Mapping
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Any, cast

import httpx
from watchdog.events import FileSystemEventHandler
from watchdog.observers import Observer

from src.connectors.openai_codex.codex_quota_notifications import (
    maybe_notify_codex_quota_reached,
)
from src.connectors.openai_codex.codex_rate_limit_logging import (
    emit_openai_codex_managed_oauth_rate_limit,
    parse_codex_usage_limit_upstream,
    usage_limit_payload_from_upstream_detail,
)
from src.connectors.openai_codex.interfaces import ICredentialManager
from src.connectors.openai_codex.managed_oauth_constants import (
    DEFAULT_ALLOW_LEGACY_FALLBACK,
    DEFAULT_REFRESH_BUFFER_SECONDS,
    DEFAULT_SELECTION_STRATEGY,
    DEFAULT_SESSION_AFFINITY_MAX_ENTRIES,
    DEFAULT_SESSION_AFFINITY_TTL_SECONDS,
    DEFAULT_STORAGE_PATH,
    OPENAI_OAUTH_CLIENT_ID,
    OPENAI_OAUTH_TOKEN_URL,
)
from src.connectors.openai_codex.managed_oauth_models import (
    ManagedOAuthAccount,
    ManagedOAuthConfig,
    SelectionStrategy,
)
from src.connectors.openai_codex.managed_oauth_refresh import (
    ManagedOAuthRefreshError,
    ManagedOAuthRefreshService,
)
from src.connectors.openai_codex.managed_oauth_selector import (
    ManagedOAuthAccountSelector,
)
from src.connectors.openai_codex.managed_oauth_storage import (
    ManagedOAuthStorageService,
)
from src.core.domain.validation import ValidationResult

if TYPE_CHECKING:
    from watchdog.observers.api import BaseObserver

    from src.core.interfaces.notification_service_interface import (
        INotificationService,
    )

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

    def __init__(
        self,
        http_client: httpx.AsyncClient,
        *,
        notification_service: INotificationService | None = None,
    ) -> None:
        """Initialize the credential manager.

        Args:
            http_client: HTTP client for OAuth token refresh API calls
            notification_service: Optional desktop notifications (Codex quota alerts).
        """
        self._http_client = http_client
        self._notification_service = notification_service
        self._codex_quota_notification_dedupe: set[tuple[str, str, str]] = set()
        self._auth_path: Path | None = None
        self._auth_credentials: dict[str, Any] | None = None
        self._last_modified: float = 0.0
        self._token_refresh_lock = asyncio.Lock()
        self._codex_telemetry_lock = asyncio.Lock()
        self._codex_quota_last_disk_write_at: dict[str, float] = {}
        self._event_loop: asyncio.AbstractEventLoop | None = None
        self._oauth_dir_override: Path | None = None
        self._watcher = CredentialWatcher(self)
        self._active_source: str = "none"  # "managed" | "legacy" | "none"
        self._managed_current_account: ManagedOAuthAccount | None = None
        self._managed_config = ManagedOAuthConfig(
            enabled=True,
            storage_path=DEFAULT_STORAGE_PATH,
            accounts="all",
            selection_strategy=cast(
                SelectionStrategy,
                DEFAULT_SELECTION_STRATEGY,
            ),
            refresh_buffer_seconds=DEFAULT_REFRESH_BUFFER_SECONDS,
            session_affinity_ttl_seconds=DEFAULT_SESSION_AFFINITY_TTL_SECONDS,
            session_affinity_max_entries=DEFAULT_SESSION_AFFINITY_MAX_ENTRIES,
            allow_legacy_fallback=DEFAULT_ALLOW_LEGACY_FALLBACK,
        )
        self._managed_storage = ManagedOAuthStorageService(
            self._managed_config.storage_path
        )
        self._managed_refresh = ManagedOAuthRefreshService(
            self._managed_storage,
            http_client=self._http_client,
        )
        self._managed_selector = self._build_managed_selector(self._managed_config)

    def configure_managed_oauth(self, config: ManagedOAuthConfig) -> None:
        """Configure managed OAuth runtime behavior from connector settings."""
        self._managed_config = config
        self._managed_storage = ManagedOAuthStorageService(config.storage_path)
        self._managed_refresh = ManagedOAuthRefreshService(
            self._managed_storage,
            http_client=self._http_client,
        )
        self._managed_selector = self._build_managed_selector(config)
        self._managed_current_account = None
        if self._active_source == "managed":
            self._active_source = "none"
            self._auth_credentials = None

    def _build_managed_selector(
        self,
        config: ManagedOAuthConfig,
    ) -> ManagedOAuthAccountSelector:
        allowed_accounts: set[str] | None = None
        if isinstance(config.accounts, list):
            allowed_accounts = {item for item in config.accounts if item}
        return ManagedOAuthAccountSelector(
            self._managed_storage,
            self._managed_refresh,
            refresh_buffer_ms=max(0, int(config.refresh_buffer_seconds * 1000)),
            allowed_account_ids=allowed_accounts,
            selection_strategy=config.selection_strategy,
            session_affinity_ttl_seconds=config.session_affinity_ttl_seconds,
            session_affinity_max_entries=config.session_affinity_max_entries,
            max_rate_limit_wait_seconds=config.max_rate_limit_wait_seconds,
            rate_limit_local_cooldown_cap_seconds=config.rate_limit_local_cooldown_cap_seconds,
            max_rate_limit_idle_polls=config.max_rate_limit_idle_polls,
        )

    def _managed_enabled(self) -> bool:
        return bool(self._managed_config.enabled)

    async def _managed_has_accounts(self) -> bool:
        if not self._managed_enabled():
            return False
        return await self._managed_storage.has_configured_accounts()

    def _managed_account_to_credentials(
        self,
        account: ManagedOAuthAccount,
    ) -> dict[str, Any]:
        tokens: dict[str, Any] = {
            "access_token": account.access_token,
            "refresh_token": account.refresh_token,
            "token_type": account.token_type,
            "scope": account.scope,
            "expiry_date": account.get_effective_expiry_ms(),
        }
        return {
            "tokens": tokens,
            "account_id": account.chatgpt_account_id or account.account_id,
            "managed_account_id": account.account_id,
            "user": {"email": account.email} if account.email else {},
            "last_refresh": account.updated_at,
            "managed_oauth": {
                "enabled": True,
                "storage_path": str(self._managed_storage.storage_path),
                "account_id": account.account_id,
                "chatgpt_account_id": account.chatgpt_account_id,
                "needs_reauth": account.needs_reauth,
                "rate_limited_until": account.rate_limited_until,
            },
        }

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
        """Load credentials, preferring managed OAuth accounts when available.

        Managed accounts always take precedence when present, even if
        ``openai_codex_path`` / ``auth_path`` points at a legacy ``auth.json``
        directory (those paths are still used for legacy fallback discovery).
        """
        if await self._load_managed_auth(force_reload=force_reload):
            return True

        explicit_legacy_override = (
            self._auth_path is not None or self._oauth_dir_override is not None
        )
        if explicit_legacy_override:
            if await self._load_legacy_auth(force_reload=force_reload):
                return True
            self._active_source = "none"
            self._managed_current_account = None
            return False

        if await self._load_legacy_auth(force_reload=force_reload):
            return True
        self._active_source = "none"
        self._managed_current_account = None
        return False

    async def _load_managed_auth(self, force_reload: bool = False) -> bool:
        if not self._managed_enabled():
            return False

        # Skip managed path when nothing is on disk — avoids selector/refresh work
        # and prevents long rate-limit polling loops during bootstrap (tests/CI).
        if not await self._managed_has_accounts():
            return False

        if force_reload:
            await self._managed_selector.reload_accounts()

        account = self._managed_selector.get_current_account()
        if account is None or account.needs_reauth:
            # Initial bootstrap must not block on rate-limit recovery sleeps
            # (see ManagedOAuthAccountSelector.get_next_account); fall back to legacy.
            account = await self._managed_selector.get_next_account(
                wait_for_rate_limit_recovery=False,
            )

        if account is None:
            return False

        self._managed_selector.update_account(account)
        self._managed_current_account = account
        self._auth_credentials = self._managed_account_to_credentials(account)
        self._auth_path = None
        self._active_source = "managed"
        if self._watcher.is_running():
            self._watcher.stop()
        return True

    async def _load_legacy_auth(self, force_reload: bool = False) -> bool:
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

            if not force_reload:
                try:
                    mtime = await asyncio.to_thread(_get_mtime)
                    if mtime == self._last_modified and self.get_access_token():
                        logger.debug(
                            "OpenAI Codex credentials file not modified, using cached."
                        )
                        self._active_source = "legacy"
                        return True
                except OSError as e:
                    if logger.isEnabledFor(logging.DEBUG):
                        logger.debug(
                            "Failed to stat OpenAI Codex credentials file for modification time: %s",
                            e,
                            exc_info=True,
                        )

            try:
                mtime = await asyncio.to_thread(_get_mtime)
                self._last_modified = mtime
            except OSError as e:
                if logger.isEnabledFor(logging.DEBUG):
                    logger.debug(
                        "Failed to stat OpenAI Codex credentials file for modification time: %s",
                        e,
                        exc_info=True,
                    )

            data: dict[str, Any] = await asyncio.to_thread(_load_file)

            self._auth_credentials = data
            self._active_source = "legacy"
            self._managed_current_account = None
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
        """Validate availability of managed accounts or legacy auth.json."""
        if self._managed_enabled():
            storage_path = self._managed_storage.storage_path
            try:
                if storage_path.exists() and storage_path.is_dir():
                    has_managed_accounts = any(
                        path.is_file() and path.suffix == ".json"
                        for path in storage_path.iterdir()
                    )
                    if has_managed_accounts:
                        return ValidationResult.success()
            except Exception as exc:
                if logger.isEnabledFor(logging.DEBUG):
                    logger.debug(
                        "Failed checking managed OAuth storage path %s: %s",
                        storage_path,
                        exc,
                        exc_info=True,
                    )

            if not self._managed_config.allow_legacy_fallback:
                return ValidationResult.failure(
                    "Managed OAuth is enabled but no managed accounts are configured."
                )

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
            if await self._load_managed_auth(force_reload=True):
                if await self._refresh_managed_access_token():
                    return True
                return await self._rotate_managed_on_auth_failure()
            return await self._refresh_legacy_access_token()

    async def _refresh_managed_access_token(self) -> bool:
        account = self._managed_selector.get_current_account()
        if account is None:
            # Refresh path should also avoid blocking on rate-limit recovery sleeps.
            account = await self._managed_selector.get_next_account(
                wait_for_rate_limit_recovery=False,
            )
        if account is None:
            return False

        try:
            updated = await self._managed_refresh.force_refresh(account)
        except ManagedOAuthRefreshError as exc:
            if logger.isEnabledFor(logging.WARNING):
                logger.warning(
                    "Managed OAuth token refresh failed for account %s: %s",
                    exc.account_id,
                    exc,
                    exc_info=True,
                )
            return False

        self._managed_selector.update_account(updated)
        self._managed_current_account = updated
        self._auth_credentials = self._managed_account_to_credentials(updated)
        self._active_source = "managed"
        return True

    async def _rotate_managed_on_auth_failure(self) -> bool:
        rotated = await self._managed_selector.rotate_on_auth_failure()
        if rotated is None:
            return False
        self._managed_current_account = rotated
        self._auth_credentials = self._managed_account_to_credentials(rotated)
        self._active_source = "managed"
        return True

    async def _refresh_legacy_access_token(self) -> bool:
        await self._load_legacy_auth(force_reload=True)
        if not self._auth_credentials:
            logger.warning("Cannot refresh OpenAI Codex token: credentials not loaded.")
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
            "client_id": OPENAI_OAUTH_CLIENT_ID,
            "grant_type": "refresh_token",
            "refresh_token": refresh_token,
            "scope": "openid profile email",
        }

        try:
            response = await self._http_client.post(
                OPENAI_OAUTH_TOKEN_URL,
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
            updated_credentials["last_refresh"] = datetime.now(timezone.utc).isoformat()

            try:
                loop = asyncio.get_running_loop()
                await loop.run_in_executor(
                    None,
                    self._persist_credentials_sync,
                    updated_credentials,
                    self._auth_path,
                )
            except Exception as exc:
                logger.warning(
                    "Failed to persist refreshed OAuth credentials: %s",
                    exc,
                    exc_info=True,
                )
                return False
        else:
            logger.warning(
                "Cannot persist refreshed OAuth credentials: auth path unknown."
            )
            return False

        self._auth_credentials = updated_credentials
        self._active_source = "legacy"
        await self._load_legacy_auth(force_reload=True)
        logger.info("Successfully refreshed OpenAI Codex access token.")
        return True

    CODEX_QUOTA_HEADER_DISK_MIN_INTERVAL_SEC = 60.0

    async def record_codex_quota_headers(
        self,
        headers: Mapping[str, Any],
        *,
        force: bool = False,
    ) -> None:
        """Persist last x-codex-* headers on the currently selected managed account.

        By default, account JSON is written at most once per
        :attr:`CODEX_QUOTA_HEADER_DISK_MIN_INTERVAL_SEC` per ``account_id`` to limit
        disk I/O. Pass ``force=True`` on 429 handling so limit-related state is not
        delayed behind the throttle window.
        """
        if not self._managed_enabled():
            return
        captured: dict[str, str] = {}
        for k, v in headers.items():
            k_lower = str(k).lower()
            if k_lower.startswith("x-codex-"):
                captured[k_lower] = str(v)
        if not captured:
            return
        async with self._codex_telemetry_lock:
            current = self._managed_selector.get_current_account()
            if current is None:
                return
            now_m = time.monotonic()
            if not force:
                last_m = self._codex_quota_last_disk_write_at.get(current.account_id)
                if (
                    last_m is not None
                    and now_m - last_m < self.CODEX_QUOTA_HEADER_DISK_MIN_INTERVAL_SEC
                ):
                    return
            observed = datetime.now(timezone.utc).isoformat()
            updated = current.model_copy(
                update={
                    "last_codex_quota_headers": captured,
                    "last_codex_quota_observed_at": observed,
                    "updated_at": observed,
                }
            )
            self._managed_selector.update_account(updated)
            await self._managed_storage.save_account(updated)
            self._codex_quota_last_disk_write_at[current.account_id] = now_m
            if (
                self._managed_current_account is not None
                and self._managed_current_account.account_id == updated.account_id
            ):
                self._managed_current_account = updated

    async def handle_rate_limit(
        self,
        retry_after_seconds: float | None,
        *,
        session_id: str | None = None,
        upstream_codex_error: Mapping[str, Any] | None = None,
        response_headers: Mapping[str, Any] | None = None,
    ) -> bool:
        """Mark managed account as rate-limited and rotate to another account."""
        async with self._token_refresh_lock:
            if not await self._load_managed_auth(force_reload=True):
                return False
            if response_headers is not None:
                await self.record_codex_quota_headers(
                    response_headers,
                    force=True,
                )
            current = self._managed_selector.get_current_account()
            if current is not None:
                emit_openai_codex_managed_oauth_rate_limit(
                    managed_account_id=current.account_id,
                    email=current.email,
                    chatgpt_account_id=current.chatgpt_account_id,
                    retry_after_seconds=retry_after_seconds,
                    session_id=session_id,
                    upstream_json=upstream_codex_error,
                    log=logger,
                )
            usage_fields = parse_codex_usage_limit_upstream(upstream_codex_error)
            if current is not None:
                other_eligible = (
                    self._managed_selector.count_eligible_accounts_excluding(
                        current.account_id
                    )
                )
                snapshot_eligible: list[str] = []
                available_managed = 0
                if self._managed_enabled():
                    try:
                        snapshot_eligible = (
                            await self._managed_selector.list_eligible_account_ids()
                        )
                        available_managed = (
                            await self._managed_selector.count_available_managed_accounts()
                        )
                    except Exception as exc:
                        if logger.isEnabledFor(logging.DEBUG):
                            logger.debug(
                                "OpenAI Codex: eligibility snapshot failed: %s",
                                exc,
                                exc_info=True,
                            )
                if logger.isEnabledFor(logging.INFO):
                    logger.info(
                        "OpenAI Codex managed OAuth: failover snapshot "
                        "current_account_id=%s other_eligible_excluding_current=%s "
                        "eligible_account_ids=%s available_managed_accounts=%s",
                        current.account_id,
                        other_eligible,
                        snapshot_eligible,
                        available_managed,
                    )
                if other_eligible == 0 and logger.isEnabledFor(logging.WARNING):
                    logger.warning(
                        "OpenAI Codex managed OAuth: no other eligible accounts to "
                        "failover to after upstream quota/limit on account_id=%s. "
                        "Per-account diagnostics (allowlist_ok, reauth, local RL): %s",
                        current.account_id,
                        self._managed_selector.eligibility_debug_snapshot(),
                    )
                await maybe_notify_codex_quota_reached(
                    self._notification_service,
                    self._codex_quota_notification_dedupe,
                    managed_account_id=current.account_id,
                    email=current.email,
                    chatgpt_account_id=current.chatgpt_account_id,
                    usage_limit_fields=usage_fields,
                    retry_after_seconds=retry_after_seconds,
                    all_accounts_exhausted=other_eligible == 0,
                )
            rotated = await self._managed_selector.rotate_on_rate_limit(
                retry_after_seconds=retry_after_seconds,
                session_id=session_id,
                codex_usage_limit_fields=usage_fields,
            )
            if rotated is None:
                return False
            self._managed_current_account = rotated
            self._auth_credentials = self._managed_account_to_credentials(rotated)
            self._active_source = "managed"
            return True

    async def effective_max_rate_limit_retries(self, floor: int) -> int:
        """Lower bound from connector config; expand with managed account count for 429 rotation."""
        base = max(0, int(floor))
        if not self._managed_enabled():
            return base
        try:
            await self._managed_selector.reload_accounts()
            n = await self._managed_selector.count_available_managed_accounts()
        except Exception as exc:
            if logger.isEnabledFor(logging.DEBUG):
                logger.debug(
                    "OpenAI Codex: could not compute managed account rotation budget: %s",
                    exc,
                    exc_info=True,
                )
            return base
        if n <= 1:
            return base
        return max(base, n)

    async def notify_codex_usage_limit_unrecovered(
        self,
        *,
        upstream_detail: Any,
        retry_after_seconds: float | None,
        all_accounts_exhausted: bool = True,
    ) -> None:
        """Notify on ``usage_limit_reached`` when the request is still failing (legacy or exhausted rotation)."""
        payload = usage_limit_payload_from_upstream_detail(upstream_detail)
        if payload is None:
            return
        usage_fields = parse_codex_usage_limit_upstream(payload)
        if usage_fields is None:
            return

        account_id = "legacy-openai-codex"
        email: str | None = None
        chatgpt_account_id: str | None = None
        if self._managed_current_account is not None:
            account_id = self._managed_current_account.account_id
            email = self._managed_current_account.email
            chatgpt_account_id = self._managed_current_account.chatgpt_account_id
        elif isinstance(self._auth_credentials, Mapping):
            managed = self._auth_credentials.get("managed_oauth")
            if isinstance(managed, Mapping):
                mid = managed.get("account_id")
                if isinstance(mid, str) and mid.strip():
                    account_id = mid.strip()
                cg = managed.get("chatgpt_account_id")
                if isinstance(cg, str) and cg.strip():
                    chatgpt_account_id = cg.strip()
            if account_id == "legacy-openai-codex":
                top_aid = self._auth_credentials.get("account_id")
                if isinstance(top_aid, str) and top_aid.strip():
                    account_id = top_aid.strip()
            user = self._auth_credentials.get("user")
            if isinstance(user, Mapping):
                raw_email = user.get("email")
                if isinstance(raw_email, str) and raw_email.strip():
                    email = raw_email.strip()

        await maybe_notify_codex_quota_reached(
            self._notification_service,
            self._codex_quota_notification_dedupe,
            managed_account_id=account_id,
            email=email,
            chatgpt_account_id=chatgpt_account_id,
            usage_limit_fields=usage_fields,
            retry_after_seconds=retry_after_seconds,
            all_accounts_exhausted=all_accounts_exhausted,
        )

    async def handle_auth_failure(
        self,
        *,
        session_id: str | None = None,
    ) -> bool:
        """Rotate away from currently failing managed account on auth denial."""
        async with self._token_refresh_lock:
            if not await self._load_managed_auth(force_reload=True):
                return await self._refresh_legacy_access_token()
            rotated = await self._managed_selector.rotate_on_auth_failure(
                session_id=session_id
            )
            if rotated is None:
                return False
            self._managed_current_account = rotated
            self._auth_credentials = self._managed_account_to_credentials(rotated)
            self._active_source = "managed"
            return True

    async def mark_account_used(self) -> None:
        """Mark currently selected managed account as used."""
        if self._active_source != "managed":
            return
        if self._managed_selector.get_current_account() is None:
            return
        await self._managed_selector.mark_current_account_used()
        updated = self._managed_selector.get_current_account()
        if updated is not None:
            self._managed_current_account = updated
            self._auth_credentials = self._managed_account_to_credentials(updated)

    def get_access_token(self) -> str | None:
        """Return current access token if available.

        Returns:
            Access token string or None if not available
        """
        if self._managed_current_account is not None:
            token = self._managed_current_account.access_token
            if token:
                return token

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
        if self._managed_current_account is not None:
            if (
                isinstance(self._managed_current_account.chatgpt_account_id, str)
                and self._managed_current_account.chatgpt_account_id
            ):
                return self._managed_current_account.chatgpt_account_id
            token_account_id = _extract_chatgpt_account_id_from_jwt(
                self._managed_current_account.access_token
            )
            if isinstance(token_account_id, str) and token_account_id:
                return token_account_id

        if self._auth_credentials is None:
            return None

        managed_meta = self._auth_credentials.get("managed_oauth")
        if isinstance(managed_meta, dict):
            chatgpt_account_id = managed_meta.get("chatgpt_account_id")
            if isinstance(chatgpt_account_id, str) and chatgpt_account_id:
                return chatgpt_account_id

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

    async def list_managed_oauth_account_ids(self) -> list[str]:
        """Return eligible managed OAuth account IDs for warm-up fan-out."""
        if not self._managed_enabled():
            return []

        await self._managed_selector.reload_accounts()
        return await self._managed_selector.list_eligible_account_ids()


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
        direct_account_id = payload.get("chatgpt_account_id")
        if isinstance(direct_account_id, str) and direct_account_id:
            return direct_account_id
        auth_claim = payload.get("https://api.openai.com/auth")
        if not isinstance(auth_claim, dict):
            return None
        account_id = auth_claim.get("chatgpt_account_id")
        return account_id if isinstance(account_id, str) and account_id else None
    except Exception:
        return None
