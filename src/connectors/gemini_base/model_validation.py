"""
Model validation utilities for Gemini Code Assist.

This module handles model name normalization, validation,
and public-to-internal model name mapping.
"""

import logging
from typing import Any

from src.connectors.base import add_vendor_prefix, strip_vendor_prefix
from src.core.common.exceptions import BackendError

logger = logging.getLogger(__name__)

# Vendor prefix for Google models in unified model naming convention
GOOGLE_VENDOR_PREFIX = "google"


class ModelValidator:
    """Handles model validation and name mapping for Gemini backends.

    This class provides:
    - Model name normalization for prompt-limit lookups
    - Model name sanitization to prevent internal name leaks
    - Public-to-internal model name mapping
    - Model availability validation
    """

    # Mapping from public aliases (without vendor prefix) to internal model names
    DEFAULT_PUBLIC_TO_INTERNAL_MAP: dict[str, str] = {
        "gemini-3-pro": "gemini-3-pro-preview",
    }

    def __init__(
        self,
        public_to_internal_map: dict[str, str] | None = None,
    ) -> None:
        """Initialize the model validator.

        Args:
            public_to_internal_map: Custom mapping from public to internal names.
                If None, uses DEFAULT_PUBLIC_TO_INTERNAL_MAP.
        """
        self._public_to_internal_map = (
            public_to_internal_map
            if public_to_internal_map is not None
            else self.DEFAULT_PUBLIC_TO_INTERNAL_MAP.copy()
        )

    @property
    def public_to_internal_map(self) -> dict[str, str]:
        """Get the public to internal model mapping."""
        return self._public_to_internal_map

    @staticmethod
    def normalize_model_key(model_name: str) -> str:
        """Normalize model identifiers for prompt-limit lookups.

        Args:
            model_name: Raw model name

        Returns:
            Normalized lowercase model key
        """
        from src.connectors.gemini_base.prompt_limiter import normalize_model_key

        return normalize_model_key(model_name)

    @staticmethod
    def sanitize_model_name(model_name: str) -> str:
        """Sanitize model name to prevent internal leaks.

        Args:
            model_name: Raw model name

        Returns:
            Sanitized model name safe for external exposure
        """
        if not model_name:
            return "unknown"
        # If it's an internal model name, map it to a generic one
        if "code-assist-model" in model_name:
            return "gemini-2.5-pro"  # Default fallback for code assist
        return model_name

    def resolve_model_name(
        self,
        model_name: str,
        backend_prefix: str | None = None,
    ) -> str:
        """Resolve a model name by stripping prefixes and mapping aliases.

        Args:
            model_name: Raw model name (may include prefixes)
            backend_prefix: Optional backend prefix to strip (e.g., "gemini-oauth-plan:")

        Returns:
            Resolved internal model name
        """
        resolved = model_name

        # Strip backend prefix if provided
        if backend_prefix and resolved.startswith(backend_prefix):
            resolved = resolved[len(backend_prefix) :]

        # Strip vendor prefix
        resolved = strip_vendor_prefix(resolved, GOOGLE_VENDOR_PREFIX)

        # Map public alias to internal name if exists
        resolved = self._public_to_internal_map.get(resolved, resolved)

        return resolved

    def get_available_models_with_prefix(
        self,
        available_models: list[str],
    ) -> list[str]:
        """Return available models with vendor prefix for unified model routing.

        Args:
            available_models: List of raw model names

        Returns:
            List of model names with 'google/' vendor prefix
        """
        # Create reverse mapping for exposure
        internal_to_public = {v: k for k, v in self._public_to_internal_map.items()}

        models = []
        for m in available_models:
            # Map internal name to public alias if exists
            public_name = internal_to_public.get(m, m)
            models.append(add_vendor_prefix(public_name, GOOGLE_VENDOR_PREFIX))

        return models

    def validate_model(
        self,
        model_name: str,
        available_models_set: set[str],
        models_from_api: bool,
        backend_type: str,
    ) -> None:
        """Validate that the requested model is available on this backend.

        Validation is only performed when models were loaded from the API.
        When using the hardcoded fallback list, validation is skipped since
        the hardcoded list may be outdated.

        Args:
            model_name: The model name to validate
            available_models_set: Set of available model names
            models_from_api: Whether models were loaded from API
            backend_type: Backend type for error messages

        Raises:
            BackendError: If the model is not in the available models list
        """
        # Only validate if models were loaded from the API
        if not models_from_api:
            logger.debug(
                "Model validation skipped - using hardcoded fallback model list"
            )
            return

        if not available_models_set:
            logger.debug(
                "Model validation skipped - available models list not loaded yet"
            )
            return

        if model_name not in available_models_set:
            available_list = sorted(available_models_set)[:10]
            suffix = (
                f"... and {len(available_models_set) - 10} more"
                if len(available_models_set) > 10
                else ""
            )
            raise BackendError(
                message=f"Model '{model_name}' is not available on this backend. "
                f"Available models: {', '.join(available_list)}{suffix}",
                code="model_not_found",
                status_code=400,
                backend_name=backend_type,
                details={
                    "requested_model": model_name,
                    "available_count": len(available_models_set),
                },
            )


