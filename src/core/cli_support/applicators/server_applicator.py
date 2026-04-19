"""Server Applicator - Extracts and applies server-related CLI arguments.

This applicator handles:
- host, port, anthropic_port
- timeout (proxy_timeout)
- command_prefix
- force_context_window (context_window_override)
- enable_activity_tracking
- request_dedup_window, disable_request_dedup
- thinking_budget

Requirements satisfied:
- 6.1: ConfigurationApplicator delegates to domain-specific applicators
- 6.2: Each domain applicator only modifies its relevant configuration section
- 6.3: Environment variables are handled within applicator's scope
"""

from __future__ import annotations

import os
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from src.core.cli_support.protocols import CliArgs, CliOverrides
    from src.core.config.parameter_resolution import ParameterResolution

# Import ParameterSource at module level for runtime use
from src.core.config.parameter_resolution import ParameterSource


class ServerApplicator:
    """Applies server-related CLI arguments to configuration.

    Handles:
    - host, port, anthropic_port: Server binding configuration
    - timeout: Proxy timeout settings
    - command_prefix: Command prefix configuration
    - force_context_window: Context window override
    - enable_activity_tracking: Activity tracking toggle
    - request_dedup_window/disable_request_dedup: Request deduplication settings
    - thinking_budget: Reasoning token budget
    """

    def apply(
        self,
        args: CliArgs,
        overrides: CliOverrides,
        resolution: ParameterResolution,
    ) -> None:
        """Apply server-related CLI arguments to configuration overrides.

        Args:
            args: Parsed command-line arguments namespace
            overrides: Dictionary to collect configuration overrides
            resolution: Parameter resolution tracker for recording sources
        """
        self._apply_host(args, overrides, resolution)
        self._apply_port(args, overrides, resolution)
        self._apply_anthropic_port(args, overrides, resolution)
        self._apply_timeout(args, overrides, resolution)
        self._apply_command_prefix(args, overrides, resolution)
        self._apply_context_window(args, overrides, resolution)
        self._apply_activity_tracking(args, overrides, resolution)
        self._apply_auto_append_first_prompt_filename(args, overrides, resolution)
        self._apply_request_dedup(args, overrides, resolution)
        self._apply_thinking_budget(args, overrides, resolution)
        self._apply_disable_stale_acp_agent_kills(args, overrides, resolution)
        self._apply_stale_acp_agent_kill_idle_seconds(args, overrides, resolution)

    def _apply_host(
        self,
        args: CliArgs,
        overrides: CliOverrides,
        resolution: ParameterResolution,
    ) -> None:
        """Apply host argument."""
        if args.host is not None:
            overrides["host"] = args.host
            resolution.record("host", args.host, ParameterSource.CLI, origin="--host")

    def _apply_port(
        self,
        args: CliArgs,
        overrides: CliOverrides,
        resolution: ParameterResolution,
    ) -> None:
        """Apply port argument and set environment variable."""
        if args.port is not None:
            overrides["port"] = args.port
            os.environ["PROXY_PORT"] = str(args.port)
            resolution.record("port", args.port, ParameterSource.CLI, origin="--port")

    def _apply_anthropic_port(
        self,
        args: CliArgs,
        overrides: CliOverrides,
        resolution: ParameterResolution,
    ) -> None:
        """Apply anthropic_port argument."""
        if getattr(args, "anthropic_port", None) is not None:
            overrides["anthropic_port"] = args.anthropic_port
            resolution.record(
                "anthropic_port",
                args.anthropic_port,
                ParameterSource.CLI,
                origin="--anthropic-port",
            )

    def _apply_timeout(
        self,
        args: CliArgs,
        overrides: CliOverrides,
        resolution: ParameterResolution,
    ) -> None:
        """Apply timeout argument."""
        if getattr(args, "timeout", None) is not None:
            overrides["proxy_timeout"] = args.timeout
            resolution.record(
                "proxy_timeout", args.timeout, ParameterSource.CLI, origin="--timeout"
            )

    def _apply_command_prefix(
        self,
        args: CliArgs,
        overrides: CliOverrides,
        resolution: ParameterResolution,
    ) -> None:
        """Apply command_prefix argument and set environment variable."""
        if getattr(args, "command_prefix", None) is not None:
            overrides["command_prefix"] = args.command_prefix
            os.environ["COMMAND_PREFIX"] = args.command_prefix
            resolution.record(
                "command_prefix",
                args.command_prefix,
                ParameterSource.CLI,
                origin="--command-prefix",
            )

    def _apply_context_window(
        self,
        args: CliArgs,
        overrides: CliOverrides,
        resolution: ParameterResolution,
    ) -> None:
        """Apply context window override and set environment variable."""
        if getattr(args, "force_context_window", None) is not None:
            overrides["context_window_override"] = args.force_context_window
            os.environ["FORCE_CONTEXT_WINDOW"] = str(args.force_context_window)
            resolution.record(
                "context_window_override",
                args.force_context_window,
                ParameterSource.CLI,
                origin="--force-context-window",
            )

    def _apply_activity_tracking(
        self,
        args: CliArgs,
        overrides: CliOverrides,
        resolution: ParameterResolution,
    ) -> None:
        """Apply activity tracking toggle and set environment variable."""
        if getattr(args, "enable_activity_tracking", None):
            overrides["enable_activity_tracking"] = True
            os.environ["ENABLE_ACTIVITY_TRACKING"] = "1"
            resolution.record(
                "enable_activity_tracking",
                True,
                ParameterSource.CLI,
                origin="--enable-activity-tracking",
            )

    def _apply_auto_append_first_prompt_filename(
        self,
        args: CliArgs,
        overrides: CliOverrides,
        resolution: ParameterResolution,
    ) -> None:
        """Apply first user-message append file path from CLI."""
        raw = getattr(args, "auto_append_first_prompt_filename", None)
        if raw is None:
            return
        overrides["auto_append_first_prompt_filename"] = raw
        if isinstance(raw, str) and raw.strip():
            os.environ["AUTO_APPEND_FIRST_PROMPT_FILENAME"] = raw.strip()
        resolution.record(
            "auto_append_first_prompt_filename",
            raw,
            ParameterSource.CLI,
            origin="--auto-append-first-prompt-filename",
        )

    def _apply_request_dedup(
        self,
        args: CliArgs,
        overrides: CliOverrides,
        resolution: ParameterResolution,
    ) -> None:
        """Apply request deduplication settings."""
        dedup_window = getattr(args, "request_dedup_window", None)
        disable_dedup = getattr(args, "disable_request_dedup", None)

        if disable_dedup:
            overrides["request_dedup_window"] = 0.0
            os.environ["LLM_REQUEST_DEDUP_WINDOW"] = "0"
            resolution.record(
                "request_dedup_window",
                0.0,
                ParameterSource.CLI,
                origin="--disable-request-dedup",
            )
        elif dedup_window is not None:
            overrides["request_dedup_window"] = dedup_window
            os.environ["LLM_REQUEST_DEDUP_WINDOW"] = str(dedup_window)
            resolution.record(
                "request_dedup_window",
                dedup_window,
                ParameterSource.CLI,
                origin="--request-dedup-window",
            )

    def _apply_thinking_budget(
        self,
        args: CliArgs,
        overrides: CliOverrides,
        resolution: ParameterResolution,
    ) -> None:
        """Apply thinking budget (reasoning tokens) setting."""
        if getattr(args, "thinking_budget", None) is not None:
            # Thinking budget goes into session.planning_phase.overrides.thinking_budget
            if "session" not in overrides:
                overrides["session"] = {}
            session_overrides = overrides["session"]
            if "planning_phase" not in session_overrides:
                session_overrides["planning_phase"] = {}
            planning_phase_overrides = session_overrides["planning_phase"]
            if "overrides" not in planning_phase_overrides:
                planning_phase_overrides["overrides"] = {}
            planning_phase_overrides["overrides"][
                "thinking_budget"
            ] = args.thinking_budget
            os.environ["THINKING_BUDGET"] = str(args.thinking_budget)
            resolution.record(
                "session.planning_phase.overrides.thinking_budget",
                args.thinking_budget,
                ParameterSource.CLI,
                origin="--thinking-budget",
            )

    def _apply_disable_stale_acp_agent_kills(
        self,
        args: CliArgs,
        overrides: CliOverrides,
        resolution: ParameterResolution,
    ) -> None:
        """Apply --disable-stale-acp-agent-kills (ACP idle process termination)."""
        raw = getattr(args, "disable_stale_acp_agent_kills", None)
        if raw is not True:
            return
        overrides["disable_stale_acp_agent_kills"] = True
        resolution.record(
            "disable_stale_acp_agent_kills",
            True,
            ParameterSource.CLI,
            origin="--disable-stale-acp-agent-kills",
        )

    def _apply_stale_acp_agent_kill_idle_seconds(
        self,
        args: CliArgs,
        overrides: CliOverrides,
        resolution: ParameterResolution,
    ) -> None:
        """Apply --stale-acp-agent-kill-idle-seconds (ACP idle process termination delay)."""
        raw = getattr(args, "stale_acp_agent_kill_idle_seconds", None)
        if raw is None:
            return
        value = float(raw)
        overrides["stale_acp_agent_kill_idle_seconds"] = value
        os.environ["STALE_ACP_AGENT_KILL_IDLE_SECONDS"] = str(value)
        resolution.record(
            "stale_acp_agent_kill_idle_seconds",
            value,
            ParameterSource.CLI,
            origin="--stale-acp-agent-kill-idle-seconds",
        )
