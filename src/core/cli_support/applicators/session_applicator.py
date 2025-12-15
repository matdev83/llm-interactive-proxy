"""Session Applicator - Extracts and applies session-related CLI arguments.

This applicator handles:
- disable_interactive_mode, force_set_project, project_dir_resolution_*
- disable_interactive_commands, strict_command_detection
- use_angel_model, angel_frequency
- Planning phase settings
- Pytest settings
- Tool access overrides
- Various session flags

Requirements satisfied:
- 6.1: ConfigurationApplicator delegates to domain-specific applicators
- 6.2: Each domain applicator only modifies its relevant configuration section
- 6.3: Environment variables are handled within applicator's scope
"""

from __future__ import annotations

import os
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from src.core.cli_support.protocols import CliArgs, CliOverrides
    from src.core.config.parameter_resolution import ParameterResolution

from src.core.config.parameter_resolution import ParameterSource


class SessionApplicator:
    """Applies session-related CLI arguments to configuration.

    Handles:
    - Interactive mode settings
    - Project settings
    - Planning phase configuration
    - Pytest settings
    - Tool access overrides
    - Various session flags
    """

    def apply(
        self,
        args: CliArgs,
        overrides: CliOverrides,
        resolution: ParameterResolution,
    ) -> None:
        """Apply session-related CLI arguments to configuration overrides.

        Args:
            args: Parsed command-line arguments namespace
            overrides: Dictionary to collect configuration overrides
            resolution: Parameter resolution tracker for recording sources
        """
        self._apply_interactive_settings(args, overrides, resolution)
        self._apply_project_settings(args, overrides, resolution)
        self._apply_angel_settings(args, overrides, resolution)
        self._apply_planning_phase(args, overrides, resolution)
        self._apply_pytest_settings(args, overrides, resolution)
        self._apply_tool_access(args, overrides, resolution)
        self._apply_session_flags(args, overrides, resolution)
        self._apply_strict_command_detection(args, overrides, resolution)
        self._apply_accounting(args, overrides, resolution)

    def _apply_interactive_settings(
        self,
        args: CliArgs,
        overrides: CliOverrides,
        resolution: ParameterResolution,
    ) -> None:
        """Apply interactive mode settings."""
        if getattr(args, "disable_interactive_mode", None) is not None:
            session = overrides.setdefault("session", {})
            session["default_interactive_mode"] = not args.disable_interactive_mode
            os.environ["DEFAULT_INTERACTIVE_MODE"] = (
                "false" if args.disable_interactive_mode else "true"
            )
            os.environ["DISABLE_INTERACTIVE_MODE"] = (
                "True" if args.disable_interactive_mode else "False"
            )
            resolution.record(
                "session.default_interactive_mode",
                not args.disable_interactive_mode,
                ParameterSource.CLI,
                origin="--disable-interactive-mode",
            )

        if getattr(args, "disable_interactive_commands", None) is not None:
            session = overrides.setdefault("session", {})
            session["disable_interactive_commands"] = args.disable_interactive_commands
            resolution.record(
                "session.disable_interactive_commands",
                args.disable_interactive_commands,
                ParameterSource.CLI,
                origin="--disable-interactive-commands",
            )

    def _apply_project_settings(
        self,
        args: CliArgs,
        overrides: CliOverrides,
        resolution: ParameterResolution,
    ) -> None:
        """Apply project-related settings."""
        if getattr(args, "force_set_project", None) is not None:
            session = overrides.setdefault("session", {})
            session["force_set_project"] = args.force_set_project
            os.environ["FORCE_SET_PROJECT"] = (
                "true" if args.force_set_project else "false"
            )
            resolution.record(
                "session.force_set_project",
                args.force_set_project,
                ParameterSource.CLI,
                origin="--force-set-project",
            )

        if getattr(args, "project_dir_resolution_model", None) is not None:
            session = overrides.setdefault("session", {})
            session["project_dir_resolution_model"] = args.project_dir_resolution_model
            resolution.record(
                "session.project_dir_resolution_model",
                args.project_dir_resolution_model,
                ParameterSource.CLI,
                origin="--project-dir-resolution-model",
            )

        if getattr(args, "project_dir_resolution_mode", None) is not None:
            session = overrides.setdefault("session", {})
            session["project_dir_resolution_mode"] = args.project_dir_resolution_mode
            resolution.record(
                "session.project_dir_resolution_mode",
                args.project_dir_resolution_mode,
                ParameterSource.CLI,
                origin="--project-dir-resolution-mode",
            )

    def _apply_angel_settings(
        self,
        args: CliArgs,
        overrides: CliOverrides,
        resolution: ParameterResolution,
    ) -> None:
        """Apply Angel model settings."""
        if getattr(args, "use_angel_model", None) is not None:
            session = overrides.setdefault("session", {})
            session["angel_model"] = args.use_angel_model
            os.environ["ANGEL_MODEL"] = args.use_angel_model
            resolution.record(
                "session.angel_model",
                args.use_angel_model,
                ParameterSource.CLI,
                origin="--use-angel-model",
            )

        if getattr(args, "angel_frequency", None) is not None:
            frequency = max(1, int(args.angel_frequency))
            session = overrides.setdefault("session", {})
            session["angel_frequency"] = frequency
            os.environ["ANGEL_FREQUENCY"] = str(frequency)
            resolution.record(
                "session.angel_frequency",
                frequency,
                ParameterSource.CLI,
                origin="--angel-frequency",
            )

    def _apply_planning_phase(
        self,
        args: CliArgs,
        overrides: CliOverrides,
        resolution: ParameterResolution,
    ) -> None:
        """Apply planning phase settings."""
        planning_phase_args_present = any(
            [
                getattr(args, "enable_planning_phase", None) is not None,
                getattr(args, "planning_phase_strong_model", None) is not None,
                getattr(args, "planning_phase_max_turns", None) is not None,
                getattr(args, "planning_phase_max_file_writes", None) is not None,
                getattr(args, "planning_phase_temperature", None) is not None,
                getattr(args, "planning_phase_top_p", None) is not None,
                getattr(args, "planning_phase_reasoning_effort", None) is not None,
                getattr(args, "planning_phase_thinking_budget", None) is not None,
            ]
        )

        if not planning_phase_args_present:
            return

        session = overrides.setdefault("session", {})
        planning_phase = session.setdefault("planning_phase", {})

        if getattr(args, "enable_planning_phase", None) is not None:
            planning_phase["enabled"] = args.enable_planning_phase
            resolution.record(
                "session.planning_phase.enabled",
                args.enable_planning_phase,
                ParameterSource.CLI,
                origin="--enable-planning-phase",
            )

        if getattr(args, "planning_phase_strong_model", None) is not None:
            planning_phase["strong_model"] = args.planning_phase_strong_model
            resolution.record(
                "session.planning_phase.strong_model",
                args.planning_phase_strong_model,
                ParameterSource.CLI,
                origin="--planning-phase-strong-model",
            )

        if getattr(args, "planning_phase_max_turns", None) is not None:
            planning_phase["max_turns"] = max(1, args.planning_phase_max_turns)
            resolution.record(
                "session.planning_phase.max_turns",
                planning_phase["max_turns"],
                ParameterSource.CLI,
                origin="--planning-phase-max-turns",
            )

        if getattr(args, "planning_phase_max_file_writes", None) is not None:
            planning_phase["max_file_writes"] = max(
                1, args.planning_phase_max_file_writes
            )
            resolution.record(
                "session.planning_phase.max_file_writes",
                planning_phase["max_file_writes"],
                ParameterSource.CLI,
                origin="--planning-phase-max-file-writes",
            )

        # Planning phase overrides
        overrides_updates: dict[str, Any] = {}
        if getattr(args, "planning_phase_temperature", None) is not None:
            overrides_updates["temperature"] = args.planning_phase_temperature
        if getattr(args, "planning_phase_top_p", None) is not None:
            overrides_updates["top_p"] = args.planning_phase_top_p
        if getattr(args, "planning_phase_reasoning_effort", None) is not None:
            overrides_updates["reasoning_effort"] = args.planning_phase_reasoning_effort
        if getattr(args, "planning_phase_thinking_budget", None) is not None:
            overrides_updates["thinking_budget"] = args.planning_phase_thinking_budget

        if overrides_updates:
            existing_overrides = planning_phase.setdefault("overrides", {})
            existing_overrides.update(overrides_updates)
            flag_mapping = {
                "temperature": "--planning-phase-temperature",
                "top_p": "--planning-phase-top-p",
                "reasoning_effort": "--planning-phase-reasoning-effort",
                "thinking_budget": "--planning-phase-thinking-budget",
            }
            for key, value in overrides_updates.items():
                resolution.record(
                    f"session.planning_phase.overrides.{key}",
                    value,
                    ParameterSource.CLI,
                    origin=flag_mapping.get(key, "--planning-phase-override"),
                )

    def _apply_pytest_settings(
        self,
        args: CliArgs,
        overrides: CliOverrides,
        resolution: ParameterResolution,
    ) -> None:
        """Apply pytest-related settings."""
        if getattr(args, "pytest_compression_enabled", None) is not None:
            session = overrides.setdefault("session", {})
            session["pytest_compression_enabled"] = args.pytest_compression_enabled
            resolution.record(
                "session.pytest_compression_enabled",
                args.pytest_compression_enabled,
                ParameterSource.CLI,
                origin="--enable-pytest-compression",
            )

        if getattr(args, "pytest_full_suite_steering_enabled", None) is not None:
            session = overrides.setdefault("session", {})
            session["pytest_full_suite_steering_enabled"] = (
                args.pytest_full_suite_steering_enabled
            )
            tool_call_reactor = session.setdefault("tool_call_reactor", {})
            tool_call_reactor["pytest_full_suite_steering_enabled"] = (
                args.pytest_full_suite_steering_enabled
            )
            resolution.record(
                "session.pytest_full_suite_steering_enabled",
                args.pytest_full_suite_steering_enabled,
                ParameterSource.CLI,
                origin="--enable/disable-pytest-full-suite-steering",
            )

        if getattr(args, "disable_binary_file_edit_steering", None) is True:
            session = overrides.setdefault("session", {})
            tool_call_reactor = session.setdefault("tool_call_reactor", {})
            tool_call_reactor["binary_file_edit_steering_enabled"] = False
            resolution.record(
                "session.tool_call_reactor.binary_file_edit_steering_enabled",
                False,
                ParameterSource.CLI,
                origin="--disable-binary-file-edit-steering",
            )

        if getattr(args, "test_execution_reminder_enabled", None) is not None:
            session = overrides.setdefault("session", {})
            session["test_execution_reminder_enabled"] = (
                args.test_execution_reminder_enabled
            )
            tool_call_reactor = session.setdefault("tool_call_reactor", {})
            tool_call_reactor["test_execution_reminder_enabled"] = (
                args.test_execution_reminder_enabled
            )
            resolution.record(
                "session.test_execution_reminder_enabled",
                args.test_execution_reminder_enabled,
                ParameterSource.CLI,
                origin="--test-execution-reminder-enabled/--no-test-execution-reminder-enabled",
            )

        if getattr(args, "pytest_context_saving_enabled", None) is not None:
            session = overrides.setdefault("session", {})
            tool_call_reactor = session.setdefault("tool_call_reactor", {})
            tool_call_reactor["pytest_context_saving_enabled"] = (
                args.pytest_context_saving_enabled
            )
            resolution.record(
                "session.tool_call_reactor.pytest_context_saving_enabled",
                args.pytest_context_saving_enabled,
                ParameterSource.CLI,
                origin="--enable-pytest-context-saving",
            )

    def _apply_tool_access(
        self,
        args: CliArgs,
        overrides: CliOverrides,
        resolution: ParameterResolution,
    ) -> None:
        """Apply tool access overrides."""
        tool_access_overrides: dict[str, Any] = {}

        if getattr(args, "tool_access_allowed_tools", None) is not None:
            patterns = [
                p.strip()
                for p in args.tool_access_allowed_tools.split(",")
                if p.strip()
            ]
            tool_access_overrides["allowed_patterns"] = patterns
            resolution.record(
                "tool_access.allowed_patterns",
                patterns,
                ParameterSource.CLI,
                origin="--allowed-tools",
            )

        if getattr(args, "tool_access_blocked_tools", None) is not None:
            patterns = [
                p.strip()
                for p in args.tool_access_blocked_tools.split(",")
                if p.strip()
            ]
            tool_access_overrides["blocked_patterns"] = patterns
            resolution.record(
                "tool_access.blocked_patterns",
                patterns,
                ParameterSource.CLI,
                origin="--blocked-tools",
            )

        if getattr(args, "tool_access_default_policy", None) is not None:
            tool_access_overrides["default_policy"] = args.tool_access_default_policy
            resolution.record(
                "tool_access.default_policy",
                args.tool_access_default_policy,
                ParameterSource.CLI,
                origin="--default-policy",
            )

        if tool_access_overrides:
            session = overrides.setdefault("session", {})
            session["tool_access_global_overrides"] = tool_access_overrides

    def _apply_session_flags(
        self,
        args: CliArgs,
        overrides: CliOverrides,
        resolution: ParameterResolution,
    ) -> None:
        """Apply various session flags."""
        if getattr(args, "droid_path_fix_enabled", None) is True:
            session = overrides.setdefault("session", {})
            session["droid_path_fix_enabled"] = True

        if getattr(args, "fix_think_tags_enabled", None) is not None:
            session = overrides.setdefault("session", {})
            session["fix_think_tags_enabled"] = args.fix_think_tags_enabled
            resolution.record(
                "session.fix_think_tags_enabled",
                args.fix_think_tags_enabled,
                ParameterSource.CLI,
                origin="--fix-think-tags",
            )

        if getattr(args, "disable_dangerous_git_commands_protection", None) is not None:
            session = overrides.setdefault("session", {})
            session["dangerous_command_prevention_enabled"] = (
                not args.disable_dangerous_git_commands_protection
            )
            resolution.record(
                "session.dangerous_command_prevention_enabled",
                not args.disable_dangerous_git_commands_protection,
                ParameterSource.CLI,
                origin="--disable-dangerous-git-commands-protection",
            )

        if (
            getattr(args, "disable_double_ampersand_fixes_for_windows", None)
            is not None
        ):
            session = overrides.setdefault("session", {})
            session["double_ampersand_fixes_for_windows_enabled"] = (
                not args.disable_double_ampersand_fixes_for_windows
            )
            resolution.record(
                "session.double_ampersand_fixes_for_windows_enabled",
                not args.disable_double_ampersand_fixes_for_windows,
                ParameterSource.CLI,
                origin="--disable-double-ampersand-fixes-for-windows",
            )

    def _apply_strict_command_detection(
        self,
        args: CliArgs,
        overrides: CliOverrides,
        resolution: ParameterResolution,
    ) -> None:
        """Apply strict command detection setting."""
        if getattr(args, "strict_command_detection", None) is not None:
            overrides["strict_command_detection"] = args.strict_command_detection
            resolution.record(
                "strict_command_detection",
                args.strict_command_detection,
                ParameterSource.CLI,
                origin="--strict-command-detection",
            )

    def _apply_accounting(
        self,
        args: CliArgs,
        overrides: CliOverrides,
        resolution: ParameterResolution,
    ) -> None:
        """Apply accounting settings."""
        if getattr(args, "disable_accounting", None) is not None:
            os.environ["DISABLE_ACCOUNTING"] = (
                "true" if args.disable_accounting else "false"
            )
            resolution.record(
                "cli.disable_accounting",
                args.disable_accounting,
                ParameterSource.CLI,
                origin="--disable-accounting",
            )
