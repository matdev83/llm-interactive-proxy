"""
Gemini OAuth connector that reuses Antigravity app credentials.

This backend mirrors the personal/free OAuth connectors but reads the access
token from Antigravity's VS Code style state database and targets the Cloud
Code PA sandbox endpoint observed in Antigravity logs.
"""

import json
import logging
import os
import sqlite3
import time
from pathlib import Path
from typing import Any

import httpx

from src.connectors.gemini_oauth_free import GeminiOAuthFreeConnector
from src.core.config.app_config import AppConfig
from src.core.services.backend_registry import backend_registry
from src.core.services.translation_service import TranslationService

logger = logging.getLogger(__name__)

ANTIGRAVITY_AUTH_KEY = "antigravityAuthStatus"
ANTIGRAVITY_SANDBOX_ENDPOINT = "https://daily-cloudcode-pa.sandbox.googleapis.com"
ANTIGRAVITY_STATE_DB_ENV = "ANTIGRAVITY_STATE_DB"
GLOBAL_STORAGE_SUBPATH = Path("Antigravity") / "User" / "globalStorage"


class GeminiOAuthAntigravityConnector(GeminiOAuthFreeConnector):
    """
    Connector for Gemini using OAuth credentials from the Antigravity app.
    """

    backend_type: str = "gemini-oauth-antigravity"

    def __init__(
        self,
        client: httpx.AsyncClient,
        config: AppConfig,
        translation_service: TranslationService,
        name: str | None = None,
    ) -> None:
        super().__init__(
            client,
            config,
            translation_service,
            name=name or self.backend_type,
        )

    async def initialize(self, **kwargs: Any) -> None:
        """Initialize using Antigravity's sandbox endpoint by default."""
        kwargs.setdefault("gemini_api_base_url", ANTIGRAVITY_SANDBOX_ENDPOINT)
        try:
            await super().initialize(**kwargs)
        except Exception as exc:
            # Never propagate init errors so other backends remain usable.
            logger.warning(
                "Failed to initialize gemini-oauth-antigravity backend: %s",
                exc,
                exc_info=True,
            )
            self._fail_init([f"Initialization failed: {exc}"])

    async def _ensure_models_loaded(self) -> None:
        """
        Fetch available models from the Antigravity sandbox if possible.

        If enumeration fails, fall back to the base class hardcoded list used by
        other OAuth connectors to keep the backend usable.
        """
        if self.available_models:
            return

        try:
            await self._load_models_from_api()
            if self.available_models:
                return
        except Exception as exc:
            logger.warning("Model enumeration failed, using defaults: %s", exc)

        await super()._ensure_models_loaded()

    async def _load_models_from_api(self) -> None:
        """
        Attempt to retrieve model slugs from available sandbox endpoints.
        """
        if not await self._refresh_token_if_needed():
            return
        if not self._oauth_credentials or not self._oauth_credentials.get(
            "access_token"
        ):
            return

        base_url = (self.gemini_api_base_url or ANTIGRAVITY_SANDBOX_ENDPOINT).rstrip(
            "/"
        )
        headers = {
            "Authorization": f"Bearer {self._oauth_credentials['access_token']}",
            "Content-Type": "application/json",
        }

        candidate_paths = [
            "/v1beta/models",
            "/v1/models",
            "/v1internal/models",
        ]

        def _normalize(name: str) -> str:
            value = name.strip()
            if value.startswith("models/"):
                value = value[len("models/") :]
            return value

        slugs: set[str] = set()
        for path in candidate_paths:
            url = f"{base_url}{path}"
            try:
                response = await self.client.get(url, headers=headers, timeout=15.0)
            except Exception as exc:
                logger.warning("Failed to reach models endpoint %s: %s", url, exc)
                continue

            if response.status_code == 404:
                logger.debug("Models endpoint %s not found (404). Trying next.", url)
                continue
            if response.status_code != 200:
                logger.warning(
                    "Models endpoint %s returned %s: %s",
                    url,
                    response.status_code,
                    response.text,
                )
                continue

            try:
                data = response.json()
            except Exception as exc:
                logger.warning("Failed to decode models response from %s: %s", url, exc)
                continue

            models_raw = (
                data.get("models")
                or data.get("model")
                or data.get("modelIds")
                or data.get("items")
                or []
            )

            for entry in models_raw:
                if isinstance(entry, str):
                    if entry.strip():
                        slugs.add(_normalize(entry))
                    continue
                if isinstance(entry, dict):
                    name = (
                        entry.get("name")
                        or entry.get("id")
                        or entry.get("displayName")
                        or entry.get("model")
                    )
                    if isinstance(name, str) and name.strip():
                        slugs.add(_normalize(name))

            if slugs:
                break

        if slugs:
            self.available_models = sorted(slugs)

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

        logger.debug(
            f"Candidate Antigravity DB paths: {[str(p) for p in unique_candidates]}"
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

            logger.debug(f"Attempting to read Antigravity DB at: {connection_string}")

            with sqlite3.connect(connection_string, uri=True) as conn:
                cursor = conn.cursor()
                cursor.execute(
                    "SELECT value FROM ItemTable WHERE key=? "
                    "ORDER BY rowid DESC LIMIT 1",
                    (ANTIGRAVITY_AUTH_KEY,),
                )
                row = cursor.fetchone()
                if not row:
                    logger.debug(f"Key '{ANTIGRAVITY_AUTH_KEY}' not found in {db_path}")
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

            logger.warning(f"Parsed auth status is not a dictionary: {type(auth_data)}")
            return None
        except json.JSONDecodeError as exc:
            logger.warning(f"Failed to parse Antigravity auth status JSON: {exc}")
            return None
        except Exception as exc:  # pragma: no cover
            logger.error(f"Unexpected error parsing auth status: {exc}", exc_info=True)
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

        return normalized

    async def _load_oauth_credentials(self, force_reload: bool = False) -> bool:
        """
        Load OAuth credentials from the Antigravity state database or its backup.
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
                    logger.debug(f"Path does not exist: {path}")
                    continue

                current_modified = None
                try:
                    current_modified = path.stat().st_mtime
                except OSError:
                    current_modified = None

                if (
                    not force_reload
                    and self._oauth_credentials
                    and self._credentials_path
                    and path == self._credentials_path
                    and current_modified is not None
                    and current_modified == self._last_modified
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

                is_valid, validation_errors = self._validate_credentials_structure(
                    credentials
                )
                errors.extend(validation_errors)
                if not is_valid:
                    logger.warning(
                        f"Invalid credentials in {path}: {validation_errors}"
                    )
                    continue

                self._oauth_credentials = credentials
                self._credentials_path = path
                self._last_modified = current_modified or time.time()
                self._credentials_fingerprint = self._compute_credentials_fingerprint(
                    credentials
                )
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
            self._credential_validation_errors = errors
            logger.error(f"Failed to load Antigravity credentials. Errors: {errors}")
        return False


backend_registry.register_backend(
    "gemini-oauth-antigravity", GeminiOAuthAntigravityConnector
)
