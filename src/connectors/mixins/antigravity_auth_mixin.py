"""
Mixin for shared Antigravity authentication and infrastructure logic.

.. deprecated::
    This mixin is deprecated. Use the Strategy Pattern components instead:
    - AntigravitySQLiteCredentialProvider for credential loading
    - AntigravitySandboxEndpoint for endpoint configuration
    - AntigravityRequestBodyBuilder for request wrapping
    - AntigravityProjectDiscovery for project discovery

    Import from src.connectors.gemini_base:
    - from src.connectors.gemini_base.credential_providers import AntigravitySQLiteCredentialProvider
    - from src.connectors.gemini_base.endpoints import AntigravitySandboxEndpoint
    - from src.connectors.gemini_base.request_builders import AntigravityRequestBodyBuilder
    - from src.connectors.gemini_base.project_discovery import AntigravityProjectDiscovery

This module is retained for backward compatibility but will be removed in a future version.
"""

import warnings

warnings.warn(
    "antigravity_auth_mixin.py is deprecated. Use Strategy Pattern components from "
    "src.connectors.gemini_base instead (AntigravitySQLiteCredentialProvider, "
    "AntigravitySandboxEndpoint, AntigravityRequestBodyBuilder, "
    "AntigravityProjectDiscovery).",
    DeprecationWarning,
    stacklevel=2,
)

import hashlib
import json
import logging
import os
import sqlite3
import time
from pathlib import Path
from typing import Any

from src.core.app.constants.logging_constants import TRACE_LEVEL

logger = logging.getLogger(__name__)

# Antigravity-specific constants
ANTIGRAVITY_AUTH_KEY = "antigravityAuthStatus"
ANTIGRAVITY_SANDBOX_ENDPOINT = "https://daily-cloudcode-pa.sandbox.googleapis.com"
ANTIGRAVITY_STATE_DB_ENV = "ANTIGRAVITY_STATE_DB"
ANTIGRAVITY_USER_AGENT = "antigravity/1.11.5 windows/amd64"
GLOBAL_STORAGE_SUBPATH = Path("Antigravity") / "User" / "globalStorage"


