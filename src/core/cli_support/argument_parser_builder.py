"""ArgumentParserBuilder for CLI argument parser construction.

This module provides the ArgumentParserBuilder class which constructs the complete
argparse.ArgumentParser for the LLM proxy CLI. The builder pattern organizes
arguments by domain, making it easier to maintain and extend.

Requirements satisfied:
- 1.1: ArgumentParser is constructed by a dedicated ArgumentParserBuilder class
- 1.5: Adding new CLI arguments only requires modifying ArgumentParserBuilder
- 7.1: Backward compatible with existing CLI API
"""

from __future__ import annotations

import argparse
import os
import re
from typing import Protocol

from src.core.domain.model_utils import (
    has_explicit_backend_selector,
    parse_model_backend,
)
from src.core.services.backend_registry import backend_registry


class BackendRegistryProtocol(Protocol):
    def get_registered_backends(self) -> list[str]: ...


class ArgumentParserBuilder:
    """Builder for constructing the CLI argument parser.

    This class extracts the argument parser construction logic from cli.py
    and organizes it by domain for better maintainability.

    Usage:
        builder = ArgumentParserBuilder()
        parser = builder.build()
        args = parser.parse_args()
    """

    def __init__(self, *, registry: BackendRegistryProtocol | None = None) -> None:
        """Initialize the builder."""
        self._parser: argparse.ArgumentParser | None = None
        self._backend_registry: BackendRegistryProtocol = registry or backend_registry

    def build(self) -> argparse.ArgumentParser:
        """Build and return the complete argument parser.

        Returns:
            Configured ArgumentParser instance with all CLI arguments.
        """
        parser = argparse.ArgumentParser(description="Run the LLM proxy server")

        # Add arguments organized by domain
        self._add_backend_arguments(parser)
        self._add_api_key_arguments(parser)
        self._add_server_arguments(parser)
        self._add_logging_arguments(parser)
        self._add_feature_flag_arguments(parser)
        self._add_compaction_arguments(parser)
        self._add_planning_phase_arguments(parser)
        self._add_edit_precision_arguments(parser)
        self._add_activity_tracking_arguments(parser)
        self._add_debugging_override_arguments(parser)
        self._add_auth_arguments(parser)
        self._add_pytest_arguments(parser)
        self._add_session_testing_arguments(parser)
        self._add_b2bua_arguments(parser)
        self._add_tool_access_arguments(parser)
        self._add_routing_arguments(parser)
        self._add_auxiliary_routing_arguments(parser)
        self._add_identity_arguments(parser)
        self._add_memory_arguments(parser)
        self._add_failure_handling_arguments(parser)
        self._add_resilience_arguments(parser)
        self._add_end_of_session_arguments(parser)
        self._add_replacement_arguments(parser)
        self._add_model_registry_arguments(parser)
        self._add_access_mode_arguments(parser)

        return parser

    def _add_model_registry_arguments(self, parser: argparse.ArgumentParser) -> None:
        """Add model registry and limit enforcement arguments."""
        registry_group = parser.add_argument_group(
            "Model Registry & Limits",
            "Options for external model metadata registry and automated limit enforcement",
        )
        registry_group.add_argument(
            "--disable-model-registry-download",
            dest="model_registry_download_enabled",
            action="store_false",
            default=None,
            help="Disable downloading updates from the external model registry",
        )
        registry_group.add_argument(
            "--model-registry-url",
            dest="model_registry_url",
            metavar="URL",
            help="URL of the model registry (default: https://models.dev/api.json)",
        )
        registry_group.add_argument(
            "--model-registry-update-interval",
            dest="model_registry_update_interval_seconds",
            type=int,
            metavar="SECONDS",
            help="Interval for checking for updates (default: 86400/1 day)",
        )
        registry_group.add_argument(
            "--disable-model-limit-enforcement",
            dest="model_limit_enforcement_enabled",
            action="store_false",
            default=None,
            help="Disable model limit enforcement (context window, etc.) based on registry data",
        )

    def _add_replacement_arguments(self, parser: argparse.ArgumentParser) -> None:
        """Add random model replacement arguments."""
        replacement_group = parser.add_argument_group(
            "Random Model Replacement",
            "Options for probabilistic swapping of models for session diversity and resilience",
        )
        replacement_group.add_argument(
            "--enable-replacement",
            dest="replacement_enabled",
            action="store_true",
            default=None,
            help="Enable random model replacement feature",
        )
        replacement_group.add_argument(
            "--disable-replacement",
            dest="replacement_enabled",
            action="store_false",
            default=None,
            help="Disable random model replacement feature",
        )
        replacement_group.add_argument(
            "--replacement-probability",
            dest="replacement_probability",
            type=float,
            metavar="FLOAT",
            help="Probability (0.0-1.0) of triggering replacement (default: 0.0)",
        )
        replacement_group.add_argument(
            "--random-model-replacement-from-to",
            dest="replacement_rules",
            action="append",
            type=self._validate_replacement_rule,
            metavar="FROM=TO",
            help=(
                "Replacement rule in format '<from-model-name>=<to-model-name>'. "
                "Can be specified multiple times. "
                "<from-model-name> can be: '*' (wildcard), 'model-name' (partial match), "
                "or 'backend:model' (exact match). "
                "<to-model-name> must be 'backend:model'. "
                "Example: --random-model-replacement-from-to '*=qwen-oauth:qwen3-coder-plus' "
                "or --random-model-replacement-from-to 'gpt-4=openai:gpt-3.5-turbo'"
            ),
        )
        replacement_group.add_argument(
            "--replacement-backend-model",
            dest="replacement_backend_model",
            metavar="BACKEND:MODEL",
            help="Deprecated: Use --random-model-replacement-from-to instead. Backend and model to use for replacement.",
        )
        replacement_group.add_argument(
            "--replacement-turn-count",
            dest="replacement_turn_count",
            type=int,
            metavar="N",
            help="Number of turns to use replacement model (default: 1)",
        )
        replacement_group.add_argument(
            "--allow-oauth-auto-replacement",
            dest="allow_oauth_auto_replacement",
            action="store_true",
            default=None,
            help="Allow random model replacement for multi-account oauth-auto backends (disabled by default for safety)",
        )

    def _add_backend_arguments(self, parser: argparse.ArgumentParser) -> None:
        """Add backend selection and configuration arguments."""
        # Dynamically get registered backends
        registered_backends: list[str] = (
            self._backend_registry.get_registered_backends()
        )

        # Backend selection
        parser.add_argument(
            "--default-backend",
            dest="default_backend",
            choices=registered_backends,  # Dynamically populated
            default=os.getenv("LLM_BACKEND"),
            help="Default backend when multiple backends are functional",
        )
        parser.add_argument(
            "--backend",
            dest="default_backend",
            choices=registered_backends,  # Dynamically populated
            help=argparse.SUPPRESS,
        )
        parser.add_argument(
            "--static-route",
            dest="static_route",
            metavar="BACKEND:MODEL",
            help="Force all requests to use this backend:model combination (e.g., gemini-oauth-plan:gemini-2.5-pro)",
        )
        parser.add_argument(
            "--disable-gemini-oauth-fallback",
            dest="disable_gemini_oauth_fallback",
            action="store_true",
            help="Disable automatic Gemini OAuth fallback to gemini-2.5-flash",
        )
        parser.add_argument(
            "--disable-gemini-oauth-reasoning-prompt-injection",
            dest="disable_gemini_oauth_reasoning_prompt_injection",
            action="store_true",
            help="Disable automatic reasoning effort prompt injection for Gemini OAuth backends (enabled by default)",
        )
        parser.add_argument(
            "--disable-hybrid-backend",
            dest="disable_hybrid_backend",
            action="store_true",
            help="Disable the hybrid backend (enabled by default)",
        )
        parser.add_argument(
            "--hybrid-backend-repeat-messages",
            dest="hybrid_backend_repeat_messages",
            action="store_true",
            help="If set, repeat reasoning output as an artificial message in the session",
        )
        parser.add_argument(
            "--reasoning-injection-probability",
            "--reasoning_injection_probability",  # Accept both formats
            dest="reasoning_injection_probability",
            type=float,
            help="Probability of using the reasoning model in the hybrid backend (0.0 to 1.0)",
        )
        parser.add_argument(
            "--hybrid-reasoning-model-timeout",
            dest="hybrid_reasoning_model_timeout",
            type=int,
            default=60,
            metavar="SECONDS",
            help="Timeout in seconds for the reasoning model call in hybrid scenarios (default: 60)",
        )
        parser.add_argument(
            "--hybrid-reasoning-force-initial-turns",
            dest="hybrid_reasoning_force_initial_turns",
            type=int,
            default=4,
            metavar="N",
            help="Number of turns at the beginning of a new session when reasoning model probability is overridden to 1 (default: 1)",
        )

        parser.add_argument(
            "--model-alias",
            dest="model_aliases",
            action="append",
            metavar="PATTERN=REPLACEMENT",
            type=self._validate_model_alias,
            help="Add a model name rewrite rule. Pattern is a regex, replacement can use capture groups (\\1, \\2, etc.). Can be specified multiple times. Example: --model-alias '^gpt-(.*)=openrouter:openai/gpt-\\1'",
        )

        # Quality Verifier model (experimental)
        parser.add_argument(
            "--quality-verifier-model",
            dest="quality_verifier_model",
            metavar="BACKEND:MODEL[?params]",
            help=(
                "Enable Quality Verifier with model spec (e.g., "
                "anthropic:claude-3-5-sonnet?temperature=1&reasoning_effort=high)"
            ),
        )
        parser.add_argument(
            "--quality-verifier-frequency",
            dest="quality_verifier_frequency",
            type=int,
            metavar="N",
            help="Run Quality Verifier every N eligible turns (default: 10)",
        )
        parser.add_argument(
            "--quality-verifier-max-history",
            dest="quality_verifier_max_history",
            type=int,
            metavar="N",
            help="Truncate history for Quality Verifier to N messages (default: unlimited/disabled)",
        )
        parser.add_argument(
            "--quality-verifier-max-consecutive-failures",
            dest="quality_verifier_max_consecutive_failures",
            type=int,
            metavar="N",
            help="Maximum consecutive failures for Quality Verifier model before tripping circuit breaker (default: 5)",
        )
        parser.add_argument(
            "--quality-verifier-cooldown-seconds",
            dest="quality_verifier_cooldown_seconds",
            type=int,
            metavar="SECONDS",
            help="Cooldown period in seconds for Quality Verifier circuit breaker (default: 300)",
        )
        parser.add_argument(
            "--quality-verifier-ttft-timeout-seconds",
            dest="quality_verifier_ttft_timeout_seconds",
            type=float,
            metavar="SECONDS",
            help="Time-to-first-token timeout for Quality Verifier calls (default: 30)",
        )

    def _validate_model_alias(self, value: str) -> tuple[str, str]:
        """Validate model alias format: pattern=replacement."""
        if "=" not in value:
            raise argparse.ArgumentTypeError(
                f"Invalid model alias format '{value}'. Expected 'pattern=replacement'"
            )
        pattern, replacement = value.split("=", 1)
        if not pattern or not replacement:
            raise argparse.ArgumentTypeError(
                f"Invalid model alias format '{value}'. Both pattern and replacement must be non-empty"
            )
        # Test regex validity
        try:
            re.compile(pattern)
        except re.error as e:
            raise argparse.ArgumentTypeError(
                f"Invalid regex pattern '{pattern}' in model alias: {e}"
            )
        return pattern, replacement

    def _validate_replacement_rule(self, value: str) -> str:
        """Validate replacement rule format: <from>=<to>.

        Args:
            value: The replacement rule string in format '<from>=<to>'

        Returns:
            The validated rule string

        Raises:
            argparse.ArgumentTypeError: If the format is invalid
        """
        if "=" not in value:
            raise argparse.ArgumentTypeError(
                f"Invalid replacement rule format '{value}'. "
                f"Expected '<from-model-name>=<to-model-name>' (use = as separator)"
            )

        parts = value.split("=", 1)
        if len(parts) != 2:
            raise argparse.ArgumentTypeError(
                f"Invalid replacement rule format '{value}'. "
                f"Expected exactly one '=' separator"
            )

        from_pattern, to_part = parts
        from_pattern = from_pattern.strip()
        to_part = to_part.strip()

        if not from_pattern:
            raise argparse.ArgumentTypeError(
                f"Invalid replacement rule format '{value}'. "
                f"<from-model-name> cannot be empty"
            )

        if not to_part:
            raise argparse.ArgumentTypeError(
                f"Invalid replacement rule format '{value}'. "
                f"<to-model-name> cannot be empty"
            )

        # Validate to_part is in explicit backend:model format
        if not has_explicit_backend_selector(to_part):
            raise argparse.ArgumentTypeError(
                f"Invalid replacement rule format '{value}'. "
                f"<to-model-name> must be in format 'backend:model', got '{to_part}'"
            )

        parsed_target = parse_model_backend(to_part, "")
        to_backend = parsed_target.backend_type.strip()
        to_model = parsed_target.model_name.strip()
        if not to_backend or not to_model:
            raise argparse.ArgumentTypeError(
                f"Invalid replacement rule format '{value}'. "
                f"Both backend and model must be specified in <to-model-name>"
            )

        # Validate that replacement target is not a wildcard
        if to_backend == "*" or to_model == "*":
            raise argparse.ArgumentTypeError(
                f"Invalid replacement rule '{value}': "
                f"Replacement target cannot use wildcard '*'. "
                f"Only the source pattern (left side) can be a wildcard."
            )

        # Validate from_pattern formats (wildcard, partial, or backend:model)
        if from_pattern != "*" and has_explicit_backend_selector(from_pattern):
            parsed_source = parse_model_backend(from_pattern, "")
            if (
                not parsed_source.backend_type.strip()
                or not parsed_source.model_name.strip()
            ):
                raise argparse.ArgumentTypeError(
                    f"Invalid replacement rule format '{value}'. "
                    f"If <from-model-name> contains ':', it must be in format 'backend:model'"
                )

        return value

    def _parse_csv_list(self, value: str) -> list[str]:
        """Parse a comma-separated list into a list of strings."""
        items = value.split(",")
        result: list[str] = []
        for item in items:
            stripped = item.strip()
            if stripped:
                result.append(stripped)
        return result

    def _add_api_key_arguments(self, parser: argparse.ArgumentParser) -> None:
        """Add API keys and URLs arguments."""
        parser.add_argument("--openrouter-api-key")
        parser.add_argument("--openrouter-api-base-url")
        parser.add_argument("--gemini-api-key")
        parser.add_argument("--gemini-api-base-url")
        parser.add_argument("--zai-api-key")
        parser.add_argument("--zenmux-api-base-url")

    def _add_server_arguments(self, parser: argparse.ArgumentParser) -> None:
        """Add basic server options arguments."""
        parser.add_argument("--host")
        parser.add_argument("--port", type=int)
        parser.add_argument(
            "--anthropic-port",
            type=int,
            help="Port for Anthropic-compatible endpoints (disabled by default)",
        )
        parser.add_argument("--timeout", type=int)
        parser.add_argument("--command-prefix")
        parser.add_argument(
            "--force-context-window",
            dest="force_context_window",
            type=int,
            metavar="TOKENS",
            help="Override context window size for all models (in tokens, overrides config file settings)",
        )
        parser.add_argument(
            "--thinking-budget",
            dest="thinking_budget",
            type=int,
            metavar="TOKENS",
            help="Set max reasoning tokens for all requests (-1=dynamic/unlimited, 0=none, >0=limit in tokens)",
        )

    def _add_logging_arguments(self, parser: argparse.ArgumentParser) -> None:
        """Add logging options arguments."""
        parser.add_argument(
            "--log",
            dest="log_file",
            metavar="FILE",
            help="Write logs to FILE (default: ./var/logs/proxy.log)",
        )
        parser.add_argument(
            "--capture-file",
            dest="capture_file",
            metavar="FILE",
            help="Write raw LLM requests and replies to FILE (disabled if omitted)",
        )
        parser.add_argument(
            "--capture-max-bytes",
            dest="capture_max_bytes",
            type=int,
            metavar="N",
            help="Maximum size of capture file in bytes before rotation (env: CAPTURE_MAX_BYTES)",
        )
        parser.add_argument(
            "--capture-truncate-bytes",
            dest="capture_truncate_bytes",
            type=int,
            metavar="N",
            help="Truncate captures to N bytes per entry (env: CAPTURE_TRUNCATE_BYTES)",
        )
        parser.add_argument(
            "--capture-max-files",
            dest="capture_max_files",
            type=int,
            metavar="N",
            help="Maximum number of capture files to retain (env: CAPTURE_MAX_FILES)",
        )
        parser.add_argument(
            "--capture-rotate-interval",
            dest="capture_rotate_interval_seconds",
            type=int,
            metavar="SECONDS",
            help="Time-based rotation period in seconds (env: CAPTURE_ROTATE_INTERVAL_SECONDS)",
        )
        parser.add_argument(
            "--capture-total-max-bytes",
            dest="capture_total_max_bytes",
            type=int,
            metavar="N",
            help="Total disk cap across capture files in bytes (env: CAPTURE_TOTAL_MAX_BYTES)",
        )
        parser.add_argument(
            "--cbor-capture-dir",
            dest="cbor_capture_dir",
            metavar="DIR",
            help="Directory for CBOR byte-precise capture files (enables CBOR capture)",
        )
        parser.add_argument(
            "--cbor-capture-session",
            dest="cbor_capture_session_id",
            metavar="ID",
            help="Fixed session ID for CBOR capture (auto-generated if omitted)",
        )
        parser.add_argument(
            "--config",
            dest="config_file",
            metavar="FILE",
            help="Path to persistent configuration file",
        )
        parser.add_argument(
            "--log-level",
            dest="log_level",
            choices=["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"],
            default=None,
            help="Set the logging level (default: use config or INFO)",
        )
        parser.add_argument(
            "--log-stream",
            dest="log_stream",
            choices=["stdout", "stderr"],
            default=None,
            help="Write console logs to stdout or stderr (default: stderr)",
        )
        parser.add_argument(
            "--log-colors",
            dest="log_use_colors",
            action="store_true",
            default=None,
            help="Enable colored logging output (overrides config)",
        )
        parser.add_argument(
            "--no-log-colors",
            dest="log_use_colors",
            action="store_false",
            default=None,
            help="Disable colored logging output (overrides config)",
        )

    def _add_feature_flag_arguments(self, parser: argparse.ArgumentParser) -> None:
        """Add feature flags arguments."""
        parser.add_argument(
            "--disable-interactive-mode",
            action="store_true",
            default=None,
            help="Disable interactive mode by default for new sessions",
        )
        parser.add_argument(
            "--disable-redact-api-keys-in-prompts",
            action="store_true",
            default=None,
            help="Disable API key redaction in prompts",
        )
        parser.add_argument(
            "--disable-sso-captcha",
            action="store_true",
            default=None,
            help="Disable SSO Captcha verification (overrides config)",
        )
        parser.add_argument(
            "--enable-sso",
            action="store_true",
            default=None,
            help="Enable SSO authentication mode (overrides config)",
        )
        parser.add_argument(
            "--sso-config",
            dest="sso_config_path",
            metavar="PATH",
            default=None,
            help="Path to SSO configuration file (e.g., config/sso_auth.yaml)",
        )
        parser.add_argument(
            "--sso-provider",
            dest="sso_provider",
            metavar="PROVIDER",
            default=None,
            help="Enable only a specific SSO provider (e.g., google, github, microsoft)",
        )
        parser.add_argument(
            "--sso-auth-mode",
            dest="sso_auth_mode",
            metavar="MODE",
            choices=["single_user", "enterprise"],
            default=None,
            help="SSO authorization mode: single_user (confirmation code) or enterprise (external API)",
        )
        parser.add_argument(
            "--disable-auth",
            action="store_true",
            default=None,
            help="Disable client API key authentication (forces binding to 127.0.0.1 for security)",
        )
        parser.add_argument(
            "--force-set-project",
            action="store_true",
            default=None,
            help="Require project name to be set before sending prompts",
        )
        parser.add_argument(
            "--project-dir-resolution-model",
            dest="project_dir_resolution_model",
            metavar="BACKEND:MODEL",
            help=(
                "Automatically detect an absolute project directory on the first user prompt "
                "using BACKEND:MODEL"
            ),
        )
        parser.add_argument(
            "--project-dir-resolution-mode",
            dest="project_dir_resolution_mode",
            choices=["deterministic", "llm", "hybrid"],
            default=None,
            help="Strategy for resolving project directory: 'deterministic', 'llm', or 'hybrid' (default).",
        )
        parser.add_argument(
            "--disable-interactive-commands",
            action="store_true",
            default=None,
            help="Disable all in-chat command processing",
        )
        parser.add_argument(
            "--disable-accounting",
            action="store_true",
            default=None,
            help="Disable LLM accounting (usage tracking and audit logging)",
        )
        parser.add_argument(
            "--no-accounting",
            dest="disable_accounting",
            action="store_true",
            default=None,
            help="Disable LLM accounting (usage tracking and audit logging) (alias for --disable-accounting)",
        )
        parser.add_argument(
            "--enable-notifications",
            dest="notifications_enabled",
            action="store_true",
            default=None,
            help="Enable desktop notifications (overrides auto-detect based on bind address)",
        )
        parser.add_argument(
            "--disable-notifications",
            dest="notifications_enabled",
            action="store_false",
            default=None,
            help="Disable desktop notifications (overrides auto-detect based on bind address)",
        )
        parser.add_argument(
            "--strict-command-detection",
            action="store_true",
            default=None,
            help="Enable strict command detection (requires commands to be at the start of messages)",
        )
        parser.add_argument(
            "--enable-sandboxing",
            action="store_true",
            default=None,
            help="Enable file access sandboxing to restrict file operations to the project directory (env: ENABLE_SANDBOXING)",
        )

    def _add_compaction_arguments(self, parser: argparse.ArgumentParser) -> None:
        """Add history compaction arguments."""
        compaction_group = parser.add_argument_group(
            "History Compaction", "Options for tool output compaction"
        )
        compaction_group.add_argument(
            "--enable-context-compaction",
            dest="enable_context_compaction",
            action="store_true",
            default=None,
            help="Enable history compaction for stale tool outputs (overrides config)",
        )
        compaction_group.add_argument(
            "--compaction-min-tokens",
            dest="compaction_min_tokens",
            type=int,
            metavar="TOKENS",
            help="Minimum token estimate to trigger compaction (default: 100,000)",
        )

    def _add_planning_phase_arguments(self, parser: argparse.ArgumentParser) -> None:
        """Add planning phase arguments."""
        parser.add_argument(
            "--enable-planning-phase",
            action="store_true",
            default=None,
            help="Enable planning phase model routing for initial requests",
        )
        parser.add_argument(
            "--planning-phase-strong-model",
            type=str,
            default=None,
            metavar="BACKEND:MODEL",
            help="Strong model to use during planning phase (e.g., openai:gpt-4)",
        )
        parser.add_argument(
            "--planning-phase-max-turns",
            type=int,
            default=None,
            metavar="N",
            help="Maximum number of turns before switching from strong model (default: 10)",
        )
        parser.add_argument(
            "--planning-phase-max-file-writes",
            type=int,
            default=None,
            metavar="N",
            help="Maximum number of file writes before switching from strong model (default: 1)",
        )
        parser.add_argument(
            "--planning-phase-temperature",
            type=float,
            default=None,
            metavar="FLOAT",
            help="Temperature override for planning strong model",
        )
        parser.add_argument(
            "--planning-phase-top-p",
            type=float,
            default=None,
            metavar="FLOAT",
            help="Top-p override for planning strong model",
        )
        parser.add_argument(
            "--planning-phase-reasoning-effort",
            type=str,
            default=None,
            metavar="EFFORT",
            help="Reasoning effort override for planning strong model",
        )
        parser.add_argument(
            "--planning-phase-thinking-budget",
            type=int,
            default=None,
            metavar="TOKENS",
            help="Reasoning tokens (thinking budget) override for planning strong model",
        )

    def _add_edit_precision_arguments(self, parser: argparse.ArgumentParser) -> None:
        """Add edit-precision tuning arguments."""
        edit_precision_toggle_group = parser.add_mutually_exclusive_group()
        edit_precision_toggle_group.add_argument(
            "--enable-edit-precision",
            dest="edit_precision_enabled",
            action="store_const",
            const=True,
            default=None,
            help="Enable automated edit-precision tuning on failed file edits",
        )
        edit_precision_toggle_group.add_argument(
            "--disable-edit-precision",
            dest="edit_precision_enabled",
            action="store_const",
            const=False,
            help="Disable automated edit-precision tuning",
        )
        parser.add_argument(
            "--edit-precision-temperature",
            dest="edit_precision_temperature",
            type=float,
            default=None,
            metavar="TEMP",
            help="Target temperature for edit-precision tuning (default: 0.1)",
        )
        parser.add_argument(
            "--edit-precision-min-top-p",
            dest="edit_precision_min_top_p",
            type=float,
            default=None,
            metavar="FLOAT",
            help="Minimum top_p value for edit-precision tuning (default: 0.3)",
        )
        parser.add_argument(
            "--edit-precision-override-top-p",
            dest="edit_precision_override_top_p",
            action="store_true",
            default=None,
            help="Enable top_p override for edit-precision tuning",
        )
        parser.add_argument(
            "--edit-precision-target-top-k",
            dest="edit_precision_target_top_k",
            type=int,
            default=None,
            metavar="N",
            help="Target top_k value for edit-precision tuning (requires override flag)",
        )
        parser.add_argument(
            "--edit-precision-override-top-k",
            dest="edit_precision_override_top_k",
            action="store_true",
            default=None,
            help="Enable top_k override for edit-precision tuning",
        )
        parser.add_argument(
            "--edit-precision-exclude-agents",
            dest="edit_precision_exclude_agents_regex",
            type=str,
            default=None,
            metavar="REGEX",
            help="Exclude agents matching this regex from edit-precision tuning",
        )

    def _add_activity_tracking_arguments(self, parser: argparse.ArgumentParser) -> None:
        """Add activity tracking and deduplication arguments."""
        parser.add_argument(
            "--enable-activity-tracking",
            dest="enable_activity_tracking",
            action="store_true",
            default=None,
            help="Enable real-time connection activity tracking (RX/TX counters per session)",
        )

        # Request deduplication options
        parser.add_argument(
            "--request-dedup-window",
            dest="request_dedup_window",
            type=float,
            default=None,
            metavar="SECONDS",
            help="Request deduplication window in seconds (0 to disable, default: 3.0, env: LLM_REQUEST_DEDUP_WINDOW)",
        )
        parser.add_argument(
            "--disable-request-dedup",
            dest="disable_request_dedup",
            action="store_true",
            default=None,
            help="Disable request deduplication entirely",
        )

    def _add_debugging_override_arguments(
        self, parser: argparse.ArgumentParser
    ) -> None:
        """Add backend debugging override arguments."""
        debugging_overrides_group = parser.add_argument_group(
            "Backend Debugging Overrides",
            "Options for enabling restricted backend connectors for debugging purposes",
        )
        debugging_overrides_group.add_argument(
            "--enable-cline-backend-debugging-override",
            action="store_true",
            default=False,
            help="Enable the Cline backend connector for debugging. Reserved for internal development.",
        )
        debugging_overrides_group.add_argument(
            "--enable-antigravity-backend-debugging-override",
            action="store_true",
            default=False,
            help="Enable the Antigravity OAuth backend connector for debugging. Reserved for internal development.",
        )
        debugging_overrides_group.add_argument(
            "--enable-gemini-oauth-free-backend-debugging-override",
            action="store_true",
            default=False,
            help="Enable the Gemini OAuth Free backend connector for debugging. Reserved for internal development.",
        )
        debugging_overrides_group.add_argument(
            "--enable-gemini-oauth-plan-backend-debugging-override",
            action="store_true",
            default=False,
            help="Enable the Gemini OAuth Plan backend connector for debugging. Reserved for internal development.",
        )
        debugging_overrides_group.add_argument(
            "--enable-gemini-oauth-auto-backend-debugging-override",
            action="store_true",
            default=False,
            help="Enable the Gemini OAuth Auto backend connector for debugging. Reserved for internal development.",
        )
        debugging_overrides_group.add_argument(
            "--enable-qwen-oauth-backend-debugging-override",
            action="store_true",
            default=False,
            help="Enable the Qwen OAuth backend connector for debugging. Reserved for internal development.",
        )
        debugging_overrides_group.add_argument(
            "--enable-openai-codex-backend-debugging-override",
            action="store_true",
            default=False,
            help="Enable the OpenAI Codex backend connector for debugging. Reserved for internal development.",
        )
        debugging_overrides_group.add_argument(
            "--enable-anthropic-oauth-backend-debugging-override",
            action="store_true",
            default=False,
            help="Enable the Anthropic OAuth backend connector for debugging. Reserved for internal development.",
        )
        debugging_overrides_group.add_argument(
            "--enable-opencode-zen-backend-debugging-override",
            action="store_true",
            default=False,
            help="Enable the Opencode Zen backend connector for debugging. Reserved for internal development.",
        )
        debugging_overrides_group.add_argument(
            "--enable-kiro-oauth-auto-backend-debugging-override",
            action="store_true",
            default=False,
            help="Enable the Kiro OAuth Auto backend connector for debugging. Reserved for internal development.",
        )
        debugging_overrides_group.add_argument(
            "--enable-droid-path-fix",
            action="store_true",
            dest="droid_path_fix_enabled",
            default=False,
            help="Enable automatic path fixing for Droid agent sessions. Converts relative paths to absolute paths.",
        )

    def _add_auth_arguments(self, parser: argparse.ArgumentParser) -> None:
        """Add authentication and security arguments."""
        brute_force_toggle_group = parser.add_mutually_exclusive_group()
        brute_force_toggle_group.add_argument(
            "--enable-brute-force-protection",
            dest="brute_force_protection_enabled",
            action="store_const",
            const=True,
            default=None,
            help="Explicitly enable API key brute-force protection",
        )
        brute_force_toggle_group.add_argument(
            "--disable-brute-force-protection",
            dest="brute_force_protection_enabled",
            action="store_const",
            const=False,
            help="Disable API key brute-force protection",
        )
        parser.add_argument(
            "--auth-max-failed-attempts",
            dest="auth_max_failed_attempts",
            type=int,
            help="Number of invalid API key attempts allowed per IP before temporary blocking",
        )
        parser.add_argument(
            "--auth-brute-force-ttl",
            dest="auth_brute_force_ttl",
            type=int,
            metavar="SECONDS",
            help="Time window for tracking failed API key attempts before reset",
        )
        parser.add_argument(
            "--auth-brute-force-initial-block",
            dest="auth_initial_block_seconds",
            type=int,
            metavar="SECONDS",
            help="Initial block duration applied once the failed attempt threshold is exceeded",
        )
        parser.add_argument(
            "--auth-brute-force-multiplier",
            dest="auth_block_multiplier",
            type=float,
            help="Multiplier applied to each subsequent block duration after repeated failures",
        )
        parser.add_argument(
            "--auth-brute-force-max-block",
            dest="auth_max_block_seconds",
            type=int,
            metavar="SECONDS",
            help="Maximum block duration enforced for repeated invalid API key attempts",
        )

        # Security and process options
        parser.add_argument(
            "--allow-admin",
            action="store_true",
            default=False,
            help="Allow running server with administrative privileges (Windows UAC/admin or root)",
        )
        parser.add_argument(
            "--daemon",
            action="store_true",
            default=False,
            help="Run the server as a daemon (in the background). Requires --log to be set.",
        )
        parser.add_argument(
            "--trusted-ip",
            action="append",
            dest="trusted_ips",
            metavar="IP",
            help="IP address to trust for bypassing authorization. Can be specified multiple times.",
        )

    def _add_pytest_arguments(self, parser: argparse.ArgumentParser) -> None:
        """Add pytest-related arguments."""
        pytest_compression_group = parser.add_mutually_exclusive_group()
        pytest_compression_group.add_argument(
            "--enable-pytest-compression",
            action="store_const",
            const=True,
            dest="pytest_compression_enabled",
            default=None,
            help="Enable pytest output compression (overrides config)",
        )
        pytest_compression_group.add_argument(
            "--disable-pytest-compression",
            action="store_const",
            const=False,
            dest="pytest_compression_enabled",
            help="Disable pytest output compression (overrides config)",
        )

        # Pytest full-suite steering
        pytest_full_suite_group = parser.add_mutually_exclusive_group()
        pytest_full_suite_group.add_argument(
            "--enable-pytest-full-suite-steering",
            action="store_const",
            const=True,
            dest="pytest_full_suite_steering_enabled",
            default=None,
            help="Enable steering for full pytest suite commands (overrides config)",
        )
        pytest_full_suite_group.add_argument(
            "--disable-pytest-full-suite-steering",
            action="store_const",
            const=False,
            dest="pytest_full_suite_steering_enabled",
            help="Disable steering for full pytest suite commands (overrides config)",
        )

        # Pytest context saving
        parser.add_argument(
            "--enable-pytest-context-saving",
            action="store_true",
            dest="pytest_context_saving_enabled",
            default=None,
            help="Enable pytest context saving - adds -r fE and -q flags to pytest commands (overrides config)",
        )

        # Binary file edit steering
        parser.add_argument(
            "--disable-binary-file-edit-steering",
            action="store_true",
            dest="disable_binary_file_edit_steering",
            default=None,
            help="Disable binary file edit steering (overrides config)",
        )

    def _add_session_testing_arguments(self, parser: argparse.ArgumentParser) -> None:
        """Add session and testing arguments."""
        # Think tags fix
        parser.add_argument(
            "--fix-think-tags",
            action="store_true",
            dest="fix_think_tags_enabled",
            default=None,
            help="Enable correction of improperly formatted <think> tags in model responses",
        )

        # Test execution reminder
        test_exec_reminder_group = parser.add_mutually_exclusive_group()
        test_exec_reminder_group.add_argument(
            "--test-execution-reminder-enabled",
            action="store_const",
            const=True,
            dest="test_execution_reminder_enabled",
            default=None,
            help="Enable test execution reminder steering (overrides config)",
        )
        test_exec_reminder_group.add_argument(
            "--no-test-execution-reminder-enabled",
            action="store_const",
            const=False,
            dest="test_execution_reminder_enabled",
            help="Disable test execution reminder steering (overrides config)",
        )

        # Dangerous command protection
        parser.add_argument(
            "--disable-dangerous-git-commands-protection",
            action="store_true",
            dest="disable_dangerous_git_commands_protection",
            default=None,
            help="Disable protection against dangerous git commands (overwrites config file and environment variable)",
        )

        # Windows double-ampersand fixes
        parser.add_argument(
            "--disable-double-ampersand-fixes-for-windows",
            action="store_true",
            dest="disable_double_ampersand_fixes_for_windows",
            default=None,
            help="Disable automatic && to ; replacement in commands for Windows clients",
        )

    def _add_b2bua_arguments(self, parser: argparse.ArgumentParser) -> None:
        """Add B2BUA session handling arguments."""
        b2bua_group = parser.add_argument_group(
            "B2BUA Session Handling",
            "Options for A-leg/B-leg session identity isolation and continuity",
        )

        b2bua_toggle_group = b2bua_group.add_mutually_exclusive_group()
        b2bua_toggle_group.add_argument(
            "--enable-b2bua-session-handling",
            dest="b2bua_enabled",
            action="store_const",
            const=True,
            default=None,
            help="Enable B2BUA-like A-leg/B-leg session handling",
        )
        b2bua_toggle_group.add_argument(
            "--disable-b2bua-session-handling",
            dest="b2bua_enabled",
            action="store_const",
            const=False,
            help="Disable B2BUA-like A-leg/B-leg session handling",
        )

        b2bua_group.add_argument(
            "--b2bua-continuity-max-age-seconds",
            dest="b2bua_continuity_max_age_seconds",
            type=int,
            metavar="SECONDS",
            help="Maximum age for continuity mapping entries (default: 3600)",
        )

        expiration_group = b2bua_group.add_mutually_exclusive_group()
        expiration_group.add_argument(
            "--b2bua-continuity-sliding-expiration",
            dest="b2bua_continuity_sliding_expiration",
            action="store_const",
            const=True,
            default=None,
            help="Extend B2BUA continuity mapping expiry on activity",
        )
        expiration_group.add_argument(
            "--b2bua-continuity-fixed-expiration",
            dest="b2bua_continuity_sliding_expiration",
            action="store_const",
            const=False,
            help="Use fixed expiration for B2BUA continuity mapping entries",
        )

        persistence_group = b2bua_group.add_mutually_exclusive_group()
        persistence_group.add_argument(
            "--enable-b2bua-persistent-mapping-store",
            dest="b2bua_persistent_mapping_store_enabled",
            action="store_const",
            const=True,
            default=None,
            help="Enable persistent continuity mapping store for B2BUA",
        )
        persistence_group.add_argument(
            "--disable-b2bua-persistent-mapping-store",
            dest="b2bua_persistent_mapping_store_enabled",
            action="store_const",
            const=False,
            help="Disable persistent continuity mapping store for B2BUA",
        )

        echo_group = b2bua_group.add_mutually_exclusive_group()
        echo_group.add_argument(
            "--enable-b2bua-session-echo",
            dest="b2bua_echo_enabled",
            action="store_const",
            const=True,
            default=None,
            help="Enable A-leg session echo header in responses",
        )
        echo_group.add_argument(
            "--disable-b2bua-session-echo",
            dest="b2bua_echo_enabled",
            action="store_const",
            const=False,
            help="Disable A-leg session echo header in responses",
        )

        b2bua_group.add_argument(
            "--b2bua-session-echo-header-name",
            dest="b2bua_echo_header_name",
            metavar="HEADER",
            help="Header name for A-leg session echo (default: x-b2bua-session-id)",
        )

        unsafe_group = b2bua_group.add_mutually_exclusive_group()
        unsafe_group.add_argument(
            "--enable-unsafe-legacy-session-inference",
            dest="b2bua_enable_unsafe_heuristic_session_inference",
            action="store_const",
            const=True,
            default=None,
            help="Enable unsafe heuristic continuity when client_session_id is absent",
        )
        unsafe_group.add_argument(
            "--disable-unsafe-legacy-session-inference",
            dest="b2bua_enable_unsafe_heuristic_session_inference",
            action="store_const",
            const=False,
            help="Disable unsafe heuristic continuity when client_session_id is absent",
        )

        b2bua_group.add_argument(
            "--b2bua-deployment-mode",
            dest="b2bua_deployment_mode",
            choices=["single-process", "multi-worker"],
            default=None,
            help="Deployment mode for B2BUA sequence allocation guarantees",
        )

    def _add_tool_access_arguments(self, parser: argparse.ArgumentParser) -> None:
        """Add tool access control arguments."""
        tool_access_group = parser.add_argument_group(
            "Tool Access Control",
            "Options for controlling which tools LLMs can access and execute",
        )
        tool_access_group.add_argument(
            "--allowed-tools",
            dest="tool_access_allowed_tools",
            type=str,
            metavar="PATTERNS",
            help="Comma-separated regex patterns for globally allowed tools (overrides config)",
        )
        tool_access_group.add_argument(
            "--blocked-tools",
            dest="tool_access_blocked_tools",
            type=str,
            metavar="PATTERNS",
            help="Comma-separated regex patterns for globally blocked tools (overrides config)",
        )
        tool_access_group.add_argument(
            "--default-policy",
            dest="tool_access_default_policy",
            choices=["allow", "deny"],
            help="Global default policy when no patterns match: 'allow' or 'deny' (overrides config)",
        )

    def _add_routing_arguments(self, parser: argparse.ArgumentParser) -> None:
        """Add routing control arguments."""
        routing_group = parser.add_argument_group(
            "Routing Control", "Options for restricting routing methods"
        )
        routing_group.add_argument(
            "--disable-routing-with-backend-ids",
            action="store_true",
            dest="disable_routing_with_backend_ids",
            default=None,
            help="Disable routing using explicit backend identifiers (e.g., openai.1:model)",
        )
        routing_group.add_argument(
            "--disable-routing-with-backend-names",
            action="store_true",
            dest="disable_routing_with_backend_names",
            default=None,
            help="Disable routing using backend names (e.g., openai:model). Implies --disable-routing-with-backend-ids",
        )
        routing_group.add_argument(
            "--disable-routing-with-only-model-names",
            action="store_true",
            dest="disable_routing_with_only_model_names",
            default=None,
            help="Disable automatic resolution of backend instances from model name only (e.g., gpt-4)",
        )

    def _add_auxiliary_routing_arguments(self, parser: argparse.ArgumentParser) -> None:
        """Add auxiliary request routing arguments."""
        aux_routing_group = parser.add_argument_group(
            "Auxiliary Request Routing",
            "Options for routing auxiliary requests (title/summary generation) to alternative backends",
        )
        aux_routing_group.add_argument(
            "--enable-auxiliary-routing",
            action="store_true",
            default=None,
            dest="auxiliary_routing_enabled",
            help="Enable routing of auxiliary requests (title/summary generation) to an alternative backend",
        )
        aux_routing_group.add_argument(
            "--auxiliary-routing-model",
            dest="auxiliary_routing_model",
            metavar="MODEL",
            help="Model for auxiliary requests. Can be '<model>' or '<backend>:<model>' format.",
        )
        aux_routing_group.add_argument(
            "--auxiliary-routing-max-messages",
            dest="auxiliary_routing_max_messages",
            type=int,
            metavar="N",
            help="Maximum message count for a request to be considered auxiliary (default: 3)",
        )

    def _add_identity_arguments(self, parser: argparse.ArgumentParser) -> None:
        """Add client identity override arguments."""
        identity_group = parser.add_argument_group(
            "Client Identity Override",
            "Options for overriding client identification headers sent to LLM backends",
        )
        identity_group.add_argument(
            "--identity-user-agent",
            dest="identity_user_agent",
            type=str,
            metavar="VALUE",
            help="Override User-Agent header (client name/version, e.g., 'MyApp/1.0.0')",
        )
        identity_group.add_argument(
            "--identity-url",
            dest="identity_url",
            type=str,
            metavar="URL",
            help="Override HTTP-Referer header (application URL, e.g., 'https://example.com')",
        )
        identity_group.add_argument(
            "--identity-title",
            dest="identity_title",
            type=str,
            metavar="TITLE",
            help="Override X-Title header (application display name, e.g., 'My Application')",
        )

    def _add_memory_arguments(self, parser: argparse.ArgumentParser) -> None:
        """Add ProxyMem (cross-session memory) arguments."""
        memory_group = parser.add_argument_group(
            "ProxyMem (Cross-Session Memory)",
            "Options for configuring the proxy-based memory layer for LLM agents",
        )
        memory_group.add_argument(
            "--memory-available",
            action="store_true",
            dest="memory_available",
            default=None,
            help="Enable ProxyMem feature globally (allows activation via commands or default)",
        )
        memory_group.add_argument(
            "--memory-default-enabled",
            action="store_true",
            dest="memory_default_enabled",
            default=None,
            help="Enable memory gathering by default for new sessions (requires --memory-available)",
        )
        memory_group.add_argument(
            "--memory-summary-model",
            type=str,
            dest="memory_summary_model",
            metavar="BACKEND:MODEL",
            help="Model for generating session summaries (e.g., openai:gpt-4o)",
        )
        memory_group.add_argument(
            "--memory-context-model",
            type=str,
            dest="memory_context_model",
            metavar="BACKEND:MODEL",
            help="Model for retrieving relevant context (e.g., openai:gpt-4o-mini)",
        )
        memory_group.add_argument(
            "--memory-summary-prompt",
            type=str,
            dest="memory_summary_prompt",
            metavar="PATH",
            help="Path to custom summary prompt file (.txt or .md)",
        )
        memory_group.add_argument(
            "--memory-context-prompt",
            type=str,
            dest="memory_context_prompt",
            metavar="PATH",
            help="Path to custom context retrieval prompt file (.txt or .md)",
        )
        memory_group.add_argument(
            "--memory-database-path",
            type=str,
            dest="memory_database_path",
            metavar="PATH",
            help="Path to SQLite database for session summaries (default: ./var/memory.sqlite3)",
        )
        memory_group.add_argument(
            "--memory-session-timeout",
            type=int,
            dest="memory_session_timeout",
            metavar="MINUTES",
            help="Session inactivity timeout before triggering analysis (default: 30)",
        )
        memory_group.add_argument(
            "--memory-summarization-delay",
            type=int,
            dest="memory_summarization_delay",
            metavar="SECONDS",
            help="Delay before summarizing completed sessions (default: 120)",
        )
        memory_group.add_argument(
            "--memory-max-sessions-to-consider",
            type=int,
            dest="memory_max_sessions_to_consider",
            metavar="COUNT",
            help="Max recent sessions to consider for context (default: 10)",
        )
        memory_group.add_argument(
            "--memory-retention-days",
            type=int,
            dest="memory_retention_days",
            metavar="DAYS",
            help="Number of days to retain session summaries (default: 90)",
        )
        memory_group.add_argument(
            "--memory-max-context-tokens",
            type=int,
            dest="memory_max_context_tokens",
            metavar="TOKENS",
            help="Maximum tokens for injected context (default: 2000)",
        )
        memory_group.add_argument(
            "--memory-max-summary-tokens",
            type=int,
            dest="memory_max_summary_tokens",
            metavar="TOKENS",
            help="Maximum tokens for summary prompt context (default: 800)",
        )
        memory_group.add_argument(
            "--memory-max-transcript-chars",
            type=int,
            dest="memory_max_transcript_chars",
            metavar="CHARS",
            help="Maximum transcript length before chunking (default: 50000)",
        )
        memory_group.add_argument(
            "--memory-summary-completion-tokens",
            type=int,
            dest="memory_summary_completion_tokens",
            metavar="TOKENS",
            help="Max completion tokens for summary generation (default: 10000)",
        )
        memory_group.add_argument(
            "--memory-context-relevance-threshold",
            type=float,
            dest="memory_context_relevance_threshold",
            metavar="THRESHOLD",
            help="Minimum relevance score for context injection (0.0-1.0, default: 0.5)",
        )
        memory_group.add_argument(
            "--memory-max-buffer-size-bytes",
            type=int,
            dest="memory_max_buffer_size_bytes",
            metavar="BYTES",
            help="Maximum capture buffer size per session (default: 10485760)",
        )
        memory_group.add_argument(
            "--memory-analysis-queue-maxsize",
            type=int,
            dest="memory_analysis_queue_maxsize",
            metavar="COUNT",
            help="Maximum size of the analysis queue (default: 100)",
        )
        memory_group.add_argument(
            "--memory-analysis-timeout",
            type=int,
            dest="memory_analysis_timeout_seconds",
            metavar="SECONDS",
            help="Timeout for summary generation per session (default: 30)",
        )
        memory_group.add_argument(
            "--memory-max-concurrent-analyses",
            type=int,
            dest="memory_max_concurrent_analyses",
            metavar="COUNT",
            help="Maximum concurrent summary analyses (default: 4)",
        )
        memory_group.add_argument(
            "--memory-context-template",
            type=str,
            dest="memory_context_template",
            metavar="TEMPLATE",
            help="Template for context injection; use {context} placeholder",
        )
        memory_group.add_argument(
            "--memory-single-user-mode",
            action="store_true",
            dest="memory_single_user_mode",
            default=None,
            help="Enable single-user mode (bypass user identity requirements)",
        )
        memory_group.add_argument(
            "--memory-fixed-user-id",
            type=str,
            dest="memory_fixed_user_id",
            metavar="USER_ID",
            help="Fixed user ID for single-user mode",
        )
        memory_group.add_argument(
            "--memory-persist-transcript",
            action="store_true",
            dest="memory_persist_transcript",
            default=None,
            help="Persist full transcripts for memory summaries (default: false)",
        )
        memory_group.add_argument(
            "--memory-redaction-pattern",
            action="append",
            dest="memory_redaction_patterns",
            metavar="REGEX",
            help="Regex pattern for redacting sensitive data (can be specified multiple times)",
        )
        memory_group.add_argument(
            "--memory-disable-user",
            action="append",
            dest="memory_disabled_users",
            metavar="USER_ID",
            help="User ID to exclude from memory features (can be specified multiple times)",
        )
        memory_group.add_argument(
            "--memory-disable-client",
            action="append",
            dest="memory_disabled_clients",
            metavar="CLIENT",
            help="Client/agent name to exclude from memory features (can be specified multiple times)",
        )
        memory_group.add_argument(
            "--memory-summary-prompt-version",
            type=str,
            dest="memory_summary_prompt_version",
            metavar="VERSION",
            help="Summary prompt version identifier (default: v1)",
        )
        memory_group.add_argument(
            "--memory-summary-schema-version",
            type=str,
            dest="memory_summary_schema_version",
            metavar="VERSION",
            help="Summary schema version identifier (default: v1)",
        )
        memory_group.add_argument(
            "--memory-require-project-discovery",
            dest="memory_require_project_discovery",
            action="store_true",
            default=None,
            help="Require project discovery before injecting context (default: true)",
        )
        memory_group.add_argument(
            "--memory-allow-missing-project",
            dest="memory_require_project_discovery",
            action="store_false",
            default=None,
            help="Allow context injection without discovered project root",
        )
        memory_group.add_argument(
            "--memory-project-discovery-mode",
            type=str,
            dest="memory_project_discovery_mode",
            choices=["deterministic", "nondeterministic", "any"],
            metavar="MODE",
            help="Project discovery mode (deterministic|nondeterministic|any, default: any)",
        )

    def _add_failure_handling_arguments(self, parser: argparse.ArgumentParser) -> None:
        """Add failure handling arguments."""
        failure_group = parser.add_argument_group(
            "Failure Handling",
            "Configure automatic retry and failover behavior for backend errors",
        )
        failure_group.add_argument(
            "--disable-failure-handling",
            dest="disable_failure_handling",
            action="store_true",
            help="Disable automatic failure handling (retry/failover)",
        )
        failure_group.add_argument(
            "--max-silent-wait",
            dest="max_silent_wait",
            type=float,
            metavar="SECONDS",
            help="Max seconds to wait before failover (default: 60.0). "
            "If retry-after <= this, proxy waits silently. If > this, it fails over.",
        )
        failure_group.add_argument(
            "--total-timeout-budget",
            dest="total_timeout_budget",
            type=float,
            metavar="SECONDS",
            help="Total timeout budget across all failover attempts (default: 90.0)",
        )
        failure_group.add_argument(
            "--keepalive-interval",
            dest="keepalive_interval",
            type=float,
            metavar="SECONDS",
            help="Seconds between SSE keepalive comments during waits (default: 8.0)",
        )
        failure_group.add_argument(
            "--max-failover-hops",
            dest="max_failover_hops",
            type=int,
            metavar="N",
            help="Maximum backend instances to try in failover chain (default: 5)",
        )
        failure_group.add_argument(
            "--min-retry-wait",
            dest="min_retry_wait",
            type=float,
            metavar="SECONDS",
            help="Minimum retry wait even for sub-second retry-after (default: 1.0)",
        )

    def _add_resilience_arguments(self, parser: argparse.ArgumentParser) -> None:
        """Add resilience scoping arguments."""
        resilience_group = parser.add_argument_group(
            "Resilience Scoping",
            "Configure how rate-limit and cooldown state is shared across clients",
        )
        resilience_group.add_argument(
            "--resilience-personal-backends",
            dest="resilience_personal_backends",
            action="append",
            type=self._parse_csv_list,
            metavar="BACKEND[,BACKEND...]",
            help=(
                "Force personal scoping for listed backend types. "
                "Provide a comma-separated list or repeat the flag."
            ),
        )
        resilience_group.add_argument(
            "--resilience-shared-backends",
            dest="resilience_shared_backends",
            action="append",
            type=self._parse_csv_list,
            metavar="BACKEND[,BACKEND...]",
            help=(
                "Force shared scoping for listed backend types. "
                "Provide a comma-separated list or repeat the flag."
            ),
        )

    def _add_end_of_session_arguments(self, parser: argparse.ArgumentParser) -> None:
        """Add end-of-session event arguments."""
        eos_group = parser.add_argument_group(
            "End-of-Session Events",
            "Options for end-of-session detection and event emission",
        )
        eos_group.add_argument(
            "--enable-end-of-session",
            dest="end_of_session_enabled",
            action="store_true",
            default=None,
            help="Enable end-of-session detection and event emission",
        )
        eos_group.add_argument(
            "--disable-end-of-session",
            dest="end_of_session_enabled",
            action="store_false",
            default=None,
            help="Disable end-of-session detection and event emission",
        )
        eos_group.add_argument(
            "--end-of-session-emit-events",
            dest="end_of_session_emit_events",
            action="store_true",
            default=None,
            help="Enable event emission (default when EoS is enabled)",
        )
        eos_group.add_argument(
            "--end-of-session-detect-only",
            dest="end_of_session_emit_events",
            action="store_false",
            default=None,
            help="Enable detect-only mode (no events emitted)",
        )
        eos_group.add_argument(
            "--end-of-session-dispatch-timeout",
            dest="end_of_session_dispatch_timeout_seconds",
            type=float,
            metavar="SECONDS",
            help="Maximum time to wait for event dispatch (default: 5.0, 0 for fire-and-forget)",
        )

    def _add_access_mode_arguments(self, parser: argparse.ArgumentParser) -> None:
        """Add access mode selection arguments."""
        access_mode_group = parser.add_mutually_exclusive_group()
        access_mode_group.add_argument(
            "--single-user-mode",
            dest="single_user_mode",
            action="store_true",
            default=False,
            help=(
                "Run in Single User Mode (default). Allows OAuth connectors, "
                "optional authentication, localhost-only binding. Suitable for "
                "local development."
            ),
        )
        access_mode_group.add_argument(
            "--multi-user-mode",
            dest="multi_user_mode",
            action="store_true",
            default=False,
            help=(
                "Run in Multi User Mode. Blocks OAuth connectors, requires "
                "authentication for non-localhost binding. Suitable for shared "
                "or production deployments."
            ),
        )
