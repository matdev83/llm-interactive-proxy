"""
Credentials handling for Gemini OAuth Base.
"""

import hashlib
import logging
import time
from pathlib import Path
from typing import TYPE_CHECKING, Any

from watchdog.events import FileSystemEventHandler

from src.core.app.constants.logging_constants import TRACE_LEVEL

if TYPE_CHECKING:
    from src.connectors.gemini_base.connector import GeminiOAuthBaseConnector

logger = logging.getLogger(__name__)

TOKEN_EXPIRY_BUFFER_SECONDS = 30.0
CLI_REFRESH_THRESHOLD_SECONDS = 120.0
CLI_REFRESH_COOLDOWN_SECONDS = 30.0
TOKEN_REFRESH_MAX_WAIT_SECONDS = 30.0
TOKEN_REFRESH_POLL_INTERVAL_SECONDS = 1.0
CLI_REFRESH_COMMAND = [
    "gemini",
    "-m",
    "gemini-2.5-flash",
    "-y",
    "-p",
    "Hi. What's up?",
]


class GeminiPersonalCredentialsFileHandler(FileSystemEventHandler):
    """File system event handler for monitoring OAuth credentials file changes."""

    def __init__(self, connector: "GeminiOAuthBaseConnector"):
        """Initialize the file handler with reference to the connector.

        Args:
            connector: The GeminiOAuthPersonalConnector instance to notify of file changes
        """
        super().__init__()
        self.connector = connector

    def on_modified(self, event):
        """Handle file modification events."""
        if not event.is_directory and isinstance(event.src_path, str):
            # Compare paths using Path objects to handle Windows/Unix differences
            try:
                event_path = Path(event.src_path).resolve()
                credentials_path = (
                    self.connector._credentials_path.resolve()
                    if self.connector._credentials_path
                    else None
                )

                if credentials_path and event_path == credentials_path:
                    try:
                        current_mtime = event_path.stat().st_mtime
                    except OSError:
                        current_mtime = None

                    last_mtime = self.connector._last_credentials_event_mtime
                    if (
                        current_mtime is not None
                        and last_mtime is not None
                        and current_mtime == last_mtime
                    ):
                        return

                    self.connector._last_credentials_event_mtime = current_mtime
                    file_hash: str | None = None
                    try:
                        file_hash = hashlib.sha256(event_path.read_bytes()).hexdigest()
                    except OSError:
                        file_hash = None

                    if file_hash is not None:
                        if (
                            file_hash == self.connector._credentials_file_hash
                            or file_hash == self.connector._last_credentials_event_hash
                        ):
                            if logger.isEnabledFor(logging.DEBUG):
                                logger.debug(
                                    "Credentials file event ignored (unchanged hash): %s",
                                    event.src_path,
                                )
                            return
                        self.connector._last_credentials_event_hash = file_hash

                    now = time.time()
                    if now - self.connector._last_credentials_event_log_ts >= 30:
                        # Log at TRACE level to reduce noise - SQLite DBs update frequently
                        logger.log(
                            TRACE_LEVEL,
                            "Credentials file modified: %s",
                            event.src_path,
                        )
                        self.connector._last_credentials_event_log_ts = now
                    else:
                        logger.log(
                            TRACE_LEVEL,
                            "Credentials file modified (suppressed log window): %s",
                            event.src_path,
                        )

                    # Schedule credential reload in the connector's event loop in a thread-safe way
                    self.connector._schedule_credentials_reload()
            except Exception as e:
                if logger.isEnabledFor(logging.ERROR):
                    logger.error(f"Error processing file modification event: {e}")


class _StaticTokenCreds:
    """Simple credentials wrapper for static OAuth tokens."""

    def __init__(self, token: str) -> None:
        self.token = token

    def before_request(
        self, request: Any, method: str, url: str, headers: dict
    ) -> None:
        """Apply the token to the authentication header."""
        headers["Authorization"] = f"Bearer {self.token}"

    def refresh(self, request: Any) -> None:
        """No-op: token is managed by the CLI; we reload from file when needed."""
        return
