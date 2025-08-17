from __future__ import annotations

import contextlib
import logging
import os
from enum import Enum
from pathlib import Path
from typing import Any, ClassVar

from pydantic import BaseModel, Field, field_validator

# Note: Avoid self-imports to prevent circular dependencies. Classes are defined below.

logger = logging.getLogger(__name__)


class LogLevel(str, Enum):
    """Log levels for configuration."""

    DEBUG = "DEBUG"
    INFO = "INFO"
    WARNING = "WARNING"
    ERROR = "ERROR"
    CRITICAL = "CRITICAL"


class BackendConfig(BaseModel):
    """Configuration for a backend service."""

    api_key: list[str] = Field(default_factory=list)
    api_url: str | None = None
    models: list[str] = Field(default_factory=list)
    timeout: int = 120  # seconds
    extra: dict[str, Any] = Field(default_factory=dict)

    @field_validator("api_url")
    @classmethod
    def validate_api_url(cls, v: str | None) -> str | None:
        """Validate the API URL if provided."""
        if v is not None and not v.startswith(("http://", "https://")):
            raise ValueError("API URL must start with http:// or https://")
        return v


class AuthConfig(BaseModel):
    """Authentication configuration."""

    disable_auth: bool = False
    api_keys: list[str] = Field(default_factory=list)
    auth_token: str | None = None
    redact_api_keys_in_prompts: bool = True


class LoggingConfig(BaseModel):
    """Logging configuration."""

    level: LogLevel = LogLevel.INFO
    request_logging: bool = False
    response_logging: bool = False
    log_file: str | None = None


class SessionConfig(BaseModel):
    """Session management configuration."""

    cleanup_enabled: bool = True
    cleanup_interval: int = 3600  # 1 hour
    max_age: int = 86400  # 1 day
    default_interactive_mode: bool = True
    force_set_project: bool = False
    disable_interactive_commands: bool = False


class BackendSettings(BaseModel):
    """Settings for all backends."""

    default_backend: str = "openai"
    openai: BackendConfig = Field(default_factory=BackendConfig)
    openrouter: BackendConfig = Field(default_factory=BackendConfig)
    anthropic: BackendConfig = Field(default_factory=BackendConfig)
    gemini: BackendConfig = Field(default_factory=BackendConfig)
    qwen_oauth: BackendConfig = Field(default_factory=BackendConfig)
    zai: BackendConfig = Field(default_factory=BackendConfig)

    @property
    def functional_backends(self) -> set[str]:
        """Get the set of functional backends (those with API keys)."""
        return {
            name
            for name, config in self.model_dump().items()
            if name != "default_backend"
            and isinstance(config, dict)
            and config.get("api_key")
        }


class AppConfig(BaseModel):
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
    AuthConfig: ClassVar[type[AuthConfig]] = AuthConfig
    LoggingConfig: ClassVar[type[LoggingConfig]] = LoggingConfig
    SessionConfig: ClassVar[type[SessionConfig]] = SessionConfig
    LogLevel: ClassVar[type[LogLevel]] = LogLevel

    # Auth settings
    auth: AuthConfig = Field(default_factory=AuthConfig)

    # Session settings
    session: SessionConfig = Field(default_factory=SessionConfig)

    # Logging settings
    logging: LoggingConfig = Field(default_factory=LoggingConfig)

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
            for backend, backend_config in self.backends.model_dump(
                exclude={"default_backend"}
            ).items():
                if isinstance(backend_config, dict):
                    config[f"{backend}_api_key"] = backend_config.get("api_key", "")
                    config[f"{backend}_api_url"] = backend_config.get("api_url", None)
                    config[f"{backend}_timeout"] = backend_config.get("timeout", 120)

                # Add any extra backend-specific settings
                for key, value in backend_config.get("extra", {}).items():
                    config[f"{backend}_{key}"] = value

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
        backends = ["openai", "openrouter", "anthropic", "gemini", "qwen_oauth", "zai"]
        for backend in backends:
            backend_config = {}

            # Extract common backend settings
            api_key = legacy_config.get(f"{backend}_api_key", "")
            if api_key:
                backend_config["api_key"] = api_key

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
                config["backends"][backend] = backend_config

        return cls(**config)

    @classmethod
    def from_env(cls) -> AppConfig:
        """Create AppConfig from environment variables.

        Returns:
            AppConfig instance
        """
        # Build configuration from environment
        config: dict[str, object] = {
            # Server settings
            "host": os.environ.get("APP_HOST", "0.0.0.0"),
            "port": int(os.environ.get("APP_PORT", "8000")),
            "proxy_timeout": int(os.environ.get("PROXY_TIMEOUT", "120")),
            "command_prefix": os.environ.get("COMMAND_PREFIX", "!/"),
            "auth": {
                "disable_auth": os.environ.get("DISABLE_AUTH", "").lower() == "true",
                "api_keys": (
                    os.environ.get("API_KEYS", "").split(",")
                    if os.environ.get("API_KEYS")
                    else []
                ),
                "auth_token": os.environ.get("AUTH_TOKEN"),
            },
            "session": {
                "cleanup_enabled": os.environ.get(
                    "SESSION_CLEANUP_ENABLED", "true"
                ).lower()
                == "true",
                "cleanup_interval": int(
                    os.environ.get("SESSION_CLEANUP_INTERVAL", "3600")
                ),
                "max_age": int(os.environ.get("SESSION_MAX_AGE", "86400")),
                "default_interactive_mode": os.environ.get(
                    "DEFAULT_INTERACTIVE_MODE", "true"
                ).lower()
                == "true",
                "force_set_project": os.environ.get("FORCE_SET_PROJECT", "").lower()
                == "true",
            },
            "logging": {
                "level": os.environ.get("LOG_LEVEL", "INFO"),
                "request_logging": os.environ.get("REQUEST_LOGGING", "").lower()
                == "true",
                "response_logging": os.environ.get("RESPONSE_LOGGING", "").lower()
                == "true",
                "log_file": os.environ.get("LOG_FILE"),
            },
            "backends": {
                "default_backend": os.environ.get("DEFAULT_BACKEND", "openai"),
            },
        }

        # Extract backend configurations from environment
        backends = ["openai", "openrouter", "anthropic", "gemini", "qwen_oauth", "zai"]
        for backend in backends:
            backend_config: dict[str, object] = {}

            api_keys = []
            main_api_key = os.environ.get(f"{backend.upper()}_API_KEY")
            if main_api_key:
                api_keys.append(main_api_key)
            for i in range(1, 21):  # Check for numbered API keys
                numbered_api_key = os.environ.get(f"{backend.upper()}_API_KEY_{i}")
                if numbered_api_key:
                    api_keys.append(numbered_api_key)
            if api_keys:
                backend_config["api_key"] = api_keys

            api_url = os.environ.get(f"{backend.upper()}_API_URL")
            if api_url:
                backend_config["api_url"] = api_url

            timeout = os.environ.get(f"{backend.upper()}_TIMEOUT")
            if timeout:
                with contextlib.suppress(ValueError):
                    backend_config["timeout"] = int(timeout)

            if backend_config:
                config_backends = config["backends"]
                assert isinstance(config_backends, dict)
                config_backends[backend] = backend_config

        return cls(**config)  # type: ignore


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
                    # Override with file config using model_copy
                    config = AppConfig.model_validate(file_config)

        except Exception as e:
            logger.error(f"Error loading configuration file: {e!s}")

    return config
