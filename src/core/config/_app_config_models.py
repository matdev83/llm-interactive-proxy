from __future__ import annotations

from enum import Enum
from typing import Any, cast

from pydantic import ConfigDict, Field, field_validator, model_validator

from src.core.domain.configuration.app_identity_config import AppIdentityConfig
from src.core.interfaces.model_bases import DomainModel
from src.core.services.backend_registry import backend_registry


class LogLevel(str, Enum):
    """Log levels for configuration."""

    DEBUG = "DEBUG"
    INFO = "INFO"
    WARNING = "WARNING"
    ERROR = "ERROR"
    CRITICAL = "CRITICAL"


class BackendConfig(DomainModel):
    """Configuration for a backend service."""

    model_config = ConfigDict(frozen=True)

    api_key: list[str] = Field(default_factory=list)
    api_url: str | None = None
    models: list[str] = Field(default_factory=list)
    timeout: int = 120
    identity: AppIdentityConfig | None = None
    extra: dict[str, Any] = Field(default_factory=dict)

    @field_validator("api_key", mode="before")
    @classmethod
    def validate_api_key(cls, value: Any) -> list[str]:
        if isinstance(value, str):
            return [value]
        return value if isinstance(value, list) else []

    @field_validator("api_url")
    @classmethod
    def validate_api_url(cls, value: str | None) -> str | None:
        if value is not None and not value.startswith(("http://", "https://")):
            raise ValueError("API URL must start with http:// or https://")
        return value


class BruteForceProtectionConfig(DomainModel):
    """Configuration for brute-force protection on API authentication."""

    model_config = ConfigDict(frozen=True)

    enabled: bool = True
    max_failed_attempts: int = 5
    ttl_seconds: int = 900
    initial_block_seconds: int = 30
    block_multiplier: float = 2.0
    max_block_seconds: int = 3600


class AuthConfig(DomainModel):
    """Authentication configuration."""

    model_config = ConfigDict(frozen=True)

    disable_auth: bool = False
    api_keys: list[str] = Field(default_factory=list)
    auth_token: str | None = None
    redact_api_keys_in_prompts: bool = True
    trusted_ips: list[str] = Field(default_factory=list)
    brute_force_protection: BruteForceProtectionConfig = Field(
        default_factory=BruteForceProtectionConfig
    )


class LoggingConfig(DomainModel):
    """Logging configuration."""

    model_config = ConfigDict(frozen=True)

    level: LogLevel = LogLevel.INFO
    request_logging: bool = False
    response_logging: bool = False
    log_file: str | None = None
    capture_file: str | None = None
    capture_max_bytes: int | None = None
    capture_truncate_bytes: int | None = None
    capture_max_files: int | None = None
    capture_rotate_interval_seconds: int = 86400
    capture_total_max_bytes: int = 104857600
    capture_buffer_size: int = 65536
    capture_flush_interval: float = 1.0
    capture_max_entries_per_flush: int = 100


class ToolCallReactorConfig(DomainModel):
    """Configuration for the Tool Call Reactor system."""

    model_config = ConfigDict(frozen=True)

    enabled: bool = True
    apply_diff_steering_enabled: bool = True
    apply_diff_steering_rate_limit_seconds: int = 60
    apply_diff_steering_message: str | None = None
    pytest_full_suite_steering_enabled: bool = False
    pytest_full_suite_steering_message: str | None = None
    pytest_context_saving_enabled: bool = False
    fix_think_tags_enabled: bool = False
    steering_rules: list[dict[str, Any]] = Field(default_factory=list)
    access_policies: list[dict[str, Any]] = Field(default_factory=list)


class PlanningPhaseConfig(DomainModel):
    """Configuration for planning phase model routing."""

    model_config = ConfigDict(frozen=True)

    enabled: bool = False
    strong_model: str | None = None
    max_turns: int = 10
    max_file_writes: int = 1
    overrides: dict[str, Any] | None = None


class SessionContinuityConfig(DomainModel):
    """Configuration for intelligent session continuity detection."""

    model_config = ConfigDict(frozen=True)

    enabled: bool = True
    fuzzy_matching: bool = True
    max_session_age_seconds: int = 604800
    fingerprint_message_count: int = 5
    client_key_includes_ip: bool = True


class SessionConfig(DomainModel):
    """Session management configuration."""

    model_config = ConfigDict(frozen=True)

    cleanup_enabled: bool = True
    cleanup_interval: int = 3600
    max_age: int = 86400
    default_interactive_mode: bool = True
    force_set_project: bool = False
    disable_interactive_commands: bool = False
    project_dir_resolution_model: str | None = None
    project_dir_resolution_mode: str = "hybrid"
    tool_call_repair_enabled: bool = True
    tool_call_repair_buffer_cap_bytes: int = 64 * 1024
    json_repair_enabled: bool = True
    json_repair_buffer_cap_bytes: int = 64 * 1024
    json_repair_strict_mode: bool = False
    json_repair_schema: dict[str, Any] | None = None
    tool_call_reactor: ToolCallReactorConfig = Field(default_factory=ToolCallReactorConfig)
    dangerous_command_prevention_enabled: bool = True
    dangerous_command_steering_message: str | None = None
    pytest_compression_enabled: bool = True
    pytest_compression_min_lines: int = 30
    pytest_full_suite_steering_enabled: bool | None = None
    pytest_full_suite_steering_message: str | None = None
    fix_think_tags_enabled: bool = False
    fix_think_tags_streaming_buffer_size: int = 4096
    planning_phase: PlanningPhaseConfig = Field(default_factory=PlanningPhaseConfig)
    max_per_session_backends: int = 32
    session_continuity: SessionContinuityConfig = Field(
        default_factory=SessionContinuityConfig
    )
    tool_access_global_overrides: dict[str, Any] | None = None
    force_reprocess_tool_calls: bool = False
    log_skipped_tool_calls: bool = False

    @model_validator(mode="before")
    @classmethod
    def _sync_pytest_full_suite_settings(cls, values: dict[str, Any]) -> dict[str, Any]:
        reactor_config = values.get("tool_call_reactor")
        if isinstance(reactor_config, ToolCallReactorConfig):
            reactor_config_dict = reactor_config.model_dump()
        elif isinstance(reactor_config, dict):
            reactor_config_dict = dict(reactor_config)
        else:
            reactor_config_dict = {}

        enabled = values.get("pytest_full_suite_steering_enabled")
        message = values.get("pytest_full_suite_steering_message")

        if enabled is not None:
            reactor_config_dict["pytest_full_suite_steering_enabled"] = enabled
        else:
            values["pytest_full_suite_steering_enabled"] = reactor_config_dict.get(
                "pytest_full_suite_steering_enabled", False
            )

        if message is not None:
            reactor_config_dict["pytest_full_suite_steering_message"] = message
        else:
            values["pytest_full_suite_steering_message"] = reactor_config_dict.get(
                "pytest_full_suite_steering_message"
            )

        values["tool_call_reactor"] = reactor_config_dict
        return values


