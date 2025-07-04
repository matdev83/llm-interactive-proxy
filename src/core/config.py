import logging
import os
import sys
from typing import Any, Dict

from dotenv import load_dotenv

from src.command_prefix import validate_command_prefix
from src.constants import DEFAULT_COMMAND_PREFIX

logger = logging.getLogger(__name__)


def _collect_api_keys(base_name: str) -> Dict[str, str]:
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
            base_name, base_name, base_name, base_name)
        return numbered_keys

    if single_key:
        return {base_name: single_key}

    return numbered_keys


def _load_config() -> Dict[str, Any]:
    load_dotenv()

    openrouter_keys = _collect_api_keys("OPENROUTER_API_KEY")
    gemini_keys = _collect_api_keys("GEMINI_API_KEY")

    def _str_to_bool(val: str | None, default: bool = False) -> bool:
        if val is None:
            return default
        val = val.strip().lower()
        if val in ("true", "1", "yes", "on"):
            return True
        if val in ("false", "0", "no", "off", "none"):
            return False
        return default

    prefix = os.getenv("COMMAND_PREFIX", DEFAULT_COMMAND_PREFIX)
    err = validate_command_prefix(prefix)
    if err:
        logger.warning(
            "Invalid command prefix %s: %s, using default",
            prefix,
            err)
        prefix = DEFAULT_COMMAND_PREFIX

    return {
        "backend": os.getenv("LLM_BACKEND"),
        "openrouter_api_key": next(iter(openrouter_keys.values()), None),
        "openrouter_api_keys": openrouter_keys,
        "openrouter_api_base_url": os.getenv(
            "OPENROUTER_API_BASE_URL", "https://openrouter.ai/api/v1"
        ),
        "gemini_api_key": next(iter(gemini_keys.values()), None),
        "gemini_api_keys": gemini_keys,
        "gemini_api_base_url": os.getenv(
            "GEMINI_API_BASE_URL", "https://generativelanguage.googleapis.com"
        ),
        "app_site_url": os.getenv("APP_SITE_URL", "http://localhost:8000"),
        "app_x_title": os.getenv("APP_X_TITLE", "InterceptorProxy"),
        "proxy_port": int(os.getenv("PROXY_PORT", "8000")),
        "proxy_host": os.getenv("PROXY_HOST", "127.0.0.1"),
        "proxy_timeout": int(
            os.getenv("PROXY_TIMEOUT", os.getenv("OPENROUTER_TIMEOUT", "300"))
        ),
        "command_prefix": prefix,
        "interactive_mode": not _str_to_bool(
            os.getenv("DISABLE_INTERACTIVE_MODE"), False
        ),
        "redact_api_keys_in_prompts": _str_to_bool(
            os.getenv("REDACT_API_KEYS_IN_PROMPTS"), True
        ),
        "disable_auth": _str_to_bool(os.getenv("DISABLE_AUTH"), False),
        "force_set_project": _str_to_bool(os.getenv("FORCE_SET_PROJECT"), False),
        "disable_interactive_commands": _str_to_bool(
            os.getenv("DISABLE_INTERACTIVE_COMMANDS"), False
        ),
    }


def get_openrouter_headers(
        cfg: Dict[str, Any], api_key: str) -> Dict[str, str]:
    return {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "HTTP-Referer": cfg["app_site_url"],
        "X-Title": cfg["app_x_title"],
    }


def _keys_for(cfg: Dict[str, Any], b_type: str) -> list[tuple[str, str]]:
    if b_type == "gemini":
        return list(cfg["gemini_api_keys"].items())
    if b_type == "openrouter":
        return list(cfg["openrouter_api_keys"].items())
    return []
