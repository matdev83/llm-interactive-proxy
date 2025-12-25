from __future__ import annotations

import asyncio
import logging
import os
from pathlib import Path
from typing import Any

import httpx
from fastapi import HTTPException

from src.connectors.openai import OpenAIConnector
from src.connectors.utils.cline_auth import ClineAuthMixin, _ClineTokenStore
from src.connectors.utils.cline_auth_types import ClineTokenData

from src.core.common.exceptions import AuthenticationError
from src.core.config.app_config import AppConfig
from src.core.domain.responses import ResponseEnvelope, StreamingResponseEnvelope
from src.core.domain.session_key import SessionKey
from src.core.interfaces.configuration_interface import IAppIdentityConfig
from src.core.interfaces.model_bases import DomainModel, InternalDTO
from src.core.services.backend_registry import backend_registry
from src.core.services.translation_service import TranslationService

logger = logging.getLogger(__name__)


class ClineConnector(ClineAuthMixin, OpenAIConnector):
    """Connector that routes requests through the Cline backend using stored auth tokens."""

    backend_type = "cline"

    # Cline is a multi-vendor router - models are already prefixed from upstream
    VENDOR_PREFIX: str | None = None

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
        self._token_cache: ClineTokenData | None = None
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

    def _unwrap_cline_data_envelope(
        self, response_json: dict[str, Any]
    ) -> dict[str, Any]:
        """
        Unwrap Cline's non-standard 'data' envelope from responses.

        Cline API wraps OpenAI-format responses in a 'data' key for non-streaming
        requests. This method extracts the inner response to normalize it to
        standard OpenAI format that the rest of the pipeline expects.
        """
        data_val = response_json.get("data")
        # Only unwrap if data_val is a dict that looks like a valid OpenAI response
        if isinstance(data_val, dict) and (
            "choices" in data_val or "id" in data_val or "model" in data_val
        ):
            logger.debug(
                "Unwrapping Cline 'data' envelope - found keys: %s",
                list(data_val.keys())[:5],
            )
            return data_val
        return response_json

    async def _handle_non_streaming_response(
        self,
        url: str,
        payload: dict[str, Any],
        headers: dict[str, str] | None,
        session_id: str,
    ) -> ResponseEnvelope:
        """
        Override to handle Cline's non-standard response format.

        Cline wraps responses in a 'data' envelope for non-streaming requests.
        We unwrap this before passing to the parent handler.
        """
        from src.core.common.exceptions import ServiceUnavailableError
        from src.core.security.loop_prevention import ensure_loop_guard_header

        if not headers or not headers.get("Authorization"):
            raise AuthenticationError(message="No auth credentials found")

        guarded_headers = ensure_loop_guard_header(headers)

        try:
            response = await self.client.post(
                url, json=payload, headers=guarded_headers
            )
        except httpx.RequestError as e:
            logger.error(f"Cline request failed to {url}. Error: {e}")
            raise ServiceUnavailableError(
                message=f"Could not connect to Cline backend ({e})"
            )

        if int(response.status_code) >= 400:
            try:
                err = response.json()
            except Exception:
                err = response.text
            raise HTTPException(status_code=response.status_code, detail=err)

        response_json = response.json()

        # Unwrap Cline's non-standard 'data' envelope
        response_json = self._unwrap_cline_data_envelope(response_json)

        # Debug log for troubleshooting
        if logger.isEnabledFor(logging.DEBUG):
            choices_count = len(response_json.get("choices", []))
            response_id = response_json.get("id", "unknown")
            response_model = response_json.get("model", "unknown")
            logger.debug(
                "Cline non-streaming response: id=%s model=%s choices_count=%d",
                response_id,
                response_model,
                choices_count,
            )

        domain_response = self.translation_service.to_domain_response(
            response_json, "openai"
        )

        try:
            response_headers = dict(response.headers)
        except Exception:
            response_headers = {}

        return ResponseEnvelope(
            content=domain_response.model_dump(),
            status_code=response.status_code,
            headers=response_headers,
            usage=domain_response.usage,
        )

    async def chat_completions(
        self,
        request_data: DomainModel | InternalDTO | dict[str, Any],
        processed_messages: list[Any],
        effective_model: str,
        identity: IAppIdentityConfig | None = None,
        cancellation_token: SessionKey | None = None,
        cancellation_coordinator: (
            Any | None
        ) = None,  # ISessionCancellationCoordinator | None
        **kwargs: Any,
    ) -> ResponseEnvelope | StreamingResponseEnvelope:
        # Structural enforcement: check cancellation immediately if coordinator and token provided
        if cancellation_coordinator is not None and cancellation_token is not None:
            cancellation_coordinator.ensure_not_cancelled(cancellation_token)
        incoming_headers = kwargs.pop("incoming_headers", None)
        if not self._enable_cline_backend_debugging_override:
            self._validate_cline_agent(incoming_headers)

        await self._ensure_auth_token()
        session_identifier = getattr(request_data, "session_id", None)
        headers_override = dict(kwargs.pop("headers_override", {}) or {})
        headers_override.update(
            self._build_default_headers(
                session_id=str(session_identifier) if session_identifier else None
            )
        )
        kwargs["headers_override"] = headers_override

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

    def _validate_cline_agent(self, headers: dict[str, Any] | None) -> None:
        """
        Restrict Cline backend usage to the Cline clients.

        Cline's API key/token is typically sourced from a user's editor auth store. If
        this backend is exposed publicly it can be accidentally used by non-Cline
        clients. We enforce that the incoming request looks like it originated from
        Cline (User-Agent or X-Title contains "Cline"), unless the debugging override
        is enabled.
        """

        normalized: dict[str, str] = {}
        if headers:
            for key, value in headers.items():
                normalized[str(key).lower()] = str(value)

        user_agent = normalized.get("user-agent", "")
        title = normalized.get("x-title", "")
        haystack = f"{user_agent} {title}".lower()

        if "cline" in haystack:
            return

        logger.warning(
            "Rejected request to Cline backend: missing 'Cline' marker in User-Agent/X-Title. "
            "To bypass for local debugging use --enable-cline-backend-debugging-override."
        )
        raise HTTPException(
            status_code=403,
            detail=(
                "Forbidden: Cline backend is restricted to Cline clients. "
                "Missing 'Cline' marker in 'User-Agent' or 'X-Title'."
            ),
        )


backend_registry.register_backend("cline", ClineConnector)
