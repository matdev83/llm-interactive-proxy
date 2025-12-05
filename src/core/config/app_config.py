from __future__ import annotations

import json
import logging
import os
from collections.abc import Callable, Mapping
from enum import Enum
from pathlib import Path
from typing import Any, cast

from pydantic import (
    ConfigDict,
    Field,
    field_validator,
    model_serializer,
    model_validator,
)

from src.core.auth.sso.config import SSOConfig
from src.core.config.parameter_resolution import ParameterResolution, ParameterSource

BACKEND_INSTANCES_DIR = Path("config/backends/backend-instances")


def get_openrouter_headers(cfg: dict[str, str], api_key: str) -> dict[str, str]:
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


from src.core.domain.configuration.app_identity_config import AppIdentityConfig
from src.core.domain.configuration.assessment_config import AssessmentConfig
from src.core.domain.configuration.header_config import (
    HeaderConfig,
    HeaderOverrideMode,
)
from src.core.domain.configuration.health_check_config import HealthCheckConfig
from src.core.domain.configuration.reasoning_aliases_config import (
    ReasoningAliasesConfig,
)
from src.core.domain.configuration.replacement_config import ReplacementConfig
from src.core.domain.configuration.sandboxing_config import SandboxingConfiguration
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

    model_config = ConfigDict(frozen=True)

    api_key: str | None = None
    api_url: str | None = None
    models: list[str] = Field(default_factory=list)
    timeout: int = 120  # seconds
    identity: AppIdentityConfig | None = None
    extra: dict[str, Any] = Field(default_factory=dict)
    allow_concurrent_use: bool = True
    credentials_path: str | None = None
    supported_input_types: list[str] | None = None
    connector: str | None = None

    @field_validator("supported_input_types", mode="before")
    @classmethod
    def validate_input_types(cls, v: Any) -> list[str] | None:
        """Validate input types against known multimodal types."""
        if v is None:
            return None

        from src.core.domain.multimodal_types import MultimodalInputType

        # If it's a single string (not a list), wrap it
        if isinstance(v, str):
            v = [v]

        if not isinstance(v, list):
            return []

        valid_types = [t.value for t in MultimodalInputType]
        result = []
        for item in v:
            if item in valid_types:
                result.append(item)
            # Be lenient with case
            elif item.lower() in valid_types:
                result.append(item.lower())

        return result

    @field_validator("api_key", mode="before")
    @classmethod
    def validate_api_key(cls, v: Any) -> str | None:
        """Ensure api_key is always a string or None."""
        if isinstance(v, list) and v:
            # Legacy list support: take first
            return str(v[0])
        if isinstance(v, list) and not v:
            return None
        return str(v) if v is not None else None

    @field_validator("api_url")
    @classmethod
    def validate_api_url(cls, v: str | None) -> str | None:
        """Validate the API URL if provided."""
        if v is not None and not v.startswith(("http://", "https://")):
            raise ValueError("API URL must start with http:// or https://")
        return v


class AuthConfig(DomainModel):
    """Authentication configuration."""

    model_config = ConfigDict(frozen=True)

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

    model_config = ConfigDict(frozen=True)

    enabled: bool = True
    max_failed_attempts: int = 5
    ttl_seconds: int = 900
    initial_block_seconds: int = 30
    block_multiplier: float = 2.0
    max_block_seconds: int = 3600


class LoggingConfig(DomainModel):
    """Logging configuration."""

    model_config = ConfigDict(frozen=True)

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

    # CBOR byte-precise capture configuration (optional, complementary to JSON capture)
    # Directory for CBOR capture files; when set, enables CBOR capture with byte precision
    cbor_capture_dir: str | None = None
    # Optional fixed session ID for CBOR capture; auto-generated if not provided
    cbor_capture_session_id: str | None = None


class RoutingConfig(DomainModel):
    """Configuration for routing policies."""

    model_config = ConfigDict(frozen=True)

    disable_backend_ids: bool = False
    disable_backend_names: bool = False
    disable_model_names: bool = False

    @model_validator(mode="after")
    def validate_at_least_one_method_enabled(self) -> RoutingConfig:
        """Ensure at least one routing method remains available."""
        if self.disable_backend_names and self.disable_model_names:
            raise ValueError(
                "Invalid routing config: cannot disable both backend names and "
                "model-only routing. At least one routing method must remain available."
            )
        return self


class ToolCallReactorConfig(DomainModel):
    """Configuration for the Tool Call Reactor system.

    The Tool Call Reactor provides event-driven reactions to tool calls
    from LLMs, allowing custom handlers to monitor, modify, or replace responses.
    """

    model_config = ConfigDict(frozen=True)

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

    pytest_context_saving_enabled: bool = False
    """Whether pytest context-saving command rewrites are enabled."""

    fix_think_tags_enabled: bool = False
    """Whether correction of improperly formatted <think> tags is enabled."""

    test_execution_reminder_enabled: bool = False
    """Whether test execution reminder steering is enabled."""

    test_execution_reminder_message: str | None = None
    """Optional custom steering message for test execution reminders."""

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

    # Tool access control policies
    access_policies: list[dict[str, Any]] = Field(default_factory=list)
    """Tool access control policies.

    Each policy defines which tools are allowed or blocked for specific models/agents.
    Minimal fields:
      - name: Unique policy identifier
      - model_pattern: Regex pattern for matching model names
      - default_policy: "allow" or "deny"
    Optional fields:
      - agent_pattern: Regex pattern for matching agents
      - allowed_patterns: List of regex patterns for allowed tools
      - blocked_patterns: List of regex patterns for blocked tools
      - block_message: Message to return when blocking a tool call
      - priority: int (higher values take precedence)
    """


