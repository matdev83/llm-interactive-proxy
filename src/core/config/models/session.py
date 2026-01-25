from __future__ import annotations

import logging
from typing import Any

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

    emit_legacy_steering_log: bool = True
    """Whether to emit a legacy-formatted steering log for compatibility."""

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
    client_key_includes_ip: bool = True

    enable_topic_similarity_matching: bool = False
    """Whether topic similarity matching may be used during fuzzy session resolution.

    WARNING: Topic similarity is inherently weaker than content overlap and can
    increase the risk of cross-session merges when multiple independent sessions
    discuss the same codebase. Keep this disabled unless you fully understand the
    trade-offs.
    """


class StreamingSamplerConfig(DomainModel):
    """Configuration for the streaming sampler (debugging/observability)."""

    model_config = ConfigDict(frozen=True)

    enabled: bool = True
    """Whether the streaming sampler is enabled."""

    sample_rate: float = Field(default=0.01, ge=0.0, le=1.0)
    """Probability of sampling a stream (0.0 to 1.0). Default: 1% of streams."""

    max_samples: int = Field(default=100, ge=1)
    """Maximum number of samples to retain in memory."""


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
    pytest_compression_enabled: bool = True
    pytest_compression_min_lines: int = 30
    pytest_full_suite_steering_enabled: bool | None = None
    pytest_full_suite_steering_message: str | None = None
    test_execution_reminder_enabled: bool | None = None
    test_execution_reminder_message: str | None = None
    droid_path_fix_enabled: bool = False
    fix_think_tags_enabled: bool = False
    fix_think_tags_streaming_buffer_size: int = 4096
    double_ampersand_fixes_for_windows_enabled: bool = True
    """Whether automatic && to ; replacement is enabled for Windows clients."""
    planning_phase: PlanningPhaseConfig = Field(default_factory=PlanningPhaseConfig)
    max_per_session_backends: int = 32
    session_continuity: SessionContinuityConfig = Field(
        default_factory=SessionContinuityConfig
    )
    tool_access_global_overrides: dict[str, Any] | None = None
    force_reprocess_tool_calls: bool = False
    log_skipped_tool_calls: bool = False
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

        angel_model = values.get("angel_model")
        if angel_model is not None and not isinstance(angel_model, str):
            try:
                values["angel_model"] = str(angel_model)
            except (MemoryError, RecursionError):
                # System-level exceptions from str() conversion (memory issues, recursion errors)
                # Log with context and set to None to allow model construction
                if logger.isEnabledFor(logging.WARNING):
                    logger.warning(
                        "Failed to convert angel_model to string due to system error, setting to None: value=%s, type=%s",
                        angel_model,
                        type(angel_model).__name__,
                        exc_info=True,
                    )
                values["angel_model"] = None
            except (TypeError, ValueError, RuntimeError):
                # Specific exceptions from str() conversion - TypeError for invalid __str__ return type,
                # ValueError for conversions, RuntimeError for execution errors in custom __str__
                # Log with full context and set to None to allow model construction
                if logger.isEnabledFor(logging.WARNING):
                    logger.warning(
                        "Failed to convert angel_model to string, setting to None: value=%s, type=%s",
                        angel_model,
                        type(angel_model).__name__,
                        exc_info=True,
                    )
                values["angel_model"] = None

        freq_value = values.get("angel_frequency", 1)
        try:
            freq_int = int(freq_value)
        except (TypeError, ValueError):
            freq_int = 1
        values["angel_frequency"] = freq_int if freq_int > 0 else 1

        return values
