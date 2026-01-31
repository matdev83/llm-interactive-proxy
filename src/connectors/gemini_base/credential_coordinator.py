"""
Credential lifecycle coordinator for Gemini OAuth connectors.

This module provides GeminiCredentialCoordinator which coordinates credential
loading, validation, refresh, and file watching operations.
"""

import asyncio
import logging
from pathlib import Path
from typing import Any

from src.connectors.gemini_base.credential_loader import (
    CredentialLoader,
)
from src.connectors.gemini_base.file_watcher import FileWatcher, FileWatcherState
from src.connectors.gemini_base.interfaces import ICredentialCoordinator
from src.connectors.gemini_base.models import GeminiOAuthCredentials
from src.connectors.gemini_base.token_manager import TokenManager
from src.core.common.exceptions import AuthenticationError

logger = logging.getLogger(__name__)


class CredentialStorageAdapter:
    """Adapter to provide CredentialStorage protocol for CredentialLoader."""

    def __init__(self, coordinator: "GeminiCredentialCoordinator") -> None:
        """Initialize the adapter.

        Args:
            coordinator: The credential coordinator instance.
        """
        self._coordinator = coordinator

    @property
    def _oauth_credentials(self) -> dict[str, Any] | None:
        """Return the current OAuth credentials dict."""
        if self._coordinator.credentials_obj:
            return self._coordinator.credentials_obj.to_dict()
        return None

    @_oauth_credentials.setter
    def _oauth_credentials(self, value: dict[str, Any] | None) -> None:
        """Set the OAuth credentials."""
        if value:
            self._coordinator.credentials_obj = GeminiOAuthCredentials.from_dict(value)
        else:
            self._coordinator.credentials_obj = None

    @property
    def _credentials_path(self) -> Path | None:
        """Return the credentials file path."""
        return self._coordinator.credentials_path

    @_credentials_path.setter
    def _credentials_path(self, value: Path | None) -> None:
        """Set the credentials file path."""
        self._coordinator.credentials_path = value

    @property
    def _last_modified(self) -> float:
        """Return the last modified timestamp."""
        return self._coordinator.last_modified_ts

    @_last_modified.setter
    def _last_modified(self, value: float) -> None:
        """Set the last modified timestamp."""
        self._coordinator.last_modified_ts = value

    @property
    def _credentials_fingerprint(self) -> str | None:
        """Return the credentials fingerprint."""
        return self._coordinator.credentials_fingerprint

    @_credentials_fingerprint.setter
    def _credentials_fingerprint(self, value: str | None) -> None:
        """Set the credentials fingerprint."""
        self._coordinator.credentials_fingerprint = value

    @property
    def _credentials_file_hash(self) -> str | None:
        """Return the credentials file hash."""
        return self._coordinator.credentials_file_hash

    @_credentials_file_hash.setter
    def _credentials_file_hash(self, value: str | None) -> None:
        """Set the credentials file hash."""
        self._coordinator.credentials_file_hash = value

    @property
    def _last_credentials_event_hash(self) -> str | None:
        """Return the last credentials event hash."""
        return self._coordinator.last_credentials_event_hash

    @_last_credentials_event_hash.setter
    def _last_credentials_event_hash(self, value: str | None) -> None:
        """Set the last credentials event hash."""
        self._coordinator.last_credentials_event_hash = value

    @property
    def gemini_cli_oauth_path(self) -> str | None:
        """Return the custom .gemini directory path."""
        return self._coordinator.gemini_cli_oauth_path

    @gemini_cli_oauth_path.setter
    def gemini_cli_oauth_path(self, value: str | None) -> None:
        """Set the custom .gemini directory path."""
        self._coordinator.gemini_cli_oauth_path = value


class CredentialProviderAdapter:
    """Adapter to provide CredentialProvider protocol for TokenManager."""

    def __init__(self, coordinator: "GeminiCredentialCoordinator") -> None:
        """Initialize the adapter.

        Args:
            coordinator: The credential coordinator instance.
        """
        self._coordinator = coordinator

    @property
    def oauth_credentials(self) -> dict[str, Any] | None:
        """Return the current OAuth credentials dict."""
        if self._coordinator.credentials_obj:
            return self._coordinator.credentials_obj.to_dict()
        return None

    async def load_oauth_credentials(
        self, force_reload: bool = False, silent: bool = False
    ) -> bool:
        """Load or reload OAuth credentials from storage."""
        return await self._coordinator.load_credentials_internal(
            force_reload=force_reload, silent=silent
        )


