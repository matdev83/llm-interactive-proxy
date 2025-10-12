import logging
import os
import warnings
from typing import Any

warnings.warn(
    "config_loader module is deprecated. Use src.core.config.app_config.AppConfig instead.",
    DeprecationWarning,
    stacklevel=2,
)

# The legacy ConfigLoader has been replaced by the new parameter resolution mechanism.
# Use src.core.config.app_config.AppConfig.from_env() or load_config() instead.

logger = logging.getLogger(__name__)


def _collect_api_keys(base_name: str) -> dict[str, str]:
    """Collect API keys as a mapping of env var names to values."""

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
    """Construct headers for OpenRouter requests.

    Be tolerant of minimal cfg dicts provided by tests by falling back to
    sensible defaults when optional keys are absent.
    """
    referer: str = cfg.get("app_site_url", "http://localhost:8000")
    x_title: str = cfg.get("app_x_title", "InterceptorProxy")
    return {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "HTTP-Referer": referer,
        "X-Title": x_title,
    }


# Import from the new location to maintain backward compatibility temporarily
def load_config(config_file: str | None = None):
    """Deprecated: Use src.core.config.app_config.load_config instead."""
    warnings.warn(
        "load_config from config_loader is deprecated. Use src.core.config.app_config.load_config instead.",
        DeprecationWarning,
        stacklevel=2,
    )
    try:
        from src.core.config.app_config import load_config as _new_load_config

        return _new_load_config(config_file)
    except ImportError:
        # Fallback implementation if new module is not available yet
        return {}
