"""
Gemini OAuth connector that reuses Antigravity app credentials.

This backend mirrors the personal/free OAuth connectors but reads the access
token from Antigravity's VS Code style state database and targets the Cloud
Code PA sandbox endpoint observed in Antigravity logs.
"""

import asyncio
import hashlib
import json
import logging
import os
import sqlite3
import time
from pathlib import Path
from typing import Any

import httpx
from fastapi import HTTPException

from src.connectors.gemini_oauth_free import GeminiOAuthFreeConnector
from src.core.app.constants.logging_constants import TRACE_LEVEL
from src.core.common.exceptions import BackendError
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
    Code Assist API endpoint. The sandbox does not expose fetchAvailableModels,
    so model discovery and health checks rely on cached/fallback lists instead.
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
        self.gemini_api_base_url = (
            getattr(self, "gemini_api_base_url", None) or ANTIGRAVITY_SANDBOX_ENDPOINT
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

    async def _load_models_from_api(self) -> None:
        """
        Skip model enumeration on the sandbox endpoint to avoid 404 noise.

        The Antigravity sandbox does not expose fetchAvailableModels; use the
        hardcoded fallback list unless a different base URL is explicitly set.
        """
        base_url = (self.gemini_api_base_url or "").rstrip("/")
        sandbox_url = ANTIGRAVITY_SANDBOX_ENDPOINT.rstrip("/")
        if not base_url:
            base_url = sandbox_url

        if base_url == sandbox_url:
            logger.info(
                "Skipping fetchAvailableModels for Antigravity sandbox; using fallback model list."
            )
            return

        await super()._load_models_from_api()

    async def list_models(
        self, *, gemini_api_base_url: str, key_name: str, api_key: str
    ) -> dict[str, Any]:
        """
        List models without hitting unavailable sandbox endpoints.

        When targeting the Antigravity sandbox, rely on the locally cached model
        list instead of calling fetchAvailableModels (which returns 404).
        """
        target_base = (gemini_api_base_url or "").rstrip("/")
        sandbox_url = ANTIGRAVITY_SANDBOX_ENDPOINT.rstrip("/")
        if not target_base:
            target_base = sandbox_url

        if not self._oauth_credentials or not self._oauth_credentials.get(
            "access_token"
        ):
            raise HTTPException(
                status_code=401, detail="No OAuth access token available"
            )

        if target_base == sandbox_url:
            await self._ensure_models_loaded()
            models = [
                {"name": f"models/{model}", "displayName": model}
                for model in self.available_models
            ]
            return {"models": models}

        return await super().list_models(
            gemini_api_base_url=gemini_api_base_url,
            key_name=key_name,
            api_key=api_key,
        )

    async def _perform_health_check(self) -> bool:
        """
        Perform a lightweight health check without hitting unavailable endpoints.

        The sandbox endpoint does not expose fetchAvailableModels; we only verify
        that credentials are usable when targeting that host.
        """
        base_url = (self.gemini_api_base_url or "").rstrip("/")
        sandbox_url = ANTIGRAVITY_SANDBOX_ENDPOINT.rstrip("/")
        if not base_url or base_url == sandbox_url:
            healthy = await self._refresh_token_if_needed()
            if healthy:
                self._health_checked = True
            return healthy

        return await super()._perform_health_check()

    async def _discover_project_id(self, auth_session: Any = None) -> str:
        """
        Discover the project id using the paid-tier onboarding flow.

        The Antigravity token maps to a real account; prefer the highest tier
        reported by loadCodeAssist instead of the free-tier defaults to avoid
        artificial quota limits.
        """
        if self._project_id:
            return str(self._project_id)

        if not auth_session:
            logger.warning(
                "auth_session required for Antigravity project discovery but missing"
            )
            initial = (
                self._oauth_credentials.get("project_id")
                if self._oauth_credentials
                else None
            )
            return str(initial or "default")

        initial_project_id = (
            self._oauth_credentials.get("project_id")
            if self._oauth_credentials
            else None
        )
        fallback_project_id = initial_project_id or "default"

        client_metadata = {
            "ideType": "IDE_UNSPECIFIED",
            "platform": "PLATFORM_UNSPECIFIED",
            "pluginType": "GEMINI",
            "duetProject": initial_project_id,
        }

        try:
            load_request = {
                "cloudaicompanionProject": initial_project_id,
                "metadata": client_metadata,
            }

            load_url = f"{self.gemini_api_base_url}/v1internal:loadCodeAssist"
            load_response = await asyncio.to_thread(
                auth_session.request,
                method="POST",
                url=load_url,
                json=load_request,
                headers={"Content-Type": "application/json"},
                timeout=30.0,
            )

            if load_response.status_code != 200:
                raise BackendError(f"LoadCodeAssist failed: {load_response.text}")

            load_data = load_response.json()
            project_candidate = load_data.get("cloudaicompanionProject")
            if project_candidate:
                self._project_id = project_candidate
                return str(self._project_id)

            allowed_tiers_raw = load_data.get("allowedTiers", [])
            allowed_tiers = [
                tier for tier in allowed_tiers_raw if isinstance(tier, dict)
            ]
            current_tier = load_data.get("currentTier")
            if isinstance(current_tier, dict):
                allowed_tiers.append(current_tier)

            def _tier_id(tier: dict[str, Any]) -> str:
                raw_id = tier.get("id") or tier.get("tierId")
                return str(raw_id or "").lower()

            def _context_tokens(tier: dict[str, Any]) -> int:
                for key in (
                    "maxContextTokens",
                    "contextTokenLimit",
                    "contextWindowTokens",
                    "tokenLimit",
                    "maxContextWindow",
                ):
                    value = tier.get(key)
                    if isinstance(value, int | float):
                        return int(value)
                return 0

            def _tier_score(tier: dict[str, Any]) -> tuple[int, int, int]:
                tier_id = _tier_id(tier)
                is_paid = int(
                    tier_id
                    in {
                        "paid-tier",
                        "google-one-tier",
                        "googleone-tier",
                        "googleone",
                        "duet-ai-pro",
                    }
                )
                context_tokens = _context_tokens(tier)
                if is_paid and context_tokens == 0:
                    context_tokens = 1_000_000
                is_default = int(bool(tier.get("isDefault")))
                return (is_paid, context_tokens, is_default)

            tier_to_use = max(allowed_tiers, key=_tier_score) if allowed_tiers else None
            selected_tier_id = (
                tier_to_use.get("id") or tier_to_use.get("tierId")
                if tier_to_use
                else None
            )
            if not selected_tier_id:
                selected_tier_id = "paid-tier"

            logger.info(
                "Selected Code Assist tier '%s' for Antigravity", selected_tier_id
            )

            onboard_request = {
                "tierId": selected_tier_id,
                "cloudaicompanionProject": initial_project_id,
                "metadata": {
                    **client_metadata,
                    "duetProject": initial_project_id,
                },
            }

            onboard_url = f"{self.gemini_api_base_url}/v1internal:onboardUser"
            max_retries = 30
            retry_count = 0

            while retry_count < max_retries:
                lro_response = await asyncio.to_thread(
                    auth_session.request,
                    method="POST",
                    url=onboard_url,
                    json=onboard_request,
                    headers={"Content-Type": "application/json"},
                    timeout=30.0,
                )

                if lro_response.status_code != 200:
                    raise BackendError(f"OnboardUser failed: {lro_response.text}")

                lro_data = lro_response.json()
                if lro_data.get("done"):
                    response_data = lro_data.get("response", {})
                    cloudai_project = response_data.get("cloudaicompanionProject", {})
                    discovered_project_id = cloudai_project.get(
                        "id", initial_project_id or "default"
                    )
                    self._project_id = discovered_project_id
                    logger.info(
                        "Discovered Antigravity project ID: %s", self._project_id
                    )
                    return str(self._project_id)

                retry_count += 1
                await asyncio.sleep(2)

            logger.warning(
                "Onboarding timed out for Antigravity; falling back to project '%s'",
                fallback_project_id,
            )
        except Exception as exc:  # pragma: no cover - defensive fallback
            logger.warning(
                "Antigravity project discovery failed, using fallback project '%s': %s",
                fallback_project_id,
                exc,
                exc_info=True,
            )

        self._project_id = fallback_project_id
        return str(self._project_id)

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
                try:
                    credentials_file_hash = hashlib.sha256(
                        path.read_bytes()
                    ).hexdigest()
                except OSError:
                    credentials_file_hash = None
                self._credentials_file_hash = credentials_file_hash
                self._last_credentials_event_hash = credentials_file_hash
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
            if logger.isEnabledFor(logging.ERROR):
                logger.error(
                    f"Failed to load Antigravity credentials. Errors: {errors}"
                )
        return False


backend_registry.register_backend(
    "gemini-oauth-antigravity", GeminiOAuthAntigravityConnector
)