class GeminiCredentialCoordinator(ICredentialCoordinator):
    """Coordinates credential loading, validation, refresh, and file watching.

    This class encapsulates the credential initialization pipeline and provides
    a typed credential state boundary for other services.
    """

    def __init__(
        self,
        token_manager: TokenManager | None = None,
        file_watcher_state: FileWatcherState | None = None,
    ) -> None:
        """Initialize the credential coordinator.

        Args:
            token_manager: Optional TokenManager instance (creates default if None).
            file_watcher_state: Optional FileWatcherState instance (creates default if None).
        """
        self._token_manager = token_manager or TokenManager()
        self._file_watcher_state = file_watcher_state or FileWatcherState()
        self.credentials_obj: GeminiOAuthCredentials | None = None
        self.credentials_path: Path | None = None
        self.last_modified_ts: float = 0.0
        self.credentials_fingerprint: str | None = None
        self.credentials_file_hash: str | None = None
        self.last_credentials_event_hash: str | None = None
        self._last_credentials_event_mtime: float | None = None
        self._last_credentials_event_log_ts: float = 0.0
        self.gemini_cli_oauth_path: str | None = None

        # Adapters for compatibility with existing helper classes
        self._storage_adapter = CredentialStorageAdapter(self)
        self._provider_adapter = CredentialProviderAdapter(self)

    async def initialize(self, *, gemini_cli_oauth_path: str | None = None) -> None:
        """Load credentials and set initial health state.

        Args:
            gemini_cli_oauth_path: Optional custom path to .gemini directory.

        Raises:
            AuthenticationError: If credentials cannot be loaded or validated.
        """
        self._gemini_cli_oauth_path = gemini_cli_oauth_path

        # 1) Validate credentials file exists
        file_result = CredentialLoader.validate_credentials_file_exists(
            gemini_cli_oauth_path
        )
        if not file_result.is_valid:
            raise AuthenticationError(
                message=f"Failed to validate credentials file: {'; '.join(file_result.errors)}",
                details={"errors": file_result.errors},
            )

        self.credentials_path = file_result.path

        # 2) Load credentials
        if not await self.load_credentials_internal(force_reload=False, silent=False):
            raise AuthenticationError(
                message="Failed to load credentials despite validation passing",
                details={"path": str(file_result.path) if file_result.path else None},
            )

        # 3) Validate structure
        if self.credentials_obj is None:
            raise AuthenticationError(
                message="OAuth credentials are None after loading",
                details={"path": str(file_result.path) if file_result.path else None},
            )

        structure_result = CredentialLoader.validate_credentials_structure(
            self.credentials_obj.to_dict(), silent=False
        )
        if not structure_result.is_valid:
            raise AuthenticationError(
                message=f"Invalid credentials structure: {'; '.join(structure_result.errors)}",
                details={"errors": structure_result.errors},
            )

        # 4) Refresh if needed
        refreshed = await self.refresh_if_needed(force_reload=False)
        if not refreshed:
            logger.warning(
                "Token refresh pending; credentials may be expired. "
                "Gemini CLI background refresh was triggered."
            )

        # 5) Start file watching
        try:
            self._file_watcher_state.main_loop = asyncio.get_running_loop()
        except RuntimeError:
            # If no running loop, try to get or create one
            try:
                self._file_watcher_state.main_loop = asyncio.get_event_loop()
            except RuntimeError:
                # No event loop available, skip file watching
                logger.warning(
                    "No event loop available for file watching", exc_info=True
                )
                return

        FileWatcher.start_file_watching(
            self.credentials_path,
            self._stop_file_watching,
            self._file_watcher_state,
            self.handle_credentials_file_change,
        )

    async def validate_runtime(self) -> bool:
        """Return True when credentials are valid for request execution.

        If the token is expired, this method will attempt to refresh it
        (potentially triggering the CLI refresh process) before returning False.

        Returns:
            True if credentials are valid and ready for use, False otherwise.
        """
        if self.credentials_obj is None:
            return False

        # Check if token is expired
        if not self._token_manager.is_token_expired(self.credentials_obj.to_dict()):
            return True

        # Token is expired - attempt refresh (this will trigger CLI if needed)
        refreshed = await self.refresh_if_needed(force_reload=False)
        return refreshed

    async def refresh_if_needed(
        self, *, force_reload: bool = False, retry_after_seconds: float | None = None
    ) -> bool:
        """Refresh access token if required and return success.

        Args:
            force_reload: If True, force reload credentials before refresh.
            retry_after_seconds: Optional explicit retry delay suggested by the API.

        Returns:
            True if refresh succeeded or was not needed, False otherwise.
        """
        return await self._token_manager.refresh_token_if_needed(
            self._provider_adapter,
            force_reload=force_reload,
            retry_after_seconds=retry_after_seconds,
        )

    @property
    def credentials(self) -> GeminiOAuthCredentials | None:
        """Return the current credential payload.

        Returns:
            Current credentials or None if not loaded.
        """
        return self.credentials_obj

    @property
    def _credentials(self) -> GeminiOAuthCredentials | None:
        """Backward-compatible access to credentials."""
        return self.credentials_obj

    @_credentials.setter
    def _credentials(self, value: GeminiOAuthCredentials | None) -> None:
        """Backward-compatible setter for credentials."""
        self.credentials_obj = value

    @property
    def _credentials_path(self) -> Path | None:
        """Backward-compatible access to credentials path."""
        return self.credentials_path

    @_credentials_path.setter
    def _credentials_path(self, value: Path | None) -> None:
        """Backward-compatible setter for credentials path."""
        self.credentials_path = value

    @property
    def _last_modified(self) -> float:
        """Backward-compatible access to last modified timestamp."""
        return self.last_modified_ts

    @_last_modified.setter
    def _last_modified(self, value: float) -> None:
        """Backward-compatible setter for last modified timestamp."""
        self.last_modified_ts = value

    @property
    def _credentials_fingerprint(self) -> str | None:
        """Backward-compatible access to credentials fingerprint."""
        return self.credentials_fingerprint

    @_credentials_fingerprint.setter
    def _credentials_fingerprint(self, value: str | None) -> None:
        """Backward-compatible setter for credentials fingerprint."""
        self.credentials_fingerprint = value

    @property
    def _credentials_file_hash(self) -> str | None:
        """Backward-compatible access to credentials file hash."""
        return self.credentials_file_hash

    @_credentials_file_hash.setter
    def _credentials_file_hash(self, value: str | None) -> None:
        """Backward-compatible setter for credentials file hash."""
        self.credentials_file_hash = value

    @property
    def _last_credentials_event_hash(self) -> str | None:
        """Backward-compatible access to last credentials event hash."""
        return self.last_credentials_event_hash

    @_last_credentials_event_hash.setter
    def _last_credentials_event_hash(self, value: str | None) -> None:
        """Backward-compatible setter for last credentials event hash."""
        self.last_credentials_event_hash = value

    @property
    def _gemini_cli_oauth_path(self) -> str | None:
        """Backward-compatible access to custom .gemini path."""
        return self.gemini_cli_oauth_path

    @_gemini_cli_oauth_path.setter
    def _gemini_cli_oauth_path(self, value: str | None) -> None:
        """Backward-compatible setter for custom .gemini path."""
        self.gemini_cli_oauth_path = value

    async def _handle_credentials_file_change(self) -> None:
        """Backward-compatible alias for file change handler."""
        await self.handle_credentials_file_change()

    def _schedule_credentials_reload(self) -> None:
        """Schedule an asynchronous reload when the credentials file changes."""
        # Sync main_loop to state
        self._file_watcher_state.main_loop = asyncio.get_running_loop()
        FileWatcher.schedule_credentials_reload(
            self._file_watcher_state,
            self.handle_credentials_file_change,
            self._stop_file_watching,
        )

    def _stop_file_watching(self) -> None:
        """Stop watching the credentials file."""
        FileWatcher.stop_file_watching(self._file_watcher_state)

    async def handle_credentials_file_change(self) -> None:
        """Handle credentials file change event.

        This method is called when the file system watcher detects a change to the
        oauth_creds.json file. It forces a reload of credentials bypassing the cache
        to ensure the latest token is loaded even if the file timestamp didn't change.
        """
        try:
            previous_fingerprint = self.credentials_fingerprint

            # Validate file first (silently)
            file_result = CredentialLoader.validate_credentials_file_exists(
                self._gemini_cli_oauth_path
            )
            if not file_result.is_valid:
                logger.warning(
                    f"Updated credentials file is invalid: {'; '.join(file_result.errors)}"
                )
                return

            # Attempt to reload silently first to check if credentials actually changed
            credentials_changed = False
            if await self.load_credentials_internal(force_reload=True, silent=True):
                if (
                    previous_fingerprint is None
                    or previous_fingerprint != self.credentials_fingerprint
                ):
                    # Credentials actually changed
                    credentials_changed = True
                    logger.debug("Handling credentials file change...")
                    logger.info("Detected credential change; refreshing token...")

                # Always refresh token, even if credentials unchanged (token may be expired)
                refreshed = await self.refresh_if_needed(force_reload=False)
                if refreshed:
                    if credentials_changed:
                        logger.info(
                            "Successfully reloaded credentials from updated file"
                        )
                    # Update event hash on success
                    self.last_credentials_event_hash = self.credentials_file_hash
                else:
                    logger.warning(
                        "Credentials file reload completed but token is still invalid"
                    )
            else:
                logger.error(
                    "Failed to reload credentials after file change",
                    exc_info=True,
                )

        except Exception as e:
            logger.error(f"Error handling credentials file change: {e}", exc_info=True)

    async def load_credentials_internal(
        self, force_reload: bool = False, silent: bool = False
    ) -> bool:
        """Internal method to load credentials using CredentialLoader.

        Args:
            force_reload: If True, bypass cache and force reload.
            silent: If True, suppress INFO level logging.

        Returns:
            True if credentials loaded successfully, False otherwise.
        """
        # CredentialStorageAdapter implements CredentialStorage protocol
        return await CredentialLoader.load_oauth_credentials(
            self._storage_adapter, force_reload=force_reload, silent=silent  # type: ignore[arg-type]
        )
