"""
Anthropic OAuth connector that uses a locally stored OAuth credential file
to obtain an access token and call Anthropic's Messages API without a user
configured API key.

This mirrors the pattern used by other oauth-based backends in this project
(e.g., Qwen OAuth, Gemini OAuth Personal):

- Loads credentials from a JSON file (default locations are probed; a custom
  directory may be provided via init kwarg `anthropic_oauth_path`).
- Expects an `access_token` field; falls back to `api_key` if present.
- Uses the token in the `x-api-key` header together with the standard
  `anthropic-version` header used by the base Anthropic backend.
- Refresh policy: we do not attempt protocol token refresh (no public endpoint);
  instead we reload the file on changes or when initialize is called.
"""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Any

import httpx

from src.connectors.anthropic import (
    ANTHROPIC_DEFAULT_BASE_URL,
    AnthropicBackend,
)
from src.core.common.exceptions import AuthenticationError
from src.core.config.app_config import AppConfig
from src.core.services.backend_registry import backend_registry
from src.core.services.translation_service import TranslationService

logger = logging.getLogger(__name__)


class AnthropicOAuthBackend(AnthropicBackend):
    """Connector that uses a locally stored OAuth token for Anthropic.

    The token is read from an oauth_creds.json file. By default, we probe a set of
    well-known directories; callers may override the directory via the
    `anthropic_oauth_path` initialization parameter.
    """

    backend_type: str = "anthropic-oauth"

    def __init__(
        self,
        client: httpx.AsyncClient,
        config: AppConfig,
        translation_service: TranslationService,
    ) -> None:
        super().__init__(client, config, translation_service)
        self.name = "anthropic-oauth"
        self.is_functional: bool = False
        self._oauth_credentials: dict[str, Any] | None = None
        self._credentials_path: Path | None = None
        self._last_modified: float = 0.0
        # Optional override for credential directory
        self._oauth_dir_override: Path | None = None

    # -----------------------------
    # Credential loading utilities
    # -----------------------------
    def _default_oauth_dirs(self) -> list[Path]:
        """Return candidate directories that may contain oauth_creds.json.

        We probe several plausible locations so users can rely on auto-discovery
        (mirroring our other oauth connectors):
        - ~/.anthropic
        - ~/.claude
        - ~/.config/claude (Linux)
        - %APPDATA%/Claude (Windows)
        """
        home = Path.home()
        candidates: list[Path] = [home / ".anthropic", home / ".claude"]
        # Linux/XDG style
        candidates.append(home / ".config" / "claude")
        # Windows roaming AppData
        appdata = os.getenv("APPDATA")
        if appdata:
            candidates.append(Path(appdata) / "Claude")
        return candidates

    def _discover_credentials_path(self) -> Path | None:
        """Determine the oauth_creds.json path to use."""
        if self._oauth_dir_override is not None:
            return self._oauth_dir_override / "oauth_creds.json"

        for d in self._default_oauth_dirs():
            p = d / "oauth_creds.json"
            if p.exists():
                return p
        return None

    async def _load_oauth_credentials(self) -> bool:
        """Load OAuth credentials from oauth_creds.json if available.

        Returns True when credentials were successfully loaded (or cached and
        unchanged), False otherwise.
        """
        creds_path = self._discover_credentials_path()
        if creds_path is None:
            if logger.isEnabledFor(logging.WARNING):
                logger.warning(
                    "Anthropic OAuth credentials file not found in default paths"
                )
            return False

        self._credentials_path = creds_path

        try:
            # Short-circuit if unchanged and we have a cached value
            try:
                mtime = creds_path.stat().st_mtime
                if mtime == self._last_modified and self._oauth_credentials is not None:
                    return True
                self._last_modified = mtime
            except OSError:
                # If we fail to stat, attempt to read anyway
                pass

            with open(creds_path, encoding="utf-8") as f:
                data: dict[str, Any] = json.load(f)

            # We expect an access_token (preferred) or api_key
            token: str | None = None
            if isinstance(data, dict):
                token = (
                    str(data.get("access_token"))
                    if data.get("access_token") is not None
                    else (
                        str(data.get("api_key"))
                        if data.get("api_key") is not None
                        else None
                    )
                )

            if not token:
                if logger.isEnabledFor(logging.WARNING):
                    logger.warning(
                        "Anthropic OAuth credentials missing access_token/api_key"
                    )
                return False

            self._oauth_credentials = data
            # Set api_key on the base class so parent logic can operate normally
            self.api_key = token
            self.key_name = self.backend_type
            return True

        except json.JSONDecodeError as e:
            if logger.isEnabledFor(logging.ERROR):
                logger.error(f"Malformed Anthropic OAuth credentials JSON: {e}")
            return False
        except Exception as e:
            if logger.isEnabledFor(logging.ERROR):
                logger.error(f"Error loading Anthropic OAuth credentials: {e}")
            return False

    # -----------------------------
    # LLMBackend API
    # -----------------------------
    async def initialize(self, **kwargs: Any) -> None:  # type: ignore[override]
        """Initialize backend by loading OAuth credentials and preparing config."""
        # Allow overriding the oauth dir (directory containing oauth_creds.json)
        override = kwargs.get("anthropic_oauth_path")
        if isinstance(override, str) and override:
            self._oauth_dir_override = Path(override)

        # Base URL override or default
        self.anthropic_api_base_url = kwargs.get(
            "anthropic_api_base_url", ANTHROPIC_DEFAULT_BASE_URL
        )

        # Load credentials; mark functional if successful
        loaded = await self._load_oauth_credentials()
        self.is_functional = loaded

        # Do not fetch models during init to avoid unnecessary outbound calls in tests;
        # they'll be lazily fetched on first use via _ensure_models_loaded in the parent.

    async def chat_completions(  # type: ignore[override]
        self,
        request_data: Any,
        processed_messages: list[Any],
        effective_model: str,
        identity: Any | None = None,
        **kwargs: Any,
    ):
        # Ensure we have a token loaded just before the call
        if not await self._load_oauth_credentials():
            raise AuthenticationError(
                message=(
                    "No valid Anthropic OAuth credentials available. "
                    "Please authenticate using Claude Code or provide a valid oauth_creds.json."
                ),
                code="missing_oauth_creds",
            )

        # Delegate to parent with our token (set on self.api_key)
        return await super().chat_completions(
            request_data=request_data,
            processed_messages=processed_messages,
            effective_model=effective_model,
            identity=identity,
            api_key=self.api_key,
            **kwargs,
        )

    def get_available_models(self) -> list[str]:
        return super().get_available_models()


# Register in backend registry
backend_registry.register_backend("anthropic-oauth", AnthropicOAuthBackend)