class AntigravityAuthMixin:
    """Shared Antigravity authentication and endpoint logic.

    This mixin provides:
    - SQLite credential loading from Antigravity state database
    - Sandbox endpoint URL configuration
    - User-Agent headers
    - Request wrapper formatting

    Expected to be mixed with a connector class that has:
    - self._oauth_credentials
    - self._credentials_path
    - self._last_modified
    - self._credentials_fingerprint
    - self._credentials_file_hash
    - self._last_credentials_event_hash
    - self._credential_validation_errors
    - self._validate_credentials_structure()
    - self._compute_credentials_fingerprint()
    """

    def _get_antigravity_user_agent(self) -> str:
        """Get the Antigravity-specific User-Agent string."""
        return ANTIGRAVITY_USER_AGENT

    def _get_antigravity_headers(self) -> dict[str, str]:
        """Get headers for API requests with Antigravity-specific User-Agent.

        The Antigravity sandbox endpoint requires a specific User-Agent header.
        """
        headers = {}
        if hasattr(super(), "_get_api_headers"):
            headers = super()._get_api_headers()  # type: ignore
        headers["User-Agent"] = self._get_antigravity_user_agent()
        return headers

    def _build_antigravity_request_wrapper(
        self,
        effective_model: str,
        project_id: str,
        request_data: Any,
        inner_request: dict[str, Any],
    ) -> dict[str, Any]:
        """Build Antigravity-specific request wrapper format.

        The Antigravity sandbox API uses a different wrapper structure:
        - 'requestId' instead of 'user_prompt_id'
        - 'model' at top level (not inside 'request')
        - Additional 'userAgent' and 'requestType' fields required

        Args:
            effective_model: The model name to use
            project_id: The project ID from loadCodeAssist
            request_data: The original request data (for generating requestId)
            inner_request: The inner request (API-specific format)

        Returns:
            Antigravity-formatted request body dict
        """
        # Generate requestId
        request_id = None
        if hasattr(self, "_generate_user_prompt_id"):
            request_id = self._generate_user_prompt_id(request_data)  # type: ignore
        else:
            # Fallback: use timestamp-based ID
            request_id = f"req_{int(time.time() * 1000)}"

        return {
            "project": project_id,
            "requestId": request_id,
            "request": inner_request,
            "model": effective_model,
            "userAgent": "antigravity",
            "requestType": "agent",
        }

    def _candidate_state_db_paths(self) -> list[Path]:
        """
        Build a prioritized list of potential Antigravity state database paths.

        Uses an explicit override when provided, otherwise resolves platform
        specific roaming/config locations with a fallback to macOS paths.
        """
        override = os.getenv(ANTIGRAVITY_STATE_DB_ENV)
        if override:
            override_path = Path(override)
            if str(override_path).strip():
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
        """
        Read the Antigravity auth status payload from the state database.
        """
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

    def _extract_credentials_from_db(self, db_path: Path) -> dict[str, Any] | None:
        """
        Load and parse the Antigravity auth status from the database.
        """
        return self._load_auth_status_from_db(db_path)

    def _parse_auth_status_value(self, raw_value: str | bytes) -> dict[str, Any] | None:
        """
        Parse the JSON string from the database into a dictionary.
        """
        try:
            if isinstance(raw_value, bytes):
                # Decode bytes to string if necessary
                raw_value = raw_value.decode("utf-8")

            # Ensure raw_value is a string before calling strip()
            raw_value_str = str(raw_value)
            if not raw_value_str.strip():
                logger.debug("Auth status value is empty.")
                return None

            auth_data = json.loads(raw_value_str)
            if isinstance(auth_data, dict):
                return auth_data

            if logger.isEnabledFor(logging.WARNING):
                logger.warning(
                    f"Parsed auth status is not a dictionary: {type(auth_data)}"
                )
            return None
        except json.JSONDecodeError as exc:
            if logger.isEnabledFor(logging.WARNING):
                logger.warning(f"Failed to parse Antigravity auth status JSON: {exc}")
            return None
        except Exception as exc:  # pragma: no cover
            if logger.isEnabledFor(logging.ERROR):
                logger.error(
                    f"Unexpected error parsing auth status: {exc}", exc_info=True
                )
            return None

    def _normalize_antigravity_credentials(
        self, credentials: dict[str, Any]
    ) -> dict[str, Any]:
        """
        Normalize Antigravity-specific credentials to standard OAuth format.

        Antigravity stores credentials with 'apiKey' field, but the OAuth system
        expects 'access_token'. This method maps the fields appropriately.
        """
        if not isinstance(credentials, dict):
            return credentials

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

    async def _load_oauth_credentials(
        self, force_reload: bool = False, silent: bool = False
    ) -> bool:
        """
        Load OAuth credentials from the Antigravity state database or its backup.

        Args:
            force_reload: If True, bypass cache and force reload from file
            silent: If True, suppress INFO level logging (used when checking for changes)
        """
        # Prefer the currently used path first to keep file watching stable
        candidate_paths = self._candidate_state_db_paths()
        if hasattr(self, "_credentials_path") and self._credentials_path:  # type: ignore
            preferred = [self._credentials_path]  # type: ignore
            preferred.extend(
                path
                for path in candidate_paths
                if path != self._credentials_path  # type: ignore
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
                    and hasattr(self, "_oauth_credentials")
                    and self._oauth_credentials  # type: ignore
                    and hasattr(self, "_credentials_path")
                    and self._credentials_path  # type: ignore
                    and path == self._credentials_path  # type: ignore
                    and current_modified is not None
                    and hasattr(self, "_last_modified")
                    and current_modified == self._last_modified  # type: ignore
                ):
                    logger.debug(
                        "Antigravity credentials unchanged; using cached copy."
                    )
                    return True

                credentials = self._extract_credentials_from_db(path)
                if not credentials:
                    errors.append(
                        f"Failed to load Antigravity credentials from {path}; missing {ANTIGRAVITY_AUTH_KEY}."
                    )
                    continue

                # Map Antigravity-specific fields to standard OAuth format
                credentials = self._normalize_antigravity_credentials(credentials)

                is_valid = False
                validation_errors = []
                if hasattr(self, "_validate_credentials_structure"):
                    is_valid, validation_errors = self._validate_credentials_structure(  # type: ignore
                        credentials, silent=silent
                    )
                else:
                    # Assume valid if method missing (should be mixed in)
                    is_valid = True

                errors.extend(validation_errors)
                if not is_valid:
                    logger.warning(
                        f"Invalid credentials in {path}: {validation_errors}"
                    )
                    continue

                self._oauth_credentials = credentials  # type: ignore
                self._credentials_path = path  # type: ignore
                self._last_modified = current_modified or time.time()  # type: ignore

                if hasattr(self, "_compute_credentials_fingerprint"):
                    self._credentials_fingerprint = self._compute_credentials_fingerprint(  # type: ignore
                        credentials
                    )

                try:
                    credentials_file_hash = hashlib.sha256(
                        path.read_bytes()
                    ).hexdigest()
                except OSError:
                    credentials_file_hash = None
                self._credentials_file_hash = credentials_file_hash  # type: ignore
                self._last_credentials_event_hash = credentials_file_hash  # type: ignore
                if not silent:
                    logger.info(
                        "Loaded Antigravity OAuth credentials from %s%s",
                        path,
                        " (force reload)" if force_reload else "",
                    )
                return True
            except Exception as exc:
                errors.append(f"Unexpected error reading {path}: {exc}")
                logger.warning(
                    "Error loading Antigravity credentials from %s: %s", path, exc
                )

        if errors:
            if hasattr(self, "_credential_validation_errors"):
                self._credential_validation_errors = errors  # type: ignore
            if logger.isEnabledFor(logging.ERROR):
                logger.error(
                    f"Failed to load Antigravity credentials. Errors: {errors}"
                )
        return False
