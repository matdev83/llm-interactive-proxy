from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from src.core.config.models.misc import ModelRegistryConfig
from src.core.domain.model_capabilities import ModelLimits

logger = logging.getLogger(__name__)


class ModelCatalogService:
    """Service for managing model metadata from an external registry."""

    _PROVIDER_MAP = {
        "gemini": "google",
        "openai": "openai",
        "anthropic": "anthropic",
        "openrouter": "openrouter",
        "deepseek": "deepseek",
        "mistral": "mistral",
    }

    def __init__(self, config: ModelRegistryConfig) -> None:
        self._config = config
        self._models: dict[str, ModelLimits] = {}
        self._providers: dict[str, Any] = {}
        self.load_catalog()

    def load_catalog(self) -> None:
        """Load the model catalog from cache or bootstrap file."""
        cache_path = Path(self._config.cache_path)
        bootstrap_path = Path(self._config.bootstrap_path)

        path_to_load = cache_path if cache_path.exists() else bootstrap_path

        if not path_to_load.exists():
            logger.warning("Model catalog file not found at %s or %s", cache_path, bootstrap_path)
            return

        try:
            with open(path_to_load, encoding="utf-8") as f:
                data = json.load(f)
                self._parse_catalog(data)
                if logger.isEnabledFor(logging.INFO):
                    logger.info("Loaded %d models from %s", len(self._models), path_to_load)
        except Exception as e:
            logger.error("Failed to load model catalog from %s: %s", path_to_load, e, exc_info=True)

    def _parse_catalog(self, data: dict[str, Any]) -> None:
        """Parse the raw catalog data into internal structures."""
        # The schema from models.dev/api.json (actually observed structure):
        # {
        #   "provider_id": {
        #     "models": {
        #       "model_id": {
        #         "limit": { "context": 128000, "output": 4096 }
        #       }
        #     }
        #   }
        # }
        self._providers = data
        
        parsed_models: dict[str, ModelLimits] = {}
        for provider_id, provider_info in data.items():
            models_data = provider_info.get("models", {})
            for model_id, info in models_data.items():
                limits = info.get("limit", {})
                context_window = limits.get("context")
                max_output = limits.get("output")
                
                # Create ModelLimits object
                model_limits = ModelLimits(
                    context_window=context_window,
                    max_output_tokens=max_output,
                    max_input_tokens=context_window  # Assume full window available for input
                )
                
                # Store with various keys for better lookup
                parsed_models[model_id] = model_limits
                
                # Also store with provider prefix (using models.dev provider ID)
                parsed_models[f"{provider_id}:{model_id}"] = model_limits
                parsed_models[f"{provider_id}/{model_id}"] = model_limits
                
        self._models = parsed_models

    def get_limits(self, model_name: str, backend_type: str | None = None) -> ModelLimits | None:
        """Look up limits for a model, optionally restricted by backend type."""
        # 1. Try exact match on model_id
        if model_name in self._models:
            return self._models[model_name]

        # 2. Try with backend prefix if provided
        if backend_type:
            # backend:model
            fq_name = f"{backend_type}:{model_name}"
            if fq_name in self._models:
                return self._models[fq_name]
            
            # models.dev often uses provider/model
            # Map our backend types to models.dev provider names
            provider = self._PROVIDER_MAP.get(backend_type)
            if provider:
                candidate_keys = [
                    f"{provider}/{model_name}",
                    f"{provider}:{model_name}",
                    f"{provider}-{model_name}",
                ]
                for k in candidate_keys:
                    if k in self._models:
                        return self._models[k]

        # 3. Try fuzzy match (stripping common prefixes if any)
        if "/" in model_name:
            base_name = model_name.split("/")[-1]
            if base_name in self._models:
                return self._models[base_name]

        # 4. Try matching by prefix (e.g., 'claude-3-5-sonnet' matches 'claude-3-5-sonnet-20241022')
        # Only do this if we have a provider to narrow it down, to avoid false positives
        if backend_type:
            provider = self._PROVIDER_MAP.get(backend_type)
            if provider:
                # Look for keys starting with provider/model_name or provider:model_name
                prefix1 = f"{provider}/{model_name}"
                prefix2 = f"{provider}:{model_name}"
                for k, v in self._models.items():
                    if k.startswith((prefix1, prefix2)):
                        return v

        return None
