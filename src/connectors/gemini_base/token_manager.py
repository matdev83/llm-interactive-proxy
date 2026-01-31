"""
Token management for Gemini OAuth connectors.

This module handles OAuth token lifecycle management including:
- Token expiry checking
- CLI-based token refresh
- Polling for refreshed tokens
"""

import asyncio
import logging
import shutil
import subprocess
import time
from typing import Any, Protocol, runtime_checkable

from src.connectors.gemini_base.credentials import (

    CLI_REFRESH_COMMAND,
    CLI_REFRESH_COOLDOWN_SECONDS,
    CLI_REFRESH_THRESHOLD_SECONDS,
    TOKEN_EXPIRY_BUFFER_SECONDS,
    TOKEN_REFRESH_MAX_WAIT_SECONDS,
    TOKEN_REFRESH_POLL_INTERVAL_SECONDS,
)

logger = logging.getLogger(__name__)


@runtime_checkable
class CredentialProvider(Protocol):

    """Protocol for credential access required by TokenManager."""

    @property
    def oauth_credentials(self) -> dict[str, Any] | None:
        """Return the current OAuth credentials dict."""
        ...

    async def load_oauth_credentials(
        self, force_reload: bool = False, silent: bool = False
    ) -> bool:
        """Load or reload OAuth credentials from storage."""
        ...


