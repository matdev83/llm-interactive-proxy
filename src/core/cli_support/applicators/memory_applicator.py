"""Memory Applicator - Extracts and applies ProxyMem CLI arguments.

This applicator handles ProxyMem (cross-session memory) configuration.

Requirements satisfied:
- 6.1: ConfigurationApplicator delegates to domain-specific applicators
- 6.2: Each domain applicator only modifies its relevant configuration section
"""

from __future__ import annotations

import contextlib
import os
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from src.core.cli_support.protocols import CliArgs, CliOverrides
    from src.core.config.parameter_resolution import ParameterResolution

from src.core.config.parameter_resolution import ParameterSource


def _parse_bool_env(val: str | None) -> bool | None:
    """Parse boolean from environment variable value."""
    if val is None:
        return None
    return val.lower() in ("true", "1", "yes", "on")


class MemoryApplicator:
    """Applies ProxyMem CLI arguments to configuration.

    Handles cross-session memory settings with precedence:
    CLI > env > config file
    """

    def apply(
        self,
        args: CliArgs,
        overrides: CliOverrides,
        resolution: ParameterResolution,
    ) -> None:
        """Apply memory-related CLI arguments to configuration overrides."""
        memory_overrides: dict[str, Any] = {}

        # Load from environment variables first (env overrides config file)
        self._apply_env_settings(memory_overrides)

        # CLI overrides env (CLI takes highest precedence)
        self._apply_cli_settings(args, memory_overrides, resolution)

        if memory_overrides:
            overrides["memory"] = memory_overrides

    def _apply_env_settings(self, memory_overrides: dict[str, Any]) -> None:
        """Apply settings from environment variables."""
        env_memory_available = os.environ.get("MEMORY_AVAILABLE")
        if env_memory_available is not None:
            memory_overrides["available"] = _parse_bool_env(env_memory_available)

        env_memory_default_enabled = os.environ.get("MEMORY_DEFAULT_ENABLED")
        if env_memory_default_enabled is not None:
            memory_overrides["default_enabled"] = _parse_bool_env(
                env_memory_default_enabled
            )

        if summary_model := os.environ.get("MEMORY_SUMMARY_MODEL"):
            memory_overrides["summary_model"] = summary_model

        if context_model := os.environ.get("MEMORY_CONTEXT_MODEL"):
            memory_overrides["context_model"] = context_model

        if summary_prompt := os.environ.get("MEMORY_SUMMARY_PROMPT"):
            memory_overrides["summary_prompt"] = summary_prompt

        if context_prompt := os.environ.get("MEMORY_CONTEXT_PROMPT"):
            memory_overrides["context_prompt"] = context_prompt

        if database_path := os.environ.get("MEMORY_DATABASE_PATH"):
            memory_overrides["database_path"] = database_path

        if session_timeout := os.environ.get("MEMORY_SESSION_TIMEOUT_MINUTES"):
            with contextlib.suppress(ValueError):
                memory_overrides["session_timeout_minutes"] = int(session_timeout)

        if retention_days := os.environ.get("MEMORY_RETENTION_DAYS"):
            with contextlib.suppress(ValueError):
                memory_overrides["retention_days"] = int(retention_days)

        if max_context_tokens := os.environ.get("MEMORY_MAX_CONTEXT_TOKENS"):
            with contextlib.suppress(ValueError):
                memory_overrides["max_context_tokens"] = int(max_context_tokens)

        if relevance_threshold := os.environ.get("MEMORY_CONTEXT_RELEVANCE_THRESHOLD"):
            with contextlib.suppress(ValueError):
                memory_overrides["context_relevance_threshold"] = float(
                    relevance_threshold
                )

    def _apply_cli_settings(
        self,
        args: CliArgs,
        memory_overrides: dict[str, Any],
        resolution: ParameterResolution,
    ) -> None:
        """Apply CLI settings (highest precedence)."""
        if getattr(args, "memory_available", None) is not None:
            memory_overrides["available"] = args.memory_available
            resolution.record(
                "memory.available",
                args.memory_available,
                ParameterSource.CLI,
                origin="--memory-available",
            )

        if getattr(args, "memory_default_enabled", None) is not None:
            memory_overrides["default_enabled"] = args.memory_default_enabled
            resolution.record(
                "memory.default_enabled",
                args.memory_default_enabled,
                ParameterSource.CLI,
                origin="--memory-default-enabled",
            )

        if getattr(args, "memory_summary_model", None) is not None:
            memory_overrides["summary_model"] = args.memory_summary_model
            resolution.record(
                "memory.summary_model",
                args.memory_summary_model,
                ParameterSource.CLI,
                origin="--memory-summary-model",
            )

        if getattr(args, "memory_context_model", None) is not None:
            memory_overrides["context_model"] = args.memory_context_model
            resolution.record(
                "memory.context_model",
                args.memory_context_model,
                ParameterSource.CLI,
                origin="--memory-context-model",
            )

        if getattr(args, "memory_summary_prompt", None) is not None:
            memory_overrides["summary_prompt"] = args.memory_summary_prompt
            resolution.record(
                "memory.summary_prompt",
                args.memory_summary_prompt,
                ParameterSource.CLI,
                origin="--memory-summary-prompt",
            )

        if getattr(args, "memory_context_prompt", None) is not None:
            memory_overrides["context_prompt"] = args.memory_context_prompt
            resolution.record(
                "memory.context_prompt",
                args.memory_context_prompt,
                ParameterSource.CLI,
                origin="--memory-context-prompt",
            )

        if getattr(args, "memory_database_path", None) is not None:
            memory_overrides["database_path"] = args.memory_database_path
            resolution.record(
                "memory.database_path",
                args.memory_database_path,
                ParameterSource.CLI,
                origin="--memory-database-path",
            )

        if getattr(args, "memory_session_timeout", None) is not None:
            memory_overrides["session_timeout_minutes"] = args.memory_session_timeout
            resolution.record(
                "memory.session_timeout_minutes",
                args.memory_session_timeout,
                ParameterSource.CLI,
                origin="--memory-session-timeout",
            )

        if getattr(args, "memory_retention_days", None) is not None:
            memory_overrides["retention_days"] = args.memory_retention_days
            resolution.record(
                "memory.retention_days",
                args.memory_retention_days,
                ParameterSource.CLI,
                origin="--memory-retention-days",
            )

        if getattr(args, "memory_max_context_tokens", None) is not None:
            memory_overrides["max_context_tokens"] = args.memory_max_context_tokens
            resolution.record(
                "memory.max_context_tokens",
                args.memory_max_context_tokens,
                ParameterSource.CLI,
                origin="--memory-max-context-tokens",
            )

        if getattr(args, "memory_context_relevance_threshold", None) is not None:
            memory_overrides["context_relevance_threshold"] = (
                args.memory_context_relevance_threshold
            )
            resolution.record(
                "memory.context_relevance_threshold",
                args.memory_context_relevance_threshold,
                ParameterSource.CLI,
                origin="--memory-context-relevance-threshold",
            )

        if getattr(args, "memory_single_user_mode", None) is not None:
            memory_overrides["single_user_mode"] = args.memory_single_user_mode
            resolution.record(
                "memory.single_user_mode",
                args.memory_single_user_mode,
                ParameterSource.CLI,
                origin="--memory-single-user-mode",
            )

        if getattr(args, "memory_fixed_user_id", None) is not None:
            memory_overrides["fixed_user_id"] = args.memory_fixed_user_id
            resolution.record(
                "memory.fixed_user_id",
                args.memory_fixed_user_id,
                ParameterSource.CLI,
                origin="--memory-fixed-user-id",
            )

        if getattr(args, "memory_redaction_patterns", None) is not None:
            memory_overrides["redaction_patterns"] = args.memory_redaction_patterns
            resolution.record(
                "memory.redaction_patterns",
                args.memory_redaction_patterns,
                ParameterSource.CLI,
                origin="--memory-redaction-pattern",
            )

        if getattr(args, "memory_disabled_users", None) is not None:
            memory_overrides["disabled_users"] = set(args.memory_disabled_users)
            resolution.record(
                "memory.disabled_users",
                list(args.memory_disabled_users),
                ParameterSource.CLI,
                origin="--memory-disable-user",
            )

        if getattr(args, "memory_disabled_clients", None) is not None:
            memory_overrides["disabled_clients"] = set(args.memory_disabled_clients)
            resolution.record(
                "memory.disabled_clients",
                list(args.memory_disabled_clients),
                ParameterSource.CLI,
                origin="--memory-disable-client",
            )
