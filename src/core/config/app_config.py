from __future__ import annotations

import json
import logging
import os
from collections.abc import Callable, Mapping
from enum import Enum
from pathlib import Path
from typing import Any, cast

from pydantic import ConfigDict, Field, field_validator, model_validator

from src.core.config.config_loader import _collect_api_keys
from src.core.config.parameter_resolution import ParameterResolution, ParameterSource
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


def _get_api_keys_from_env(
    env: Mapping[str, str], resolution: ParameterResolution | None = None
) -> list[str]:
    """Get API keys from environment variables."""
    result: list[str] = []

    # Get API keys from API_KEYS environment variable
    api_keys_raw: str | None = env.get("API_KEYS")
    if api_keys_raw and isinstance(api_keys_raw, str):
        result.extend(_process_api_keys(api_keys_raw))

    if result and resolution is not None:
        resolution.record(
            "auth.api_keys",
            result,
            ParameterSource.ENVIRONMENT,
            origin="API_KEYS",
        )

    return result


def _env_to_bool(
    name: str,
    default: bool,
    env: Mapping[str, str],
    *,
    path: str | None = None,
    resolution: ParameterResolution | None = None,
) -> bool:
    """Return an environment variable parsed as a boolean flag."""
    value = env.get(name)
    if value is None:
        return default
    result = value.strip().lower() in {"1", "true", "yes", "on"}
    if resolution is not None and path is not None:
        resolution.record(path, result, ParameterSource.ENVIRONMENT, origin=name)
    return result


def _env_to_int(
    name: str,
    default: int,
    env: Mapping[str, str],
    *,
    path: str | None = None,
    resolution: ParameterResolution | None = None,
) -> int:
    """Return an environment variable parsed as an integer."""
    value = env.get(name)
    if value is None:
        return default
    try:
        result = int(value)
    except (TypeError, ValueError):
        result = default
    if resolution is not None and path is not None and value is not None:
        resolution.record(path, result, ParameterSource.ENVIRONMENT, origin=name)
    return result


def _env_to_float(
    name: str,
    default: float,
    env: Mapping[str, str],
    *,
    path: str | None = None,
    resolution: ParameterResolution | None = None,
) -> float:
    """Return an environment variable parsed as a float."""
    value = env.get(name)
    if value is None:
        return default
    try:
        result = float(value)
    except (TypeError, ValueError):
        result = default
    if resolution is not None and path is not None and value is not None:
        resolution.record(path, result, ParameterSource.ENVIRONMENT, origin=name)
    return result


def _get_env_value(
    env: Mapping[str, str],
    name: str,
    default: Any,
    *,
    path: str,
    resolution: ParameterResolution | None = None,
    transform: Callable[[str], Any] | None = None,
) -> Any:
    """Return an environment variable value and optionally record its source."""

    if name in env:
        raw_value = env[name]
        value = transform(raw_value) if transform is not None else raw_value
        if resolution is not None:
            resolution.record(path, value, ParameterSource.ENVIRONMENT, origin=name)
        return value
    return default