class TokenManager:
    """Manages OAuth token lifecycle for Gemini connectors.

    This class handles token expiry checking, CLI-based refresh triggering,
    and polling for refreshed tokens. It is designed to be composed into
    connector classes that provide credential storage.

    Attributes:
        _token_refresh_lock: Lock for thread-safe token refresh operations.
        _last_cli_refresh_attempt: Timestamp of the last CLI refresh attempt.
        _cli_refresh_process: Reference to the running CLI refresh subprocess.
        _refresh_token: Cached refresh token value.
    """

    def __init__(self) -> None:
        """Initialize the token manager."""
        self._token_refresh_lock = asyncio.Lock()
        self._last_cli_refresh_attempt: float = 0.0
        self._cli_refresh_process: subprocess.Popen[bytes] | None = None
        self._refresh_token: str | None = None

    def seconds_until_token_expiry(
        self, credentials: dict[str, Any] | None
    ) -> float | None:
        """Return seconds remaining before token expiry, or None if unknown.

        Args:
            credentials: The OAuth credentials dict containing expiry_date.

        Returns:
            Seconds until expiry, or None if expiry cannot be determined.
        """
        if not credentials:
            return None

        expiry_value = credentials.get("expiry_date")
        if not isinstance(expiry_value, int | float):
            return None

        expiry_seconds = float(expiry_value) / 1000.0
        return expiry_seconds - time.time()

    def is_token_expired(
        self,
        credentials: dict[str, Any] | None,
        buffer_seconds: float = TOKEN_EXPIRY_BUFFER_SECONDS,
    ) -> bool:
        """Check if the current access token is expired or within buffer window.

        Args:
            credentials: The OAuth credentials dict.
            buffer_seconds: Buffer time before expiry to consider token expired.

        Returns:
            True if token is expired or will expire within buffer, False otherwise.
        """
        if not credentials:
            return True

        seconds_remaining = self.seconds_until_token_expiry(credentials)
        if seconds_remaining is None:
            return False

        return seconds_remaining <= buffer_seconds

    def should_trigger_cli_refresh(self, credentials: dict[str, Any] | None) -> bool:
        """Determine whether we should proactively trigger CLI token refresh.

        Args:
            credentials: The OAuth credentials dict.

        Returns:
            True if CLI refresh should be triggered, False otherwise.
        """
        if not credentials:
            return True

        seconds_remaining = self.seconds_until_token_expiry(credentials)
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

    def launch_cli_refresh_process(self) -> None:
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

            self._cli_refresh_process = subprocess.Popen(
                command,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                shell=False,
            )
            self._last_cli_refresh_attempt = now
            logger.info("Triggered Gemini CLI background refresh process")
        except FileNotFoundError:
            self._last_cli_refresh_attempt = now
            logger.error(
                "Gemini CLI binary not found; cannot refresh OAuth token automatically.",
                exc_info=True,
            )
        except Exception as exc:  # pragma: no cover - defensive logging
            self._last_cli_refresh_attempt = now
            logger.error(
                "Failed to launch Gemini CLI for token refresh: %s",
                exc,
                exc_info=True,
            )

    async def poll_for_new_token(
        self,
        credential_provider: CredentialProvider,
        max_wait_seconds: float | None = None,
    ) -> bool:
        """Poll the credential file for an updated token after CLI refresh.

        Args:
            credential_provider: Object providing credential access and loading.
            max_wait_seconds: Maximum time to wait for token refresh.

        Returns:
            True if a valid token was obtained, False otherwise.
        """
        credentials = credential_provider.oauth_credentials
        if not self.is_token_expired(credentials):
            return True

        wait_window = (
            TOKEN_REFRESH_MAX_WAIT_SECONDS
            if max_wait_seconds is None
            else max_wait_seconds
        )
        if wait_window <= 0:
            return not self.is_token_expired(credentials)

        deadline = time.time() + wait_window
        attempts = 0

        while time.time() < deadline:
            remaining = deadline - time.time()
            sleep_for = min(TOKEN_REFRESH_POLL_INTERVAL_SECONDS, remaining)
            if sleep_for > 0:
                await asyncio.sleep(sleep_for)
            attempts += 1
            loaded = await credential_provider.load_oauth_credentials(silent=True)
            if loaded and not self.is_token_expired(
                credential_provider.oauth_credentials
            ):
                logger.debug("Token refresh succeeded after %d poll attempts", attempts)
                return True

        # One final check in case the token refreshed just as the loop exited
        loaded = await credential_provider.load_oauth_credentials(silent=True)
        if loaded and not self.is_token_expired(credential_provider.oauth_credentials):
            logger.debug(
                "Token refresh finalized after max wait window (%s seconds)",
                wait_window,
            )
            return True

        return not self.is_token_expired(credential_provider.oauth_credentials)

    def get_refresh_token(self, credentials: dict[str, Any] | None) -> str | None:
        """Get refresh token, either from credentials or cached value.

        Args:
            credentials: The OAuth credentials dict.

        Returns:
            The refresh token string, or None if not available.
        """
        if self._refresh_token:
            return self._refresh_token

        if credentials and "refresh_token" in credentials:
            self._refresh_token = credentials["refresh_token"]
            return self._refresh_token

        return None

    async def refresh_token_if_needed(
        self,
        credential_provider: CredentialProvider,
        *,
        force_reload: bool = False,
        retry_after_seconds: float | None = None,
    ) -> bool:
        """Ensure a valid access token is available, refreshing when necessary.

        This method orchestrates the token refresh flow:
        1. Check if token is expired or near expiry
        2. If near expiry but not expired, trigger background CLI refresh
        3. If expired, reload credentials and/or trigger CLI refresh and poll

        Args:
            credential_provider: Object providing credential access and loading.
            force_reload: If True, bypass cache and force reload.
            retry_after_seconds: Optional explicit retry delay suggested by the API.

        Returns:
            True if a valid token is available, False otherwise.
        """
        credentials = credential_provider.oauth_credentials
        if not credentials or force_reload:
            await credential_provider.load_oauth_credentials(force_reload=force_reload)
            credentials = credential_provider.oauth_credentials

        if not credentials:
            return False

        expired = self.is_token_expired(credentials)
        near_expiry = self.should_trigger_cli_refresh(credentials)

        if not expired and not near_expiry:
            return True

        async with self._token_refresh_lock:
            credentials = credential_provider.oauth_credentials
            if not credentials:
                await credential_provider.load_oauth_credentials()
                credentials = credential_provider.oauth_credentials

            if not credentials:
                return False

            expired = self.is_token_expired(credentials)
            near_expiry = self.should_trigger_cli_refresh(credentials)

            if not expired and near_expiry:
                self.launch_cli_refresh_process()
                return True

            if not expired:
                return True

            logger.info(
                "Access token expired; reloading credentials and invoking CLI refresh if needed."
            )

            reloaded = await credential_provider.load_oauth_credentials()
            credentials = credential_provider.oauth_credentials
            if reloaded and not self.is_token_expired(credentials):
                if self.should_trigger_cli_refresh(credentials):
                    self.launch_cli_refresh_process()
                return True

            self.launch_cli_refresh_process()

            refreshed = await self.poll_for_new_token(credential_provider)
            if refreshed:
                return True

            logger.warning(
                "Automatic Gemini CLI refresh did not produce a valid token in time."
            )
            return False

    async def cleanup(self) -> None:
        """Clean up subprocess to prevent resource leaks.

        This method explicitly terminates the CLI refresh subprocess if it's
        still running. Should be called during connector shutdown to ensure
        subprocesses are properly terminated.

        Note: This is the preferred cleanup method over relying on __del__,
        which may not be called in scenarios with circular references or
        during interpreter shutdown.
        """
        if hasattr(self, "_cli_refresh_process"):
            process = self._cli_refresh_process
            if process is not None:
                try:
                    # Check if process is still running
                    if process.poll() is None:
                        # Process is still running, terminate it
                        process.terminate()
                        try:
                            # Wait with timeout
                            process.wait(timeout=5)
                        except subprocess.TimeoutExpired:
                            # Process didn't terminate, force kill
                            process.kill()
                            import contextlib

                            with contextlib.suppress(
                                subprocess.TimeoutExpired, Exception
                            ):
                                process.wait(timeout=5)
                except Exception:
                    # Log cleanup errors but don't let them prevent cleanup completion
                    # This ensures the reference is cleared even if termination fails
                    if logger.isEnabledFor(logging.WARNING):
                        logger.warning(
                            "Error during TokenManager cleanup (subprocess termination)",
                            exc_info=True,
                        )
                finally:
                    # Clear reference to prevent leaks
                    self._cli_refresh_process = None

    def __del__(self) -> None:
        """Cleanup subprocess on destruction.

        This ensures that if TokenManager is used independently or if
        the connector's __del__ fails, subprocesses are still cleaned up.
        """
        # Guard against partial initialization
        if hasattr(self, "_cli_refresh_process"):
            process = self._cli_refresh_process
            if process is not None:
                # Use contextlib.suppress for expected cleanup exceptions
                import contextlib

                # Expected exceptions during subprocess cleanup:
                # - OSError: process operations may fail during shutdown
                # - ProcessLookupError: process already terminated
                # - AttributeError: partial initialization state
                # - Exception: any other exceptions that might occur during cleanup
                # Suppress these as they're cleanup-time artifacts
                with contextlib.suppress(
                    OSError, ProcessLookupError, AttributeError, Exception
                ):
                    if process.poll() is None:
                        # Process is still running, terminate it
                        process.terminate()
                        try:
                            process.wait(timeout=5)
                        except subprocess.TimeoutExpired:
                            # Process didn't terminate, force kill
                            process.kill()
                            with contextlib.suppress(
                                subprocess.TimeoutExpired, OSError
                            ):
                                process.wait(timeout=5)

                # Finally clause runs regardless of exceptions
                # Always clear the reference to prevent leaks
                self._cli_refresh_process = None


__all__ = [
    "TokenManager",
    "CredentialProvider",
]
