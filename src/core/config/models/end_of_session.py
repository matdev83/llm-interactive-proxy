"""End-of-Session configuration model.

This module defines configuration options for end-of-session detection
and event emission, including toggles for detection, emission, and timeout settings.
"""

from __future__ import annotations

from pydantic import ConfigDict, Field, model_validator

from src.core.interfaces.model_bases import DomainModel


class EndOfSessionConfig(DomainModel):
    """Configuration for End-of-Session detection and event emission.

    This configuration controls when and how end-of-session events are detected
    and emitted. It provides toggles for different detection modes and timeout
    settings for event dispatch.

    Attributes:
        enabled: Global toggle for end-of-session detection. When False, no
            detection or emission occurs.
        emit_events: Whether to emit events (True) or only detect (False).
            When False, detection runs but no events are emitted.
        detect_stream_signals: Whether to detect completion signals in streams.
        detect_tool_completion: Whether to detect completion tool calls.
        emission_ttl_seconds: TTL in seconds for emission state (default 1 hour).
        dispatch_timeout_seconds: Maximum time to wait for event dispatch
            before continuing (default 5 seconds). Zero disables timeout.

    Note:
        Configuration precedence: CLI > ENV > YAML
        When enabled=False, other settings can be any value (fail-open).
        When enabled=True and emit_events=False, detect-only mode is enabled.
    """

    model_config = ConfigDict(frozen=True)

    enabled: bool = False
    """Global toggle for end-of-session detection and emission."""

    emit_events: bool = True
    """Whether to emit events (True) or only detect (False)."""

    detect_stream_signals: bool = True
    """Whether to detect completion signals in streaming responses."""

    detect_tool_completion: bool = True
    """Whether to detect completion tool calls."""

    emission_ttl_seconds: int = Field(default=3600, ge=0)
    """TTL in seconds for emission state (default 1 hour)."""

    dispatch_timeout_seconds: float = Field(default=5.0, ge=0.0)
    """Maximum time to wait for event dispatch before continuing (default 5 seconds).

    Zero disables timeout (fire-and-forget).
    """

    @model_validator(mode="after")
    def validate_configuration(self) -> EndOfSessionConfig:
        """Validate configuration consistency.

        When enabled=False, other settings can be any value (fail-open).
        When enabled=True and emit_events=False, detect-only mode is allowed.

        Returns:
            Self for chaining.

        Raises:
            ValueError: If configuration is invalid.
        """
        # Validation is handled by Field constraints (ge=0)
        # Additional business logic validation can be added here if needed
        return self