class ModelListManager:
    """Manages the list of available models for a backend."""

    # Default fallback model list
    DEFAULT_MODELS: list[str] = [
        # Current generation (2.5 series) - DEFAULT models
        "gemini-2.5-pro",
        "gemini-2.5-flash",
        "gemini-2.5-flash-lite",
        # Preview models
        "gemini-2.5-pro-preview-05-06",
        "gemini-2.5-pro-preview-06-05",
        "gemini-2.5-flash-preview-05-20",
        # 2.0 series
        "gemini-2.0-flash",
        "gemini-2.0-flash-thinking-exp-1219",
        "gemini-2.0-flash-preview-image-generation",
        # 1.5 series
        "gemini-1.5-pro",
        "gemini-1.5-flash",
        # Embedding model
        "gemini-embedding-001",
    ]

    def __init__(self) -> None:
        self._available_models: list[str] = []
        self._available_models_set: set[str] = set()
        self._models_from_api: bool = False

    @property
    def available_models(self) -> list[str]:
        """Get the list of available models."""
        return self._available_models

    @available_models.setter
    def available_models(self, value: list[str]) -> None:
        """Set the list of available models."""
        self._available_models = value
        self._available_models_set = set(value)

    @property
    def available_models_set(self) -> set[str]:
        """Get the set of available models for fast lookups."""
        if not self._available_models_set:
            self._available_models_set = set(self._available_models or [])
        return self._available_models_set

    @property
    def models_from_api(self) -> bool:
        """Check if models were loaded from API."""
        return self._models_from_api

    @models_from_api.setter
    def models_from_api(self, value: bool) -> None:
        """Set whether models were loaded from API."""
        self._models_from_api = value

    def set_from_api_response(self, models: list[str]) -> None:
        """Update models from API response.

        Args:
            models: List of models from API
        """
        self._available_models = sorted(models)
        self._available_models_set = set(models)
        self._models_from_api = True
        logger.info(
            "Loaded %d models from fetchAvailableModels endpoint",
            len(self._available_models),
        )

    def set_fallback_models(self) -> None:
        """Set the default fallback model list."""
        self._available_models = self.DEFAULT_MODELS.copy()
        self._available_models_set = set(self._available_models)
        self._models_from_api = False
        logger.info(
            f"Loaded {len(self._available_models)} known Code Assist models (hardcoded fallback)"
        )

    def parse_models_from_response(self, data: dict[str, Any]) -> list[str]:
        """Parse model IDs from fetchAvailableModels API response.

        Args:
            data: API response data

        Returns:
            List of model names
        """
        slugs: set[str] = set()
        models_dict = data.get("models", {})
        if isinstance(models_dict, dict):
            for model_key in models_dict:
                if isinstance(model_key, str) and model_key.strip():
                    slugs.add(model_key.strip())
        return list(slugs)

    def transform_for_list_models_response(
        self, data: dict[str, Any]
    ) -> dict[str, Any]:
        """Transform fetchAvailableModels response to expected format.

        Args:
            data: Raw API response

        Returns:
            Transformed response matching expected format
        """
        models_list = []
        models_dict = data.get("models", {})
        if isinstance(models_dict, dict):
            for model_id, model_info in models_dict.items():
                model_entry: dict[str, Any] = {"name": f"models/{model_id}"}
                if isinstance(model_info, dict):
                    if "displayName" in model_info:
                        model_entry["displayName"] = model_info["displayName"]
                    if "maxTokens" in model_info:
                        model_entry["inputTokenLimit"] = model_info["maxTokens"]
                    if "maxOutputTokens" in model_info:
                        model_entry["outputTokenLimit"] = model_info["maxOutputTokens"]
                models_list.append(model_entry)
        return {"models": models_list}
