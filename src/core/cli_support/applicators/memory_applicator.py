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


def _parse_list_env(val: str | None) -> list[str]:
    """Parse a comma-separated list from an environment variable."""
    if not val:
        return []
    return [item.strip() for item in val.split(",") if item.strip()]


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

        session_timeout = os.environ.get("MEMORY_SESSION_TIMEOUT_MINUTES")
        if session_timeout is None:
            session_timeout = os.environ.get("MEMORY_SESSION_TIMEOUT")
        if session_timeout is not None:
            with contextlib.suppress(ValueError):
                memory_overrides["session_timeout_minutes"] = int(session_timeout)

        if summarization_delay := os.environ.get("MEMORY_SUMMARIZATION_DELAY_SECONDS"):
            with contextlib.suppress(ValueError):
                memory_overrides["summarization_delay_seconds"] = int(
                    summarization_delay
                )

        if max_sessions := os.environ.get("MEMORY_MAX_SESSIONS_TO_CONSIDER"):
            with contextlib.suppress(ValueError):
                memory_overrides["max_sessions_to_consider"] = int(max_sessions)

        if retention_days := os.environ.get("MEMORY_RETENTION_DAYS"):
            with contextlib.suppress(ValueError):
                memory_overrides["retention_days"] = int(retention_days)

        if max_context_tokens := os.environ.get("MEMORY_MAX_CONTEXT_TOKENS"):
            with contextlib.suppress(ValueError):
                memory_overrides["max_context_tokens"] = int(max_context_tokens)

        if max_summary_tokens := os.environ.get("MEMORY_MAX_SUMMARY_TOKENS"):
            with contextlib.suppress(ValueError):
                memory_overrides["max_summary_tokens"] = int(max_summary_tokens)

        if max_transcript_chars := os.environ.get("MEMORY_MAX_TRANSCRIPT_CHARS"):
            with contextlib.suppress(ValueError):
                memory_overrides["max_transcript_chars"] = int(max_transcript_chars)

        if completion_tokens := os.environ.get("MEMORY_SUMMARY_COMPLETION_TOKENS"):
            with contextlib.suppress(ValueError):
                memory_overrides["summary_completion_tokens"] = int(completion_tokens)

        if relevance_threshold := os.environ.get("MEMORY_CONTEXT_RELEVANCE_THRESHOLD"):
            with contextlib.suppress(ValueError):
                memory_overrides["context_relevance_threshold"] = float(
                    relevance_threshold
                )

        if max_buffer_size := os.environ.get("MEMORY_MAX_BUFFER_SIZE_BYTES"):
            with contextlib.suppress(ValueError):
                memory_overrides["max_buffer_size_bytes"] = int(max_buffer_size)

        if queue_maxsize := os.environ.get("MEMORY_ANALYSIS_QUEUE_MAXSIZE"):
            with contextlib.suppress(ValueError):
                memory_overrides["analysis_queue_maxsize"] = int(queue_maxsize)

        if analysis_timeout := os.environ.get("MEMORY_ANALYSIS_TIMEOUT_SECONDS"):
            with contextlib.suppress(ValueError):
                memory_overrides["analysis_timeout_seconds"] = int(analysis_timeout)

        if max_concurrent := os.environ.get("MEMORY_MAX_CONCURRENT_ANALYSES"):
            with contextlib.suppress(ValueError):
                memory_overrides["max_concurrent_analyses"] = int(max_concurrent)

        if context_template := os.environ.get("MEMORY_CONTEXT_TEMPLATE"):
            memory_overrides["context_template"] = context_template

        if persist_transcript := os.environ.get("MEMORY_PERSIST_TRANSCRIPT"):
            memory_overrides["persist_transcript"] = _parse_bool_env(persist_transcript)

        if redaction_patterns := os.environ.get("MEMORY_REDACTION_PATTERNS"):
            parsed = _parse_list_env(redaction_patterns)
            if parsed:
                memory_overrides["redaction_patterns"] = parsed

        if disabled_users := os.environ.get("MEMORY_DISABLED_USERS"):
            parsed = _parse_list_env(disabled_users)
            if parsed:
                memory_overrides["disabled_users"] = set(parsed)

        if disabled_clients := os.environ.get("MEMORY_DISABLED_CLIENTS"):
            parsed = _parse_list_env(disabled_clients)
            if parsed:
                memory_overrides["disabled_clients"] = set(parsed)

        if single_user_mode := os.environ.get("MEMORY_SINGLE_USER_MODE"):
            memory_overrides["single_user_mode"] = _parse_bool_env(single_user_mode)

        if fixed_user_id := os.environ.get("MEMORY_FIXED_USER_ID"):
            memory_overrides["fixed_user_id"] = fixed_user_id

        if summary_prompt_version := os.environ.get("MEMORY_SUMMARY_PROMPT_VERSION"):
            memory_overrides["summary_prompt_version"] = summary_prompt_version

        if summary_schema_version := os.environ.get("MEMORY_SUMMARY_SCHEMA_VERSION"):
            memory_overrides["summary_schema_version"] = summary_schema_version

        if require_project := os.environ.get("MEMORY_REQUIRE_PROJECT_DISCOVERY"):
            memory_overrides["require_project_discovery"] = _parse_bool_env(
                require_project
            )

        if discovery_mode := os.environ.get("MEMORY_PROJECT_DISCOVERY_MODE"):
            memory_overrides["project_discovery_mode"] = discovery_mode

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

        if getattr(args, "memory_summarization_delay", None) is not None:
            memory_overrides["summarization_delay_seconds"] = (
                args.memory_summarization_delay
            )
            resolution.record(
                "memory.summarization_delay_seconds",
                args.memory_summarization_delay,
                ParameterSource.CLI,
                origin="--memory-summarization-delay",
            )

        if getattr(args, "memory_max_sessions_to_consider", None) is not None:
            memory_overrides["max_sessions_to_consider"] = (
                args.memory_max_sessions_to_consider
            )
            resolution.record(
                "memory.max_sessions_to_consider",
                args.memory_max_sessions_to_consider,
                ParameterSource.CLI,
                origin="--memory-max-sessions-to-consider",
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

        if getattr(args, "memory_max_summary_tokens", None) is not None:
            memory_overrides["max_summary_tokens"] = args.memory_max_summary_tokens
            resolution.record(
                "memory.max_summary_tokens",
                args.memory_max_summary_tokens,
                ParameterSource.CLI,
                origin="--memory-max-summary-tokens",
            )

        if getattr(args, "memory_max_transcript_chars", None) is not None:
            memory_overrides["max_transcript_chars"] = args.memory_max_transcript_chars
            resolution.record(
                "memory.max_transcript_chars",
                args.memory_max_transcript_chars,
                ParameterSource.CLI,
                origin="--memory-max-transcript-chars",
            )

        if getattr(args, "memory_summary_completion_tokens", None) is not None:
            memory_overrides["summary_completion_tokens"] = (
                args.memory_summary_completion_tokens
            )
            resolution.record(
                "memory.summary_completion_tokens",
                args.memory_summary_completion_tokens,
                ParameterSource.CLI,
                origin="--memory-summary-completion-tokens",
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

        if getattr(args, "memory_max_buffer_size_bytes", None) is not None:
            memory_overrides["max_buffer_size_bytes"] = (
                args.memory_max_buffer_size_bytes
            )
            resolution.record(
                "memory.max_buffer_size_bytes",
                args.memory_max_buffer_size_bytes,
                ParameterSource.CLI,
                origin="--memory-max-buffer-size-bytes",
            )

        if getattr(args, "memory_analysis_queue_maxsize", None) is not None:
            memory_overrides["analysis_queue_maxsize"] = (
                args.memory_analysis_queue_maxsize
            )
            resolution.record(
                "memory.analysis_queue_maxsize",
                args.memory_analysis_queue_maxsize,
                ParameterSource.CLI,
                origin="--memory-analysis-queue-maxsize",
            )

        if getattr(args, "memory_analysis_timeout_seconds", None) is not None:
            memory_overrides["analysis_timeout_seconds"] = (
                args.memory_analysis_timeout_seconds
            )
            resolution.record(
                "memory.analysis_timeout_seconds",
                args.memory_analysis_timeout_seconds,
                ParameterSource.CLI,
                origin="--memory-analysis-timeout",
            )

        if getattr(args, "memory_max_concurrent_analyses", None) is not None:
            memory_overrides["max_concurrent_analyses"] = (
                args.memory_max_concurrent_analyses
            )
            resolution.record(
                "memory.max_concurrent_analyses",
                args.memory_max_concurrent_analyses,
                ParameterSource.CLI,
                origin="--memory-max-concurrent-analyses",
            )

        if getattr(args, "memory_context_template", None) is not None:
            memory_overrides["context_template"] = args.memory_context_template
            resolution.record(
                "memory.context_template",
                args.memory_context_template,
                ParameterSource.CLI,
                origin="--memory-context-template",
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

        if getattr(args, "memory_persist_transcript", None) is not None:
            memory_overrides["persist_transcript"] = args.memory_persist_transcript
            resolution.record(
                "memory.persist_transcript",
                args.memory_persist_transcript,
                ParameterSource.CLI,
                origin="--memory-persist-transcript",
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

        if getattr(args, "memory_summary_prompt_version", None) is not None:
            memory_overrides["summary_prompt_version"] = (
                args.memory_summary_prompt_version
            )
            resolution.record(
                "memory.summary_prompt_version",
                args.memory_summary_prompt_version,
                ParameterSource.CLI,
                origin="--memory-summary-prompt-version",
            )

        if getattr(args, "memory_summary_schema_version", None) is not None:
            memory_overrides["summary_schema_version"] = (
                args.memory_summary_schema_version
            )
            resolution.record(
                "memory.summary_schema_version",
                args.memory_summary_schema_version,
                ParameterSource.CLI,
                origin="--memory-summary-schema-version",
            )

        if getattr(args, "memory_require_project_discovery", None) is not None:
            memory_overrides["require_project_discovery"] = (
                args.memory_require_project_discovery
            )
            resolution.record(
                "memory.require_project_discovery",
                args.memory_require_project_discovery,
                ParameterSource.CLI,
                origin="--memory-require-project-discovery",
            )

        if getattr(args, "memory_project_discovery_mode", None) is not None:
            memory_overrides["project_discovery_mode"] = (
                args.memory_project_discovery_mode
            )
            resolution.record(
                "memory.project_discovery_mode",
                args.memory_project_discovery_mode,
                ParameterSource.CLI,
                origin="--memory-project-discovery-mode",
            )
