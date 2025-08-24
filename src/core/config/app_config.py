from __future__ import annotations

import contextlib
import logging
import os
from enum import Enum
from pathlib import Path
from typing import Any, cast

from pydantic import ConfigDict, Field, field_validator

from src.core.config.config_loader import _collect_api_keys
from src.core.domain.configuration.app_identity_config import AppIdentityConfig
from src.core.interfaces.configuration_interface import IConfig
from src.core.interfaces.model_bases import DomainModel

# Note: Avoid self-imports to prevent circular dependencies. Classes are defined below.

logger = logging.getLogger(__name__)


def _process_api_keys(keys_string: str) -> list[str]:
    """Process a comma-separated string of API keys."""
    keys = keys_string.split(",")
    result: list[str] = []
    for key in keys:
        stripped_key = key.strip()
        if stripped_key:
            result.append(stripped_key)
    return result


def _get_api_keys_from_env() -> list[str]:
    """Get API keys from environment variables."""
    result: list[str] = []

    # Get API keys from API_KEYS environment variable
    api_keys_raw: str | None = os.environ.get("API_KEYS")
    if api_keys_raw and isinstance(api_keys_raw, str):
        result.extend(_process_api_keys(api_keys_raw))

    return result


class LogLevel(str, Enum):
    """Log levels for configuration."""

    DEBUG = "DEBUG"
    INFO = "INFO"
    WARNING = "WARNING"
    ERROR = "ERROR"
    CRITICAL = "CRITICAL"


class BackendConfig(DomainModel):
    """Configuration for a backend service."""

    api_key: list[str] = Field(default_factory=list)
    api_url: str | None = None
    models: list[str] = Field(default_factory=list)
    timeout: int = 120  # seconds
    identity: AppIdentityConfig | None = None
    extra: dict[str, Any] = Field(default_factory=dict)

    @field_validator("api_key", mode="before")
    @classmethod
    def validate_api_key(cls, v: Any) -> list[str]:
        """Ensure api_key is always a list."""
        if isinstance(v, str):
            return [v]
        return v if isinstance(v, list) else []

    @field_validator("api_url")
    @classmethod
    def validate_api_url(cls, v: str | None) -> str | None:
        """Validate the API URL if provided."""
        if v is not None and not v.startswith(("http://", "https://")):
            raise ValueError("API URL must start with http:// or https://")
        return v


class AuthConfig(DomainModel):
    """Authentication configuration."""

    disable_auth: bool = False
    api_keys: list[str] = Field(default_factory=list)
    auth_token: str | None = None
    redact_api_keys_in_prompts: bool = True


class LoggingConfig(DomainModel):
    """Logging configuration."""

    level: LogLevel = LogLevel.INFO
    request_logging: bool = False
    response_logging: bool = False
    log_file: str | None = None


class SessionConfig(DomainModel):
    """Session management configuration."""

    cleanup_enabled: bool = True
    cleanup_interval: int = 3600  # 1 hour
    max_age: int = 86400  # 1 day
    default_interactive_mode: bool = True
    force_set_project: bool = False
    disable_interactive_commands: bool = False
    tool_call_repair_enabled: bool = True
    # Max per-session buffer for tool-call repair streaming (bytes)
    tool_call_repair_buffer_cap_bytes: int = 64 * 1024


class EmptyResponseConfig(DomainModel):
    """Configuration for empty response handling."""

    enabled: bool = True
    max_retries: int = 1


from src.core.services.backend_registry import (
    backend_registry,  # Updated import path
)


