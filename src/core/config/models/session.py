from __future__ import annotations

import logging
import re
from typing import Any, Literal

from pydantic import ConfigDict, Field, field_validator, model_validator

from src.core.interfaces.model_bases import DomainModel
from src.services.steering.models import SteeringRule

logger = logging.getLogger(__name__)


class ToolCallReactorConfig(DomainModel):
    """Configuration for the Tool Call Reactor system.

    The Tool Call Reactor provides event-driven reactions to tool calls
    from LLMs, allowing custom handlers to monitor, modify, or replace responses.
    """

    model_config = ConfigDict(frozen=True)

    enabled: bool = True
    """Whether the Tool Call Reactor is enabled."""

    unified_steering_enabled: bool = True
    """DEPRECATED: Unified steering is now the only implementation.

    This field is kept for backward compatibility but is ignored.
    Legacy steering handlers have been removed.
    """

    steering_policy_priorities: dict[str, int] | None = None
    """Overrides for steering policy priorities. Map of policy name to priority integer."""

    steering_session_ttl_seconds: int = 1800
    """TTL in seconds for steering session state (default 30 mins)."""

    steering_max_sessions: int = 1024
    """Maximum number of sessions to track in steering state store."""

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

    inline_python_steering_enabled: bool = True
    """Whether inline Python execution steering is enabled."""

    inline_python_steering_message: str | None = None
    """Optional custom steering message for inline Python execution."""

    binary_file_edit_steering_enabled: bool = True
    """Whether binary file edit steering is enabled."""

    binary_file_edit_steering_message: str | None = None
    """Optional custom steering message for binary file edit attempts."""

    cat_file_edits_steering_enabled: bool = False
    """Whether steering for cat output redirection (cat > / cat >>) is enabled."""

    cat_file_edits_steering_message: str | None = None
    """Optional custom steering message for cat-based file create/append attempts."""

    pytest_context_saving_enabled: bool = False
    """Whether pytest context-saving command rewrites are enabled."""

    fix_think_tags_enabled: bool = False
    """Whether correction of improperly formatted <think> tags is enabled."""

    test_execution_reminder_enabled: bool = False
    """Whether test execution reminder steering is enabled."""

    test_execution_reminder_message: str | None = None
    """Optional custom steering message for test execution reminders."""

    steering_rules: list[SteeringRule] = Field(default_factory=list)
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
    overrides: dict[str, Any] | None = None


class SessionContinuityConfig(DomainModel):
    """Configuration for intelligent session continuity detection."""

    model_config = ConfigDict(frozen=True)

    enabled: bool = True
    fuzzy_matching: bool = True
    max_session_age_seconds: int = 604800  # 7 days
    fingerprint_message_count: int = 5
    client_key_includes_ip: bool = False

    enable_topic_similarity_matching: bool = False
    """Whether topic similarity matching may be used during fuzzy session resolution.

    WARNING: Topic similarity is inherently weaker than content overlap and can
    increase the risk of cross-session merges when multiple independent sessions
    discuss the same codebase. Keep this disabled unless you fully understand the
    trade-offs.
    """


class B2BUAConfig(DomainModel):
    """Configuration for B2BUA-like A-leg/B-leg session handling."""

    model_config = ConfigDict(frozen=True)

    enabled: bool = True
    continuity_max_age_seconds: int = Field(default=3600, ge=1)
    continuity_sliding_expiration: bool = True
    persistent_mapping_store_enabled: bool = False
    echo_enabled: bool = True
    echo_header_name: str = "x-b2bua-session-id"
    enable_unsafe_heuristic_session_inference: bool = False
    deployment_mode: Literal["single-process", "multi-worker"] = "single-process"

    @field_validator("echo_header_name")
    @classmethod
    def _validate_echo_header_name(cls, value: str) -> str:
        header_name = value.strip()
        if not header_name:
            raise ValueError("session.b2bua.echo_header_name cannot be empty")
        return header_name


class StreamingSamplerConfig(DomainModel):
    """Configuration for the streaming sampler (debugging/observability)."""

    model_config = ConfigDict(frozen=True)

    enabled: bool = True
    """Whether the streaming sampler is enabled."""

    sample_rate: float = Field(default=0.01, ge=0.0, le=1.0)
    """Probability of sampling a stream (0.0 to 1.0). Default: 1% of streams."""

    max_samples: int = Field(default=100, ge=1)
    """Maximum number of samples to retain in memory."""


ReasoningMode = Literal[
    "passthrough",
    "coerce_to_content",
    "drop",
]


