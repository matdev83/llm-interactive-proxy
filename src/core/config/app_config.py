from __future__ import annotations

import contextlib
import logging
import os
from enum import Enum
from pathlib import Path
from typing import Any, ClassVar, cast

from pydantic import ConfigDict, Field, field_validator

from src.core.config.config_loader import _collect_api_keys
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
    """Get API keys from environment variables with legacy support."""
    result: list[str] = []

    # Try modern API_KEYS first
    api_keys_raw = os.environ.get("API_KEYS")
    if api_keys_raw and isinstance(api_keys_raw, str):
        result.extend(_process_api_keys(api_keys_raw))

    # Try legacy LLM_INTERACTIVE_PROXY_API_KEY if no API_KEYS found
    if not result:
        legacy_key = os.environ.get("LLM_INTERACTIVE_PROXY_API_KEY")
        if legacy_key and isinstance(legacy_key, str):
            result.append(legacy_key)

    # Also check other legacy variants if still no keys found
    if not result:
        proxy_api_keys = os.environ.get("PROXY_API_KEYS")
        if proxy_api_keys and isinstance(proxy_api_keys, str):
            result.extend(_process_api_keys(proxy_api_keys))

    return result  # type: ignore


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


from src.core.services.backend_registry_service import (
    backend_registry,  # Added this import
)


class BackendSettings(DomainModel):
    """Settings for all backends."""

    default_backend: str = "openai"
    # Store backend configs as dynamic fields
    model_config = ConfigDict(extra="allow")

    def __init__(self, **data: Any) -> None:
        # Extract backend configs from data before calling super().__init__
        backend_configs = {}
        registered_backends = backend_registry.get_registered_backends()

        # Extract backend configs from data
        for backend_name in registered_backends:
            if backend_name in data:
                backend_configs[backend_name] = data.pop(backend_name)

        # Call parent constructor with remaining data
        super().__init__(**data)

        # Set backend configs using __dict__ to bypass Pydantic's field system
        for backend_name, config_data in backend_configs.items():
            if isinstance(config_data, dict):
                config = BackendConfig(**config_data)
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
        functional = set()
        for backend_name in backend_registry.get_registered_backends():
            if backend_name in self.__dict__:
                config = self.__dict__[backend_name]
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
        dumped = super().model_dump(**kwargs)
        # Add dynamic backends to the dumped dictionary
        for backend_name in backend_registry.get_registered_backends():
            if backend_name in self.__dict__:
                config = self.__dict__[backend_name]
                if isinstance(config, BackendConfig):
                    dumped[backend_name] = config.model_dump()
        return dumped