class PlanningPhaseConfig(DomainModel):
    """Configuration for planning phase model routing."""

    model_config = ConfigDict(frozen=True)

    enabled: bool = False
    strong_model: str | None = None
    max_turns: int = 10
    max_file_writes: int = 1
    # Optional parameter overrides for the strong model
    overrides: dict[str, Any] | None = None


class SessionContinuityConfig(DomainModel):
    """Configuration for intelligent session continuity detection."""

    model_config = ConfigDict(frozen=True)

    enabled: bool = True
    fuzzy_matching: bool = True
    max_session_age_seconds: int = 604800  # 7 days
    fingerprint_message_count: int = 5
    client_key_includes_ip: bool = True


class StreamingSamplerConfig(DomainModel):
    """Configuration for the streaming sampler (debugging/observability)."""

    model_config = ConfigDict(frozen=True)

    enabled: bool = True
    """Whether the streaming sampler is enabled."""

    sample_rate: float = Field(default=0.01, ge=0.0, le=1.0)
    """Probability of sampling a stream (0.0 to 1.0). Default: 1% of streams."""

    max_samples: int = Field(default=100, ge=1)
    """Maximum number of samples to retain in memory."""


class CodebuffConfig(DomainModel):
    """Codebuff WebSocket server configuration."""

    model_config = ConfigDict(frozen=True)

    enabled: bool = False
    websocket_path: str = "/ws"
    heartbeat_timeout_seconds: int = 60
    session_cleanup_hours: int = 1
    max_connections: int = 1000
    max_message_size_bytes: int = 1048576  # 1MB


class UsageTrackingConfig(DomainModel):
    """Usage tracking and statistics configuration."""

    model_config = ConfigDict(frozen=True)

    enabled: bool = True
    """Whether detailed usage tracking is enabled."""

    persistence_path: str = "./var/usage_data.json"
    """Path for persistence file."""

    flush_interval_seconds: float = 30.0
    """Interval for periodic persistence (in seconds)."""

    max_records_in_memory: int = 100000
    """Maximum records to keep in memory before applying retention policies."""


class SessionConfig(DomainModel):
    """Session management configuration."""

    model_config = ConfigDict(frozen=True)

    cleanup_enabled: bool = True
    cleanup_interval: int = 3600  # 1 hour
    max_age: int = 86400  # 1 day
    default_interactive_mode: bool = True
    force_set_project: bool = False
    disable_interactive_commands: bool = False
    project_dir_resolution_model: str | None = None
    project_dir_resolution_mode: str = "hybrid"
    tool_call_repair_enabled: bool = True
    # Max per-session buffer for tool-call repair streaming (bytes)
    tool_call_repair_buffer_cap_bytes: int = 64 * 1024
    json_repair_enabled: bool = True
    # Max per-session buffer for JSON repair streaming (bytes)
    json_repair_buffer_cap_bytes: int = 64 * 1024
    json_repair_strict_mode: bool = False
    json_repair_schema: dict[str, Any] | None = None  # Added
    # Streaming sampler configuration
    streaming_sampler: StreamingSamplerConfig = Field(
        default_factory=StreamingSamplerConfig
    )
    tool_call_reactor: ToolCallReactorConfig = Field(
        default_factory=ToolCallReactorConfig
    )
    dangerous_command_prevention_enabled: bool = True
    dangerous_command_steering_message: str | None = None
    pytest_compression_enabled: bool = True
    pytest_compression_min_lines: int = 30
    pytest_full_suite_steering_enabled: bool | None = None
    pytest_full_suite_steering_message: str | None = None
    test_execution_reminder_enabled: bool | None = None
    test_execution_reminder_message: str | None = None
    droid_antigravity_path_fix_enabled: bool = False
    fix_think_tags_enabled: bool = False
    fix_think_tags_streaming_buffer_size: int = 4096
    planning_phase: PlanningPhaseConfig = Field(default_factory=PlanningPhaseConfig)
    max_per_session_backends: int = 32
    session_continuity: SessionContinuityConfig = Field(
        default_factory=SessionContinuityConfig
    )
    tool_access_global_overrides: dict[str, Any] | None = None
    # Tool call processing behavior configuration
    force_reprocess_tool_calls: bool = False
    log_skipped_tool_calls: bool = False
    # Angel verification model (backend:model with optional URI params)
    angel_model: str | None = None
    angel_frequency: int = 1

    @field_validator("angel_frequency")
    @classmethod
    def _validate_angel_frequency(cls, value: int) -> int:
        try:
            freq = int(value)
        except (TypeError, ValueError):
            return 1
        return freq if freq > 0 else 1

    @model_validator(mode="before")
    @classmethod
    def _sync_pytest_full_suite_settings(cls, values: dict[str, Any]) -> dict[str, Any]:
        """Keep pytest full-suite steering settings mirrored with reactor config."""
        reactor_config = values.get("tool_call_reactor")

        # Convert to dict if it's already a ToolCallReactorConfig instance
        if isinstance(reactor_config, ToolCallReactorConfig):
            reactor_config_dict = reactor_config.model_dump()
        elif isinstance(reactor_config, dict):
            reactor_config_dict = dict(reactor_config)
        else:
            reactor_config_dict = {}

        enabled = values.get("pytest_full_suite_steering_enabled")
        message = values.get("pytest_full_suite_steering_message")

        # Update the dict instead of mutating frozen model
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

        fix_think_tags = values.get("fix_think_tags_enabled")
        if fix_think_tags is not None:
            reactor_config_dict["fix_think_tags_enabled"] = fix_think_tags
        else:
            values["fix_think_tags_enabled"] = reactor_config_dict.get(
                "fix_think_tags_enabled",
                values.get("fix_think_tags_enabled", False),
            )

        test_exec_reminder_enabled = values.get("test_execution_reminder_enabled")
        if test_exec_reminder_enabled is not None:
            reactor_config_dict["test_execution_reminder_enabled"] = (
                test_exec_reminder_enabled
            )
        else:
            values["test_execution_reminder_enabled"] = reactor_config_dict.get(
                "test_execution_reminder_enabled",
                values.get("test_execution_reminder_enabled", False),
            )

        test_exec_reminder_message = values.get("test_execution_reminder_message")
        if test_exec_reminder_message is not None:
            reactor_config_dict["test_execution_reminder_message"] = (
                test_exec_reminder_message
            )
        else:
            values["test_execution_reminder_message"] = reactor_config_dict.get(
                "test_execution_reminder_message"
            )

        # Store the dict - Pydantic will convert it to ToolCallReactorConfig
        values["tool_call_reactor"] = reactor_config_dict
        # Ensure angel_model is either valid string or None
        angel_model = values.get("angel_model")
        if angel_model is not None and not isinstance(angel_model, str):
            try:
                values["angel_model"] = str(angel_model)
            except Exception:
                values["angel_model"] = None
        # Normalize angel_frequency
        freq_value = values.get("angel_frequency", 1)
        try:
            freq_int = int(freq_value)
        except (TypeError, ValueError):
            freq_int = 1
        values["angel_frequency"] = freq_int if freq_int > 0 else 1
        return values


