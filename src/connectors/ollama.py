"""Ollama connector for locally-hosted models via OpenAI-compatible API."""

from __future__ import annotations

import logging
import os
import time
from typing import TYPE_CHECKING, Any

import httpx

from src.connectors.openai import OpenAIConnector
from src.core.config.app_config import AppConfig
from src.core.domain.chat import CanonicalChatRequest
from src.core.services.backend_registry import backend_registry

if TYPE_CHECKING:
    from src.connectors.contracts import ConnectorRequestContext
    from src.core.services.translation_service import TranslationService

logger = logging.getLogger(__name__)

OLLAMA_DEFAULT_BASE_URL = "http://localhost:11434/v1"
OLLAMA_CLOUD_MODELS_URL = "https://ollama.com/api/tags"
_CLOUD_MODEL_TTL = 1800  # 30 minutes

# Lazy-initialized shared client for cloud model discovery (not used for inference).
_cloud_models_client: httpx.AsyncClient | None = None
# Simple TTL-based cache: (models_list, fetched_at)
_cached_cloud_models: tuple[list[str], float] | None = None


async def _fetch_cloud_models(force: bool = False) -> list[str]:
    """Fetch available cloud models from ollama.com.

    Results are cached for ``_CLOUD_MODEL_TTL`` seconds (default 30 min)
    to avoid hammering the upstream endpoint on every ``initialize`` call.
    Use *force= True`` to bypass the cache (used in tests).

    Returns model names with a ``-cloud`` suffix so the proxy can
    distinguish remote-capable models from locally-pulled ones.
    """
    global _cached_cloud_models, _cloud_models_client

    if not force and _cached_cloud_models is not None:
        cached_models, fetched_at = _cached_cloud_models
        if time.monotonic() - fetched_at < _CLOUD_MODEL_TTL:
            return cached_models

    if _cloud_models_client is None or _cloud_models_client.is_closed:
        _cloud_models_client = httpx.AsyncClient(timeout=15.0)
    try:
        resp = await _cloud_models_client.get(OLLAMA_CLOUD_MODELS_URL)
        resp.raise_for_status()
        data = resp.json()
    except Exception as e:
        if logger.isEnabledFor(logging.WARNING):
            logger.warning("Failed to fetch Ollama cloud models: %s", e, exc_info=True)
        return []
    models: list[str] = []
    for entry in data.get("models", []):
        name = entry.get("name")
        if isinstance(name, str) and name:
            models.append(f"{name}-cloud")

    if not force:
        _cached_cloud_models = (models, time.monotonic())
    return models


def _clear_cloud_models_cache() -> None:
    """Reset the cloud-models cache (useful for tests / admin reset)."""
    global _cached_cloud_models
    _cached_cloud_models = None


