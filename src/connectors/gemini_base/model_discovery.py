"""
Model discovery strategies for Gemini OAuth connectors.

This module provides different model discovery implementations:
- ApiModelDiscovery: Calls fetchAvailableModels API endpoint
- FallbackModelDiscovery: Returns hardcoded model list (for sandboxes)
"""

import logging
from typing import TYPE_CHECKING, Any

from src.connectors.gemini_base.config import DEFAULT_AVAILABLE_MODELS

if TYPE_CHECKING:
    import httpx

logger = logging.getLogger(__name__)


class ApiModelDiscovery:
    """Model discovery strategy that uses fetchAvailableModels API.

    Used by gemini-oauth-plan and gemini-oauth-free backends.
    """

    def __init__(
        self,
        fallback_models: list[str] | None = None,
    ) -> None:
        """Initialize the API model discovery strategy.

        Args:
            fallback_models: Models to use when API fails (default: DEFAULT_AVAILABLE_MODELS).
        """
        self._fallback_models = list(fallback_models or DEFAULT_AVAILABLE_MODELS)
        self._cached_models: list[str] | None = None

    def get_fallback_models(self) -> list[str]:
        """Get the fallback model list.

        Returns:
            List of fallback model names.
        """
        return self._fallback_models.copy()

    async def discover(
        self,
        client: "httpx.AsyncClient",
        headers: dict[str, str],
        base_url: str,
    ) -> list[str]:
        """Discover available models from fetchAvailableModels API.

        Uses the v1internal:fetchAvailableModels endpoint which returns a dictionary
        of available models. The models are extracted from the "models" dictionary keys
        in the response.

        Args:
            client: The HTTP client for API calls.
            headers: HTTP headers including authorization.
            base_url: The API base URL.

        Returns:
            List of available model names.
        """
        if self._cached_models:
            return self._cached_models.copy()

        base_url = (base_url or "").rstrip("/")
        url = f"{base_url}/v1internal:fetchAvailableModels"

        try:
            response = await client.get(url, headers=headers, timeout=15.0)
        except Exception as exc:
            logger.warning(
                "Failed to reach fetchAvailableModels endpoint %s: %s", url, exc
            )
            return self.get_fallback_models()

        if response.status_code != 200:
            logger.debug(
                "fetchAvailableModels endpoint %s returned %s: %s",
                url,
                response.status_code,
                response.text[:200] if response.text else "",
            )
            return self.get_fallback_models()

        try:
            data = response.json()
            models = self._extract_models_from_response(data)
            if models:
                self._cached_models = models
                logger.info(
                    "Successfully discovered %d models from fetchAvailableModels",
                    len(models),
                )
                return models
        except Exception as exc:
            logger.warning("Failed to parse fetchAvailableModels response: %s", exc)

        return self.get_fallback_models()

    def _extract_models_from_response(self, data: dict[str, Any]) -> list[str]:
        """Extract model names from the API response.

        Args:
            data: The JSON response from fetchAvailableModels.

        Returns:
            List of model names.
        """
        models: list[str] = []

        # Handle the format: {"models": {"model_name": {...}, ...}}
        models_dict = data.get("models", {})
        if isinstance(models_dict, dict):
            models.extend(models_dict.keys())

        # Handle the format: {"models": [{"name": "models/model_name"}, ...]}
        if isinstance(models_dict, list):
            for item in models_dict:
                if isinstance(item, dict):
                    name = item.get("name", "")
                    if name.startswith("models/"):
                        name = name[7:]  # Remove "models/" prefix
                    if name:
                        models.append(name)

        return models

    def clear_cache(self) -> None:
        """Clear the cached models list."""
        self._cached_models = None


class FallbackModelDiscovery:
    """Model discovery strategy that returns a hardcoded model list.

    Used by gemini-oauth-antigravity backend where the sandbox
    doesn't expose fetchAvailableModels endpoint.
    """

    # Extended model list for Antigravity (includes Claude models)
    ANTIGRAVITY_MODELS = [
        # Gemini models
        "gemini-2.5-pro",
        "gemini-2.5-flash",
        "gemini-2.5-flash-lite",
        "gemini-2.5-pro-preview-05-06",
        "gemini-2.5-pro-preview-06-05",
        "gemini-2.5-flash-preview-05-20",
        "gemini-2.0-flash",
        "gemini-2.0-flash-thinking-exp-1219",
        "gemini-1.5-pro",
        "gemini-1.5-flash",
        # Claude models (Antigravity sandbox supports these)
        "claude-sonnet-4-5",
        "claude-3-5-sonnet",
        "claude-3-5-sonnet-v2",
        "anthropic/claude-opus-4-5",
    ]

    def __init__(
        self,
        models: list[str] | None = None,
    ) -> None:
        """Initialize the fallback model discovery strategy.

        Args:
            models: Custom model list (default: ANTIGRAVITY_MODELS).
        """
        self._models = list(models or self.ANTIGRAVITY_MODELS)

    def get_fallback_models(self) -> list[str]:
        """Get the fallback model list.

        Returns:
            List of model names.
        """
        return self._models.copy()

    async def discover(
        self,
        client: "httpx.AsyncClient",
        headers: dict[str, str],
        base_url: str,
    ) -> list[str]:
        """Return the hardcoded model list without API calls.

        This method skips API discovery since the Antigravity sandbox
        doesn't expose fetchAvailableModels endpoint.

        Args:
            client: The HTTP client (unused).
            headers: HTTP headers (unused).
            base_url: The API base URL (unused).

        Returns:
            List of available model names.
        """
        logger.info(
            "Skipping fetchAvailableModels for sandbox endpoint; using fallback model list."
        )
        return self.get_fallback_models()


__all__ = [
    "ApiModelDiscovery",
    "FallbackModelDiscovery",
]