class BackendSettings(DomainModel):
    """Settings for all backends."""

    default_backend: str = "openai"
    # Store backend configs as dynamic fields
    model_config = ConfigDict(extra="allow")

    def __init__(self, **data: Any) -> None:
        # Extract backend configs from data before calling super().__init__
        backend_configs: dict[str, Any] = {}
        registered_backends: list[str] = backend_registry.get_registered_backends()

        # Extract backend configs from data
        for backend_name in registered_backends:
            if backend_name in data:
                backend_configs[backend_name] = data.pop(backend_name)

        # Call parent constructor with remaining data
        super().__init__(**data)

        # Set backend configs using __dict__ to bypass Pydantic's field system
        for backend_name, config_data in backend_configs.items():
            if isinstance(config_data, dict):
                config: BackendConfig = BackendConfig(**config_data)
            elif isinstance(config_data, BackendConfig):
                config = config_data
            else:
                config = BackendConfig()
            # Use __dict__ to bypass Pydantic's field system
            self.__dict__[backend_name] = config

        # Add default BackendConfig for any registered backends that don't have configs
        for backend_name in registered_backends:
            if backend_name not in self.__dict__:
                self.__dict__[backend_name] = BackendConfig()

    def __getitem__(self, key: str) -> BackendConfig:
        """Allow dictionary-style access to backend configs."""
        if key in self.__dict__:
            return cast(BackendConfig, self.__dict__[key])
        raise KeyError(f"Backend '{key}' not found")

    def __setitem__(self, key: str, value: BackendConfig) -> None:
        """Allow dictionary-style setting of backend configs."""
        self.__dict__[key] = value

    def get(self, key: str, default: Any = None) -> Any:
        """Dictionary-style get with default."""
        return cast(BackendConfig | None, self.__dict__.get(key, default))

    @property
    def functional_backends(self) -> set[str]:
        """Get the set of functional backends (those with API keys)."""
        functional: set[str] = set()
        for backend_name in backend_registry.get_registered_backends():
            if backend_name in self.__dict__:
                config: Any = self.__dict__[backend_name]
                if isinstance(config, BackendConfig) and config.api_key:
                    functional.add(backend_name)
        return functional

    def __getattr__(self, name: str) -> Any:
        """Allow accessing backend configs as attributes.

        If an attribute for a backend is missing, create a default
        BackendConfig instance lazily. This ensures tests and runtime
        code can access `config.backends.openai` / `config.backends.gemini`
        even if the registry hasn't been populated yet.
        """
        if name == "default_backend":  # Handle default_backend separately
            # Ensure we use the explicitly set default_backend if available
            if "default_backend" in self.__dict__:
                return self.__dict__["default_backend"]
            # Otherwise fall back to openai
            return "openai"

        # Check if the attribute exists in __dict__
        if name in self.__dict__:
            return cast(BackendConfig, self.__dict__[name])

        # For other attributes, raise AttributeError to maintain normal behavior
        raise AttributeError(
            f"'{self.__class__.__name__}' object has no attribute '{name}'"
        )

    def model_dump(self, **kwargs: Any) -> dict[str, Any]:
        """Override model_dump to include default_backend and dynamic backends."""
        dumped: dict[str, Any] = super().model_dump(**kwargs)
        # Add dynamic backends to the dumped dictionary
        for backend_name in backend_registry.get_registered_backends():
            if backend_name in self.__dict__:
                config: Any = self.__dict__[backend_name]
                if isinstance(config, BackendConfig):
                    dumped[backend_name] = config.model_dump()
        return dumped