class OllamaConnector(OpenAIConnector):
    """Connector for Ollama's OpenAI-compatible API.

    Ollama runs locally and serves models pulled via ``ollama pull``.
    No API key is required by default.  This connector is a thin wrapper
    around ``OpenAIConnector`` that only overrides the base URL and
    skips API-key-dependent initialization when no key is provided.

    Cloud models are discovered from ``https://ollama.com/api/tags`` and
    exposed with a ``-cloud`` suffix; the Ollama app automatically
    routes those requests to the proper remote backend.
    """

    backend_type: str = "ollama"

    # Ollama serves local models only; no vendor prefix is used.
    VENDOR_PREFIX: str | None = None

    def __init__(
        self,
        client: httpx.AsyncClient,
        config: AppConfig,
        translation_service: TranslationService | None = None,
    ) -> None:
        super().__init__(client, config, translation_service=translation_service)
        self.api_base_url = OLLAMA_DEFAULT_BASE_URL

    async def initialize(self, **kwargs: Any) -> None:
        """Initialize the connector.

        Ollama does not require an API key by default.  An optional key
        can be supplied for setups where Ollama sits behind a
        reverse-proxy with auth (e.g. ``OLLAMA_API_KEY`` env var or
        ``api_key`` kwarg), but model discovery always proceeds because
        the local server does not gate ``GET /v1/models``.
        """

        # Accept optional API key (for proxied setups); do not require it.
        self.api_key = kwargs.get("api_key") or os.getenv("OLLAMA_API_KEY")

        if "api_base_url" in kwargs:
            self.api_base_url = kwargs["api_base_url"]

        # Ollama's GET /v1/models does not require authentication, so
        # always attempt model discovery regardless of api_key presence.
        local_models: list[str] = []
        try:
            headers = self.get_headers()
            response = await self.client.get(
                f"{self.api_base_url}/models", headers=headers
            )
            data = self._decode_json_payload(response)
            if isinstance(data, dict):
                local_models = [
                    model["id"]
                    for model in data.get("data") or []
                    if isinstance(model, dict) and "id" in model
                ]
            else:
                local_models = []
        except Exception as e:
            if logger.isEnabledFor(logging.WARNING):
                logger.warning(
                    "Failed to fetch local models from Ollama: %s", e, exc_info=True
                )

        # Fetch cloud models concurrently from ollama.com
        cloud_models = await _fetch_cloud_models()

        # Merge: local models take precedence, cloud models get "-cloud" suffix
        self.available_models = local_models + cloud_models
        if logger.isEnabledFor(logging.INFO):
            logger.info(
                "Ollama models loaded: %d local, %d cloud",
                len(local_models),
                len(cloud_models),
            )

    def get_headers(self, identity: Any = None) -> dict[str, str]:
        """Return request headers; inject a dummy bearer when no API key is set.

        The parent ``OpenAIConnector`` gates streaming and non-streaming paths
        on the presence of an ``Authorization`` header.  Ollama does not
        require authentication, so we supply a placeholder value when no
        real key is configured.  Ollama silently ignores the header.
        """
        headers = super().get_headers(identity)
        if not headers.get("Authorization"):
            headers["Authorization"] = "Bearer ollama"
        return headers

    async def _prepare_payload(
        self,
        request_data: CanonicalChatRequest,
        processed_messages: list[Any],
        effective_model: str,
        context: ConnectorRequestContext | None = None,
    ) -> dict[str, Any]:
        """Build JSON body for Ollama; strip fields the Ollama gateway rejects."""

        payload = await super()._prepare_payload(
            request_data, processed_messages, effective_model, context
        )
        # Ollama's OpenAI-compat API returns 400 for unknown fields.
        payload.pop("stream_options", None)
        # Ollama does not support OpenAI o1/o3 reasoning effort controls.
        payload.pop("reasoning", None)
        payload.pop("reasoning_effort", None)
        # Ollama may reject max_completion_tokens (prefers max_tokens).
        mct = payload.pop("max_completion_tokens", None)
        if mct is not None and payload.get("max_tokens") is None:
            payload["max_tokens"] = mct
        return payload

    async def _perform_health_check(self) -> bool:
        """Check connectivity to the local Ollama server.

        Unlike the parent ``OpenAIConnector`` health check, this does **not**
        require an API key because Ollama serves models without authentication
        by default.
        """

        try:
            headers = self.get_headers()
            url = f"{self.api_base_url}/models"
            response = await self.client.get(url, headers=headers)

            if response.status_code == 200:
                if logger.isEnabledFor(logging.INFO):
                    logger.info("Ollama health check passed - server reachable")
                self._health_checked = True
                return True
            else:
                if logger.isEnabledFor(logging.WARNING):
                    logger.warning(
                        "Ollama health check failed - server returned status %s",
                        response.status_code,
                    )
                return False

        except httpx.ConnectError as e:
            if logger.isEnabledFor(logging.WARNING):
                logger.warning(
                    "Ollama health check failed - cannot connect to %s: %s",
                    self.api_base_url,
                    e,
                )
            return False
        except Exception as e:
            if logger.isEnabledFor(logging.ERROR):
                logger.error(
                    "Ollama health check failed - unexpected error: %s",
                    e,
                    exc_info=True,
                )
            return False


backend_registry.register_backend("ollama", OllamaConnector)