class ClientCompatibilityRule(DomainModel):
    """User-Agent based default compatibility overrides.

    These rules provide sane defaults for known clients without hard-coding
    client-specific behavior into streaming services.
    """

    model_config = ConfigDict(frozen=True)

    name: str
    enabled: bool = True
    user_agent_regex: str

    reasoning_mode: ReasoningMode = "passthrough"
    reasoning_counts_as_meaningful: bool = False

    @field_validator("user_agent_regex")
    @classmethod
    def _validate_user_agent_regex(cls, value: str) -> str:
        pattern = value.strip()
        if not pattern:
            raise ValueError("user_agent_regex cannot be empty")
        try:
            re.compile(pattern)
        except re.error as exc:
            raise ValueError(f"Invalid user_agent_regex: {exc}") from exc
        return pattern


class ClientCompatibilityConfig(DomainModel):
    """Client capability overrides used by the proxy compatibility layer."""

    model_config = ConfigDict(frozen=True)

    reasoning_mode_header: str = "x-llmproxy-reasoning-mode"
    reasoning_meaningful_header: str = "x-llmproxy-reasoning-meaningful"

    user_agent_rules: list[ClientCompatibilityRule] = Field(default_factory=list)


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
    project_dir_resolution_filesystem_mode: Literal["auto", "enabled", "disabled"] = (
        "auto"
    )
    disable_default_openrouter_project_dir_resolution_fallback: bool = False
    tool_call_repair_enabled: bool = True
    tool_call_repair_buffer_cap_bytes: int = 64 * 1024
    json_repair_enabled: bool = True
    json_repair_buffer_cap_bytes: int = 64 * 1024
    json_repair_strict_mode: bool = False
    json_repair_schema: dict[str, Any] | None = None  # Added
    streaming_sampler: StreamingSamplerConfig = Field(
        default_factory=StreamingSamplerConfig
    )
    tool_call_reactor: ToolCallReactorConfig = Field(
        default_factory=ToolCallReactorConfig
    )
    dangerous_command_prevention_enabled: bool = True
    dangerous_command_steering_message: str | None = None
    pytest_full_suite_steering_enabled: bool | None = None
    pytest_full_suite_steering_message: str | None = None
    cat_file_edits_steering_enabled: bool | None = None
    cat_file_edits_steering_message: str | None = None
    test_execution_reminder_enabled: bool | None = None
    test_execution_reminder_message: str | None = None
    droid_path_fix_enabled: bool = False
    fix_think_tags_enabled: bool = False
    fix_think_tags_streaming_buffer_size: int = 4096
    double_ampersand_fixes_for_windows_enabled: bool = True
    """Whether automatic && to ; replacement is enabled for Windows clients."""
    auto_continue_removal_enabled: bool = True
    # Streaming/content loop detection (HybridLoopDetector); opt-in via CLI or env.
    streaming_loop_detection_enabled: bool = False
    planning_phase: PlanningPhaseConfig = Field(default_factory=PlanningPhaseConfig)
    max_per_session_backends: int = 32
    session_continuity: SessionContinuityConfig = Field(
        default_factory=SessionContinuityConfig
    )
    b2bua: B2BUAConfig = Field(default_factory=B2BUAConfig)

    client_compatibility: ClientCompatibilityConfig = Field(
        default_factory=ClientCompatibilityConfig
    )
    tool_access_global_overrides: dict[str, Any] | None = None
    force_reprocess_tool_calls: bool = False
    log_skipped_tool_calls: bool = False
    quality_verifier_model: str | None = None
    # Quality Verifier frequency (every N eligible turns)
    # Default intentionally conservative to limit latency/cost.
    quality_verifier_frequency: int = 10

    # Tool followup turn weight for Quality Verifier turn counting.
    # Tool followup requests (requests with tool role messages after the last user message)
    # are counted as fractional turns to ensure Quality Verifier eventually runs even in
    # tool-heavy coding sessions. A weight of 0.2 means 5 tool followups = 1 turn.
    # Set to 0.0 to exclude tool followups entirely from turn counting.
    quality_verifier_tool_followup_weight: float = 0.2

    # Optional history truncation for Quality Verifier.
    # Note: This is separate from model context-window settings and is applied only
    # for the Quality Verifier request payload.
    quality_verifier_max_history: int | None = None

    # Quality Verifier health check settings.
    # Consecutive failures to generate a valid XML response or backend errors before
    # tripping the circuit breaker for the cooldown period.
    quality_verifier_max_consecutive_failures: int = 5

    # Cooldown period in seconds when the Quality Verifier circuit breaker is tripped.
    quality_verifier_cooldown_seconds: int = 300

    # Time-to-first-token timeout in seconds for Quality Verifier backend calls.
    # If no non-keepalive token is received within this window, verifier fails-open.
    quality_verifier_ttft_timeout_seconds: float = 30.0

    # Session-level guard for repeated tool-only progress loops.
    tool_progress_loop_guard_enabled: bool = True
    tool_progress_loop_max_consecutive_followups: int = Field(default=50, ge=1)
    tool_progress_loop_max_repeated_call_signature: int = Field(default=7, ge=1)
    tool_progress_loop_max_repeated_output: int = Field(default=7, ge=1)
    tool_progress_loop_max_counts_per_session: int = Field(default=256, ge=1)
    tool_progress_loop_max_cached_sessions: int = Field(default=1000, ge=1)

    @field_validator("quality_verifier_frequency")
    @classmethod
    def _validate_quality_verifier_frequency(cls, value: int) -> int:
        try:
            freq = int(value)
        except (TypeError, ValueError):
            return 10
        return freq if freq > 0 else 1

    @field_validator("quality_verifier_tool_followup_weight")
    @classmethod
    def _validate_quality_verifier_tool_followup_weight(cls, value: float) -> float:
        try:
            weight = float(value)
        except (TypeError, ValueError):
            return 0.2
        # Clamp between 0.0 and 1.0
        return max(0.0, min(1.0, weight))

    @field_validator("quality_verifier_ttft_timeout_seconds")
    @classmethod
    def _validate_quality_verifier_ttft_timeout_seconds(cls, value: float) -> float:
        try:
            timeout = float(value)
        except (TypeError, ValueError):
            return 30.0
        return timeout if timeout > 0 else 30.0

    @model_validator(mode="before")
    @classmethod
    def _sync_pytest_full_suite_settings(cls, values: dict[str, Any]) -> dict[str, Any]:
        """Keep pytest full-suite steering settings mirrored with reactor config."""
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

        cat_enabled = values.get("cat_file_edits_steering_enabled")
        cat_message = values.get("cat_file_edits_steering_message")

        if cat_enabled is not None:
            reactor_config_dict["cat_file_edits_steering_enabled"] = cat_enabled
        else:
            values["cat_file_edits_steering_enabled"] = reactor_config_dict.get(
                "cat_file_edits_steering_enabled", False
            )

        if cat_message is not None:
            reactor_config_dict["cat_file_edits_steering_message"] = cat_message
        else:
            values["cat_file_edits_steering_message"] = reactor_config_dict.get(
                "cat_file_edits_steering_message"
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

        values["tool_call_reactor"] = reactor_config_dict

        quality_verifier_model = values.get("quality_verifier_model")
        if quality_verifier_model is not None and not isinstance(
            quality_verifier_model, str
        ):
            try:
                values["quality_verifier_model"] = str(quality_verifier_model)
            except (MemoryError, RecursionError):
                # System-level exceptions from str() conversion (memory issues, recursion errors)
                # Log with context and set to None to allow model construction
                if logger.isEnabledFor(logging.WARNING):
                    logger.warning(
                        "Failed to convert quality_verifier_model to string due to system error, setting to None: value=%s, type=%s",
                        quality_verifier_model,
                        type(quality_verifier_model).__name__,
                        exc_info=True,
                    )
                values["quality_verifier_model"] = None
            except (TypeError, ValueError, RuntimeError):
                # Specific exceptions from str() conversion - TypeError for invalid __str__ return type,
                # ValueError for conversions, RuntimeError for execution errors in custom __str__
                # Log with full context and set to None to allow model construction
                if logger.isEnabledFor(logging.WARNING):
                    logger.warning(
                        "Failed to convert quality_verifier_model to string, setting to None: value=%s, type=%s",
                        quality_verifier_model,
                        type(quality_verifier_model).__name__,
                        exc_info=True,
                    )
                values["quality_verifier_model"] = None

        freq_value = values.get("quality_verifier_frequency", 10)
        try:
            freq_int = int(freq_value)
        except (TypeError, ValueError):
            freq_int = 10
        values["quality_verifier_frequency"] = freq_int if freq_int > 0 else 1

        ttft_value = values.get("quality_verifier_ttft_timeout_seconds", 30.0)
        try:
            ttft_float = float(ttft_value)
        except (TypeError, ValueError):
            ttft_float = 30.0
        values["quality_verifier_ttft_timeout_seconds"] = (
            ttft_float if ttft_float > 0 else 30.0
        )

        return values