class EmptyResponseConfig(DomainModel):
    """Configuration for empty response handling."""

    model_config = ConfigDict(frozen=True)

    enabled: bool = True
    """Whether the empty response recovery is enabled."""

    max_retries: int = 1
    """Maximum number of retries for empty responses."""


class ModelAliasRule(DomainModel):
    """A rule for rewriting a model name."""

    model_config = ConfigDict(frozen=True)

    pattern: str
    replacement: str


class RewritingConfig(DomainModel):
    """Configuration for content rewriting."""

    model_config = ConfigDict(frozen=True)

    enabled: bool = False
    config_path: str = "config/replacements"


class EditPrecisionConfig(DomainModel):
    """Configuration for automated edit-precision tuning.

    When enabled, detects agent edit-failure prompts and lowers sampling
    parameters for the next single call to improve precision.
    """

    model_config = ConfigDict(frozen=True)

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
    """Settings for all backends.

    Note: This class is intentionally not frozen because it needs to support
    dynamic backend configurations that are added at runtime. Backend configs
    are stored in __dict__ to allow attribute-style access (e.g., config.backends.openai)
    without pre-defining all possible backends as fields.
    """

    model_config = ConfigDict(frozen=False, extra="allow")

    default_backend: str = "openai"
    static_route: str | None = (
        None  # Force all requests to backend:model (e.g., "gemini-oauth-plan:gemini-2.5-pro")
    )
    disable_gemini_oauth_fallback: bool = False
    disable_hybrid_backend: bool = False
    hybrid_backend_repeat_messages: bool = False
    reasoning_injection_probability: float = Field(
        default=1.0,
        ge=0.0,
        le=1.0,
        description="Probability of using the reasoning model for a request in the hybrid backend.",
    )
    hybrid_reasoning_model_timeout: int = Field(
        default=60,
        ge=1,
        description="Timeout in seconds for the reasoning model call in hybrid scenarios. Defaults to 60.",
    )
    hybrid_reasoning_force_initial_turns: int = Field(
        default=1,
        ge=0,
        description="Number of turns at the beginning of a new session when the reasoning model probability is overridden to 1 (100%). Defaults to 1.",
    )
    hybrid_execution_model_timeout: int = Field(
        default=120,
        ge=1,
        description="Timeout in seconds for execution model call in hybrid scenarios. Defaults to 120.",
    )
    hybrid_reasoning_latency_threshold: float = Field(
        default=8.0,
        ge=0.0,
        description="Latency threshold (seconds) that triggers adaptive reasoning backoff when exceeded. Set 0 to disable.",
    )
    hybrid_reasoning_backoff_turns: int = Field(
        default=2,
        ge=0,
        description="Number of subsequent turns to skip reasoning after latency threshold is exceeded. Set 0 to disable adaptive backoff.",
    )

    def __init__(self, **data: Any) -> None:
        # Separate standard fields from backend-specific configs
        known_fields = set(self.model_fields.keys())

        init_data = {k: v for k, v in data.items() if k in known_fields}
        backend_data = {k: v for k, v in data.items() if k not in known_fields}

        # Initialize the model with standard fields
        super().__init__(**init_data)

        # Manually set the backend configurations
        for backend_name, config_data in backend_data.items():
            if isinstance(config_data, dict):
                self.__dict__[backend_name] = BackendConfig(**config_data)
            elif isinstance(config_data, BackendConfig):
                self.__dict__[backend_name] = config_data

        # Ensure all registered backends have a config
        registered_backends = backend_registry.get_registered_backends()
        for backend_name in registered_backends:
            if backend_name not in self.__dict__:
                self.__dict__[backend_name] = BackendConfig()

        self._discover_backend_instances(registered_backends)
        self._initialization_complete = True

    def _discover_backend_instances(self, registered_backends: list[str]) -> None:
        """Discover backend instances via env vars and config files."""
        import re

        # Track instances discovered via environment variables
        env_discovered_instances: set[str] = set()

        # Strategy A: API Key Backends (Env Vars)
        # Format: {CONNECTOR_UPPERCASE}_API_KEY_{N} -> connector.N
        # We need a mapping from connector name to env var prefix.
        # This is heuristics based on existing conventions.

        env_prefixes = {
            "openai": "OPENAI_API_KEY",
            "anthropic": "ANTHROPIC_API_KEY",
            "gemini": "GEMINI_API_KEY",
            "openrouter": "OPENROUTER_API_KEY",
            "zai": "ZAI_API_KEY",
            "minimax": "MINIMAX_API_KEY",
            "zenmux": "ZENMUX_API_KEY",
        }

        for connector, prefix in env_prefixes.items():
            if connector not in registered_backends:
                continue

            for i in range(1, 100):  # Reasonable limit
                env_key = f"{prefix}_{i}"
                api_key = os.getenv(env_key)
                if api_key:
                    instance_name = f"{connector}.{i}"
                    # Don't overwrite if defined in config.yaml (passed via data)
                    if instance_name not in self.__dict__:
                        self.__dict__[instance_name] = BackendConfig(
                            api_key=api_key, connector=connector
                        )
                        env_discovered_instances.add(instance_name)
                        if logger.isEnabledFor(logging.DEBUG):
                            logger.debug(
                                f"Discovered backend instance via env: {instance_name}"
                            )

        # Strategy B: Credential File Backends (Config Files)
        # Scan config/backends/backend-instances/*.yaml
        # Pattern: <connector>.<instance>.yaml

        # Allow override for testing (mocking BACKEND_INSTANCES_DIR if it were a module constant)
        config_dir = BACKEND_INSTANCES_DIR

        # Track instances that have a dedicated configuration file
        file_configured_instances: set[str] = set()

        if config_dir.exists():
            for config_file in config_dir.glob("*.yaml"):
                filename = config_file.name
                match = re.match(
                    r"^(?P<connector>[^.]+)\.(?P<name>.+)\.yaml$", filename
                )
                if match:
                    connector = match.group("connector")

                    # Validate connector is registered
                    if connector not in registered_backends:
                        if logger.isEnabledFor(logging.WARNING):
                            logger.warning(
                                f"Skipping config file {filename}: connector '{connector}' not registered"
                            )
                        continue

                    instance_name = f"{connector}.{match.group('name')}"
                    file_configured_instances.add(instance_name)

                    try:
                        import yaml

                        with open(config_file, encoding="utf-8") as f:
                            file_config = yaml.safe_load(f)

                        if not isinstance(file_config, dict):
                            logger.warning(
                                f"Skipping invalid config file {filename}: content is not a dict"
                            )
                            continue

                        # If instance exists (e.g. from env var or main config), merge it
                        # Otherwise create new

                        existing_config = self.__dict__.get(instance_name)

                        # Prepare new config data
                        new_config_data = file_config.copy()
                        new_config_data["connector"] = connector

                        if existing_config:
                            # Merge: file overrides existing (e.g. env var)
                            # Convert existing to dict
                            merged_data = existing_config.model_dump(exclude_unset=True)
                            merged_data.update(new_config_data)
                            self.__dict__[instance_name] = BackendConfig(**merged_data)
                        else:
                            self.__dict__[instance_name] = BackendConfig(
                                **new_config_data
                            )

                        if logger.isEnabledFor(logging.INFO):
                            logger.info(
                                f"Loaded backend instance config: {instance_name}"
                            )

                    except Exception as e:
                        logger.error(
                            f"Error loading backend instance config {filename}: {e}"
                        )

        # Check for missing config files for environment-discovered instances
        for instance_name in env_discovered_instances:
            if instance_name not in file_configured_instances:
                expected_path = BACKEND_INSTANCES_DIR / f"{instance_name}.yaml"
                logger.warning(
                    "Backend instance '%s' created from environment variables but no configuration file found. "
                    "Using default settings. Expected file location: %s",
                    instance_name,
                    expected_path,
                )

        # Validation: Uniqueness check for file-based credentials
        # We need to check if multiple instances of the same connector use the same credentials path
        # This applies mostly to OAuth backends like qwen-oauth, gemini-oauth-*

        file_based_connectors = {
            "qwen-oauth",
            "gemini-oauth-free",
            "gemini-oauth-plan",
            "gemini-oauth-antigravity",
            "gemini-cli-cloud-project",
            "anthropic-oauth",
        }

        connector_paths: dict[str, dict[str, str]] = (
            {}
        )  # connector -> {path -> instance_name}

        for name, config in self.__dict__.items():
            if (
                name == "default_backend"
                or name.startswith("_")
                or not isinstance(config, BackendConfig)
            ):
                continue

            # Determine connector type
            connector = config.connector or name.split(".")[0]

            if connector in file_based_connectors:
                # Check credentials_path
                creds_path = config.credentials_path or config.extra.get(
                    "credentials_path"
                )

                # Some connectors have default paths, but we only check explicit ones or if we can resolve default
                # If path is None, it uses default. We can't easily check uniqueness of defaults without
                # duplicating connector logic. But the requirement says "Enforce uniqueness of credential file paths"

                if creds_path:
                    normalized_path = str(Path(creds_path).resolve())

                    if connector not in connector_paths:
                        connector_paths[connector] = {}

                    if normalized_path in connector_paths[connector]:
                        prev_instance = connector_paths[connector][normalized_path]
                        msg = f"Duplicate credentials path '{creds_path}' detected for connector '{connector}' in instances '{prev_instance}' and '{name}'"
                        # For now log error, maybe raise exception? Spec says "Raise error/warn"
                        # Tests expect ValueError
                        raise ValueError(msg)

                    connector_paths[connector][normalized_path] = name

        # Fallback for file-based connectors: if no numbered instances found, create default .1
        # The spec says: "If no configs found... create default <connector>.1"
        for connector in file_based_connectors:
            if connector not in registered_backends:
                continue

            # Check if any numbered instance (connector.X) exists for this connector
            has_numbered_instance = any(
                name.startswith(f"{connector}.")
                for name, cfg in self.__dict__.items()
                if isinstance(cfg, BackendConfig) and name != "default_backend"
            )

            if not has_numbered_instance:
                # Create default .1 instance
                instance_name = f"{connector}.1"
                self.__dict__[instance_name] = BackendConfig(connector=connector)
                if logger.isEnabledFor(logging.INFO):
                    logger.info(
                        f"Created default instance '{instance_name}' for file-based connector '{connector}'"
                    )

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
            if name.endswith("-oauth") or name.startswith("gemini-oauth"):
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

        # Check if we're still initializing (indicated by presence of __dict__ keys
        # that suggest initialization hasn't completed). Don't create empty configs
        # during initialization - let the __init__ method handle it.
        # Only create empty configs after initialization is complete.
        if not hasattr(self, "_initialization_complete"):
            # During initialization, raise AttributeError to let __init__ handle it
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

    @model_serializer(mode="wrap")
    def serialize_model(self, handler: Any) -> dict[str, Any]:
        """Custom serializer to include dynamic backends."""
        dumped: dict[str, Any] = handler(self)

        # Add dynamic backends to the dumped dictionary
        registered = backend_registry.get_registered_backends()
        for backend_name in registered:
            if backend_name in self.__dict__:
                config: Any = self.__dict__[backend_name]
                if isinstance(config, BackendConfig):
                    dumped[backend_name] = config.model_dump()

        # Also include numbered instances or other dynamic keys
        for key, value in self.__dict__.items():
            if (
                key not in dumped
                and isinstance(value, BackendConfig)
                and key != "default_backend"
            ):
                dumped[key] = value.model_dump()

        return dumped

    def model_is_functional(self, model_id: str) -> bool:
        """Check if a model is available in any functional backend."""
        if ":" not in model_id:
            return False  # Invalid format

        backend_name, _ = model_id.split(":", 1)
        return backend_name in self.functional_backends