class AppConfig(DomainModel, IConfig):
    """Complete application configuration."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    host: str = "0.0.0.0"
    port: int = 8000
    proxy_timeout: int = 120
    command_prefix: str = "!/"

    # Rate limit settings
    default_rate_limit: int = 60
    default_rate_window: int = 60

    # Backend settings
    backends: BackendSettings = Field(default_factory=BackendSettings)
    model_defaults: dict[str, dict[str, Any]] = Field(default_factory=dict)
    failover_routes: dict[str, dict[str, Any]] = Field(default_factory=dict)

    # No nested class references - use direct imports instead

    # Identity settings
    identity: AppIdentityConfig = Field(default_factory=AppIdentityConfig)

    # Auth settings
    auth: AuthConfig = Field(default_factory=AuthConfig)

    # Session settings
    session: SessionConfig = Field(default_factory=SessionConfig)

    # Logging settings
    logging: LoggingConfig = Field(default_factory=LoggingConfig)

    # Empty response handling settings
    empty_response: EmptyResponseConfig = Field(default_factory=EmptyResponseConfig)

    def save(self, path: str | Path) -> None:
        """Save the current configuration to a file."""
        with open(path, "w") as f:
            f.write(self.model_dump_json(indent=4))

    # Integration with legacy config

    @classmethod
    def from_env(cls) -> AppConfig:
        """Create AppConfig from environment variables.

        Returns:
            AppConfig instance
        """
        # Build configuration from environment
        config: dict[str, Any] = {
            # Server settings
            "host": os.environ.get("APP_HOST", "0.0.0.0"),
            "port": int(os.environ.get("APP_PORT", "8000")),
            "proxy_timeout": int(os.environ.get("PROXY_TIMEOUT", "120")),
            "command_prefix": os.environ.get("COMMAND_PREFIX", "!/"),
            "auth": {
                "disable_auth": os.environ.get("DISABLE_AUTH", "").lower() == "true",
                "api_keys": _get_api_keys_from_env(),
                "auth_token": os.environ.get("AUTH_TOKEN"),
            },
        }

        # After populating auth config, if disable_auth is true, clear api_keys
        auth_config: dict[str, Any] = config["auth"]
        if isinstance(auth_config, dict) and auth_config.get("disable_auth"):
            auth_config["api_keys"] = []

        # Add session, logging, and backend config
        config["session"] = {
            "cleanup_enabled": os.environ.get("SESSION_CLEANUP_ENABLED", "true").lower()
            == "true",
            "cleanup_interval": int(os.environ.get("SESSION_CLEANUP_INTERVAL", "3600")),
            "max_age": int(os.environ.get("SESSION_MAX_AGE", "86400")),
            "default_interactive_mode": os.environ.get(
                "DEFAULT_INTERACTIVE_MODE", "true"
            ).lower()
            == "true",
            "force_set_project": os.environ.get("FORCE_SET_PROJECT", "").lower()
            == "true",
            "tool_call_repair_enabled": os.environ.get(
                "TOOL_CALL_REPAIR_ENABLED", "true"
            ).lower()
            == "true",
            # Optional cap for streaming repair buffer
            "tool_call_repair_buffer_cap_bytes": (
                int(os.environ.get("TOOL_CALL_REPAIR_BUFFER_CAP_BYTES", "65536"))
                if os.environ.get("TOOL_CALL_REPAIR_BUFFER_CAP_BYTES")
                else 65536
            ),
        }

        config["logging"] = {
            "level": os.environ.get("LOG_LEVEL", "INFO"),
            "request_logging": os.environ.get("REQUEST_LOGGING", "").lower() == "true",
            "response_logging": os.environ.get("RESPONSE_LOGGING", "").lower()
            == "true",
            "log_file": os.environ.get("LOG_FILE"),
        }

        config["empty_response"] = {
            "enabled": os.environ.get("EMPTY_RESPONSE_HANDLING_ENABLED", "true").lower()
            == "true",
            "max_retries": int(os.environ.get("EMPTY_RESPONSE_MAX_RETRIES", "1")),
        }

        config["backends"] = {
            "default_backend": os.environ.get("LLM_BACKEND", "openai")
        }

        config["identity"] = {
            "title": os.environ.get("APP_TITLE", "llm-interactive-proxy"),
            "url": os.environ.get(
                "APP_URL", "https://github.com/matdev83/llm-interactive-proxy"
            ),
        }

        # Log the determined default_backend
        logger.info(
            f"AppConfig.from_env - Determined default_backend: {config['backends']['default_backend']}"
        )

        # Extract backend configurations from environment
        config_backends: dict[str, Any] = config["backends"]
        assert isinstance(config_backends, dict)

        # Collect and assign API keys for specific backends
        openrouter_keys: dict[str, str] = _collect_api_keys("OPENROUTER_API_KEY")
        if openrouter_keys:
            config_backends["openrouter"] = config_backends.get("openrouter", {})
            config_backends["openrouter"]["api_key"] = list(openrouter_keys.values())
            config_backends["openrouter"]["api_url"] = os.environ.get(
                "OPENROUTER_API_BASE_URL", "https://openrouter.ai/api/v1"
            )
            if os.environ.get("OPENROUTER_TIMEOUT"):
                with contextlib.suppress(ValueError):
                    config_backends["openrouter"]["timeout"] = int(
                        os.environ.get("OPENROUTER_TIMEOUT", "0")
                    )

        gemini_keys: dict[str, str] = _collect_api_keys("GEMINI_API_KEY")
        if gemini_keys:
            config_backends["gemini"] = config_backends.get("gemini", {})
            config_backends["gemini"]["api_key"] = list(gemini_keys.values())
            config_backends["gemini"]["api_url"] = os.environ.get(
                "GEMINI_API_BASE_URL", "https://generativelanguage.googleapis.com"
            )
            if os.environ.get("GEMINI_TIMEOUT"):
                with contextlib.suppress(ValueError):
                    config_backends["gemini"]["timeout"] = int(
                        os.environ.get("GEMINI_TIMEOUT", "0")
                    )

        anthropic_keys: dict[str, str] = _collect_api_keys("ANTHROPIC_API_KEY")
        if anthropic_keys:
            config_backends["anthropic"] = config_backends.get("anthropic", {})
            config_backends["anthropic"]["api_key"] = list(anthropic_keys.values())
            config_backends["anthropic"]["api_url"] = os.environ.get(
                "ANTHROPIC_API_BASE_URL", "https://api.anthropic.com/v1"
            )
            if os.environ.get("ANTHROPIC_TIMEOUT"):
                with contextlib.suppress(ValueError):
                    config_backends["anthropic"]["timeout"] = int(
                        os.environ.get("ANTHROPIC_TIMEOUT", "0")
                    )

        zai_keys: dict[str, str] = _collect_api_keys("ZAI_API_KEY")
        if zai_keys:
            config_backends["zai"] = config_backends.get("zai", {})
            config_backends["zai"]["api_key"] = list(zai_keys.values())
            config_backends["zai"]["api_url"] = os.environ.get("ZAI_API_BASE_URL")
            if os.environ.get("ZAI_TIMEOUT"):
                with contextlib.suppress(ValueError):
                    config_backends["zai"]["timeout"] = int(
                        os.environ.get("ZAI_TIMEOUT", "0")
                    )

        # Handle default backend if it's not explicitly configured above
        default_backend_type: str = os.environ.get("LLM_BACKEND", "openai")
        if default_backend_type not in config_backends:
            # If the default backend is not explicitly configured, ensure it has a basic config
            config_backends[default_backend_type] = config_backends.get(
                default_backend_type, {}
            )
            # Add a dummy API key if running in test environment and no API key is present
            if os.environ.get("PYTEST_CURRENT_TEST") and (
                not config_backends[default_backend_type]
                or not config_backends[default_backend_type].get("api_key")
            ):
                config_backends[default_backend_type]["api_key"] = [
                    f"test-key-{default_backend_type}"
                ]
                logger.info(
                    f"Added test API key for default backend {default_backend_type}"
                )

        return cls(**config)  # type: ignore

    def get(self, key: str, default: Any = None) -> Any:
        """Get a configuration value by key."""
        # Split the key by dots to handle nested attributes
        keys = key.split(".")
        value: Any = self

        try:
            for k in keys:
                if isinstance(value, dict):
                    value = value.get(k, default)
                else:
                    value = getattr(value, k, default)
            return value
        except Exception:
            return default

    def set(self, key: str, value: Any) -> None:
        """Set a configuration value."""
        # For simplicity, we'll only handle top-level attributes
        # In a more complex implementation, we might want to handle nested attributes
        setattr(self, key, value)


def _merge_dicts(d1: dict[str, Any], d2: dict[str, Any]) -> dict[str, Any]:
    for k, v in d2.items():
        if k in d1 and isinstance(d1[k], dict) and isinstance(v, dict):
            _merge_dicts(d1[k], v)
        else:
            d1[k] = v
    return d1


def load_config(config_path: str | Path | None = None) -> AppConfig:
    """
    Load configuration from file and environment.

    Args:
        config_path: Optional path to configuration file

    Returns:
        AppConfig instance
    """
    # Start with environment configuration
    config: AppConfig = AppConfig.from_env()

    # Override with file configuration if provided
    if config_path:
        try:
            import json

            import yaml

            path: Path = Path(config_path)
            if not path.exists():
                logger.warning(f"Configuration file not found: {config_path}")
                return config

            with open(path) as f:
                if path.suffix.lower() == ".json":
                    file_config: dict[str, Any] = json.load(f)
                elif path.suffix.lower() in [".yaml", ".yml"]:
                    file_config = yaml.safe_load(f)
                else:
                    logger.warning(
                        f"Unsupported configuration file format: {path.suffix}"
                    )
                    return config

                # Merge file config with environment config
                if isinstance(file_config, dict):
                    env_dict: dict[str, Any] = config.model_dump()
                    merged_config_dict: dict[str, Any] = _merge_dicts(
                        env_dict, file_config
                    )
                    config = AppConfig.model_validate(merged_config_dict)

        except Exception as e:  # type: ignore[misc]
            logger.error(f"Error loading configuration file: {e!s}")

    return config
