import logging
import os
from typing import Any

from dotenv import load_dotenv

from src.command_prefix import validate_command_prefix
from src.constants import DEFAULT_COMMAND_PREFIX

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
    referer = cfg.get("app_site_url", "http://localhost:8000")
    x_title = cfg.get("app_x_title", "InterceptorProxy")
    return {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "HTTP-Referer": referer,
        "X-Title": x_title,
    }


def _keys_for(cfg: dict[str, Any], b_type: str) -> list[tuple[str, str]]:
    if b_type == "gemini":
        return list(cfg["gemini_api_keys"].items())
    if b_type == "openrouter":
        return list(cfg["openrouter_api_keys"].items())
    if b_type == "anthropic":
        return list(cfg["anthropic_api_keys"].items())
    if b_type == "zai":
        return list(cfg["zai_api_keys"].items())
    if b_type == "qwen-oauth":
        # Qwen OAuth backend uses OAuth tokens, not API keys
        return [(b_type, "oauth-token")]
    return []


def _str_to_bool(val: str | None, default: bool = False) -> bool:
    if val is None:
        return default
    val = val.strip().lower()
    if val in ("true", "1", "yes", "on"):
        return True
    if val in ("false", "0", "no", "off", "none"):
        return False
    return default


def _load_config(config_file: str | None = None) -> dict[str, Any]:
    """Legacy wrapper function for backward compatibility.

    This function provides the same interface as the old _load_config function
    but uses the new ConfigLoader implementation.

    Args:
        config_file: Optional path to configuration file

    Returns:
        Dictionary containing all configuration values
    """
    loader = ConfigLoader()
    return loader.load_config(config_file)


class ConfigLoader:
    """Configuration loader for the SOLID architecture.

    This class provides a structured interface for loading configuration data
    from environment variables and configuration files.
    """

    def __init__(self):
        """Initialize the configuration loader."""
        self._config_cache: dict[str, Any] | None = None

    def load_config(self, config_file: str | None = None) -> dict[str, Any]:
        """Load configuration from environment and optional config file.

        Args:
            config_file: Optional path to configuration file

        Returns:
            Dictionary containing all configuration values
        """
        if self._config_cache is None:
            self._config_cache = self._load_base_config()

        config = dict(self._config_cache)

        # Override with config file if provided
        if config_file:
            try:
                file_config = self._load_config_file(config_file)
                config.update(file_config)
            except Exception as exc:
                logger.warning("Failed to load config file %s: %s", config_file, exc)

        return config

    def _load_base_config(self) -> dict[str, Any]:
        """Load base configuration from environment variables.

        Returns:
            Dictionary containing base configuration
        """
        load_dotenv()

        openrouter_keys = _collect_api_keys("OPENROUTER_API_KEY")
        gemini_keys = _collect_api_keys("GEMINI_API_KEY")
        anthropic_keys = _collect_api_keys("ANTHROPIC_API_KEY")
        zai_keys = _collect_api_keys("ZAI_API_KEY")

        prefix = os.getenv("COMMAND_PREFIX", DEFAULT_COMMAND_PREFIX)
        err = validate_command_prefix(prefix)
        if err:
            logger.warning("Invalid command prefix %s: %s, using default", prefix, err)
            prefix = DEFAULT_COMMAND_PREFIX

        # Security: Check if authentication is disabled
        disable_auth = _str_to_bool(os.getenv("DISABLE_AUTH"), False)
        proxy_host = os.getenv("PROXY_HOST", "127.0.0.1")

        # Force localhost when authentication is disabled
        if disable_auth and proxy_host != "127.0.0.1":
            logger.warning(
                "Authentication is disabled but PROXY_HOST is set to %s. Forcing to 127.0.0.1 for security.",
                proxy_host,
            )
            proxy_host = "127.0.0.1"

        return {
            "backend": os.getenv("LLM_BACKEND"),
            "openrouter_api_key": next(iter(openrouter_keys.values()), None),
            "openrouter_api_keys": openrouter_keys,
            "openrouter_api_base_url": os.getenv(
                "OPENROUTER_API_BASE_URL", "https://openrouter.ai/api/v1"
            ),
            "gemini_api_key": next(iter(gemini_keys.values()), None),
            "anthropic_api_key": next(iter(anthropic_keys.values()), None),
            "gemini_api_keys": gemini_keys,
            "anthropic_api_keys": anthropic_keys,
            "zai_api_key": next(iter(zai_keys.values()), None),
            "zai_api_keys": zai_keys,
            "gemini_api_base_url": os.getenv(
                "GEMINI_API_BASE_URL", "https://generativelanguage.googleapis.com"
            ),
            "anthropic_api_base_url": os.getenv(
                "ANTHROPIC_API_BASE_URL", "https://api.anthropic.com/v1"
            ),
            "google_cloud_project": os.getenv("GOOGLE_CLOUD_PROJECT"),
            "app_site_url": os.getenv("APP_SITE_URL", "http://localhost:8000"),
            "app_x_title": os.getenv("APP_X_TITLE", "InterceptorProxy"),
            "proxy_port": int(os.getenv("PROXY_PORT", "8000")),
            "proxy_host": proxy_host,
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
            "disable_auth": disable_auth,
            "force_set_project": _str_to_bool(os.getenv("FORCE_SET_PROJECT"), False),
            "disable_interactive_commands": _str_to_bool(
                os.getenv("DISABLE_INTERACTIVE_COMMANDS"), False
            ),
            "disable_accounting": _str_to_bool(os.getenv("DISABLE_ACCOUNTING"), False),
            # Loop detection configuration
            "loop_detection_enabled": _str_to_bool(
                os.getenv("LOOP_DETECTION_ENABLED"), True
            ),
            "loop_detection_buffer_size": int(
                os.getenv("LOOP_DETECTION_BUFFER_SIZE", "2048")
            ),
            "loop_detection_max_pattern_length": int(
                os.getenv("LOOP_DETECTION_MAX_PATTERN_LENGTH", "500")
            ),
            # Tool call loop detection configuration
            "tool_loop_detection_enabled": _str_to_bool(
                os.getenv("TOOL_LOOP_DETECTION_ENABLED"), True
            ),
            "tool_loop_max_repeats": int(os.getenv("TOOL_LOOP_MAX_REPEATS", "4")),
            "tool_loop_ttl_seconds": int(os.getenv("TOOL_LOOP_TTL_SECONDS", "120")),
            # Normalize mode; accept shorthand 'chance'
            "tool_loop_mode": (
                lambda m: (
                    "chance_then_break"
                    if (m or "").strip().lower() == "chance"
                    else (m or "break")
                )
            )(os.getenv("TOOL_LOOP_MODE", "break")),
        }

    def _load_config_file(self, config_file: str) -> dict[str, Any]:
        """Load configuration from a file.

        Args:
            config_file: Path to the configuration file

        Returns:
            Dictionary containing configuration from file

        Raises:
            FileNotFoundError: If config file doesn't exist
            ValueError: If config file has invalid format
        """
        import json
        from pathlib import Path

        import yaml

        path = Path(config_file)
        if not path.exists():
            raise FileNotFoundError(f"Configuration file not found: {config_file}")

        try:
            content = path.read_text(encoding="utf-8")

            # Try YAML first, then JSON
            try:
                return yaml.safe_load(content) or {}
            except yaml.YAMLError:
                return json.loads(content)

        except (json.JSONDecodeError, yaml.YAMLError) as exc:
            raise ValueError(f"Invalid configuration file format: {exc}") from exc

    def reload_config(self) -> None:
        """Clear the config cache to force reload on next access."""
        self._config_cache = None
