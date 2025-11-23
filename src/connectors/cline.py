from __future__ import annotations

import asyncio
import logging
import os
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import httpx
from fastapi import HTTPException

from src.connectors.openai import OpenAIConnector
from src.connectors.utils.cline_auth import ClineAuthMixin, _ClineTokenStore
from src.core.common.exceptions import AuthenticationError
from src.core.config.app_config import AppConfig
from src.core.domain.responses import ResponseEnvelope, StreamingResponseEnvelope
from src.core.interfaces.configuration_interface import IAppIdentityConfig
from src.core.interfaces.model_bases import DomainModel, InternalDTO
from src.core.services.backend_registry import backend_registry
from src.core.services.translation_service import TranslationService

logger = logging.getLogger(__name__)


class ClineConnector(ClineAuthMixin, OpenAIConnector):
    """Connector that routes requests through the Cline backend using stored auth tokens."""

    backend_type = "cline"

    _ENVIRONMENT_BASES: dict[str, str] = {
        "production": "https://api.cline.bot",
        "staging": "https://core-api.staging.int.cline.bot",
        "local": "http://localhost:7777",
    }

    def __init__(
        self,
        client: httpx.AsyncClient,
        config: AppConfig,
        translation_service: TranslationService,
        name: str | None = None,
    ) -> None:
        super().__init__(client, config, translation_service=translation_service)
        self.name = name or self.backend_type
        self._secrets_path: Path | None = None
        self._token_store: _ClineTokenStore | None = None
        self._token_cache: dict[str, Any] | None = None
        self._token_file_mtime: float | None = None
        self._token_lock = asyncio.Lock()
        self._cline_api_host = self._ENVIRONMENT_BASES["production"]
        self.api_base_url = f"{self._cline_api_host}/api/v1"
        self._refresh_endpoint = f"{self._cline_api_host}/api/v1/auth/refresh"
        self._user_info_endpoint = f"{self._cline_api_host}/api/v1/users/me"
        self._request_timeout = 120.0
        self._codex_auth_override: Path | None = None
        default_client_version = "3.38.1"
        self._client_version = os.getenv(
            "CLINE_CLIENT_VERSION_OVERRIDE", default_client_version
        )
        self._client_type = os.getenv("CLINE_CLIENT_TYPE_OVERRIDE", "vscode-extension")
        self._core_version = os.getenv(
            "CLINE_CORE_VERSION_OVERRIDE", self._client_version
        )
        self._user_agent = os.getenv(
            "CLINE_USER_AGENT_OVERRIDE", "cline-vscode-extension"
        )
        self._is_multiroot = os.getenv("CLINE_IS_MULTIROOT", "false")
        self._enable_cline_backend_debugging_override = False

    async def initialize(self, **kwargs: Any) -> None:
        backend_config = getattr(self.config.backends, "cline", None)
        extras = backend_config.extra if backend_config else {}

        self._request_timeout = float(getattr(backend_config, "timeout", 120))

        secrets_path = (
            kwargs.get("secrets_path")
            or extras.get("secrets_path")
            or os.getenv("CLINE_SECRETS_PATH")
        )
        cline_dir = (
            kwargs.get("cline_dir") or extras.get("cline_dir") or os.getenv("CLINE_DIR")
        )
        environment = (
            kwargs.get("cline_environment")
            or extras.get("environment")
            or os.getenv("CLINE_ENVIRONMENT_OVERRIDE")
            or os.getenv("CLINE_ENVIRONMENT")
        )
        explicit_api_base = (
            kwargs.get("cline_api_base_url")
            or extras.get("api_base_url")
            or os.getenv("CLINE_API_BASE_URL")
        )

        self._enable_cline_backend_debugging_override = kwargs.get(
            "enable_cline_backend_debugging_override"
        ) or extras.get("enable_cline_backend_debugging_override", False)

        self._secrets_path = self._resolve_secrets_path(secrets_path, cline_dir)
        self._token_store = _ClineTokenStore(self._secrets_path)
        self._token_file_mtime = None

        host_base, api_base_url = self._resolve_api_base(explicit_api_base, environment)
        self._cline_api_host = host_base
        self.api_base_url = api_base_url
        self._refresh_endpoint = f"{self._cline_api_host}/api/v1/auth/refresh"
        self._user_info_endpoint = f"{self._cline_api_host}/api/v1/users/me"
        codex_auth_path = (
            kwargs.get("codex_auth_path")
            or extras.get("codex_auth_path")
            or os.getenv("CLINE_CODEX_AUTH_PATH")
        )
        if codex_auth_path:
            self._codex_auth_override = Path(codex_auth_path).expanduser()
        else:
            self._codex_auth_override = None

        await self._ensure_auth_token(force_reload=True)

        passthrough = {
            key: value
            for key, value in kwargs.items()
            if key
            not in {
                "secrets_path",
                "cline_dir",
                "cline_environment",
                "cline_api_base_url",
                "codex_auth_path",
                "enable_cline_backend_debugging_override",
            }
        }
        passthrough["api_key"] = self.api_key
        passthrough["api_base_url"] = self.api_base_url

        await super().initialize(**passthrough)

    async def chat_completions(
        self,
        request_data: DomainModel | InternalDTO | dict[str, Any],
        processed_messages: list[Any],
        effective_model: str,
        identity: IAppIdentityConfig | None = None,
        **kwargs: Any,
    ) -> ResponseEnvelope | StreamingResponseEnvelope:
        await self._ensure_auth_token()
        session_identifier = getattr(request_data, "session_id", None)
        headers_override = dict(kwargs.pop("headers_override", {}) or {})
        headers_override.update(
            self._build_default_headers(
                session_id=str(session_identifier) if session_identifier else None
            )
        )
        kwargs["headers_override"] = headers_override

        # Extract incoming headers for validation
        incoming_headers = kwargs.pop("incoming_headers", {}) or {}

        # Validate Cline agent if not overridden
        if not self._enable_cline_backend_debugging_override:
            self._validate_cline_agent(incoming_headers)

        retry_attempted = False
        while True:
            try:
                return await super().chat_completions(
                    request_data,
                    processed_messages,
                    effective_model,
                    identity,
                    **kwargs,
                )
            except HTTPException as exc:
                if exc.status_code != 401:
                    raise
                if retry_attempted:
                    await self._invalidate_token_cache()
                    raise AuthenticationError(
                        "Cline authentication failed. Please re-authenticate through the Cline client.",
                        details={"status_code": 401, "response": exc.detail},
                    ) from exc
                retry_attempted = True
                await self._invalidate_token_cache()
                await self._ensure_auth_token(force_reload=True, force_refresh=True)

    def _validate_cline_agent(self, headers: Mapping[str, str]) -> None:
        """Validate that the request comes from a Cline agent based on headers."""
        lower_headers = {k.lower(): v for k, v in headers.items()}

        user_agent = lower_headers.get("user-agent", "")
        x_title = lower_headers.get("x-title", "")

        # Check if "Cline" is present in either User-Agent or X-Title (case-insensitive)
        is_cline = "cline" in user_agent.lower() or "cline" in x_title.lower()

        if not is_cline:
            logger.warning(
                f"Rejected request: missing 'Cline' in User-Agent or X-Title headers. "
                f"User-Agent: '{user_agent}', X-Title: '{x_title}'. "
                f"To bypass, use the --enable-cline-backend-debugging-override flag."
            )
            raise HTTPException(
                status_code=403,
                detail="Forbidden: This backend only accepts requests from Cline clients.",
            )


backend_registry.register_backend("cline", ClineConnector)
