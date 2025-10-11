# Configuration package

# For backward compatibility, provide placeholder implementations
import logging
import warnings
from typing import Any

from src.core.config.app_config import AppConfig

logger = logging.getLogger(__name__)


def _collect_api_keys(base_name: str) -> dict[str, str]:
    """Collect API keys as a mapping of env var names to values."""
    import os

    single_key = os.getenv(base_name)
    numbered_keys = {}
    for i in range(1, 21):
        key = os.getenv(f"{base_name}_{i}")
        if key:
            numbered_keys[f"{base_name}_{i}"] = key

    if single_key and numbered_keys:
        logger.warning(
            "Both %s and %s_<n> environment variables are set. Prioritizing %s_<n> and ignoring %s.",
            base_name,
            base_name,
            base_name,
            base_name,
        )
        return numbered_keys

    if single_key:
        return {base_name: single_key}

    return numbered_keys


def get_openrouter_headers(cfg: dict[str, Any], api_key: str) -> dict[str, str]:
    """Construct headers for OpenRouter requests."""
    referer: str = cfg.get("app_site_url", "http://localhost:8000")
    x_title: str = cfg.get("app_x_title", "InterceptorProxy")
    return {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "HTTP-Referer": referer,
        "X-Title": x_title,
    }


class ConfigLoader:
    """Deprecated placeholder for backward compatibility."""

    def __init__(self):
        warnings.warn(
            "ConfigLoader is deprecated. Use AppConfig.from_env() instead.",
            DeprecationWarning,
            stacklevel=2,
        )

    def load_config(self, config_file=None):
        warnings.warn(
            "ConfigLoader.load_config is deprecated. Use AppConfig.from_env() instead.",
            DeprecationWarning,
            stacklevel=2,
        )
        return {}


__all__ = [
    "AppConfig",
    "ConfigLoader",
    "_collect_api_keys",
    "get_openrouter_headers",
    "logger",
]