class EmptyResponseConfig(DomainModel):
    """Configuration for empty response handling."""

    model_config = ConfigDict(frozen=True)

    enabled: bool = True
    max_retries: int = 1


class ModelAliasRule(DomainModel):
    """Rule for remapping model names."""

    model_config = ConfigDict(frozen=True)

    pattern: str
    replacement: str


class RewritingConfig(DomainModel):
    """Configuration for content rewriting."""

    model_config = ConfigDict(frozen=True)

    enabled: bool = False
    config_path: str = "config/replacements"


class EditPrecisionConfig(DomainModel):
    """Configuration for automated edit-precision tuning."""

    model_config = ConfigDict(frozen=True)

    enabled: bool = True
    temperature: float = 0.1
    min_top_p: float | None = 0.3
    override_top_p: bool = False
    override_top_k: bool = False
    target_top_k: int | None = None
    exclude_agents_regex: str | None = None


class BackendSettings(DomainModel):
    """Settings for all backends."""

    model_config = ConfigDict(frozen=False, extra="allow")

    default_backend: str = "openai"
    static_route: str | None = None
    disable_gemini_oauth_fallback: bool = False
    disable_hybrid_backend: bool = False
    hybrid_backend_repeat_messages: bool = False
    reasoning_injection_probability: float = Field(
        default=1.0,
        ge=0.0,
        le=1.0,
        description="Probability of using the reasoning model for a request in the hybrid backend.",
    )

    def __init__(self, **data: Any) -> None:
        known_fields = set(self.model_fields.keys())
        init_data = {key: value for key, value in data.items() if key in known_fields}
        backend_data = {key: value for key, value in data.items() if key not in known_fields}
        super().__init__(**init_data)

        for backend_name, config_data in backend_data.items():
            if isinstance(config_data, dict):
                self.__dict__[backend_name] = BackendConfig(**config_data)
            elif isinstance(config_data, BackendConfig):
                self.__dict__[backend_name] = config_data

        for backend_name in backend_registry.get_registered_backends():
            if backend_name not in self.__dict__:
                self.__dict__[backend_name] = BackendConfig()

        self._initialization_complete = True

    def __getitem__(self, key: str) -> BackendConfig:
        if key in self.__dict__:
            return cast(BackendConfig, self.__dict__[key])
        raise KeyError(f"Backend '{key}' not found")

    def __setitem__(self, key: str, value: BackendConfig) -> None:
        self.__dict__[key] = value

    def __setattr__(self, name: str, value: Any) -> None:
        if name in {"default_backend"} or name.startswith("_") or name in self.model_fields:
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
        return cast(BackendConfig | None, self.__dict__.get(key, default))

    @property
    def functional_backends(self) -> set[str]:
        functional: set[str] = set()
        registered = backend_registry.get_registered_backends()
        for backend_name in registered:
            if backend_name in self.__dict__:
                config = self.__dict__[backend_name]
                if isinstance(config, BackendConfig) and config.api_key:
                    functional.add(backend_name)

        oauth_like: set[str] = set()
        for name in registered:
            if name.endswith("-oauth") or name.startswith("gemini-oauth"):
                oauth_like.add(name)
            if name == "gemini-cli-cloud-project":
                oauth_like.add(name)

        functional.update(oauth_like.intersection(set(registered)))

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
        if name == "default_backend":
            if "default_backend" in self.__dict__:
                return self.__dict__["default_backend"]
            return "openai"

        if name in self.__dict__:
            return cast(BackendConfig, self.__dict__[name])

        if name.startswith(("_", "__")):
            raise AttributeError(
                f"'{self.__class__.__name__}' object has no attribute '{name}'"
            )

        if not hasattr(self, "_initialization_complete"):
            raise AttributeError(
                f"'{self.__class__.__name__}' object has no attribute '{name}'"
            )

        config = BackendConfig()
        self.__dict__[name] = config
        return config

    def set(self, key: str, value: Any) -> None:
        setattr(self, key, value)

    def get_gcp_project_id(self) -> str | None:
        return self.gcp_project_id


__all__ = [
    "AuthConfig",
    "BackendConfig",
    "BackendSettings",
    "BruteForceProtectionConfig",
    "EditPrecisionConfig",
    "EmptyResponseConfig",
    "LogLevel",
    "LoggingConfig",
    "ModelAliasRule",
    "PlanningPhaseConfig",
    "RewritingConfig",
    "SessionConfig",
    "SessionContinuityConfig",
    "ToolCallReactorConfig",
]