def _to_int(value: str, fallback: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return fallback


def _to_float(value: str, fallback: float | None) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return fallback


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

    pytest_full_suite_steering_enabled: bool = False
    """Whether steering for full pytest suite commands is enabled."""

    pytest_full_suite_steering_message: str | None = None
    """Optional custom steering message when detecting full pytest suite runs."""

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


class PlanningPhaseConfig(DomainModel):
    """Configuration for planning phase model routing."""

    enabled: bool = False
    strong_model: str | None = None
    max_turns: int = 10
    max_file_writes: int = 1
    # Optional parameter overrides for the strong model
    overrides: dict[str, Any] | None = None


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
    pytest_full_suite_steering_enabled: bool | None = None
    pytest_full_suite_steering_message: str | None = None
    planning_phase: PlanningPhaseConfig = Field(default_factory=PlanningPhaseConfig)

    @model_validator(mode="after")
    def _sync_pytest_full_suite_settings(self) -> SessionConfig:
        """Keep pytest full-suite steering settings mirrored with reactor config."""
        if self.pytest_full_suite_steering_enabled is not None:
            self.tool_call_reactor.pytest_full_suite_steering_enabled = (
                self.pytest_full_suite_steering_enabled
            )
        else:
            self.pytest_full_suite_steering_enabled = (
                self.tool_call_reactor.pytest_full_suite_steering_enabled
            )

        if self.pytest_full_suite_steering_message is not None:
            self.tool_call_reactor.pytest_full_suite_steering_message = (
                self.pytest_full_suite_steering_message
            )
        else:
            self.pytest_full_suite_steering_message = (
                self.tool_call_reactor.pytest_full_suite_steering_message
            )

        return self


class EmptyResponseConfig(DomainModel):
    """Configuration for empty response handling."""

    enabled: bool = True
    """Whether the empty response recovery is enabled."""

    max_retries: int = 1
    """Maximum number of retries for empty responses."""


class ModelAliasRule(DomainModel):
    """A rule for rewriting a model name."""

    pattern: str
    replacement: str


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

    def __setattr__(self, name: str, value: Any) -> None:
        """Allow attribute-style assignment for backend configs."""
        if (
            name in {"default_backend"}
            or name.startswith("_")
            or name in self.model_fields
        ):
            super().__setattr__(name, value)
            return
        if isinstance(value, BackendConfig):
            config = value
        elif isinstance(value, dict):
            config = BackendConfig(**value)
        else:
            config = BackendConfig()
        self.__dict__[name] = config

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
    strict_command_detection: bool = False
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

    # Model name rewrite rules
    model_aliases: list[ModelAliasRule] = Field(default_factory=list)

    # FastAPI app instance
    app: Any = None

    def save(self, path: str | Path) -> None:
        """Save the current configuration to a file."""
        p = Path(path)
        data = self.model_dump(mode="json", exclude_none=True)
        # Normalize structure to match schema expectations
        # - default_backend must be at top-level (already present)
        # - Remove runtime-only fields that are not part of schema or can cause validation errors
        for runtime_key in ["app"]:
            if runtime_key in data:
                data[runtime_key] = None
        # Filter out unsupported top-level keys (schema has additionalProperties: false)
        allowed_top_keys = {
            "host",
            "port",
            "anthropic_port",
            "proxy_timeout",
            "command_prefix",
            "strict_command_detection",
            "context_window_override",
            "default_rate_limit",
            "default_rate_window",
            "model_defaults",
            "failover_routes",
            "identity",
            "empty_response",
            "edit_precision",
            "rewriting",
            "app",
            "logging",
            "auth",
            "session",
            "backends",
            "default_backend",
            "reasoning_aliases",
            "model_aliases",
        }
        data = {k: v for k, v in data.items() if k in allowed_top_keys}
        # Ensure nested sections only include serializable primitives
        # (model_dump already handles pydantic models)
        if p.suffix.lower() in {".yaml", ".yml"}:
            import yaml

            with p.open("w", encoding="utf-8") as f:
                yaml.safe_dump(data, f, sort_keys=False)
        else:
            # Legacy: still allow JSON save if requested by extension
            with p.open("w", encoding="utf-8") as f:
                f.write(self.model_dump_json(indent=4))

    @classmethod
    def from_env(
        cls,
        *,
        environ: Mapping[str, str] | None = None,
        resolution: ParameterResolution | None = None,
    ) -> AppConfig:
        """Create AppConfig from environment variables.

        Returns:
            AppConfig instance
        """
        env: Mapping[str, str] = environ or os.environ

        # Build configuration from environment
        config: dict[str, Any] = {
            # Server settings
            "host": _get_env_value(
                env,
                "APP_HOST",
                "0.0.0.0",
                path="host",
                resolution=resolution,
            ),
            "port": _get_env_value(
                env,
                "APP_PORT",
                8000,
                path="port",
                resolution=resolution,
                transform=lambda value: _to_int(value, 8000),
            ),
            "anthropic_port": _get_env_value(
                env,
                "ANTHROPIC_PORT",
                None,
                path="anthropic_port",
                resolution=resolution,
                transform=lambda value: _to_int(value, 0) if value else None,
            ),
            "proxy_timeout": _get_env_value(
                env,
                "PROXY_TIMEOUT",
                120,
                path="proxy_timeout",
                resolution=resolution,
                transform=lambda value: _to_int(value, 120),
            ),
            "command_prefix": _get_env_value(
                env,
                "COMMAND_PREFIX",
                "!/",
                path="command_prefix",
                resolution=resolution,
            ),
            "auth": {
                "disable_auth": _env_to_bool(
                    "DISABLE_AUTH",
                    False,
                    env,
                    path="auth.disable_auth",
                    resolution=resolution,
                ),
                "api_keys": _get_api_keys_from_env(env, resolution),
                "auth_token": _get_env_value(
                    env,
                    "AUTH_TOKEN",
                    None,
                    path="auth.auth_token",
                    resolution=resolution,
                ),
                "brute_force_protection": {
                    "enabled": _env_to_bool(
                        "BRUTE_FORCE_PROTECTION_ENABLED",
                        True,
                        env,
                        path="auth.brute_force_protection.enabled",
                        resolution=resolution,
                    ),
                    "max_failed_attempts": _env_to_int(
                        "BRUTE_FORCE_MAX_FAILED_ATTEMPTS",
                        5,
                        env,
                        path="auth.brute_force_protection.max_failed_attempts",
                        resolution=resolution,
                    ),
                    "ttl_seconds": _env_to_int(
                        "BRUTE_FORCE_TTL_SECONDS",
                        900,
                        env,
                        path="auth.brute_force_protection.ttl_seconds",
                        resolution=resolution,
                    ),
                    "initial_block_seconds": _env_to_int(
                        "BRUTE_FORCE_INITIAL_BLOCK_SECONDS",
                        30,
                        env,
                        path="auth.brute_force_protection.initial_block_seconds",
                        resolution=resolution,
                    ),
                    "block_multiplier": _env_to_float(
                        "BRUTE_FORCE_BLOCK_MULTIPLIER",
                        2.0,
                        env,
                        path="auth.brute_force_protection.block_multiplier",
                        resolution=resolution,
                    ),
                    "max_block_seconds": _env_to_int(
                        "BRUTE_FORCE_MAX_BLOCK_SECONDS",
                        3600,
                        env,
                        path="auth.brute_force_protection.max_block_seconds",
                        resolution=resolution,
                    ),
                },
            },
        }

        if not config.get("anthropic_port"):
            config["anthropic_port"] = int(config["port"]) + 1
            if resolution is not None:
                resolution.record(
                    "anthropic_port",
                    config["anthropic_port"],
                    ParameterSource.DERIVED,
                    origin="port+1",
                )

        # After populating auth config, if disable_auth is true, clear api_keys
        auth_config: dict[str, Any] = config["auth"]
        if isinstance(auth_config, dict) and auth_config.get("disable_auth"):
            auth_config["api_keys"] = []

        # Add session, logging, and backend config
        planning_overrides: dict[str, Any] = {}
        planning_temperature = _get_env_value(
            env,
            "PLANNING_PHASE_TEMPERATURE",
            None,
            path="session.planning_phase.overrides.temperature",
            resolution=resolution,
            transform=lambda value: _to_float(value, None),
        )
        if planning_temperature is not None:
            planning_overrides["temperature"] = planning_temperature

        planning_top_p = _get_env_value(
            env,
            "PLANNING_PHASE_TOP_P",
            None,
            path="session.planning_phase.overrides.top_p",
            resolution=resolution,
            transform=lambda value: _to_float(value, None),
        )
        if planning_top_p is not None:
            planning_overrides["top_p"] = planning_top_p

        planning_reasoning = _get_env_value(
            env,
            "PLANNING_PHASE_REASONING_EFFORT",
            None,
            path="session.planning_phase.overrides.reasoning_effort",
            resolution=resolution,
        )
        if planning_reasoning is not None:
            planning_overrides["reasoning_effort"] = planning_reasoning

        planning_budget = _get_env_value(
            env,
            "PLANNING_PHASE_THINKING_BUDGET",
            None,
            path="session.planning_phase.overrides.thinking_budget",
            resolution=resolution,
            transform=lambda value: _to_int(value, 0),
        )
        if planning_budget is not None:
            planning_overrides["thinking_budget"] = planning_budget

        config["session"] = {
            "cleanup_enabled": _env_to_bool(
                "SESSION_CLEANUP_ENABLED",
                True,
                env,
                path="session.cleanup_enabled",
                resolution=resolution,
            ),
            "cleanup_interval": _env_to_int(
                "SESSION_CLEANUP_INTERVAL",
                3600,
                env,
                path="session.cleanup_interval",
                resolution=resolution,
            ),
            "max_age": _env_to_int(
                "SESSION_MAX_AGE",
                86400,
                env,
                path="session.max_age",
                resolution=resolution,
            ),
            "default_interactive_mode": _env_to_bool(
                "DEFAULT_INTERACTIVE_MODE",
                True,
                env,
                path="session.default_interactive_mode",
                resolution=resolution,
            ),
            "force_set_project": _env_to_bool(
                "FORCE_SET_PROJECT",
                False,
                env,
                path="session.force_set_project",
                resolution=resolution,
            ),
            "tool_call_repair_enabled": _env_to_bool(
                "TOOL_CALL_REPAIR_ENABLED",
                True,
                env,
                path="session.tool_call_repair_enabled",
                resolution=resolution,
            ),
            "tool_call_repair_buffer_cap_bytes": _get_env_value(
                env,
                "TOOL_CALL_REPAIR_BUFFER_CAP_BYTES",
                65536,
                path="session.tool_call_repair_buffer_cap_bytes",
                resolution=resolution,
                transform=lambda value: _to_int(value, 65536),
            ),
            "json_repair_enabled": _env_to_bool(
                "JSON_REPAIR_ENABLED",
                True,
                env,
                path="session.json_repair_enabled",
                resolution=resolution,
            ),
            "json_repair_buffer_cap_bytes": _get_env_value(
                env,
                "JSON_REPAIR_BUFFER_CAP_BYTES",
                65536,
                path="session.json_repair_buffer_cap_bytes",
                resolution=resolution,
                transform=lambda value: _to_int(value, 65536),
            ),
            "json_repair_schema": _get_env_value(
                env,
                "JSON_REPAIR_SCHEMA",
                None,
                path="session.json_repair_schema",
                resolution=resolution,
                transform=lambda value: json.loads(value),
            ),
            "dangerous_command_prevention_enabled": _env_to_bool(
                "DANGEROUS_COMMAND_PREVENTION_ENABLED",
                True,
                env,
                path="session.dangerous_command_prevention_enabled",
                resolution=resolution,
            ),
            "dangerous_command_steering_message": _get_env_value(
                env,
                "DANGEROUS_COMMAND_STEERING_MESSAGE",
                None,
                path="session.dangerous_command_steering_message",
                resolution=resolution,
            ),
            "pytest_compression_enabled": _env_to_bool(
                "PYTEST_COMPRESSION_ENABLED",
                True,
                env,
                path="session.pytest_compression_enabled",
                resolution=resolution,
            ),
            "pytest_compression_min_lines": _env_to_int(
                "PYTEST_COMPRESSION_MIN_LINES",
                30,
                env,
                path="session.pytest_compression_min_lines",
                resolution=resolution,
            ),
            "pytest_full_suite_steering_enabled": _env_to_bool(
                "PYTEST_FULL_SUITE_STEERING_ENABLED",
                False,
                env,
                path="session.pytest_full_suite_steering_enabled",
                resolution=resolution,
            ),
            "pytest_full_suite_steering_message": _get_env_value(
                env,
                "PYTEST_FULL_SUITE_STEERING_MESSAGE",
                None,
                path="session.pytest_full_suite_steering_message",
                resolution=resolution,
            ),
            "planning_phase": {
                "enabled": _env_to_bool(
                    "PLANNING_PHASE_ENABLED",
                    False,
                    env,
                    path="session.planning_phase.enabled",
                    resolution=resolution,
                ),
                "strong_model": _get_env_value(
                    env,
                    "PLANNING_PHASE_STRONG_MODEL",
                    None,
                    path="session.planning_phase.strong_model",
                    resolution=resolution,
                ),
                "max_turns": _env_to_int(
                    "PLANNING_PHASE_MAX_TURNS",
                    10,
                    env,
                    path="session.planning_phase.max_turns",
                    resolution=resolution,
                ),
                "max_file_writes": _env_to_int(
                    "PLANNING_PHASE_MAX_FILE_WRITES",
                    1,
                    env,
                    path="session.planning_phase.max_file_writes",
                    resolution=resolution,
                ),
                "overrides": planning_overrides,
            },
        }

        config["logging"] = {
            "level": _get_env_value(
                env,
                "LOG_LEVEL",
                "INFO",
                path="logging.level",
                resolution=resolution,
            ),
            "request_logging": _env_to_bool(
                "REQUEST_LOGGING",
                False,
                env,
                path="logging.request_logging",
                resolution=resolution,
            ),
            "response_logging": _env_to_bool(
                "RESPONSE_LOGGING",
                False,
                env,
                path="logging.response_logging",
                resolution=resolution,
            ),
            "log_file": _get_env_value(
                env,
                "LOG_FILE",
                None,
                path="logging.log_file",
                resolution=resolution,
            ),
            "capture_file": _get_env_value(
                env,
                "CAPTURE_FILE",
                None,
                path="logging.capture_file",
                resolution=resolution,
            ),
            "capture_max_bytes": _get_env_value(
                env,
                "CAPTURE_MAX_BYTES",
                None,
                path="logging.capture_max_bytes",
                resolution=resolution,
                transform=lambda value: _to_int(value, 0),
            ),
            "capture_truncate_bytes": _get_env_value(
                env,
                "CAPTURE_TRUNCATE_BYTES",
                None,
                path="logging.capture_truncate_bytes",
                resolution=resolution,
                transform=lambda value: _to_int(value, 0),
            ),
            "capture_max_files": _get_env_value(
                env,
                "CAPTURE_MAX_FILES",
                None,
                path="logging.capture_max_files",
                resolution=resolution,
                transform=lambda value: _to_int(value, 0),
            ),
            "capture_rotate_interval_seconds": _get_env_value(
                env,
                "CAPTURE_ROTATE_INTERVAL_SECONDS",
                86400,
                path="logging.capture_rotate_interval_seconds",
                resolution=resolution,
                transform=lambda value: _to_int(value, 86400),
            ),
            "capture_total_max_bytes": _get_env_value(
                env,
                "CAPTURE_TOTAL_MAX_BYTES",
                104857600,
                path="logging.capture_total_max_bytes",
                resolution=resolution,
                transform=lambda value: _to_int(value, 104857600),
            ),
            "capture_buffer_size": _get_env_value(
                env,
                "CAPTURE_BUFFER_SIZE",
                65536,
                path="logging.capture_buffer_size",
                resolution=resolution,
                transform=lambda value: _to_int(value, 65536),
            ),
            "capture_flush_interval": _get_env_value(
                env,
                "CAPTURE_FLUSH_INTERVAL",
                1.0,
                path="logging.capture_flush_interval",
                resolution=resolution,
                transform=lambda value: _to_float(value, 1.0),
            ),
            "capture_max_entries_per_flush": _get_env_value(
                env,
                "CAPTURE_MAX_ENTRIES_PER_FLUSH",
                100,
                path="logging.capture_max_entries_per_flush",
                resolution=resolution,
                transform=lambda value: _to_int(value, 100),
            ),
        }

        config["empty_response"] = {
            "enabled": _env_to_bool(
                "EMPTY_RESPONSE_HANDLING_ENABLED",
                True,
                env,
                path="empty_response.enabled",
                resolution=resolution,
            ),
            "max_retries": _env_to_int(
                "EMPTY_RESPONSE_MAX_RETRIES",
                1,
                env,
                path="empty_response.max_retries",
                resolution=resolution,
            ),
        }

        # Edit precision settings
        config["edit_precision"] = {
            "enabled": _env_to_bool(
                "EDIT_PRECISION_ENABLED",
                True,
                env,
                path="edit_precision.enabled",
                resolution=resolution,
            ),
            "temperature": _env_to_float(
                "EDIT_PRECISION_TEMPERATURE",
                0.1,
                env,
                path="edit_precision.temperature",
                resolution=resolution,
            ),
            "min_top_p": _env_to_float(
                "EDIT_PRECISION_MIN_TOP_P",
                0.3,
                env,
                path="edit_precision.min_top_p",
                resolution=resolution,
            ),
            "override_top_p": _env_to_bool(
                "EDIT_PRECISION_OVERRIDE_TOP_P",
                False,
                env,
                path="edit_precision.override_top_p",
                resolution=resolution,
            ),
            "override_top_k": _env_to_bool(
                "EDIT_PRECISION_OVERRIDE_TOP_K",
                False,
                env,
                path="edit_precision.override_top_k",
                resolution=resolution,
            ),
            "target_top_k": _get_env_value(
                env,
                "EDIT_PRECISION_TARGET_TOP_K",
                None,
                path="edit_precision.target_top_k",
                resolution=resolution,
                transform=lambda value: _to_int(value, 0) or None,
            ),
            "exclude_agents_regex": _get_env_value(
                env,
                "EDIT_PRECISION_EXCLUDE_AGENTS_REGEX",
                None,
                path="edit_precision.exclude_agents_regex",
                resolution=resolution,
            ),
        }

        config["rewriting"] = {
            "enabled": _env_to_bool(
                "REWRITING_ENABLED",
                False,
                env,
                path="rewriting.enabled",
                resolution=resolution,
            ),
            "config_path": _get_env_value(
                env,
                "REWRITING_CONFIG_PATH",
                "config/replacements",
                path="rewriting.config_path",
                resolution=resolution,
            ),
        }

        # Model aliases configuration from environment
        model_aliases_env = env.get("MODEL_ALIASES")
        if model_aliases_env:
            try:
                alias_data = json.loads(model_aliases_env)
                if isinstance(alias_data, list):
                    config["model_aliases"] = [
                        {"pattern": item["pattern"], "replacement": item["replacement"]}
                        for item in alias_data
                        if isinstance(item, dict)
                        and "pattern" in item
                        and "replacement" in item
                    ]
                    if resolution is not None:
                        resolution.record(
                            "model_aliases",
                            config["model_aliases"],
                            ParameterSource.ENVIRONMENT,
                            origin="MODEL_ALIASES",
                        )
            except (json.JSONDecodeError, KeyError, TypeError) as e:
                logger.warning(
                    f"Invalid MODEL_ALIASES environment variable format: {e}"
                )
                config["model_aliases"] = []
        else:
            config["model_aliases"] = []

        config["backends"] = {
            "default_backend": _get_env_value(
                env,
                "LLM_BACKEND",
                "openai",
                path="backends.default_backend",
                resolution=resolution,
            )
        }

        config["identity"] = AppIdentityConfig(
            title=HeaderConfig(
                override_value=_get_env_value(
                    env,
                    "APP_TITLE",
                    None,
                    path="identity.title.override_value",
                    resolution=resolution,
                ),
                mode=HeaderOverrideMode(
                    _get_env_value(
                        env,
                        "APP_TITLE_MODE",
                        "passthrough",
                        path="identity.title.mode",
                        resolution=resolution,
                    )
                ),
                default_value="llm-interactive-proxy",
                passthrough_name="x-title",
            ),
            url=HeaderConfig(
                override_value=_get_env_value(
                    env,
                    "APP_URL",
                    None,
                    path="identity.url.override_value",
                    resolution=resolution,
                ),
                mode=HeaderOverrideMode(
                    _get_env_value(
                        env,
                        "APP_URL_MODE",
                        "passthrough",
                        path="identity.url.mode",
                        resolution=resolution,
                    )
                ),
                default_value="https://github.com/matdev83/llm-interactive-proxy",
                passthrough_name="http-referer",
            ),
            user_agent=HeaderConfig(
                override_value=_get_env_value(
                    env,
                    "APP_USER_AGENT",
                    None,
                    path="identity.user_agent.override_value",
                    resolution=resolution,
                ),
                mode=HeaderOverrideMode(
                    _get_env_value(
                        env,
                        "APP_USER_AGENT_MODE",
                        "passthrough",
                        path="identity.user_agent.mode",
                        resolution=resolution,
                    )
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
            config_backends["openrouter"]["api_url"] = _get_env_value(
                env,
                "OPENROUTER_API_BASE_URL",
                "https://openrouter.ai/api/v1",
                path="backends.openrouter.api_url",
                resolution=resolution,
            )
            timeout_value = _get_env_value(
                env,
                "OPENROUTER_TIMEOUT",
                None,
                path="backends.openrouter.timeout",
                resolution=resolution,
                transform=lambda value: _to_int(value, 0),
            )
            if timeout_value:
                config_backends["openrouter"]["timeout"] = timeout_value
            if resolution is not None:
                resolution.record(
                    "backends.openrouter.api_key",
                    config_backends["openrouter"]["api_key"],
                    ParameterSource.ENVIRONMENT,
                    origin="OPENROUTER_API_KEY*",
                )

        gemini_keys: dict[str, str] = _collect_api_keys("GEMINI_API_KEY")
        if gemini_keys:
            config_backends["gemini"] = config_backends.get("gemini", {})
            config_backends["gemini"]["api_key"] = list(gemini_keys.values())
            config_backends["gemini"]["api_url"] = _get_env_value(
                env,
                "GEMINI_API_BASE_URL",
                "https://generativelanguage.googleapis.com",
                path="backends.gemini.api_url",
                resolution=resolution,
            )
            gemini_timeout = _get_env_value(
                env,
                "GEMINI_TIMEOUT",
                None,
                path="backends.gemini.timeout",
                resolution=resolution,
                transform=lambda value: _to_int(value, 0),
            )
            if gemini_timeout:
                config_backends["gemini"]["timeout"] = gemini_timeout
            if resolution is not None:
                resolution.record(
                    "backends.gemini.api_key",
                    config_backends["gemini"]["api_key"],
                    ParameterSource.ENVIRONMENT,
                    origin="GEMINI_API_KEY*",
                )

        anthropic_keys: dict[str, str] = _collect_api_keys("ANTHROPIC_API_KEY")
        if anthropic_keys:
            config_backends["anthropic"] = config_backends.get("anthropic", {})
            config_backends["anthropic"]["api_key"] = list(anthropic_keys.values())
            config_backends["anthropic"]["api_url"] = _get_env_value(
                env,
                "ANTHROPIC_API_BASE_URL",
                "https://api.anthropic.com/v1",
                path="backends.anthropic.api_url",
                resolution=resolution,
            )
            anthropic_timeout = _get_env_value(
                env,
                "ANTHROPIC_TIMEOUT",
                None,
                path="backends.anthropic.timeout",
                resolution=resolution,
                transform=lambda value: _to_int(value, 0),
            )
            if anthropic_timeout:
                config_backends["anthropic"]["timeout"] = anthropic_timeout
            if resolution is not None:
                resolution.record(
                    "backends.anthropic.api_key",
                    config_backends["anthropic"]["api_key"],
                    ParameterSource.ENVIRONMENT,
                    origin="ANTHROPIC_API_KEY*",
                )

        zai_keys: dict[str, str] = _collect_api_keys("ZAI_API_KEY")
        if zai_keys:
            config_backends["zai"] = config_backends.get("zai", {})
            config_backends["zai"]["api_key"] = list(zai_keys.values())
            config_backends["zai"]["api_url"] = _get_env_value(
                env,
                "ZAI_API_BASE_URL",
                None,
                path="backends.zai.api_url",
                resolution=resolution,
            )
            zai_timeout = _get_env_value(
                env,
                "ZAI_TIMEOUT",
                None,
                path="backends.zai.timeout",
                resolution=resolution,
                transform=lambda value: _to_int(value, 0),
            )
            if zai_timeout:
                config_backends["zai"]["timeout"] = zai_timeout
            if resolution is not None:
                resolution.record(
                    "backends.zai.api_key",
                    config_backends["zai"]["api_key"],
                    ParameterSource.ENVIRONMENT,
                    origin="ZAI_API_KEY*",
                )

        openai_keys: dict[str, str] = _collect_api_keys("OPENAI_API_KEY")
        if openai_keys:
            config_backends["openai"] = config_backends.get("openai", {})
            config_backends["openai"]["api_key"] = list(openai_keys.values())
            config_backends["openai"]["api_url"] = _get_env_value(
                env,
                "OPENAI_API_BASE_URL",
                "https://api.openai.com/v1",
                path="backends.openai.api_url",
                resolution=resolution,
            )
            openai_timeout = _get_env_value(
                env,
                "OPENAI_TIMEOUT",
                None,
                path="backends.openai.timeout",
                resolution=resolution,
                transform=lambda value: _to_int(value, 0),
            )
            if openai_timeout:
                config_backends["openai"]["timeout"] = openai_timeout
            if resolution is not None:
                resolution.record(
                    "backends.openai.api_key",
                    config_backends["openai"]["api_key"],
                    ParameterSource.ENVIRONMENT,
                    origin="OPENAI_API_KEY*",
                )

        # Handle default backend if it's not explicitly configured above
        default_backend_type: str = str(
            config["backends"].get("default_backend", "openai")
        )
        if default_backend_type not in config_backends:
            # If the default backend is not explicitly configured, ensure it has a basic config
            config_backends[default_backend_type] = config_backends.get(
                default_backend_type, {}
            )
            # Add a dummy API key if running in test environment and no API key is present
            if env.get("PYTEST_CURRENT_TEST") and (
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


def _set_by_path(target: dict[str, Any], path: str, value: Any) -> None:
    parts = path.split(".")
    current: dict[str, Any] = target
    for key in parts[:-1]:
        current = current.setdefault(key, {})  # type: ignore[assignment]
    current[parts[-1]] = value


def _get_by_path(source: dict[str, Any], path: str) -> Any:
    parts = path.split(".")
    current: Any = source
    for key in parts:
        if not isinstance(current, dict):
            return None
        current = current.get(key)
    return current


def _flatten_dict(data: dict[str, Any]) -> dict[str, Any]:
    flattened: dict[str, Any] = {}

    def _walk(value: Any, prefix: str) -> None:
        if isinstance(value, dict):
            for key, child in value.items():
                new_prefix = f"{prefix}.{key}" if prefix else key
                _walk(child, new_prefix)
        else:
            flattened[prefix] = value

    _walk(data, "")
    return flattened


def load_config(
    config_path: str | Path | None = None,
    *,
    resolution: ParameterResolution | None = None,
    environ: Mapping[str, str] | None = None,
) -> AppConfig:
    """
    Load configuration from file and environment.

    Args:
        config_path: Optional path to configuration file

    Returns:
        AppConfig instance
    """
    env = environ or os.environ
    res = resolution or ParameterResolution()

    config_data: dict[str, Any] = AppConfig().model_dump()

    if config_path:
        try:
            import yaml

            path: Path = Path(config_path)
            if not path.exists():
                logger.warning(f"Configuration file not found: {config_path}")
            else:
                if path.suffix.lower() not in [".yaml", ".yml"]:
                    raise ValueError(
                        f"Unsupported configuration file format: {path.suffix}. Use YAML (.yaml/.yml)."
                    )

                with open(path, encoding="utf-8") as f:
                    file_config: dict[str, Any] = yaml.safe_load(f) or {}

                from pathlib import Path as _Path

                from src.core.config.semantic_validation import (
                    validate_config_semantics,
                )
                from src.core.config.yaml_validation import validate_yaml_against_schema

                schema_path = (
                    _Path.cwd() / "config" / "schemas" / "app_config.schema.yaml"
                )
                validate_yaml_against_schema(_Path(path), schema_path)
                validate_config_semantics(file_config, path)

                _merge_dicts(config_data, file_config)
                origin = str(path)
                for name, value in _flatten_dict(file_config).items():
                    res.record(
                        name,
                        value,
                        ParameterSource.CONFIG_FILE,
                        origin=origin,
                    )
        except Exception as exc:  # type: ignore[misc]
            logger.critical(f"Error loading configuration file: {exc!s}")
            raise

    env_config = AppConfig.from_env(environ=env, resolution=res)
    env_dump = env_config.model_dump()
    for name in res.latest_by_source(ParameterSource.ENVIRONMENT):
        value = _get_by_path(env_dump, name)
        _set_by_path(config_data, name, value)

    return AppConfig.model_validate(config_data)
