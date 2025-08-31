"""
OpenAI OAuth connector that uses ChatGPT/Codex auth.json tokens instead of API keys.

This backend reads a local `auth.json` file (created by Codex CLI via ChatGPT login)
and uses `tokens.access_token` as the bearer for OpenAI API requests. If the file
also contains `OPENAI_API_KEY`, that is used as a fallback.

Default credential file locations (first that exists is used):
- Windows: %USERPROFILE%\.codex\auth.json
- Cross-platform: ~/.codex/auth.json

Configuration:
- `openai_oauth_path`: optional directory that contains `auth.json` (overrides defaults)
- `openai_api_base_url`: optional base URL override (default: https://api.openai.com/v1)
"""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Any

import httpx

from src.connectors.openai import OpenAIConnector
from src.core.common.exceptions import AuthenticationError
from src.core.config.app_config import AppConfig
from src.core.services.backend_registry import backend_registry
from src.core.services.translation_service import TranslationService

logger = logging.getLogger(__name__)


class OpenAIOAuthConnector(OpenAIConnector):
    backend_type: str = "openai-oauth"

    def __init__(
        self,
        client: httpx.AsyncClient,
        config: AppConfig,
        response_processor: Any | None = None,
        translation_service: TranslationService | None = None,
    ) -> None:
        super().__init__(client, config, response_processor, translation_service)
        self.name = "openai-oauth"
        self._oauth_dir_override: Path | None = None
        self._auth_path: Path | None = None
        self._last_modified: float = 0.0
        self.is_functional: bool = False

    def _default_auth_paths(self) -> list[Path]:
        paths: list[Path] = []
        userprofile = os.getenv("USERPROFILE")
        if userprofile:
            paths.append(Path(userprofile) / ".codex" / "auth.json")
        # Cross-platform default
        paths.append(Path.home() / ".codex" / "auth.json")
        return paths

    def _discover_auth_path(self) -> Path | None:
        if self._oauth_dir_override is not None:
            return self._oauth_dir_override / "auth.json"
        for p in self._default_auth_paths():
            if p.exists():
                return p
        return None

    async def _load_auth(self) -> bool:
        auth_path = self._discover_auth_path()
        if auth_path is None:
            logger.warning("OpenAI OAuth auth.json not found in default locations")
            return False

        self._auth_path = auth_path
        try:
            try:
                mtime = auth_path.stat().st_mtime
                if mtime == self._last_modified and self.api_key:
                    return True
                self._last_modified = mtime
            except OSError:
                pass

            with open(auth_path, encoding="utf-8") as f:
                data: dict[str, Any] = json.load(f)

            token: str | None = None
            # Prefer ChatGPT OAuth access token
            tokens = data.get("tokens")
            if isinstance(tokens, dict):
                tok = tokens.get("access_token")
                if isinstance(tok, str) and tok:
                    token = tok
            # Fallback to OPENAI_API_KEY if present
            if not token:
                api_key = data.get("OPENAI_API_KEY")
                if isinstance(api_key, str) and api_key:
                    token = api_key

            if not token:
                logger.warning(
                    "OpenAI OAuth auth.json missing tokens.access_token and OPENAI_API_KEY"
                )
                return False

            # Set as API key for parent header logic
            self.api_key = token
            return True
        except json.JSONDecodeError as e:
            logger.error(f"Malformed auth.json for OpenAI OAuth: {e}")
            return False
        except Exception as e:
            logger.error(f"Failed to load OpenAI OAuth credentials: {e}")
            return False

    async def initialize(self, **kwargs: Any) -> None:  # type: ignore[override]
        # Allow base URL override
        base = kwargs.get("openai_api_base_url") or kwargs.get("api_base_url")
        if isinstance(base, str) and base:
            self.api_base_url = base

        # Optional directory override for auth.json
        dir_override = kwargs.get("openai_oauth_path")
        if isinstance(dir_override, str) and dir_override:
            self._oauth_dir_override = Path(dir_override)

        loaded = await self._load_auth()
        self.is_functional = loaded

        # Optionally prefetch models (non-fatal if it fails)
        if loaded:
            import contextlib

            with contextlib.suppress(Exception):
                await self.list_models()

    async def chat_completions(  # type: ignore[override]
        self,
        request_data: Any,
        processed_messages: list[Any],
        effective_model: str,
        identity: Any | None = None,
        **kwargs: Any,
    ):
        if not await self._load_auth():
            raise AuthenticationError(
                message=(
                    "No valid OpenAI OAuth credentials (auth.json) found. "
                    "Run codex login or set openai_oauth_path to the directory containing auth.json."
                ),
                code="missing_oauth_creds",
            )

        return await super().chat_completions(
            request_data=request_data,
            processed_messages=processed_messages,
            effective_model=effective_model,
            identity=identity,
            **kwargs,
        )


backend_registry.register_backend("openai-oauth", OpenAIOAuthConnector)