class AppConfig(DomainModel, IConfig):
    """Complete application configuration."""

    model_config = ConfigDict(frozen=True, arbitrary_types_allowed=True)

    host: str = "127.0.0.1"  # Default to localhost for security
    port: int = 8000
    # Publicly accessible URL for the proxy (required for correct SSO redirects when deployed)
    # If not set, defaults to http://{host}:{port}. Required if binding to 0.0.0.0 or behind a reverse proxy.
    public_url: str | None = None
    anthropic_port: int | None = None  # Will be set to port + 1 if not provided
    proxy_timeout: int = 120
    command_prefix: str = "!/"
    strict_command_detection: bool = False
    context_window_override: int | None = None  # Override context window for all models
    gcp_project_id: str | None = None
    gemini_credentials_path: str | None = None
    disable_health_checks: bool = False
    enable_activity_tracking: bool = False  # Disabled by default for performance

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

    # SSO authentication settings
    sso: SSOConfig | None = None

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
    assessment: AssessmentConfig = Field(default_factory=AssessmentConfig)

    # Reasoning aliases settings
    reasoning_aliases: ReasoningAliasesConfig = Field(
        default_factory=lambda: ReasoningAliasesConfig(reasoning_alias_settings=[])
    )

    # Model name rewrite rules
    model_aliases: list[ModelAliasRule] = Field(default_factory=list)

    # Sandboxing settings
    sandboxing: SandboxingConfiguration = Field(default_factory=SandboxingConfiguration)

    # Codebuff WebSocket server settings
    codebuff: CodebuffConfig = Field(default_factory=CodebuffConfig)

    # Usage tracking settings
    usage_tracking: UsageTrackingConfig = Field(default_factory=UsageTrackingConfig)

    # Replacement settings
    replacement: ReplacementConfig = Field(default_factory=ReplacementConfig)

    # Health check settings for backend endpoints
    health_check: HealthCheckConfig = Field(default_factory=HealthCheckConfig)

    # Routing settings
    routing: RoutingConfig = Field(default_factory=RoutingConfig)

    # Virtual Tool Calling (VTC) client detection patterns
    # Case-insensitive substring matching against User-Agent header
    vtc_client_patterns: list[str] = Field(
        default_factory=lambda: ["cline", "kilo", "roo"]
    )

    # FastAPI app instance
    app: Any = None

    def model_is_functional(self, model_id: str) -> bool:
        """Check if a model is available in any functional backend."""
        return self.backends.model_is_functional(model_id)

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
            "sso",
            "session",
            "backends",
            "default_backend",
            "reasoning_aliases",
            "model_aliases",
            "sandboxing",
            "codebuff",
            "usage_tracking",
            "replacement",
            "health_check",
            "routing",
            "vtc_client_patterns",
        }
        data = {k: v for k, v in data.items() if k in allowed_top_keys}
        # Ensure nested sections only include serializable primitives
        # (model_dump already handles pydantic models)
        if p.suffix.lower() in {".yaml", ".yml"}:
            import yaml

            if logger.isEnabledFor(logging.DEBUG):
                logger.debug(f"Saving configuration to {p}: {data}")
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
        env: Mapping[str, str] = os.environ if environ is None else environ

        # Build configuration from environment
        config: dict[str, Any] = {
            # Server settings
            "gcp_project_id": _get_env_value(
                env,
                "GOOGLE_CLOUD_PROJECT",
                _get_env_value(
                    env,
                    "GCP_PROJECT_ID",
                    None,
                    path="gcp_project_id",
                    resolution=resolution,
                ),
                path="gcp_project_id",
                resolution=resolution,
            ),
            "gemini_credentials_path": _get_env_value(
                env,
                "GEMINI_CREDENTIALS_PATH",
                None,
                path="gemini_credentials_path",
                resolution=resolution,
            ),
            "disable_health_checks": _env_to_bool(
                "DISABLE_HEALTH_CHECKS",
                False,
                env,
                path="disable_health_checks",
                resolution=resolution,
            ),
            "enable_activity_tracking": _env_to_bool(
                "ENABLE_ACTIVITY_TRACKING",
                False,
                env,
                path="enable_activity_tracking",
                resolution=resolution,
            ),
            "host": _get_env_value(
                env,
                "APP_HOST",
                "127.0.0.1",  # Default to localhost for security
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
            "public_url": _get_env_value(
                env,
                "PUBLIC_URL",
                None,
                path="public_url",
                resolution=resolution,
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

        # Anthropic port is no longer automatically derived to avoid port conflicts
        # if not config.get("anthropic_port"):
        #     config["anthropic_port"] = int(config["port"]) + 1
        #     if resolution is not None:
        #         resolution.record(
        #             "anthropic_port",
        #             config["anthropic_port"],
        #             ParameterSource.DERIVED,
        #             origin="port+1",
        #         )

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
            "project_dir_resolution_model": _get_env_value(
                env,
                "PROJECT_DIR_RESOLUTION_MODEL",
                None,
                path="session.project_dir_resolution_model",
                resolution=resolution,
            ),
            "project_dir_resolution_mode": _get_env_value(
                env,
                "PROJECT_DIR_RESOLUTION_MODE",
                "hybrid",
                path="session.project_dir_resolution_mode",
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
            "test_execution_reminder_enabled": _env_to_bool(
                "TEST_EXECUTION_REMINDER_ENABLED",
                False,
                env,
                path="session.test_execution_reminder_enabled",
                resolution=resolution,
            ),
            "test_execution_reminder_message": _get_env_value(
                env,
                "TEST_EXECUTION_REMINDER_MESSAGE",
                None,
                path="session.test_execution_reminder_message",
                resolution=resolution,
            ),
            "fix_think_tags_enabled": _env_to_bool(
                "FIX_THINK_TAGS_ENABLED",
                False,
                env,
                path="session.fix_think_tags_enabled",
                resolution=resolution,
            ),
            "fix_think_tags_streaming_buffer_size": _env_to_int(
                "FIX_THINK_TAGS_STREAMING_BUFFER_SIZE",
                4096,
                env,
                path="session.fix_think_tags_streaming_buffer_size",
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
            "force_reprocess_tool_calls": _env_to_bool(
                "FORCE_REPROCESS_TOOL_CALLS",
                False,
                env,
                path="session.force_reprocess_tool_calls",
                resolution=resolution,
            ),
            "log_skipped_tool_calls": _env_to_bool(
                "LOG_SKIPPED_TOOL_CALLS",
                False,
                env,
                path="session.log_skipped_tool_calls",
                resolution=resolution,
            ),
            # Angel verification model selection via env var
            "angel_model": _get_env_value(
                env,
                "ANGEL_MODEL",
                None,
                path="session.angel_model",
                resolution=resolution,
            ),
            "angel_frequency": _env_to_int(
                "ANGEL_FREQUENCY",
                1,
                env,
                path="session.angel_frequency",
                resolution=resolution,
            ),
            # Streaming sampler configuration
            "streaming_sampler": {
                "enabled": _env_to_bool(
                    "STREAMING_SAMPLER_ENABLED",
                    True,
                    env,
                    path="session.streaming_sampler.enabled",
                    resolution=resolution,
                ),
                "sample_rate": _env_to_float(
                    "STREAMING_SAMPLER_RATE",
                    0.01,
                    env,
                    path="session.streaming_sampler.sample_rate",
                    resolution=resolution,
                ),
                "max_samples": _env_to_int(
                    "STREAMING_SAMPLER_MAX_SAMPLES",
                    100,
                    env,
                    path="session.streaming_sampler.max_samples",
                    resolution=resolution,
                ),
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

        # Assessment configuration from environment
        config["assessment"] = {
            "enabled": _env_to_bool(
                "LLM_ASSESSMENT_ENABLED",
                False,
                env,
                path="assessment.enabled",
                resolution=resolution,
            ),
            "turn_threshold": _env_to_int(
                "LLM_ASSESSMENT_TURN_THRESHOLD",
                30,
                env,
                path="assessment.turn_threshold",
                resolution=resolution,
            ),
            "confidence_threshold": _env_to_float(
                "LLM_ASSESSMENT_CONFIDENCE_THRESHOLD",
                0.9,
                env,
                path="assessment.confidence_threshold",
                resolution=resolution,
            ),
            "backend": _get_env_value(
                env,
                "LLM_ASSESSMENT_BACKEND",
                "openai",  # Default backend
                path="assessment.backend",
                resolution=resolution,
            ),
            "model": _get_env_value(
                env,
                "LLM_ASSESSMENT_MODEL",
                "gpt-4o-mini",  # Default model
                path="assessment.model",
                resolution=resolution,
            ),
            "history_window": _env_to_int(
                "LLM_ASSESSMENT_HISTORY_WINDOW",
                20,
                env,
                path="assessment.history_window",
                resolution=resolution,
            ),
        }

        # Sandboxing configuration from environment
        config["sandboxing"] = {
            "enabled": _env_to_bool(
                "ENABLE_SANDBOXING",
                False,
                env,
                path="sandboxing.enabled",
                resolution=resolution,
            ),
            "strict_mode": _env_to_bool(
                "SANDBOXING_STRICT_MODE",
                False,
                env,
                path="sandboxing.strict_mode",
                resolution=resolution,
            ),
            "allow_parent_access": _env_to_bool(
                "SANDBOXING_ALLOW_PARENT_ACCESS",
                False,
                env,
                path="sandboxing.allow_parent_access",
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
            ),
            "disable_gemini_oauth_fallback": _env_to_bool(
                "DISABLE_GEMINI_OAUTH_FALLBACK",
                False,
                env,
                path="backends.disable_gemini_oauth_fallback",
                resolution=resolution,
            ),
            "disable_hybrid_backend": _env_to_bool(
                "DISABLE_HYBRID_BACKEND",
                False,
                env,
                path="backends.disable_hybrid_backend",
                resolution=resolution,
            ),
            "hybrid_backend_repeat_messages": _env_to_bool(
                "HYBRID_BACKEND_REPEAT_MESSAGES",
                False,
                env,
                path="backends.hybrid_backend_repeat_messages",
                resolution=resolution,
            ),
            "reasoning_injection_probability": _env_to_float(
                "REASONING_INJECTION_PROBABILITY",
                1.0,
                env,
                path="backends.reasoning_injection_probability",
                resolution=resolution,
            ),
            "hybrid_reasoning_model_timeout": _env_to_int(
                "HYBRID_REASONING_MODEL_TIMEOUT",
                60,
                env,
                path="backends.hybrid_reasoning_model_timeout",
                resolution=resolution,
            ),
            "hybrid_reasoning_force_initial_turns": _env_to_int(
                "HYBRID_REASONING_FORCE_INITIAL_TURNS",
                1,
                env,
                path="backends.hybrid_reasoning_force_initial_turns",
                resolution=resolution,
            ),
            "hybrid_execution_model_timeout": _env_to_int(
                "HYBRID_EXECUTION_MODEL_TIMEOUT",
                120,
                env,
                path="backends.hybrid_execution_model_timeout",
                resolution=resolution,
            ),
        }

        # Routing configuration
        config["routing"] = {
            "disable_backend_ids": _env_to_bool(
                "DISABLE_ROUTING_WITH_BACKEND_IDS",
                False,
                env,
                path="routing.disable_backend_ids",
                resolution=resolution,
            ),
            "disable_backend_names": _env_to_bool(
                "DISABLE_ROUTING_WITH_BACKEND_NAMES",
                False,
                env,
                path="routing.disable_backend_names",
                resolution=resolution,
            ),
            "disable_model_names": _env_to_bool(
                "DISABLE_ROUTING_WITH_ONLY_MODEL_NAMES",
                False,
                env,
                path="routing.disable_model_names",
                resolution=resolution,
            ),
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
        if env.get("OPENROUTER_API_KEY"):
            config_backends["openrouter"] = config_backends.get("openrouter", {})
            config_backends["openrouter"]["api_key"] = env["OPENROUTER_API_KEY"]
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
                    origin="OPENROUTER_API_KEY",
                )

        if env.get("GEMINI_API_KEY"):
            config_backends["gemini"] = config_backends.get("gemini", {})
            config_backends["gemini"]["api_key"] = env["GEMINI_API_KEY"]
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
                    origin="GEMINI_API_KEY",
                )

        if env.get("ANTHROPIC_API_KEY"):
            config_backends["anthropic"] = config_backends.get("anthropic", {})
            config_backends["anthropic"]["api_key"] = env["ANTHROPIC_API_KEY"]
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
                    origin="ANTHROPIC_API_KEY",
                )

        if env.get("ZAI_API_KEY"):
            config_backends["zai"] = config_backends.get("zai", {})
            config_backends["zai"]["api_key"] = env["ZAI_API_KEY"]
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
                    origin="ZAI_API_KEY",
                )

        if env.get("ZENMUX_API_KEY"):
            config_backends["zenmux"] = config_backends.get("zenmux", {})
            config_backends["zenmux"]["api_key"] = env["ZENMUX_API_KEY"]
            config_backends["zenmux"]["api_url"] = _get_env_value(
                env,
                "ZENMUX_API_BASE_URL",
                "https://zenmux.ai/api/v1",
                path="backends.zenmux.api_url",
                resolution=resolution,
            )
            zenmux_timeout = _get_env_value(
                env,
                "ZENMUX_TIMEOUT",
                None,
                path="backends.zenmux.timeout",
                resolution=resolution,
                transform=lambda value: _to_int(value, 0),
            )
            if zenmux_timeout:
                config_backends["zenmux"]["timeout"] = zenmux_timeout
            if resolution is not None:
                resolution.record(
                    "backends.zenmux.api_key",
                    config_backends["zenmux"]["api_key"],
                    ParameterSource.ENVIRONMENT,
                    origin="ZENMUX_API_KEY",
                )

        if env.get("OPENAI_API_KEY"):
            config_backends["openai"] = config_backends.get("openai", {})
            config_backends["openai"]["api_key"] = env["OPENAI_API_KEY"]
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
                    origin="OPENAI_API_KEY",
                )

        if env.get("MINIMAX_API_KEY"):
            config_backends["minimax"] = config_backends.get("minimax", {})
            config_backends["minimax"]["api_key"] = env["MINIMAX_API_KEY"]
            config_backends["minimax"]["api_url"] = _get_env_value(
                env,
                "MINIMAX_API_BASE_URL",
                "https://api.minimax.io/v1",
                path="backends.minimax.api_url",
                resolution=resolution,
            )
            minimax_timeout = _get_env_value(
                env,
                "MINIMAX_TIMEOUT",
                None,
                path="backends.minimax.timeout",
                resolution=resolution,
                transform=lambda value: _to_int(value, 0),
            )
            if minimax_timeout:
                config_backends["minimax"]["timeout"] = minimax_timeout
            if resolution is not None:
                resolution.record(
                    "backends.minimax.api_key",
                    config_backends["minimax"]["api_key"],
                    ParameterSource.ENVIRONMENT,
                    origin="MINIMAX_API_KEY",
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

        # Replacement configuration
        config["replacement"] = {
            "enabled": _env_to_bool(
                "REPLACEMENT_ENABLED",
                False,
                env,
                path="replacement.enabled",
                resolution=resolution,
            ),
            "probability": _env_to_float(
                "REPLACEMENT_PROBABILITY",
                0.0,
                env,
                path="replacement.probability",
                resolution=resolution,
            ),
            "backend_model": _get_env_value(
                env,
                "REPLACEMENT_BACKEND_MODEL",
                "",
                path="replacement.backend_model",
                resolution=resolution,
            ),
            "turn_count": _env_to_int(
                "REPLACEMENT_TURN_COUNT",
                1,
                env,
                path="replacement.turn_count",
                resolution=resolution,
            ),
        }

        # SSO authentication configuration
        sso_enabled = _env_to_bool(
            "SSO_ENABLED",
            False,
            env,
            path="sso.enabled",
            resolution=resolution,
        )

        if sso_enabled:
            from src.core.auth.sso.config import (
                AuthorizationConfig,
                CaptchaConfig,
                SSOConfig,
            )

            captcha_enabled = _env_to_bool(
                "SSO_CAPTCHA_ENABLED",
                True,
                env,
                path="sso.captcha.enabled",
                resolution=resolution,
            )

            captcha_config = CaptchaConfig(
                enabled=captcha_enabled,
                provider=_get_env_value(
                    env,
                    "SSO_CAPTCHA_PROVIDER",
                    "cloudflare_turnstile",
                    path="sso.captcha.provider",
                    resolution=resolution,
                ),
                site_key=_get_env_value(
                    env,
                    "SSO_CAPTCHA_SITE_KEY",
                    None,
                    path="sso.captcha.site_key",
                    resolution=resolution,
                ),
                secret_key=_get_env_value(
                    env,
                    "SSO_CAPTCHA_SECRET_KEY",
                    None,
                    path="sso.captcha.secret_key",
                    resolution=resolution,
                ),
                verify_url=_get_env_value(
                    env,
                    "SSO_CAPTCHA_VERIFY_URL",
                    "https://challenges.cloudflare.com/turnstile/v0/siteverify",
                    path="sso.captcha.verify_url",
                    resolution=resolution,
                ),
                widget_mode=_get_env_value(
                    env,
                    "SSO_CAPTCHA_WIDGET_MODE",
                    "invisible",
                    path="sso.captcha.widget_mode",
                    resolution=resolution,
                ),
                timeout_seconds=_env_to_float(
                    "SSO_CAPTCHA_TIMEOUT_SECONDS",
                    5.0,
                    env,
                    path="sso.captcha.timeout_seconds",
                    resolution=resolution,
                ),
            )

            # Load SSO configuration from environment
            config["sso"] = SSOConfig(
                enabled=True,
                session_lifetime_hours=_env_to_int(
                    "SSO_SESSION_LIFETIME_HOURS",
                    24,
                    env,
                    path="sso.session_lifetime_hours",
                    resolution=resolution,
                ),
                database_path=_get_env_value(
                    env,
                    "SSO_DATABASE_PATH",
                    "./var/sso_auth.db",
                    path="sso.database_path",
                    resolution=resolution,
                ),
                authorization=AuthorizationConfig(
                    mode=_get_env_value(
                        env,
                        "SSO_AUTH_MODE",
                        "single_user",
                        path="sso.authorization.mode",
                        resolution=resolution,
                    ),
                    api_url=_get_env_value(
                        env,
                        "SSO_AUTH_API_URL",
                        None,
                        path="sso.authorization.api_url",
                        resolution=resolution,
                    ),
                    api_timeout=_env_to_int(
                        "SSO_AUTH_API_TIMEOUT",
                        30,
                        env,
                        path="sso.authorization.api_timeout",
                        resolution=resolution,
                    ),
                    confirmation_code_expiry_minutes=_env_to_int(
                        "SSO_CONFIRMATION_CODE_EXPIRY_MINUTES",
                        10,
                        env,
                        path="sso.authorization.confirmation_code_expiry_minutes",
                        resolution=resolution,
                    ),
                    max_confirmation_attempts=_env_to_int(
                        "SSO_MAX_CONFIRMATION_ATTEMPTS",
                        3,
                        env,
                        path="sso.authorization.max_confirmation_attempts",
                        resolution=resolution,
                    ),
                ),
                captcha=captcha_config,
                providers={},  # Providers loaded from config file
            )
        else:
            config["sso"] = None

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

    def get_gcp_project_id(self) -> str | None:
        """Return the GCP Project ID."""
        return self.gcp_project_id


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
        val = current.get(key)
        if val is None or not isinstance(val, dict):
            current[key] = {}
        current = current[key]
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
    env = os.environ if environ is None else environ
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
