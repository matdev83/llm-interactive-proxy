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
ANTIGRAVITY_USER_AGENT = "antigravity/1.11.5 windows/amd64"
GLOBAL_STORAGE_SUBPATH = Path("Antigravity") / "User" / "globalStorage"


class GeminiOAuthAntigravityConnector(GeminiOAuthFreeConnector):
    """
    Connector for Gemini using OAuth credentials from the Antigravity app.

    This connector uses the Antigravity sandbox endpoint instead of the standard
    Code Assist API endpoint. Model enumeration, validation, health checks, and
    listing are all inherited from the base class, which uses the
    fetchAvailableModels endpoint that works with both endpoints.
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

    def _get_api_headers(self) -> dict[str, str]:
        """
        Get headers for API requests with Antigravity-specific User-Agent.

        The Antigravity sandbox endpoint requires a specific User-Agent header.
        """
        headers = super()._get_api_headers()
        headers["User-Agent"] = ANTIGRAVITY_USER_AGENT
        return headers

    def _get_session_headers(self) -> dict[str, str]:
        """
        Get headers for AuthorizedSession requests with Antigravity User-Agent.

        The Antigravity sandbox endpoint requires a specific User-Agent header
        for all API calls, including those made via AuthorizedSession.
        """
        headers = super()._get_session_headers()
        headers["User-Agent"] = ANTIGRAVITY_USER_AGENT
        return headers

    def _build_code_assist_request_body(
        self,
        effective_model: str,
        project_id: str,
        request_data: Any,
        code_assist_request: dict[str, Any],
    ) -> dict[str, Any]:
        """Build Antigravity-specific request body format.

        The Antigravity sandbox API uses a different wrapper structure than
        the standard Code Assist API:
        - 'requestId' instead of 'user_prompt_id'
        - 'model' at top level (not inside 'request')
        - Additional 'userAgent' and 'requestType' fields required

        Args:
            effective_model: The model name to use
            project_id: The project ID from loadCodeAssist
            request_data: The original request data (for generating requestId)
            code_assist_request: The inner request with contents, generationConfig, etc.

        Returns:
            Antigravity-formatted request body dict
        """
        return {
            "project": project_id,
            "requestId": self._generate_user_prompt_id(request_data),
            "request": code_assist_request,
            "model": effective_model,
            "userAgent": "antigravity",
            "requestType": "agent",
        }

    async def initialize(self, **kwargs: Any) -> None:
        """Initialize using Antigravity's sandbox endpoint and custom User-Agent."""
        kwargs.setdefault("gemini_api_base_url", ANTIGRAVITY_SANDBOX_ENDPOINT)

        # Create a custom client with Antigravity-specific User-Agent
        # This ensures all requests use the correct User-Agent regardless of settings
        self.client = httpx.AsyncClient(
            headers={"User-Agent": ANTIGRAVITY_USER_AGENT},
            timeout=httpx.Timeout(60.0, connect=30.0),
        )

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

    async def chat_completions(  # type: ignore[override]
        self,
        request_data: Any,
        processed_messages: list[Any],
        effective_model: str,
        identity: Any = None,
        openrouter_api_base_url: str | None = None,
        openrouter_headers_provider: Any = None,
        key_name: str | None = None,
        api_key: str | None = None,
        project: str | None = None,
        agent: str | None = None,
        gemini_api_base_url: str | None = None,
        **kwargs: Any,
    ) -> Any:
        """Handle chat completions with model validation.

        This method validates the requested model against the available models list
        before delegating to the parent implementation.

        Raises:
            BackendError: If the requested model is not available
        """
        # Ensure models are loaded (cached after first call)
        await self._ensure_models_loaded()

        # Strip any prefix from the model name for validation
        model_name = effective_model
        prefix = "gemini-oauth-plan:"
        if model_name.startswith(prefix):
            model_name = model_name[len(prefix) :]

        # Validate the model is available on this backend
        self.validate_model(model_name)

        # Delegate to parent implementation
        return await super().chat_completions(
            request_data=request_data,
            processed_messages=processed_messages,
            effective_model=effective_model,
            identity=identity,
            openrouter_api_base_url=openrouter_api_base_url,
            openrouter_headers_provider=openrouter_headers_provider,
            key_name=key_name,
            api_key=api_key,
            project=project,
            agent=agent,
            gemini_api_base_url=gemini_api_base_url,
            **kwargs,
        )

    # -------------------------------------------------------------------------
    # Antigravity-specific credential loading methods
    # -------------------------------------------------------------------------

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

    async def _load_oauth_credentials(self, force_reload: bool = False, silent: bool = False) -> bool:
        """
        Load OAuth credentials from the Antigravity state database or its backup.
        
        Args:
            force_reload: If True, bypass cache and force reload from file
            silent: If True, suppress INFO level logging (used when checking for changes)
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
                    credentials, silent=silent
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
            self._credential_validation_errors = errors
            logger.error(f"Failed to load Antigravity credentials. Errors: {errors}")
        return False


backend_registry.register_backend(
    "gemini-oauth-antigravity", GeminiOAuthAntigravityConnector
)