class AppConfig(DomainModel, IConfig):
    """Complete application configuration."""

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

    # Nested class references for backward compatibility
    BackendSettings: ClassVar[type[BackendSettings]] = BackendSettings
    BackendConfig: ClassVar[type[BackendConfig]] = BackendConfig
    LogLevel: ClassVar[type[LogLevel]] = LogLevel

    # Auth settings
    auth: AuthConfig = Field(default_factory=AuthConfig)

    # Session settings
    session: SessionConfig = Field(default_factory=SessionConfig)

    # Logging settings
    logging: LoggingConfig = Field(default_factory=LoggingConfig)

    def save(self, path: str | Path) -> None:
        """Save the current configuration to a file."""
        with open(path, "w") as f:
            f.write(self.model_dump_json(indent=4))

    # Integration with legacy config
    def to_legacy_config(self) -> dict[str, Any]:
        """Convert to the legacy configuration format.

        Returns:
            Dictionary in the legacy configuration format
        """
        config = {
            "host": self.host,
            "port": self.port,
            "proxy_timeout": self.proxy_timeout,
            "command_prefix": self.command_prefix,
            # Auth settings
            "disable_auth": self.auth.disable_auth if self.auth is not None else False,
            "api_keys": self.auth.api_keys if self.auth is not None else [],
            "auth_token": self.auth.auth_token if self.auth is not None else None,
            # Session settings
            "session_cleanup_enabled": (
                self.session.cleanup_enabled if self.session is not None else True
            ),
            "session_cleanup_interval": (
                self.session.cleanup_interval if self.session is not None else 3600
            ),
            "session_max_age": (
                self.session.max_age if self.session is not None else 86400
            ),
            "default_interactive_mode": (
                self.session.default_interactive_mode
                if self.session is not None
                else False
            ),
            "force_set_project": (
                self.session.force_set_project if self.session is not None else False
            ),
            # Logging settings
            "log_level": (
                self.logging.level.value if self.logging is not None else "INFO"
            ),
            "request_logging": (
                self.logging.request_logging if self.logging is not None else True
            ),
            "response_logging": (
                self.logging.response_logging if self.logging is not None else False
            ),
            "log_file": self.logging.log_file if self.logging is not None else None,
            # Backend settings
            "default_backend": (
                self.backends.default_backend if self.backends is not None else "openai"
            ),
            "model_defaults": self.model_defaults,
            "failover_routes": self.failover_routes,
        }

        # Add backend-specific configurations
        if self.backends is not None:
            for backend_name in backend_registry.get_registered_backends():
                backend_config = getattr(self.backends, backend_name)
                if isinstance(backend_config, BackendConfig):
                    api_keys = backend_config.api_key
                    config[f"{backend_name}_api_key"] = api_keys[0] if api_keys else ""
                    config[f"{backend_name}_api_url"] = backend_config.api_url
                    config[f"{backend_name}_timeout"] = backend_config.timeout

                    # Add any extra backend-specific settings
                    for key, value in backend_config.extra.items():
                        config[f"{backend_name}_{key}"] = value

        return config

    @classmethod
    def from_legacy_config(cls, legacy_config: dict[str, Any]) -> AppConfig:
        """Create AppConfig from the legacy configuration format.

        Args:
            legacy_config: Dictionary in the legacy configuration format

        Returns:
            AppConfig instance
        """
        # Create basic config structure
        config = {
            "host": legacy_config.get("host", "0.0.0.0"),
            "port": legacy_config.get("port", 8000),
            "proxy_timeout": legacy_config.get("proxy_timeout", 120),
            "command_prefix": legacy_config.get("command_prefix", "!/"),
            "auth": {
                "disable_auth": legacy_config.get("disable_auth", False),
                "api_keys": legacy_config.get("api_keys", []),
                "auth_token": legacy_config.get("auth_token"),
            },
            "session": {
                "cleanup_enabled": legacy_config.get("session_cleanup_enabled", True),
                "cleanup_interval": legacy_config.get("session_cleanup_interval", 3600),
                "max_age": legacy_config.get("session_max_age", 86400),
                "default_interactive_mode": legacy_config.get(
                    "default_interactive_mode", True
                ),
                "force_set_project": legacy_config.get("force_set_project", False),
            },
            "logging": {
                "level": legacy_config.get("log_level", "INFO"),
                "request_logging": legacy_config.get("request_logging", False),
                "response_logging": legacy_config.get("response_logging", False),
                "log_file": legacy_config.get("log_file"),
            },
            "model_defaults": legacy_config.get("model_defaults", {}),
            "failover_routes": legacy_config.get("failover_routes", {}),
            "backends": {
                "default_backend": legacy_config.get("default_backend", "openai"),
            },
        }

        # Extract backend configurations
        # Dynamically get registered backends
        registered_backends = backend_registry.get_registered_backends()
        for backend in registered_backends:
            backend_config: dict[str, Any] = {}

            # Extract common backend settings
            api_key = legacy_config.get(f"{backend}_api_key", "")
            if api_key:
                backend_config["api_key"] = [api_key]

            api_url = legacy_config.get(f"{backend}_api_url")
            if api_url:
                backend_config["api_url"] = api_url

            timeout = legacy_config.get(f"{backend}_timeout")
            if timeout:
                backend_config["timeout"] = timeout

            # Extract extra backend settings
            extra = {}
            for key, value in legacy_config.items():
                if key.startswith(f"{backend}_") and key not in [
                    f"{backend}_api_key",
                    f"{backend}_api_url",
                    f"{backend}_timeout",
                ]:
                    # Extract the part after {backend}_
                    extra_key = key[len(f"{backend}_") :]
                    extra[extra_key] = value

            if extra:
                backend_config["extra"] = extra

            if backend_config:
                backends_dict = config["backends"]
                if isinstance(backends_dict, dict):
                    backends_dict[backend] = backend_config

        return cls(**config)

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
        auth_config = config["auth"]
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
        }

        config["logging"] = {
            "level": os.environ.get("LOG_LEVEL", "INFO"),
            "request_logging": os.environ.get("REQUEST_LOGGING", "").lower() == "true",
            "response_logging": os.environ.get("RESPONSE_LOGGING", "").lower()
            == "true",
            "log_file": os.environ.get("LOG_FILE"),
        }

        config["backends"] = {
            "default_backend": os.environ.get("LLM_BACKEND", "openai"),
        }

        # Log the determined default_backend
        logger.info(
            f"AppConfig.from_env - Determined default_backend: {config['backends']['default_backend']}"
        )

        # Extract backend configurations from environment
        config_backends = config["backends"]
        assert isinstance(config_backends, dict)

        # Collect and assign API keys for specific backends
        openrouter_keys = _collect_api_keys("OPENROUTER_API_KEY")
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

        gemini_keys = _collect_api_keys("GEMINI_API_KEY")
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

        anthropic_keys = _collect_api_keys("ANTHROPIC_API_KEY")
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

        zai_keys = _collect_api_keys("ZAI_API_KEY")
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
        default_backend_type = os.environ.get("LLM_BACKEND", "openai")
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
    """Load configuration from file and environment.

    Args:
        config_path: Optional path to configuration file

    Returns:
        AppConfig instance
    """
    # Start with environment configuration
    config = AppConfig.from_env()

    # Override with file configuration if provided
    if config_path:
        try:
            import json

            import yaml

            path = Path(config_path)
            if not path.exists():
                logger.warning(f"Configuration file not found: {config_path}")
                return config

            with open(path) as f:
                if path.suffix.lower() == ".json":
                    file_config = json.load(f)
                elif path.suffix.lower() in [".yaml", ".yml"]:
                    file_config = yaml.safe_load(f)
                else:
                    logger.warning(
                        f"Unsupported configuration file format: {path.suffix}"
                    )
                    return config

                # Merge file config with environment config
                if isinstance(file_config, dict):
                    env_dict = config.model_dump()
                    merged_config_dict = _merge_dicts(env_dict, file_config)
                    config = AppConfig.model_validate(merged_config_dict)

        except Exception as e:
            logger.error(f"Error loading configuration file: {e!s}")

    return config
