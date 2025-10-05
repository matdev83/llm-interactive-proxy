from __future__ import annotations

import contextlib
import json
import logging
import os
from enum import Enum
from pathlib import Path
from typing import Any, cast

from pydantic import ConfigDict, Field, field_validator

from src.core.config.config_loader import _collect_api_keys
from src.core.domain.configuration.app_identity_config import AppIdentityConfig
from src.core.domain.configuration.header_config import (
    HeaderConfig,
    HeaderOverrideMode,
)
from src.core.domain.configuration.reasoning_aliases_config import (
    ReasoningAliasesConfig,
)
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


def _env_to_bool(name: str, default: bool) -> bool:
    """Return an environment variable parsed as a boolean flag."""
    value = os.environ.get(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _env_to_int(name: str, default: int) -> int:
    """Return an environment variable parsed as an integer."""
    value = os.environ.get(name)
    if value is None:
        return default
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _env_to_float(name: str, default: float | None) -> float | None:
    """Return an environment variable parsed as a float."""
    value = os.environ.get(name)
    if value is None:
        return default
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


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
    trusted_ips: list[str] = Field(default_factory=list)
    brute_force_protection: BruteForceProtectionConfig = Field(
        default_factory=lambda: BruteForceProtectionConfig()
    )


class BruteForceProtectionConfig(DomainModel):
    """Configuration for brute-force protection on API authentication."""

    enabled: bool = True
    max_failed_attempts: int = 5
    ttl_seconds: int = 900
    initial_block_seconds: int = 30
    block_multiplier: float = 2.0
    max_block_seconds: int = 3600


class LoggingConfig(DomainModel):
    """Logging configuration."""

    level: LogLevel = LogLevel.INFO
    request_logging: bool = False
    response_logging: bool = False
    log_file: str | None = None
    # Optional separate wire-capture log file; when set, all outbound requests
    # and inbound replies/SSE payloads are captured verbatim to this file.
    capture_file: str | None = None
    # Optional max size in bytes; when exceeded, rotate current capture to
    # `<capture_file>.1` and start a new file (overwrite existing .1).
    capture_max_bytes: int | None = None
    # Optional per-chunk truncation size in bytes for streaming capture. When
    # set, stream chunks written to capture are truncated to this size with a
    # short marker appended; streaming to client remains unmodified.
    capture_truncate_bytes: int | None = None
    # Optional number of rotated files to keep (e.g., file.1..file.N). If not
    # set or <= 0, keeps a single rotation (file.1). Used only when
    # capture_max_bytes is set.
    capture_max_files: int | None = None
    # Time-based rotation period in seconds (default 1 day). If set <= 0, time
    # rotation is disabled.
    capture_rotate_interval_seconds: int = 86400
    # Total disk cap across current capture file and rotated files. If set <= 0,
    # disabled. Default is 100 MiB.
    capture_total_max_bytes: int = 104857600
    # Buffer size for wire capture writes (bytes). Default 64KB.
    capture_buffer_size: int = 65536
    # How often to flush buffer to disk (seconds). Default 1.0 second.
    capture_flush_interval: float = 1.0
    # Maximum entries to buffer before forcing flush. Default 100.
    capture_max_entries_per_flush: int = 100


class ToolCallReactorConfig(DomainModel):
    """Configuration for the Tool Call Reactor system.

    The Tool Call Reactor provides event-driven reactions to tool calls
    from LLMs, allowing custom handlers to monitor, modify, or replace responses.
    """

    enabled: bool = True
    """Whether the Tool Call Reactor is enabled."""

    apply_diff_steering_enabled: bool = True
    """Whether the legacy apply_diff steering handler is enabled."""

    apply_diff_steering_rate_limit_seconds: int = 60
    """Legacy rate limit window for apply_diff steering in seconds.

    Controls how often steering messages are shown for apply_diff tool calls
    within the same session. Default: 60 seconds (1 message per minute).
    """

    apply_diff_steering_message: str | None = None
    """Legacy custom steering message for apply_diff tool calls.

    If None, uses the default message. Can be customized to fit your workflow.
    """

    # New: fully configurable steering rules
    steering_rules: list[dict[str, Any]] = Field(default_factory=list)
    """Configurable steering rules.

    Each rule is a dict describing when to trigger steering and what message to
    return. See README for details. Minimal fields:
      - name: Unique rule name
      - enabled: bool
      - triggers: { tool_names: [..], phrases: [..] }
      - message: Replacement content when swallowed
      - rate_limit: { calls_per_window: int, window_seconds: int }
      - priority: int (optional; higher runs first)
    """


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
    json_repair_enabled: bool = True
    # Max per-session buffer for JSON repair streaming (bytes)
    json_repair_buffer_cap_bytes: int = 64 * 1024
    json_repair_strict_mode: bool = False
    json_repair_schema: dict[str, Any] | None = None  # Added
    tool_call_reactor: ToolCallReactorConfig = Field(
        default_factory=ToolCallReactorConfig
    )
    dangerous_command_prevention_enabled: bool = True
    dangerous_command_steering_message: str | None = None
    pytest_compression_enabled: bool = True
    pytest_compression_min_lines: int = 30


class EmptyResponseConfig(DomainModel):
    """Configuration for empty response handling."""

    enabled: bool = True
    """Whether the empty response recovery is enabled."""

    max_retries: int = 1
    """Maximum number of retries for empty responses."""


class RewritingConfig(DomainModel):
    """Configuration for content rewriting."""

    enabled: bool = False
    config_path: str = "config/replacements"


class EditPrecisionConfig(DomainModel):
    """Configuration for automated edit-precision tuning.

    When enabled, detects agent edit-failure prompts and lowers sampling
    parameters for the next single call to improve precision.
    """

    enabled: bool = True
    temperature: float = 0.1
    # Only applied if override_top_p is True; otherwise top_p remains unchanged
    min_top_p: float | None = 0.3
    # Control whether top_p/top_k are overridden by this feature
    override_top_p: bool = False
    override_top_k: bool = False
    # Target top_k to apply when override_top_k is True (for providers that support it, e.g., Gemini)
    target_top_k: int | None = None
    # Optional regex pattern; when set, agents with names matching this pattern
    # will be excluded (feature disabled) even if enabled=True.
    exclude_agents_regex: str | None = None


from src.core.services.backend_registry import (
    backend_registry,  # Updated import path
)


class BackendSettings(DomainModel):
    """Settings for all backends."""

    default_backend: str = "openai"
    static_route: str | None = (
        None  # Force all requests to backend:model (e.g., "gemini-cli-oauth-personal:gemini-2.5-pro")
    )
    # Store backend configs as dynamic fields
    model_config = ConfigDict(extra="allow")

    def __init__(self, **data: Any) -> None:
        # Extract backend configs from data before calling super().__init__
        backend_configs: dict[str, Any] = {}
        # Keep a copy of remaining data to capture non-registered backends too
        remaining_data = dict(data)
        registered_backends: list[str] = backend_registry.get_registered_backends()

        # Extract backend configs from data
        for backend_name in registered_backends:
            if backend_name in data:
                backend_configs[backend_name] = data.pop(backend_name)
                # Also remove from remaining_data
                remaining_data.pop(backend_name, None)

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

        # Finally, absorb any non-registered backend configs that were provided via env/file
        # so that attribute access like config.backends.openai works even if
        # connectors haven't been imported yet (empty registry).
        for key, value in remaining_data.items():
            if key == "default_backend" or key.startswith("_"):
                continue
            if isinstance(value, dict):
                self.__dict__[key] = BackendConfig(**value)
            elif isinstance(value, BackendConfig):
                self.__dict__[key] = value

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
        registered = backend_registry.get_registered_backends()
        for backend_name in registered:
            if backend_name in self.__dict__:
                config: Any = self.__dict__[backend_name]
                if isinstance(config, BackendConfig) and config.api_key:
                    functional.add(backend_name)

        # Consider OAuth-style backends functional even without an api_key in config,
        # since they source credentials from local auth stores (e.g., CLI-managed files).
        oauth_like: set[str] = set()
        for name in registered:
            if name.endswith("-oauth") or name.startswith("gemini-cli-oauth"):
                oauth_like.add(name)
            if name == "gemini-cli-cloud-project":
                oauth_like.add(name)

        functional.update(oauth_like.intersection(set(registered)))

        # Include any dynamically added backends present in __dict__ that have api_key
        # (used in tests and when users add custom backends not in the registry).
        for name, cfg in getattr(self, "__dict__", {}).items():
            if (
                name == "default_backend"
                or name.startswith("_")
                or not isinstance(cfg, BackendConfig)
            ):
                continue
            if cfg.api_key:
                functional.add(name)
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

        # Avoid creating configs for private/internal attributes to maintain security
        if name.startswith(("_", "__")):
            raise AttributeError(
                f"'{self.__class__.__name__}' object has no attribute '{name}'"
            )

        # Lazily create a default backend configuration for unknown backends.
        # This allows accessing backend configs without pre-registration while
        # maintaining backward compatibility. Created configs are cached for
        # subsequent access to avoid creating multiple instances.
        config = BackendConfig()
        self.__dict__[name] = config
        return config

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
    anthropic_port: int | None = None  # Will be set to port + 1 if not provided
    proxy_timeout: int = 120
    command_prefix: str = "!/"
    context_window_override: int | None = None  # Override context window for all models

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

    # Edit-precision tuning settings
    edit_precision: EditPrecisionConfig = Field(default_factory=EditPrecisionConfig)

    # Rewriting settings
    rewriting: RewritingConfig = Field(default_factory=RewritingConfig)

    # Reasoning aliases settings
    reasoning_aliases: ReasoningAliasesConfig = Field(
        default_factory=lambda: ReasoningAliasesConfig(reasoning_alias_settings=[])
    )

    # FastAPI app instance
    app: Any = None

    def save(self, path: str | Path) -> None:
        """Save the current configuration to a file."""
        p = Path(path)
        data = self.model_dump(mode="json")
        if p.suffix.lower() in {".yaml", ".yml"}:
            import yaml

            with p.open("w", encoding="utf-8") as f:
                yaml.safe_dump(data, f, sort_keys=False)
        else:
            # Legacy: still allow JSON save if requested by extension
            with p.open("w", encoding="utf-8") as f:
                f.write(self.model_dump_json(indent=4))

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
            "anthropic_port": int(os.environ.get("ANTHROPIC_PORT") or 0)
            or (int(os.environ.get("APP_PORT", "8000")) + 1),
            "proxy_timeout": int(os.environ.get("PROXY_TIMEOUT", "120")),
            "command_prefix": os.environ.get("COMMAND_PREFIX", "!/"),
            "auth": {
                "disable_auth": os.environ.get("DISABLE_AUTH", "").lower() == "true",
                "api_keys": _get_api_keys_from_env(),
                "auth_token": os.environ.get("AUTH_TOKEN"),
                "brute_force_protection": {
                    "enabled": _env_to_bool("BRUTE_FORCE_PROTECTION_ENABLED", True),
                    "max_failed_attempts": _env_to_int(
                        "BRUTE_FORCE_MAX_FAILED_ATTEMPTS", 5
                    ),
                    "ttl_seconds": _env_to_int("BRUTE_FORCE_TTL_SECONDS", 900),
                    "initial_block_seconds": _env_to_int(
                        "BRUTE_FORCE_INITIAL_BLOCK_SECONDS", 30
                    ),
                    "block_multiplier": _env_to_float(
                        "BRUTE_FORCE_BLOCK_MULTIPLIER", 2.0
                    ),
                    "max_block_seconds": _env_to_int(
                        "BRUTE_FORCE_MAX_BLOCK_SECONDS", 3600
                    ),
                },
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
            "json_repair_enabled": os.environ.get("JSON_REPAIR_ENABLED", "true").lower()
            == "true",
            # Optional cap for streaming repair buffer
            "json_repair_buffer_cap_bytes": (
                int(os.environ.get("JSON_REPAIR_BUFFER_CAP_BYTES", "65536"))
                if os.environ.get("JSON_REPAIR_BUFFER_CAP_BYTES")
                else 65536
            ),
            "json_repair_schema": json.loads(
                os.environ.get("JSON_REPAIR_SCHEMA", "null")
            ),  # Added
            "dangerous_command_prevention_enabled": os.environ.get(
                "DANGEROUS_COMMAND_PREVENTION_ENABLED", "true"
            ).lower()
            == "true",
            "dangerous_command_steering_message": os.environ.get(
                "DANGEROUS_COMMAND_STEERING_MESSAGE"
            ),
            "pytest_compression_enabled": os.environ.get(
                "PYTEST_COMPRESSION_ENABLED", "true"
            ).lower()
            == "true",
            "pytest_compression_min_lines": int(
                os.environ.get("PYTEST_COMPRESSION_MIN_LINES", "30")
            ),
        }

        config["logging"] = {
            "level": os.environ.get("LOG_LEVEL", "INFO"),
            "request_logging": os.environ.get("REQUEST_LOGGING", "").lower() == "true",
            "response_logging": os.environ.get("RESPONSE_LOGGING", "").lower()
            == "true",
            "log_file": os.environ.get("LOG_FILE"),
            # Optional wire-capture file (disabled by default)
            "capture_file": os.environ.get("CAPTURE_FILE"),
            # Optional rotation/truncation
            "capture_max_bytes": (
                int(os.environ.get("CAPTURE_MAX_BYTES", "0"))
                if os.environ.get("CAPTURE_MAX_BYTES")
                else None
            ),
            "capture_truncate_bytes": (
                int(os.environ.get("CAPTURE_TRUNCATE_BYTES", "0"))
                if os.environ.get("CAPTURE_TRUNCATE_BYTES")
                else None
            ),
            "capture_max_files": (
                int(os.environ.get("CAPTURE_MAX_FILES", "0"))
                if os.environ.get("CAPTURE_MAX_FILES")
                else None
            ),
            "capture_rotate_interval_seconds": (
                int(os.environ.get("CAPTURE_ROTATE_INTERVAL_SECONDS", "86400"))
            ),
            "capture_total_max_bytes": (
                int(os.environ.get("CAPTURE_TOTAL_MAX_BYTES", "104857600"))
            ),
            "capture_buffer_size": (
                int(os.environ.get("CAPTURE_BUFFER_SIZE", "65536"))
            ),
            "capture_flush_interval": (
                float(os.environ.get("CAPTURE_FLUSH_INTERVAL", "1.0"))
            ),
            "capture_max_entries_per_flush": (
                int(os.environ.get("CAPTURE_MAX_ENTRIES_PER_FLUSH", "100"))
            ),
        }

        config["empty_response"] = {
            "enabled": os.environ.get("EMPTY_RESPONSE_HANDLING_ENABLED", "true").lower()
            == "true",
            "max_retries": int(os.environ.get("EMPTY_RESPONSE_MAX_RETRIES", "1")),
        }

        # Edit precision settings
        config["edit_precision"] = {
            "enabled": _env_to_bool("EDIT_PRECISION_ENABLED", True),
            "temperature": _env_to_float("EDIT_PRECISION_TEMPERATURE", 0.1) or 0.1,
            "min_top_p": _env_to_float("EDIT_PRECISION_MIN_TOP_P", 0.3),
            "override_top_p": _env_to_bool("EDIT_PRECISION_OVERRIDE_TOP_P", False),
            "override_top_k": _env_to_bool("EDIT_PRECISION_OVERRIDE_TOP_K", False),
            "target_top_k": (
                int(os.environ.get("EDIT_PRECISION_TARGET_TOP_K", "0")) or None
            ),
            "exclude_agents_regex": os.environ.get(
                "EDIT_PRECISION_EXCLUDE_AGENTS_REGEX"
            ),
        }

        config["rewriting"] = {
            "enabled": _env_to_bool("REWRITING_ENABLED", False),
            "config_path": os.environ.get(
                "REWRITING_CONFIG_PATH", "config/replacements"
            ),
        }

        config["backends"] = {
            "default_backend": os.environ.get("LLM_BACKEND", "openai")
        }

        config["identity"] = AppIdentityConfig(
            title=HeaderConfig(
                override_value=os.environ.get("APP_TITLE"),
                mode=HeaderOverrideMode(
                    os.environ.get("APP_TITLE_MODE", "passthrough")
                ),
                default_value="llm-interactive-proxy",
                passthrough_name="x-title",
            ),
            url=HeaderConfig(
                override_value=os.environ.get("APP_URL"),
                mode=HeaderOverrideMode(os.environ.get("APP_URL_MODE", "passthrough")),
                default_value="https://github.com/matdev83/llm-interactive-proxy",
                passthrough_name="http-referer",
            ),
            user_agent=HeaderConfig(
                override_value=os.environ.get("APP_USER_AGENT"),
                mode=HeaderOverrideMode(
                    os.environ.get("APP_USER_AGENT_MODE", "passthrough")
                ),
                default_value="llm-interactive-proxy",
                passthrough_name="user-agent",
            ),
        )

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

        openai_keys: dict[str, str] = _collect_api_keys("OPENAI_API_KEY")
        if openai_keys:
            config_backends["openai"] = config_backends.get("openai", {})
            config_backends["openai"]["api_key"] = list(openai_keys.values())
            config_backends["openai"]["api_url"] = os.environ.get(
                "OPENAI_API_BASE_URL", "https://api.openai.com/v1"
            )
            if os.environ.get("OPENAI_TIMEOUT"):
                with contextlib.suppress(ValueError):
                    config_backends["openai"]["timeout"] = int(
                        os.environ.get("OPENAI_TIMEOUT", "0")
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

            import yaml

            path: Path = Path(config_path)
            if not path.exists():
                logger.warning(f"Configuration file not found: {config_path}")
                return config

            # YAML-only configuration files
            if path.suffix.lower() not in [".yaml", ".yml"]:
                raise ValueError(
                    f"Unsupported configuration file format: {path.suffix}. Use YAML (.yaml/.yml)."
                )

            with open(path, encoding="utf-8") as f:
                file_config: dict[str, Any] = yaml.safe_load(f)

            # Validate against schema for helpful diagnostics
            try:
                from pathlib import Path as _Path

                from src.core.config.semantic_validation import (
                    validate_config_semantics,
                )
                from src.core.config.yaml_validation import validate_yaml_against_schema

                schema_path = (
                    _Path.cwd() / "config" / "schemas" / "app_config.schema.yaml"
                )
                # First validate JSON schema
                validate_yaml_against_schema(_Path(path), schema_path)

                # Then validate semantic correctness
                validate_config_semantics(file_config, path)

            except Exception as _ex:  # pragma: no cover
                logger.critical("Config validation failed for %s: %s", str(path), _ex)
                raise

            # Merge file config with environment defaults, preferring file values
            if isinstance(file_config, dict):
                env_dict: dict[str, Any] = config.model_dump()

                def _merge_missing(
                    dst: dict[str, Any], src: dict[str, Any]
                ) -> dict[str, Any]:
                    for k, v in src.items():
                        if k in dst:
                            if isinstance(dst[k], dict) and isinstance(v, dict):
                                _merge_missing(dst[k], v)
                            # else: keep dst value (from file)
                        else:
                            dst[k] = v
                    return dst

                merged_config_dict: dict[str, Any] = _merge_missing(
                    dict(file_config), env_dict
                )
                config = AppConfig.model_validate(merged_config_dict)

        except Exception as e:  # type: ignore[misc]
            logger.critical(f"Error loading configuration file: {e!s}")
            raise

    return config
