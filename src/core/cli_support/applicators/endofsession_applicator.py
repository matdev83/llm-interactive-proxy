"""EndOfSession Applicator - Extracts and applies end-of-session CLI arguments.

This applicator handles:
- end_of_session_enabled
- end_of_session_emit_events
- end_of_session_dispatch_timeout_seconds

Requirements satisfied:
- 6.1: ConfigurationApplicator delegates to domain-specific applicators
- 6.2: Each domain applicator only modifies its relevant configuration section
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from src.core.cli_support.protocols import CliArgs, CliOverrides
    from src.core.config.parameter_resolution import ParameterResolution

from src.core.config.parameter_resolution import ParameterSource


class EndOfSessionApplicator:
    """Applies end-of-session CLI arguments to configuration."""

    def apply(
        self,
        args: CliArgs,
        overrides: CliOverrides,
        resolution: ParameterResolution,
    ) -> None:
        """Apply end-of-session CLI arguments to configuration overrides."""
        eos_overrides: dict[str, Any] = {}

        if getattr(args, "end_of_session_enabled", None) is not None:
            eos_overrides["enabled"] = args.end_of_session_enabled
            resolution.record(
                "end_of_session.enabled",
                args.end_of_session_enabled,
                ParameterSource.CLI,
                origin="--enable-end-of-session/--disable-end-of-session",
            )

        if getattr(args, "end_of_session_emit_events", None) is not None:
            eos_overrides["emit_events"] = args.end_of_session_emit_events
            resolution.record(
                "end_of_session.emit_events",
                args.end_of_session_emit_events,
                ParameterSource.CLI,
                origin="--end-of-session-emit-events/--end-of-session-detect-only",
            )

        dispatch_timeout = getattr(
            args, "end_of_session_dispatch_timeout_seconds", None
        )
        if dispatch_timeout is not None:
            eos_overrides["dispatch_timeout_seconds"] = dispatch_timeout
            resolution.record(
                "end_of_session.dispatch_timeout_seconds",
                dispatch_timeout,
                ParameterSource.CLI,
                origin="--end-of-session-dispatch-timeout",
            )

        if eos_overrides:
            overrides["end_of_session"] = eos_overrides
