"""
SQLite-based credential provider for Antigravity backend.

Loads OAuth credentials from the Antigravity VS Code state database.
"""

import hashlib
import json
import logging
import os
import sqlite3
import time
import asyncio
from pathlib import Path
from typing import Any

from src.core.app.constants.logging_constants import TRACE_LEVEL

logger = logging.getLogger(__name__)

# Antigravity-specific constants
ANTIGRAVITY_AUTH_KEY = "antigravityAuthStatus"
ANTIGRAVITY_STATE_DB_ENV = "ANTIGRAVITY_STATE_DB"
GLOBAL_STORAGE_SUBPATH = Path("Antigravity") / "User" / "globalStorage"


class AntigravitySQLiteCredentialProvider:
    """Credential provider that loads from Antigravity SQLite database.

    This provider implements the ICredentialProvider protocol and is used by
    the antigravity-oauth backend.
    """

    def __init__(self) -> None:
        """Initialize the SQLite credential provider."""
        self._credentials_path: Path | None = None
        self._last_modified: float = 0
        self._cached_credentials: dict[str, Any] | None = None
        self._credentials_fingerprint: str | None = None
        self._credentials_file_hash: str | None = None

    def get_path(self) -> Path | None:
        """Get the path to the credentials database.

        Returns:
            Path to the state.vscdb file.
        """
        return self._credentials_path

    def _candidate_state_db_paths(self) -> list[Path]:
        """Build a prioritized list of potential Antigravity state database paths.

        Uses an explicit override when provided, otherwise resolves platform
        specific roaming/config locations with a fallback to macOS paths.
        """
        override = os.getenv(ANTIGRAVITY_STATE_DB_ENV)
        if override:
            override_path = Path(override)
            if str(override_path).strip():
                if logger.isEnabledFor(logging.DEBUG):
                    logger.debug(
                        f"Using explicit ANTIGRAVITY_STATE_DB override: {override_path}"
                    )
                return [override_path]

        candidates: list[Path] = []
        # Windows roaming profile (e.g., %APPDATA%)
        appdata = os.getenv("APPDATA")
        if appdata:
            base = Path(appdata)
            candidates.append(base / GLOBAL_STORAGE_SUBPATH / "state.vscdb")
            candidates.append(base / GLOBAL_STORAGE_SUBPATH / "state.vscdb.backup")
        elif os.name == "nt":
            roaming_home = Path.home() / "AppData" / "Roaming"
            candidates.append(roaming_home / GLOBAL_STORAGE_SUBPATH / "state.vscdb")
            candidates.append(
                roaming_home / GLOBAL_STORAGE_SUBPATH / "state.vscdb.backup"
            )

        # XDG config locations (Linux) or ~/.config fallback
        home_dir = Path.home()
        xdg_config_home = os.getenv("XDG_CONFIG_HOME")
        config_home = Path(xdg_config_home) if xdg_config_home else home_dir / ".config"
        candidates.append(config_home / GLOBAL_STORAGE_SUBPATH / "state.vscdb")
        candidates.append(config_home / GLOBAL_STORAGE_SUBPATH / "state.vscdb.backup")

        # macOS Application Support location
        mac_config_base = home_dir / "Library" / "Application Support"
        candidates.append(mac_config_base / GLOBAL_STORAGE_SUBPATH / "state.vscdb")
        candidates.append(
            mac_config_base / GLOBAL_STORAGE_SUBPATH / "state.vscdb.backup"
        )

        # Deduplicate while preserving order
        seen: set[str] = set()
        unique_candidates: list[Path] = []
        for path in candidates:
            path_key = str(path)
            if path_key in seen:
                continue
            seen.add(path_key)
            unique_candidates.append(path)

        if logger.isEnabledFor(TRACE_LEVEL):
            logger.log(
                TRACE_LEVEL,
                f"Candidate Antigravity DB paths: {[str(p) for p in unique_candidates]}",
            )
        return unique_candidates

    def _load_auth_status_from_db(self, db_path: Path) -> dict[str, Any] | None:
        """Read the Antigravity auth status payload from the state database."""
        try:
            # Use URI mode for read-only access to avoid locking issues
            uri_path = (
                db_path.as_uri().replace("file:///", "file:/")
                if os.name == "nt"
                else db_path.as_uri()
            )
            # Ensure proper URI format for sqlite3
            if not uri_path.startswith("file:"):
                uri_path = f"file:{db_path.as_posix()}"

            connection_string = f"{uri_path}?mode=ro"

            if logger.isEnabledFor(TRACE_LEVEL):
                logger.log(
                    TRACE_LEVEL,
                    f"Attempting to read Antigravity DB at: {connection_string}",
                )

            with sqlite3.connect(connection_string, uri=True) as conn:
                cursor = conn.cursor()
                cursor.execute(
                    "SELECT value FROM ItemTable WHERE key=? "
                    "ORDER BY rowid DESC LIMIT 1",
                    (ANTIGRAVITY_AUTH_KEY,),
                )
                row = cursor.fetchone()
                if not row:
                    if logger.isEnabledFor(logging.DEBUG):
                        logger.debug(
                            f"Key '{ANTIGRAVITY_AUTH_KEY}' not found in {db_path}"
                        )
                    return None
                raw_value = row[0]
                return self._parse_auth_status_value(raw_value)
        except sqlite3.Error as exc:
            logger.warning(
                "Unable to read Antigravity state database at %s: %s", db_path, exc
            )
            return None
        except Exception as exc:  # pragma: no cover - defensive guardrail
            logger.warning(
                "Unexpected error reading Antigravity state db %s: %s", db_path, exc
            )
            return None

    def _parse_auth_status_value(self, raw_value: str | bytes) -> dict[str, Any] | None:
        """Parse the JSON string from the database into a dictionary."""
        try:
            if isinstance(raw_value, bytes):
                raw_value = raw_value.decode("utf-8")

            raw_value_str = str(raw_value)
            if not raw_value_str.strip():
                if logger.isEnabledFor(logging.DEBUG):
                    logger.debug("Auth status value is empty.")
                return None

            auth_data = json.loads(raw_value_str)

            if auth_data is None:
                if logger.isEnabledFor(logging.DEBUG):
                    logger.debug("Auth status value is null/None.")
                return None

            if isinstance(auth_data, dict):
                return auth_data

            if logger.isEnabledFor(logging.WARNING):
                logger.warning(
                    f"Parsed auth status is not a dictionary: {type(auth_data)}"
                )
            return None
        except json.JSONDecodeError as exc:
            if logger.isEnabledFor(logging.WARNING):
                logger.warning(
                    f"Failed to parse Antigravity auth status JSON: {exc}",
                    exc_info=True,
                )
            return None
        except Exception as exc:  # pragma: no cover
            if logger.isEnabledFor(logging.ERROR):
                logger.error(
                    f"Unexpected error parsing auth status: {exc}", exc_info=True
                )
            return None

    def _normalize_credentials(self, credentials: dict[str, Any]) -> dict[str, Any]:
        """Normalize Antigravity-specific credentials to standard OAuth format.

        Antigravity stores credentials with 'apiKey' field, but the OAuth system
        expects 'access_token'. This method maps the fields appropriately.
        """
        # Create a copy to avoid modifying the original
        normalized = credentials.copy()

        # Map Antigravity 'apiKey' to standard OAuth 'access_token'
        if "apiKey" in normalized and "access_token" not in normalized:
            normalized["access_token"] = normalized.pop("apiKey")
        elif "apiKey" in normalized and "access_token" in normalized:
            # Both present - prefer access_token but keep apiKey for compatibility
            normalized.pop("apiKey")

        # The Antigravity token behaves like a static bearer; if no refresh_token is
        # present, ignore expiry metadata so the base class does not mark it stale.
        if not normalized.get("refresh_token"):
            normalized.pop("expiry_date", None)
            normalized.pop("refresh_token", None)

        return normalized

    def validate(
        self, credentials: dict[str, Any], silent: bool = False
    ) -> tuple[bool, list[str]]:
        """Validate the structure and content of OAuth credentials.

        Args:
            credentials: The credentials dictionary to validate.
            silent: If True, suppress INFO level logging.

        Returns:
            Tuple of (is_valid, list_of_errors).
        """
        errors: list[str] = []

        # Required fields for OAuth credentials
        if "access_token" not in credentials:
            errors.append("Missing required field: access_token")
        elif (
            not isinstance(credentials["access_token"], str)
            or not credentials["access_token"]
        ):
            errors.append("Invalid access_token: must be a non-empty string")

        return len(errors) == 0, errors

    def compute_fingerprint(self, credentials: dict[str, Any]) -> str:
        """Compute a stable fingerprint for the credentials.

        Args:
            credentials: The credentials dictionary.

        Returns:
            SHA-256 hash of the relevant credential fields.
        """
        relevant = {
            "access_token": credentials.get("access_token", ""),
            "refresh_token": credentials.get("refresh_token", ""),
            "expiry_date": credentials.get("expiry_date"),
        }
        payload = json.dumps(relevant, sort_keys=True, default=str)
        return hashlib.sha256(payload.encode("utf-8", "ignore")).hexdigest()

    async def load(
        self, force_reload: bool = False, silent: bool = False
    ) -> dict[str, Any] | None:
        """Load OAuth credentials from the Antigravity state database.

        Args:
            force_reload: If True, bypass cache and force reload from file.
            silent: If True, suppress INFO level logging.

        Returns:
            Credentials dictionary or None if loading failed.
        """
        # Prefer the currently used path first to keep file watching stable
        candidate_paths = self._candidate_state_db_paths()
        if self._credentials_path:
            preferred = [self._credentials_path]
            preferred.extend(
                path for path in candidate_paths if path != self._credentials_path
            )
            candidate_paths = preferred

        errors: list[str] = []
        for path in candidate_paths:
            try:
                if not path.exists():
                    if logger.isEnabledFor(logging.DEBUG):
                        logger.debug(f"Path does not exist: {path}")
                    continue

                current_modified = None
                try:
                    current_modified = path.stat().st_mtime
                except OSError:
                    current_modified = None

                if (
                    not force_reload
                    and self._cached_credentials
                    and self._credentials_path
                    and path == self._credentials_path
                    and current_modified is not None
                    and current_modified == self._last_modified
                ):
                    if logger.isEnabledFor(logging.DEBUG):
                        logger.debug(
                            "Antigravity credentials unchanged; using cached copy."
                        )
                    return self._cached_credentials

                credentials = self._load_auth_status_from_db(path)
                if not credentials:
                    errors.append(
                        f"Failed to load Antigravity credentials from {path}; "
                        f"missing {ANTIGRAVITY_AUTH_KEY}."
                    )
                    continue

                # Map Antigravity-specific fields to standard OAuth format
                credentials = self._normalize_credentials(credentials)

                is_valid, validation_errors = self.validate(credentials, silent=silent)
                errors.extend(validation_errors)
                if not is_valid:
                    if logger.isEnabledFor(logging.WARNING):
                        logger.warning(
                            f"Invalid credentials in {path}: {validation_errors}"
                        )
                    continue

                self._cached_credentials = credentials
                self._credentials_path = path
                self._last_modified = current_modified or time.time()
                self._credentials_fingerprint = self.compute_fingerprint(credentials)

                try:
                    credentials_file_hash = hashlib.sha256(
                        await asyncio.to_thread(path.read_bytes)
                    ).hexdigest()
                except OSError:
                    credentials_file_hash = None
                self._credentials_file_hash = credentials_file_hash

                if not silent:
                    logger.info(
                        "Loaded Antigravity OAuth credentials from %s%s",
                        path,
                        " (force reload)" if force_reload else "",
                    )
                return credentials
            except Exception as exc:
                errors.append(f"Unexpected error reading {path}: {exc}")
                logger.warning(
                    "Error loading Antigravity credentials from %s: %s", path, exc
                )

        if errors and logger.isEnabledFor(logging.ERROR):
            logger.error(f"Failed to load Antigravity credentials. Errors: {errors}")
        return None

    def get_fingerprint(self) -> str | None:
        """Get the current credentials fingerprint.

        Returns:
            The fingerprint string or None if not computed.
        """
        return self._credentials_fingerprint

    def get_file_hash(self) -> str | None:
        """Get the current credentials file hash.

        Returns:
            The file hash string or None if not computed.
        """
        return self._credentials_file_hash

    def get_last_modified(self) -> float:
        """Get the last modified timestamp.

        Returns:
            The last modified timestamp.
        """
        return self._last_modified


__all__ = ["AntigravitySQLiteCredentialProvider"]
