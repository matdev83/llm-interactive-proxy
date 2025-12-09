"""
Enhanced CLI implementation using staged initialization with 100% feature parity.

This demonstrates how the new architecture provides the same functionality as the original
CLI while maintaining clean separation of concerns through staged initialization.
"""

import argparse
import asyncio
import contextlib
import logging
import os
import re
import socket
import sys
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any, cast

import uvicorn
from fastapi import FastAPI

from src.anthropic_server import create_anthropic_app_async
from src.command_prefix import validate_command_prefix
from src.constants import DEFAULT_COMMAND_PREFIX
from src.core.app.application_builder import (
    ApplicationBuilder,
    build_app_async,
)
from src.core.common.uvicorn_logging import (
    get_uvicorn_logging_config,
)
from src.core.config.app_config import AppConfig, LogLevel, _merge_dicts, load_config
from src.core.config.parameter_resolution import ParameterResolution, ParameterSource

# Import backend connectors to ensure they register themselves
from src.core.services import backend_imports  # noqa: F401
from src.core.services.backend_registry import backend_registry

logger = logging.getLogger(__name__)


def is_port_in_use(host: str, port: int) -> bool:
    """Check if a port is in use on a given host."""

    try:
        addr_infos = socket.getaddrinfo(
            host,
            port,
            type=socket.SOCK_STREAM,
        )
    except socket.gaierror as exc:
        logger.debug("Failed to resolve host %s:%s: %s", host, port, exc)
        return False

    for family, socktype, proto, _, sockaddr in addr_infos:
        try:
            with socket.socket(family, socktype, proto) as sock:
                sock.settimeout(0.1)
                if sock.connect_ex(sockaddr) == 0:
                    return True
        except OSError as exc:
            logger.debug(
                "Port probe failed for %s:%s using family %s: %s",
                host,
                port,
                family,
                exc,
            )
            continue

    return False


def _normalize_api_key_value(value: str | Sequence[str]) -> list[str]:
    """Normalize CLI-supplied API key values into the expected list format."""

    if isinstance(value, str):
        cleaned = value.strip()
        return [cleaned] if cleaned else []

    return [item for item in value if isinstance(item, str) and item.strip()]


def build_cli_parser() -> argparse.ArgumentParser:
    """Build the CLI argument parser with full feature parity to original CLI."""
    parser = argparse.ArgumentParser(description="Run the LLM proxy server")

    # Dynamically get registered backends
    registered_backends: list[str] = backend_registry.get_registered_backends()

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

    def validate_model_alias(value: str) -> tuple[str, str]:
        """Validate model alias format: pattern=replacement"""
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

    parser.add_argument(
        "--model-alias",
        dest="model_aliases",
        action="append",
        metavar="PATTERN=REPLACEMENT",
        type=validate_model_alias,
        help="Add a model name rewrite rule. Pattern is a regex, replacement can use capture groups (\\1, \\2, etc.). Can be specified multiple times. Example: --model-alias '^gpt-(.*)=openrouter:openai/gpt-\\1'",
    )

    # Angel verification model (experimental)
    parser.add_argument(
        "--use-angel-model",
        dest="use_angel_model",
        metavar="BACKEND:MODEL[?params]",
        help=(
            "Enable Angel verification with model spec (e.g., "
            "anthropic:claude-3-5-sonnet?temperature=1&reasoning_effort=high)"
        ),
    )
    parser.add_argument(
        "--angel-frequency",
        dest="angel_frequency",
        type=int,
        metavar="N",
        help="Run Angel verification every N user turns (default: 1)",
    )

    # API Keys and URLs
    parser.add_argument("--openrouter-api-key")
    parser.add_argument("--openrouter-api-base-url")
    parser.add_argument("--gemini-api-key")
    parser.add_argument("--gemini-api-base-url")
    parser.add_argument("--zai-api-key")
    parser.add_argument("--zenmux-api-base-url")

    # Basic server options
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

    # Logging options
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

    # Feature flags
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

    # History Compaction options
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

    # Planning phase options
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

    # Edit-precision tuning options
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

    # Activity tracking (disabled by default for performance)
    parser.add_argument(
        "--enable-activity-tracking",
        dest="enable_activity_tracking",
        action="store_true",
        default=None,
        help="Enable real-time connection activity tracking (RX/TX counters per session)",
    )

    # Backend Debugging Overrides
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
        help="Enable the Gemini Antigravity backend connector for debugging. Reserved for internal development.",
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
        "--enable-droid-path-fix",
        action="store_true",
        dest="droid_path_fix_enabled",
        default=False,
        help="Enable automatic path fixing for Droid agent sessions. Converts relative paths to absolute paths.",
    )

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

    # Pytest output compression
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

    # Tool Access Control arguments
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

    # Routing Control arguments
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

    # LLM Assessment arguments
    assessment_group = parser.add_argument_group(
        "LLM Assessment", "Options for LLM-based conversation assessment"
    )
    # Primary enable flag (opt-in design - feature is disabled by default)
    assessment_group.add_argument(
        "--enable-llm-assessment",
        action="store_true",
        dest="llm_assessment_enabled",
        help="Enable LLM-based conversation assessment for detecting unproductive patterns",
    )
    # Legacy alias for backward compatibility
    assessment_group.add_argument(
        "--enable-llm-loop-assessment",
        action="store_true",
        dest="llm_assessment_enabled",
        help=argparse.SUPPRESS,  # Hide from help, kept for backward compatibility
    )
    assessment_group.add_argument(
        "--disable-llm-loop-assessment",
        action="store_false",
        dest="llm_assessment_enabled",
        default=None,
        help="Disable LLM-based conversation assessment (overrides config)",
    )

    assessment_group.add_argument(
        "--llm-assessment-turn-threshold",
        type=int,
        help="Number of turns before assessment is activated (default: 30, replicates gemini-cli LLM_CHECK_AFTER_TURNS)",
    )
    assessment_group.add_argument(
        "--llm-assessment-confidence-threshold",
        type=float,
        help="Confidence threshold for triggering interventions (default: 0.9)",
    )
    assessment_group.add_argument(
        "--llm-assessment-model",
        type=str,
        dest="llm_assessment_model",
        metavar="BACKEND:MODEL",
        help="Consolidated backend and model for loop assessment (e.g., openai:gpt-4o-mini)",
    )
    assessment_group.add_argument(
        "--llm-assessment-history-window",
        type=int,
        help="Number of recent conversation turns to include in assessment (default: 20, replicates gemini-cli LLM_LOOP_CHECK_HISTORY_COUNT)",
    )

    # Client Identity Override arguments
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

    # ProxyMem (Cross-Session Memory) arguments
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
        "--memory-context-relevance-threshold",
        type=float,
        dest="memory_context_relevance_threshold",
        metavar="THRESHOLD",
        help="Minimum relevance score for context injection (0.0-1.0, default: 0.5)",
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

    # Failure handling configuration
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
        help="Max seconds to wait before failover (default: 30.0). "
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

    return parser


def _validate_llm_loop_assessment_config(args: argparse.Namespace) -> None:
    """Validate LLM assessment configuration.

    Raises:
        ValueError: If assessment is enabled but the model is missing or invalid.
    """
    # Check if assessment is enabled
    assessment_enabled = getattr(args, "llm_assessment_enabled", None)
    if not assessment_enabled:
        return

    # Get the consolidated model string
    model_str = getattr(args, "llm_assessment_model", None)

    # The model must be provided when assessment is enabled
    if not model_str or not model_str.strip():
        raise ValueError(
            "LLM assessment model must be specified when --enable-llm-assessment is used.\n"
            "Use --llm-assessment-model BACKEND:MODEL\n"
            "Example: --llm-assessment-model openai:gpt-4o-mini"
        )

    # Validate the format
    if ":" not in model_str:
        raise ValueError(
            "Invalid format for --llm-assessment-model. Expected BACKEND:MODEL.\n"
            "Example: --llm-assessment-model openai:gpt-4o-mini"
        )

    backend, model = model_str.split(":", 1)
    backend = backend.strip()
    model = model.strip()
    if not backend or not model:
        raise ValueError(
            "Invalid format for --llm-assessment-model. Both backend and model must be specified.\n"
            "Example: --llm-assessment-model openai:gpt-4o-mini"
        )

    # Validate backend exists
    try:
        import importlib

        importlib.import_module("src.connectors")
        from src.core.services.backend_registry import backend_registry

        registered_backends = backend_registry.get_registered_backends()
        if backend not in registered_backends:
            available_backends = ", ".join(sorted(registered_backends))
            raise ValueError(
                f"Invalid backend '{backend}' specified for LLM assessment.\n"
                f"Available backends: {available_backends}\n"
                f"Use a valid backend in the format BACKEND:MODEL."
            )
    except ImportError:
        # If we can't import connectors, skip backend validation
        pass


def parse_cli_args(argv: list[str] | None = None) -> argparse.Namespace:
    """Parse command line arguments with full feature parity to original CLI."""
    parser = build_cli_parser()
    parsed_args = parser.parse_args(argv)

    # Validate LLM loop assessment configuration
    _validate_llm_loop_assessment_config(parsed_args)

    return parsed_args


def apply_cli_args(
    args: argparse.Namespace,
    *,
    return_resolution: bool = False,
    resolution: ParameterResolution | None = None,
) -> AppConfig | tuple[AppConfig, ParameterResolution]:
    """Apply CLI arguments to configuration with full feature parity."""
    res = resolution or ParameterResolution()
    config_path = getattr(args, "config_file", None)
    cfg: AppConfig = cast(
        AppConfig,
        load_config(config_path, resolution=res),
    )

    def record_cli(path: str, value: Any, flag: str) -> None:
        res.record(path, value, ParameterSource.CLI, origin=flag)

    # Collect all CLI overrides in a dict to create a new config
    cli_overrides: dict[str, Any] = {}

    # Basic server configuration
    if args.host is not None:
        cli_overrides["host"] = args.host
        record_cli("host", args.host, "--host")
    if args.port is not None:
        cli_overrides["port"] = args.port
        os.environ["PROXY_PORT"] = str(args.port)
        record_cli("port", args.port, "--port")

    # Anthropic port must be handled after main port to allow derivation
    if args.anthropic_port is not None:
        cli_overrides["anthropic_port"] = args.anthropic_port
        record_cli("anthropic_port", args.anthropic_port, "--anthropic-port")
    elif "port" in cli_overrides:
        # If main port is overridden, we no longer automatically derive anthropic_port
        pass

    if args.timeout is not None:
        cli_overrides["proxy_timeout"] = args.timeout
        record_cli("proxy_timeout", args.timeout, "--timeout")
    if args.command_prefix is not None:
        cli_overrides["command_prefix"] = args.command_prefix
        os.environ["COMMAND_PREFIX"] = args.command_prefix
        record_cli("command_prefix", args.command_prefix, "--command-prefix")

    # Context window override
    if args.force_context_window is not None:
        cli_overrides["context_window_override"] = args.force_context_window
        os.environ["FORCE_CONTEXT_WINDOW"] = str(args.force_context_window)
        record_cli(
            "context_window_override",
            args.force_context_window,
            "--force-context-window",
        )

    # Activity tracking (disabled by default for performance)
    if getattr(args, "enable_activity_tracking", None):
        cli_overrides["enable_activity_tracking"] = True
        os.environ["ENABLE_ACTIVITY_TRACKING"] = "1"
        record_cli(
            "enable_activity_tracking",
            True,
            "--enable-activity-tracking",
        )

    # Thinking budget override (for reasoning/thinking tokens)
    if args.thinking_budget is not None:
        if "session" not in cli_overrides:
            cli_overrides["session"] = {}
        session_overrides = cli_overrides.setdefault("session", {})
        planning_phase_overrides = session_overrides.setdefault("planning_phase", {})
        overrides = planning_phase_overrides.setdefault("overrides", {})
        overrides["thinking_budget"] = args.thinking_budget
        os.environ["THINKING_BUDGET"] = str(args.thinking_budget)
        record_cli(
            "session.planning_phase.overrides.thinking_budget",
            args.thinking_budget,
            "--thinking-budget",
        )

    # Logging configuration
    logging_overrides: dict[str, Any] = {}
    if args.log_file is not None:
        log_path = Path(args.log_file).expanduser()
        log_path.parent.mkdir(parents=True, exist_ok=True)
        logging_overrides["log_file"] = str(log_path)
        record_cli("logging.log_file", str(log_path), "--log")
    elif cfg.logging.log_file is None:
        # Set default log file only if none specified in config or CLI
        default_log_file = Path("./var/logs/proxy.log")
        # Ensure logs directory exists
        default_log_file.parent.mkdir(parents=True, exist_ok=True)
        # Apply the default to logging_overrides so it gets used
        logging_overrides["log_file"] = str(default_log_file)
        record_cli("logging.log_file", str(default_log_file), "default")
    if args.log_level is not None:
        logging_overrides["level"] = LogLevel[args.log_level]
        record_cli("logging.level", LogLevel[args.log_level].value, "--log-level")

    # Wire capture configuration
    if getattr(args, "capture_file", None) is not None:
        logging_overrides["capture_file"] = args.capture_file
        record_cli("logging.capture_file", args.capture_file, "--capture-file")
    if getattr(args, "capture_max_bytes", None) is not None:
        logging_overrides["capture_max_bytes"] = args.capture_max_bytes
        record_cli(
            "logging.capture_max_bytes", args.capture_max_bytes, "--capture-max-bytes"
        )
    if getattr(args, "capture_truncate_bytes", None) is not None:
        logging_overrides["capture_truncate_bytes"] = args.capture_truncate_bytes
        record_cli(
            "logging.capture_truncate_bytes",
            args.capture_truncate_bytes,
            "--capture-truncate-bytes",
        )
    if getattr(args, "capture_max_files", None) is not None:
        logging_overrides["capture_max_files"] = args.capture_max_files
        record_cli(
            "logging.capture_max_files", args.capture_max_files, "--capture-max-files"
        )
    if getattr(args, "capture_rotate_interval_seconds", None) is not None:
        logging_overrides["capture_rotate_interval_seconds"] = (
            args.capture_rotate_interval_seconds
        )
        record_cli(
            "logging.capture_rotate_interval_seconds",
            args.capture_rotate_interval_seconds,
            "--capture-rotate-interval",
        )
    if getattr(args, "capture_total_max_bytes", None) is not None:
        logging_overrides["capture_total_max_bytes"] = args.capture_total_max_bytes
        record_cli(
            "logging.capture_total_max_bytes",
            args.capture_total_max_bytes,
            "--capture-total-max-bytes",
        )

    # CBOR byte-precise capture configuration
    if getattr(args, "cbor_capture_dir", None) is not None:
        logging_overrides["cbor_capture_dir"] = args.cbor_capture_dir
        record_cli(
            "logging.cbor_capture_dir",
            args.cbor_capture_dir,
            "--cbor-capture-dir",
        )
    if getattr(args, "cbor_capture_session_id", None) is not None:
        logging_overrides["cbor_capture_session_id"] = args.cbor_capture_session_id
        record_cli(
            "logging.cbor_capture_session_id",
            args.cbor_capture_session_id,
            "--cbor-capture-session",
        )

    # Add logging overrides to main overrides if any
    if logging_overrides:
        cli_overrides["logging"] = logging_overrides

    # Backend-specific configuration
    backend_overrides: dict[str, Any] = {}
    if args.default_backend is not None:
        backend_overrides = cli_overrides.setdefault("backends", {})
        backend_overrides["default_backend"] = args.default_backend
        os.environ["LLM_BACKEND"] = args.default_backend
        record_cli(
            "backends.default_backend", args.default_backend, "--default-backend"
        )

    # Static route configuration
    if getattr(args, "static_route", None) is not None:
        backend_overrides = cli_overrides.setdefault("backends", {})
        backend_overrides["static_route"] = args.static_route
        os.environ["STATIC_ROUTE"] = args.static_route
        record_cli("backends.static_route", args.static_route, "--static-route")
    if getattr(args, "disable_gemini_oauth_fallback", False):
        backend_overrides = cli_overrides.setdefault("backends", {})
        backend_overrides["disable_gemini_oauth_fallback"] = True
        os.environ["DISABLE_GEMINI_OAUTH_FALLBACK"] = "1"
        record_cli(
            "backends.disable_gemini_oauth_fallback",
            True,
            "--disable-gemini-oauth-fallback",
        )
    if getattr(args, "disable_hybrid_backend", False):
        backend_overrides = cli_overrides.setdefault("backends", {})
        backend_overrides["disable_hybrid_backend"] = True
        os.environ["DISABLE_HYBRID_BACKEND"] = "1"
        record_cli(
            "backends.disable_hybrid_backend",
            True,
            "--disable-hybrid-backend",
        )

    if getattr(args, "hybrid_backend_repeat_messages", False):
        backend_overrides = cli_overrides.setdefault("backends", {})
        backend_overrides["hybrid_backend_repeat_messages"] = True
        os.environ["HYBRID_BACKEND_REPEAT_MESSAGES"] = "1"
        record_cli(
            "backends.hybrid_backend_repeat_messages",
            True,
            "--hybrid-backend-repeat-messages",
        )

    if getattr(args, "reasoning_injection_probability", None) is not None:
        backend_overrides = cli_overrides.setdefault("backends", {})
        backend_overrides["reasoning_injection_probability"] = (
            args.reasoning_injection_probability
        )
        record_cli(
            "backends.reasoning_injection_probability",
            args.reasoning_injection_probability,
            "--reasoning-injection-probability",
        )

    if getattr(args, "hybrid_reasoning_model_timeout", None) is not None:
        backend_overrides = cli_overrides.setdefault("backends", {})
        backend_overrides["hybrid_reasoning_model_timeout"] = (
            args.hybrid_reasoning_model_timeout
        )
        os.environ["HYBRID_REASONING_MODEL_TIMEOUT"] = str(
            args.hybrid_reasoning_model_timeout
        )
        record_cli(
            "backends.hybrid_reasoning_model_timeout",
            args.hybrid_reasoning_model_timeout,
            "--hybrid-reasoning-model-timeout",
        )

    if getattr(args, "hybrid_reasoning_force_initial_turns", None) is not None:
        backend_overrides = cli_overrides.setdefault("backends", {})
        backend_overrides["hybrid_reasoning_force_initial_turns"] = (
            args.hybrid_reasoning_force_initial_turns
        )
        os.environ["HYBRID_REASONING_FORCE_INITIAL_TURNS"] = str(
            args.hybrid_reasoning_force_initial_turns
        )
        record_cli(
            "backends.hybrid_reasoning_force_initial_turns",
            args.hybrid_reasoning_force_initial_turns,
            "--hybrid-reasoning-force-initial-turns",
        )

    # Model aliases configuration (CLI overrides config file)
    if getattr(args, "model_aliases", None) is not None:
        from src.core.config.app_config import ModelAliasRule

        # Convert CLI tuples to ModelAliasRule objects
        cli_aliases = [
            ModelAliasRule(pattern=pattern, replacement=replacement)
            for pattern, replacement in args.model_aliases
        ]
        cli_overrides["model_aliases"] = cli_aliases
        record_cli(
            "model_aliases",
            [alias.model_dump() for alias in cli_aliases],
            "--model-alias",
        )

        # Store in environment for other processes
        import json

        alias_data = [
            {"pattern": rule.pattern, "replacement": rule.replacement}
            for rule in cli_aliases
        ]
        os.environ["MODEL_ALIASES"] = json.dumps(alias_data)

    # Compaction configuration
    compaction_overrides: dict[str, Any] = {}
    if getattr(args, "enable_context_compaction", None) is not None:
        compaction_overrides["enabled"] = args.enable_context_compaction
        record_cli(
            "compaction.enabled",
            args.enable_context_compaction,
            "--enable-context-compaction",
        )

    if getattr(args, "compaction_min_tokens", None) is not None:
        compaction_overrides["token_threshold"] = args.compaction_min_tokens
        record_cli(
            "compaction.token_threshold",
            args.compaction_min_tokens,
            "--compaction-min-tokens",
        )

    if compaction_overrides:
        cli_overrides["compaction"] = compaction_overrides

    # API keys and URLs
    if args.openrouter_api_key is not None:
        normalized_key = _normalize_api_key_value(args.openrouter_api_key)
        backend_overrides = cli_overrides.setdefault("backends", {})
        openrouter_overrides = backend_overrides.setdefault("openrouter", {})
        openrouter_overrides["api_key"] = normalized_key
        record_cli(
            "backends.openrouter.api_key",
            normalized_key,
            "--openrouter-api-key",
        )
    if args.openrouter_api_base_url is not None:
        backend_overrides = cli_overrides.setdefault("backends", {})
        openrouter_overrides = backend_overrides.setdefault("openrouter", {})
        openrouter_overrides["api_url"] = args.openrouter_api_base_url
        record_cli(
            "backends.openrouter.api_url",
            args.openrouter_api_base_url,
            "--openrouter-api-base-url",
        )
    if args.gemini_api_key is not None:
        normalized_key = _normalize_api_key_value(args.gemini_api_key)
        backend_overrides = cli_overrides.setdefault("backends", {})
        gemini_overrides = backend_overrides.setdefault("gemini", {})
        gemini_overrides["api_key"] = normalized_key
        if normalized_key:
            os.environ["GEMINI_API_KEY"] = normalized_key[0]
        else:
            os.environ.pop("GEMINI_API_KEY", None)
        record_cli(
            "backends.gemini.api_key",
            normalized_key,
            "--gemini-api-key",
        )
    if args.gemini_api_base_url is not None:
        backend_overrides = cli_overrides.setdefault("backends", {})
        gemini_overrides = backend_overrides.setdefault("gemini", {})
        gemini_overrides["api_url"] = args.gemini_api_base_url
        record_cli(
            "backends.gemini.api_url",
            args.gemini_api_base_url,
            "--gemini-api-base-url",
        )
    if args.zai_api_key is not None:
        normalized_key = _normalize_api_key_value(args.zai_api_key)
        backend_overrides = cli_overrides.setdefault("backends", {})
        zai_overrides = backend_overrides.setdefault("zai", {})
        zai_overrides["api_key"] = normalized_key
        record_cli(
            "backends.zai.api_key",
            normalized_key,
            "--zai-api-key",
        )
    if args.zenmux_api_base_url is not None:
        backend_overrides = cli_overrides.setdefault("backends", {})
        zenmux_overrides = backend_overrides.setdefault("zenmux", {})
        zenmux_overrides["api_url"] = args.zenmux_api_base_url
        record_cli(
            "backends.zenmux.api_url",
            args.zenmux_api_base_url,
            "--zenmux-api-base-url",
        )

    # Feature flags (inverted boolean logic)
    if args.disable_interactive_mode is not None:
        session = cli_overrides.setdefault("session", {})
        session["default_interactive_mode"] = not args.disable_interactive_mode
        os.environ["DEFAULT_INTERACTIVE_MODE"] = (
            "false" if args.disable_interactive_mode else "true"
        )
        os.environ["DISABLE_INTERACTIVE_MODE"] = (
            "True" if args.disable_interactive_mode else "False"
        )
        record_cli(
            "session.default_interactive_mode",
            not args.disable_interactive_mode,
            "--disable-interactive-mode",
        )
    if args.disable_auth is not None:
        auth_overrides = cli_overrides.setdefault("auth", {})
        auth_overrides["disable_auth"] = args.disable_auth
        record_cli("auth.disable_auth", args.disable_auth, "--disable-auth")
    if args.disable_sso_captcha is not None:
        # Note: sso.captcha.enabled is the full path
        if "sso" not in cli_overrides:
            cli_overrides["sso"] = {}
        sso_overrides = cli_overrides.setdefault("sso", {})
        if "captcha" not in sso_overrides:
            sso_overrides["captcha"] = {}
        captcha_overrides = sso_overrides.setdefault("captcha", {})
        captcha_overrides["enabled"] = not args.disable_sso_captcha
        record_cli(
            "sso.captcha.enabled", not args.disable_sso_captcha, "--disable-sso-captcha"
        )
    if args.enable_sso is not None:
        # Feature: sso-authentication - CLI flag to enable SSO
        sso_overrides = cli_overrides.setdefault("sso", {})
        sso_overrides["enabled"] = True
        record_cli("sso.enabled", True, "--enable-sso")
    if getattr(args, "sso_config_path", None) is not None:
        # Feature: sso-authentication - CLI flag to load SSO config file
        # Load the SSO config file and merge it
        import yaml

        sso_config_file = Path(args.sso_config_path)
        if not sso_config_file.exists():
            logger.error(f"SSO config file not found: {args.sso_config_path}")
            sys.exit(1)
        with open(sso_config_file) as f:
            sso_file_config = yaml.safe_load(f)
        if sso_file_config:
            # Merge SSO config from file
            sso_overrides = cli_overrides.setdefault("sso", {})

            # Deep merge the config
            def merge_dict(target, source):
                for key, value in source.items():
                    if (
                        isinstance(value, dict)
                        and key in target
                        and isinstance(target[key], dict)
                    ):
                        merge_dict(target[key], value)
                    else:
                        target[key] = value

            merge_dict(sso_overrides, sso_file_config.get("sso", sso_file_config))
            record_cli("sso", f"loaded from {args.sso_config_path}", "--sso-config")
    if getattr(args, "sso_provider", None) is not None:
        # Feature: sso-authentication - CLI flag to select specific provider
        # Requirement 1.1: Enable SSO via CLI
        # Disable all providers except the specified one
        sso_overrides = cli_overrides.setdefault("sso", {})
        providers_overrides = sso_overrides.setdefault("providers", {})

        # Mark the specified provider as the only enabled one
        # This will be merged with config, effectively disabling others
        specified_provider = args.sso_provider

        # We need to disable all OTHER providers
        # Since we don't know all providers at this stage, we'll use a special marker
        providers_overrides["_cli_selected_provider"] = specified_provider
        record_cli(
            "sso.providers", f"only {specified_provider} enabled", "--sso-provider"
        )

        # Note: The actual provider disabling will happen in config merge logic
        # For now, we'll enable the specified provider explicitly
        if specified_provider not in providers_overrides:
            providers_overrides[specified_provider] = {}
        providers_overrides[specified_provider]["enabled"] = True

    if getattr(args, "sso_auth_mode", None) is not None:
        # Feature: sso-authentication - CLI flag to set authorization mode
        # Requirement 1.1: Configure SSO via CLI
        sso_overrides = cli_overrides.setdefault("sso", {})
        auth_overrides = sso_overrides.setdefault("authorization", {})
        auth_overrides["mode"] = args.sso_auth_mode
        record_cli("sso.authorization.mode", args.sso_auth_mode, "--sso-auth-mode")
    if getattr(args, "trusted_ips", None) is not None:
        auth_overrides = cli_overrides.setdefault("auth", {})
        auth_overrides["trusted_trusted_ips"] = args.trusted_ips
        record_cli("auth.trusted_ips", args.trusted_ips, "--trusted-ip")
    if args.force_set_project is not None:
        session = cli_overrides.setdefault("session", {})
        session["force_set_project"] = args.force_set_project
        os.environ["FORCE_SET_PROJECT"] = "true" if args.force_set_project else "false"
        record_cli(
            "session.force_set_project", args.force_set_project, "--force-set-project"
        )
    if getattr(args, "project_dir_resolution_model", None) is not None:
        session = cli_overrides.setdefault("session", {})
        session["project_dir_resolution_model"] = args.project_dir_resolution_model
        record_cli(
            "session.project_dir_resolution_model",
            args.project_dir_resolution_model,
            "--project-dir-resolution-model",
        )
    if getattr(args, "project_dir_resolution_mode", None) is not None:
        session = cli_overrides.setdefault("session", {})
        session["project_dir_resolution_mode"] = args.project_dir_resolution_mode
        record_cli(
            "session.project_dir_resolution_mode",
            args.project_dir_resolution_mode,
            "--project-dir-resolution-mode",
        )

    if getattr(args, "log_use_colors", None) is not None:
        logging_overrides = cli_overrides.setdefault("logging", {})
        logging_overrides["use_colors"] = args.log_use_colors
        record_cli(
            "logging.use_colors",
            args.log_use_colors,
            "--log-colors" if args.log_use_colors else "--no-log-colors",
        )

    # These still rely on environment variables for now
    if args.disable_redact_api_keys_in_prompts is not None:
        auth_overrides = cli_overrides.setdefault("auth", {})
        auth_overrides["redact_api_keys_in_prompts"] = (
            not args.disable_redact_api_keys_in_prompts
        )
        record_cli(
            "auth.redact_api_keys_in_prompts",
            not args.disable_redact_api_keys_in_prompts,
            "--disable-redact-api-keys-in-prompts",
        )
    if args.disable_interactive_commands is not None:
        session = cli_overrides.setdefault("session", {})
        session["disable_interactive_commands"] = args.disable_interactive_commands
        record_cli(
            "session.disable_interactive_commands",
            args.disable_interactive_commands,
            "--disable-interactive-commands",
        )
    if args.disable_accounting is not None:
        os.environ["DISABLE_ACCOUNTING"] = (
            "true" if args.disable_accounting else "false"
        )
        record_cli(
            "cli.disable_accounting", args.disable_accounting, "--disable-accounting"
        )
    if getattr(args, "strict_command_detection", None) is not None:
        cli_overrides["strict_command_detection"] = args.strict_command_detection
        record_cli(
            "strict_command_detection",
            args.strict_command_detection,
            "--strict-command-detection",
        )

    # Angel verification model override from CLI
    if getattr(args, "use_angel_model", None) is not None:
        session_overrides = cli_overrides.setdefault("session", {})
        session_overrides["angel_model"] = args.use_angel_model
        os.environ["ANGEL_MODEL"] = args.use_angel_model
        record_cli(
            "session.angel_model",
            args.use_angel_model,
            "--use-angel-model",
        )
    if getattr(args, "angel_frequency", None) is not None:
        frequency = max(1, int(args.angel_frequency))
        session_overrides = cli_overrides.setdefault("session", {})
        session_overrides["angel_frequency"] = frequency
        os.environ["ANGEL_FREQUENCY"] = str(frequency)
        record_cli(
            "session.angel_frequency",
            frequency,
            "--angel-frequency",
        )

    # Brute force protection configuration (auth_overrides may already exist from earlier setdefault calls)
    brute_force_overrides: dict[str, Any] = {}

    if getattr(args, "brute_force_protection_enabled", None) is not None:
        brute_force_overrides["enabled"] = bool(args.brute_force_protection_enabled)
        record_cli(
            "auth.brute_force_protection.enabled",
            brute_force_overrides["enabled"],
            "--enable/disable-brute-force-protection",
        )
    if getattr(args, "auth_max_failed_attempts", None) is not None:
        brute_force_overrides["max_failed_attempts"] = max(
            1, int(args.auth_max_failed_attempts)
        )
        record_cli(
            "auth.brute_force_protection.max_failed_attempts",
            brute_force_overrides["max_failed_attempts"],
            "--auth-max-failed-attempts",
        )
    if getattr(args, "auth_brute_force_ttl", None) is not None:
        brute_force_overrides["ttl_seconds"] = max(1, int(args.auth_brute_force_ttl))
        record_cli(
            "auth.brute_force_protection.ttl_seconds",
            brute_force_overrides["ttl_seconds"],
            "--auth-brute-force-ttl",
        )
    if getattr(args, "auth_initial_block_seconds", None) is not None:
        brute_force_overrides["initial_block_seconds"] = max(
            1, int(args.auth_initial_block_seconds)
        )
        record_cli(
            "auth.brute_force_protection.initial_block_seconds",
            brute_force_overrides["initial_block_seconds"],
            "--auth-brute-force-initial-block",
        )
    if getattr(args, "auth_block_multiplier", None) is not None:
        multiplier = float(args.auth_block_multiplier)
        brute_force_overrides["block_multiplier"] = (
            multiplier if multiplier > 1 else 1.0
        )
        record_cli(
            "auth.brute_force_protection.block_multiplier",
            brute_force_overrides["block_multiplier"],
            "--auth-brute-force-multiplier",
        )
    if getattr(args, "auth_max_block_seconds", None) is not None:
        brute_force_overrides["max_block_seconds"] = max(
            1, int(args.auth_max_block_seconds)
        )
        record_cli(
            "auth.brute_force_protection.max_block_seconds",
            brute_force_overrides["max_block_seconds"],
            "--auth-brute-force-max-block",
        )

    # Add brute force overrides to auth if any
    if brute_force_overrides:
        auth_overrides_dict = cli_overrides.setdefault("auth", {})
        auth_overrides_dict["brute_force_protection"] = brute_force_overrides

    # Pytest compression flag
    if args.pytest_compression_enabled is not None:
        session = cli_overrides.setdefault("session", {})
        session["pytest_compression_enabled"] = args.pytest_compression_enabled
        record_cli(
            "session.pytest_compression_enabled",
            args.pytest_compression_enabled,
            "--enable-pytest-compression",
        )

    # Pytest full-suite steering flag
    if getattr(args, "pytest_full_suite_steering_enabled", None) is not None:
        session = cli_overrides.setdefault("session", {})
        session["pytest_full_suite_steering_enabled"] = (
            args.pytest_full_suite_steering_enabled
        )
        # Also update tool_call_reactor
        tool_call_reactor_overrides: dict[str, Any] = session.get(
            "tool_call_reactor", {}
        )
        tool_call_reactor_overrides["pytest_full_suite_steering_enabled"] = (
            args.pytest_full_suite_steering_enabled
        )
        session["tool_call_reactor"] = tool_call_reactor_overrides
        record_cli(
            "session.pytest_full_suite_steering_enabled",
            args.pytest_full_suite_steering_enabled,
            "--enable/disable-pytest-full-suite-steering",
        )

    # Test execution reminder flag
    if getattr(args, "test_execution_reminder_enabled", None) is not None:
        session = cli_overrides.setdefault("session", {})
        session["test_execution_reminder_enabled"] = (
            args.test_execution_reminder_enabled
        )
        # Also update tool_call_reactor
        tool_call_reactor_overrides_ter: dict[str, Any] = session.get(
            "tool_call_reactor", {}
        )
        tool_call_reactor_overrides_ter["test_execution_reminder_enabled"] = (
            args.test_execution_reminder_enabled
        )
        session["tool_call_reactor"] = tool_call_reactor_overrides_ter
        record_cli(
            "session.test_execution_reminder_enabled",
            args.test_execution_reminder_enabled,
            "--test-execution-reminder-enabled/--no-test-execution-reminder-enabled",
        )

    # Droid path fix flag (for Droid agent sessions)
    if getattr(args, "droid_path_fix_enabled", None) is True:
        session = cli_overrides.setdefault("session", {})
        session["droid_path_fix_enabled"] = True

    # Pytest context saving flag
    if getattr(args, "pytest_context_saving_enabled", None) is not None:
        session = cli_overrides.setdefault("session", {})
        # Also update tool_call_reactor
        tool_call_reactor_overrides = session.get("tool_call_reactor", {})
        tool_call_reactor_overrides["pytest_context_saving_enabled"] = (
            args.pytest_context_saving_enabled
        )
        session["tool_call_reactor"] = tool_call_reactor_overrides
        record_cli(
            "session.tool_call_reactor.pytest_context_saving_enabled",
            args.pytest_context_saving_enabled,
            "--enable-pytest-context-saving",
        )

    # Think tags fix flag
    if getattr(args, "fix_think_tags_enabled", None) is not None:
        session = cli_overrides.setdefault("session", {})
        session["fix_think_tags_enabled"] = args.fix_think_tags_enabled
        record_cli(
            "session.fix_think_tags_enabled",
            args.fix_think_tags_enabled,
            "--fix-think-tags",
        )

    # Dangerous command protection
    if getattr(args, "disable_dangerous_git_commands_protection", None) is not None:
        session = cli_overrides.setdefault("session", {})
        # CLI flag should override the default (which is True) and environment variable
        session["dangerous_command_prevention_enabled"] = (
            not args.disable_dangerous_git_commands_protection
        )
        record_cli(
            "session.dangerous_command_prevention_enabled",
            not args.disable_dangerous_git_commands_protection,
            "--disable-dangerous-git-commands-protection",
        )

    # Windows double-ampersand fixes
    if getattr(args, "disable_double_ampersand_fixes_for_windows", None) is not None:
        session = cli_overrides.setdefault("session", {})
        session["double_ampersand_fixes_for_windows_enabled"] = (
            not args.disable_double_ampersand_fixes_for_windows
        )
        record_cli(
            "session.double_ampersand_fixes_for_windows_enabled",
            not args.disable_double_ampersand_fixes_for_windows,
            "--disable-double-ampersand-fixes-for-windows",
        )

    # File access sandboxing
    if getattr(args, "enable_sandboxing", None) is not None:
        sandboxing_overrides = cli_overrides.setdefault("sandboxing", {})
        sandboxing_overrides["enabled"] = args.enable_sandboxing
        os.environ["ENABLE_SANDBOXING"] = "true" if args.enable_sandboxing else "false"
        record_cli(
            "sandboxing.enabled",
            args.enable_sandboxing,
            "--enable-sandboxing",
        )

    # Tool Access Control global overrides
    tool_access_overrides: dict[str, Any] = {}

    if getattr(args, "tool_access_allowed_tools", None) is not None:
        # Parse comma-separated patterns
        patterns = [
            p.strip() for p in args.tool_access_allowed_tools.split(",") if p.strip()
        ]
        tool_access_overrides["allowed_patterns"] = patterns
        record_cli(
            "tool_access.allowed_patterns",
            patterns,
            "--allowed-tools",
        )

    if getattr(args, "tool_access_blocked_tools", None) is not None:
        # Parse comma-separated patterns
        patterns = [
            p.strip() for p in args.tool_access_blocked_tools.split(",") if p.strip()
        ]
        tool_access_overrides["blocked_patterns"] = patterns
        record_cli(
            "tool_access.blocked_patterns",
            patterns,
            "--blocked-tools",
        )

    if getattr(args, "tool_access_default_policy", None) is not None:
        tool_access_overrides["default_policy"] = args.tool_access_default_policy
        record_cli(
            "tool_access.default_policy",
            args.tool_access_default_policy,
            "--default-policy",
        )

    # Add tool access overrides to session if any
    if tool_access_overrides:
        session = cli_overrides.setdefault("session", {})
        session["tool_access_global_overrides"] = tool_access_overrides

    # Routing Control configuration
    routing_overrides: dict[str, Any] = {}
    if getattr(args, "disable_routing_with_backend_ids", None) is not None:
        routing_overrides["disable_backend_ids"] = args.disable_routing_with_backend_ids
        record_cli(
            "routing.disable_backend_ids",
            args.disable_routing_with_backend_ids,
            "--disable-routing-with-backend-ids",
        )
    if getattr(args, "disable_routing_with_backend_names", None) is not None:
        routing_overrides["disable_backend_names"] = (
            args.disable_routing_with_backend_names
        )
        record_cli(
            "routing.disable_backend_names",
            args.disable_routing_with_backend_names,
            "--disable-routing-with-backend-names",
        )
    if getattr(args, "disable_routing_with_only_model_names", None) is not None:
        routing_overrides["disable_model_names"] = (
            args.disable_routing_with_only_model_names
        )
        record_cli(
            "routing.disable_model_names",
            args.disable_routing_with_only_model_names,
            "--disable-routing-with-only-model-names",
        )

    if routing_overrides:
        cli_overrides["routing"] = routing_overrides

    # LLM Assessment configuration
    assessment_overrides: dict[str, Any] = {}

    if getattr(args, "llm_assessment_enabled", None) is not None:
        assessment_overrides["enabled"] = args.llm_assessment_enabled
        record_cli(
            "assessment.enabled",
            args.llm_assessment_enabled,
            "--enable-llm-assessment",
        )

    if getattr(args, "llm_assessment_turn_threshold", None) is not None:
        assessment_overrides["turn_threshold"] = args.llm_assessment_turn_threshold
        record_cli(
            "assessment.turn_threshold",
            args.llm_assessment_turn_threshold,
            "--llm-assessment-turn-threshold",
        )

    if getattr(args, "llm_assessment_confidence_threshold", None) is not None:
        assessment_overrides["confidence_threshold"] = (
            args.llm_assessment_confidence_threshold
        )
        record_cli(
            "assessment.confidence_threshold",
            args.llm_assessment_confidence_threshold,
            "--llm-assessment-confidence-threshold",
        )

    if getattr(args, "llm_assessment_model", None) is not None:
        model_str = args.llm_assessment_model
        backend, model = model_str.split(":", 1)
        assessment_overrides["backend"] = backend
        assessment_overrides["model"] = model
        record_cli(
            "assessment.backend",
            backend,
            "--llm-assessment-model",
        )
        record_cli(
            "assessment.model",
            model,
            "--llm-assessment-model",
        )

    if getattr(args, "llm_assessment_history_window", None) is not None:
        assessment_overrides["history_window"] = args.llm_assessment_history_window
        record_cli(
            "assessment.history_window",
            args.llm_assessment_history_window,
            "--llm-assessment-history-window",
        )

    # Add assessment overrides to main overrides if any
    if assessment_overrides:
        cli_overrides["assessment"] = assessment_overrides

    # Planning phase configuration
    # Only create session dict if planning phase args are present
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
    if planning_phase_args_present:
        session = cli_overrides.setdefault("session", {})
        planning_phase_overrides = session.setdefault("planning_phase", {})
    else:
        # Create temporary references without modifying cli_overrides
        session = {}
        planning_phase_overrides = {}
    if getattr(args, "enable_planning_phase", None) is not None:
        planning_phase_overrides["enabled"] = args.enable_planning_phase
        record_cli(
            "session.planning_phase.enabled",
            args.enable_planning_phase,
            "--enable-planning-phase",
        )
    if getattr(args, "planning_phase_strong_model", None) is not None:
        planning_phase_overrides["strong_model"] = args.planning_phase_strong_model
        record_cli(
            "session.planning_phase.strong_model",
            args.planning_phase_strong_model,
            "--planning-phase-strong-model",
        )
    if getattr(args, "planning_phase_max_turns", None) is not None:
        planning_phase_overrides["max_turns"] = max(1, args.planning_phase_max_turns)
        record_cli(
            "session.planning_phase.max_turns",
            planning_phase_overrides["max_turns"],
            "--planning-phase-max-turns",
        )
    if getattr(args, "planning_phase_max_file_writes", None) is not None:
        planning_phase_overrides["max_file_writes"] = max(
            1, args.planning_phase_max_file_writes
        )
        record_cli(
            "session.planning_phase.max_file_writes",
            planning_phase_overrides["max_file_writes"],
            "--planning-phase-max-file-writes",
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
        existing_overrides = planning_phase_overrides.setdefault("overrides", {})
        existing_overrides.update(overrides_updates)
        flag_mapping = {
            "temperature": "--planning-phase-temperature",
            "top_p": "--planning-phase-top-p",
            "reasoning_effort": "--planning-phase-reasoning-effort",
            "thinking_budget": "--planning-phase-thinking-budget",
        }
        for key, value in overrides_updates.items():
            record_cli(
                f"session.planning_phase.overrides.{key}",
                value,
                flag_mapping.get(key, "--planning-phase-override"),
            )

    # Edit-precision tuning configuration
    edit_precision_overrides: dict[str, Any] = {}
    if getattr(args, "edit_precision_enabled", None) is not None:
        edit_precision_overrides["enabled"] = args.edit_precision_enabled
        record_cli(
            "edit_precision.enabled",
            args.edit_precision_enabled,
            "--enable/disable-edit-precision",
        )
    if getattr(args, "edit_precision_temperature", None) is not None:
        edit_precision_overrides["temperature"] = max(
            0.0, args.edit_precision_temperature
        )
        record_cli(
            "edit_precision.temperature",
            edit_precision_overrides["temperature"],
            "--edit-precision-temperature",
        )
    if getattr(args, "edit_precision_min_top_p", None) is not None:
        edit_precision_overrides["min_top_p"] = max(0.0, args.edit_precision_min_top_p)
        record_cli(
            "edit_precision.min_top_p",
            edit_precision_overrides["min_top_p"],
            "--edit-precision-min-top-p",
        )
    if getattr(args, "edit_precision_override_top_p", None) is not None:
        edit_precision_overrides["override_top_p"] = args.edit_precision_override_top_p
        record_cli(
            "edit_precision.override_top_p",
            edit_precision_overrides["override_top_p"],
            "--edit-precision-override-top-p",
        )
    if getattr(args, "edit_precision_override_top_k", None) is not None:
        edit_precision_overrides["override_top_k"] = args.edit_precision_override_top_k
        record_cli(
            "edit_precision.override_top_k",
            edit_precision_overrides["override_top_k"],
            "--edit-precision-override-top-k",
        )
    if getattr(args, "edit_precision_target_top_k", None) is not None:
        edit_precision_overrides["target_top_k"] = (
            args.edit_precision_target_top_k
            if args.edit_precision_target_top_k > 0
            else None
        )
        record_cli(
            "edit_precision.target_top_k",
            edit_precision_overrides["target_top_k"],
            "--edit-precision-target-top-k",
        )
    if getattr(args, "edit_precision_exclude_agents_regex", None) is not None:
        edit_precision_overrides["exclude_agents_regex"] = (
            args.edit_precision_exclude_agents_regex
        )
        record_cli(
            "edit_precision.exclude_agents_regex",
            edit_precision_overrides["exclude_agents_regex"],
            "--edit-precision-exclude-agents",
        )

    # Client Identity Override configuration
    identity_overrides: dict[str, Any] = {}
    if getattr(args, "identity_user_agent", None) is not None:
        user_agent_override = identity_overrides.setdefault("user_agent", {})
        user_agent_override["mode"] = "override"
        user_agent_override["override_value"] = args.identity_user_agent
        record_cli(
            "identity.user_agent.override_value",
            args.identity_user_agent,
            "--identity-user-agent",
        )
        record_cli("identity.user_agent.mode", "override", "--identity-user-agent")
    if getattr(args, "identity_url", None) is not None:
        url_override = identity_overrides.setdefault("url", {})
        url_override["mode"] = "override"
        url_override["override_value"] = args.identity_url
        record_cli("identity.url.override_value", args.identity_url, "--identity-url")
        record_cli("identity.url.mode", "override", "--identity-url")
    if getattr(args, "identity_title", None) is not None:
        title_override = identity_overrides.setdefault("title", {})
        title_override["mode"] = "override"
        title_override["override_value"] = args.identity_title
        record_cli(
            "identity.title.override_value", args.identity_title, "--identity-title"
        )
        record_cli("identity.title.mode", "override", "--identity-title")

    # Add identity overrides to main overrides if any
    if identity_overrides:
        cli_overrides["identity"] = identity_overrides

    # Add edit-precision overrides to main overrides if any
    if edit_precision_overrides:
        cli_overrides["edit_precision"] = edit_precision_overrides

    # Backend debugging overrides
    if getattr(args, "enable_cline_backend_debugging_override", False):
        backend_overrides = cli_overrides.setdefault("backends", {})
        cline_overrides = backend_overrides.setdefault("cline", {})
        cline_overrides["extra"] = cline_overrides.get("extra", {})
        cline_overrides["extra"]["enable_cline_backend_debugging_override"] = True
        record_cli(
            "backends.cline.extra.enable_cline_backend_debugging_override",
            True,
            "--enable-cline-backend-debugging-override",
        )

    if getattr(args, "enable_antigravity_backend_debugging_override", False):
        backend_overrides = cli_overrides.setdefault("backends", {})
        antigravity_overrides = backend_overrides.setdefault(
            "gemini-oauth-antigravity", {}
        )
        antigravity_overrides["extra"] = antigravity_overrides.get("extra", {})
        antigravity_overrides["extra"][
            "enable_antigravity_backend_debugging_override"
        ] = True
        record_cli(
            "backends.gemini-oauth-antigravity.extra.enable_antigravity_backend_debugging_override",
            True,
            "--enable-antigravity-backend-debugging-override",
        )

    if getattr(args, "enable_gemini_oauth_free_backend_debugging_override", False):
        backend_overrides = cli_overrides.setdefault("backends", {})
        free_overrides = backend_overrides.setdefault("gemini-oauth-free", {})
        free_overrides["extra"] = free_overrides.get("extra", {})
        free_overrides["extra"][
            "enable_gemini_oauth_free_backend_debugging_override"
        ] = True
        record_cli(
            "backends.gemini-oauth-free.extra.enable_gemini_oauth_free_backend_debugging_override",
            True,
            "--enable-gemini-oauth-free-backend-debugging-override",
        )

    if getattr(args, "enable_gemini_oauth_plan_backend_debugging_override", False):
        backend_overrides = cli_overrides.setdefault("backends", {})
        plan_overrides = backend_overrides.setdefault("gemini-oauth-plan", {})
        plan_overrides["extra"] = plan_overrides.get("extra", {})
        plan_overrides["extra"][
            "enable_gemini_oauth_plan_backend_debugging_override"
        ] = True
        record_cli(
            "backends.gemini-oauth-plan.extra.enable_gemini_oauth_plan_backend_debugging_override",
            True,
            "--enable-gemini-oauth-plan-backend-debugging-override",
        )

    if getattr(args, "enable_qwen_oauth_backend_debugging_override", False):
        backend_overrides = cli_overrides.setdefault("backends", {})
        qwen_overrides = backend_overrides.setdefault("qwen-oauth", {})
        qwen_overrides["extra"] = qwen_overrides.get("extra", {})
        qwen_overrides["extra"]["enable_qwen_oauth_backend_debugging_override"] = True
        record_cli(
            "backends.qwen-oauth.extra.enable_qwen_oauth_backend_debugging_override",
            True,
            "--enable-qwen-oauth-backend-debugging-override",
        )

    if getattr(args, "enable_openai_codex_backend_debugging_override", False):
        backend_overrides = cli_overrides.setdefault("backends", {})
        codex_overrides = backend_overrides.setdefault("openai-codex", {})
        codex_overrides["extra"] = codex_overrides.get("extra", {})
        codex_overrides["extra"][
            "enable_openai_codex_backend_debugging_override"
        ] = True
        record_cli(
            "backends.openai-codex.extra.enable_openai_codex_backend_debugging_override",
            True,
            "--enable-openai-codex-backend-debugging-override",
        )

    if getattr(args, "enable_anthropic_oauth_backend_debugging_override", False):
        backend_overrides = cli_overrides.setdefault("backends", {})
        anthropic_overrides = backend_overrides.setdefault("anthropic-oauth", {})
        anthropic_overrides["extra"] = anthropic_overrides.get("extra", {})
        anthropic_overrides["extra"][
            "enable_anthropic_oauth_backend_debugging_override"
        ] = True
        record_cli(
            "backends.anthropic-oauth.extra.enable_anthropic_oauth_backend_debugging_override",
            True,
            "--enable-anthropic-oauth-backend-debugging-override",
        )

        # Add backend overrides to main overrides if any
    if backend_overrides:
        cli_overrides["backends"] = backend_overrides

    # ProxyMem (Cross-Session Memory) configuration
    # Precedence: CLI > env > config file (Req 1.5)
    memory_overrides: dict[str, Any] = {}

    # Load from environment variables first (env overrides config file)
    def _parse_bool_env(val: str | None) -> bool | None:
        if val is None:
            return None
        return val.lower() in ("true", "1", "yes", "on")

    env_memory_available = os.environ.get("MEMORY_AVAILABLE")
    if env_memory_available is not None:
        memory_overrides["available"] = _parse_bool_env(env_memory_available)

    env_memory_default_enabled = os.environ.get("MEMORY_DEFAULT_ENABLED")
    if env_memory_default_enabled is not None:
        memory_overrides["default_enabled"] = _parse_bool_env(
            env_memory_default_enabled
        )

    env_memory_summary_model = os.environ.get("MEMORY_SUMMARY_MODEL")
    if env_memory_summary_model:
        memory_overrides["summary_model"] = env_memory_summary_model

    env_memory_context_model = os.environ.get("MEMORY_CONTEXT_MODEL")
    if env_memory_context_model:
        memory_overrides["context_model"] = env_memory_context_model

    env_memory_summary_prompt = os.environ.get("MEMORY_SUMMARY_PROMPT")
    if env_memory_summary_prompt:
        memory_overrides["summary_prompt"] = env_memory_summary_prompt

    env_memory_context_prompt = os.environ.get("MEMORY_CONTEXT_PROMPT")
    if env_memory_context_prompt:
        memory_overrides["context_prompt"] = env_memory_context_prompt

    env_memory_database_path = os.environ.get("MEMORY_DATABASE_PATH")
    if env_memory_database_path:
        memory_overrides["database_path"] = env_memory_database_path

    env_memory_session_timeout = os.environ.get("MEMORY_SESSION_TIMEOUT_MINUTES")
    if env_memory_session_timeout:
        with contextlib.suppress(ValueError):
            memory_overrides["session_timeout_minutes"] = int(
                env_memory_session_timeout
            )

    env_memory_retention_days = os.environ.get("MEMORY_RETENTION_DAYS")
    if env_memory_retention_days:
        with contextlib.suppress(ValueError):
            memory_overrides["retention_days"] = int(env_memory_retention_days)

    env_memory_max_context_tokens = os.environ.get("MEMORY_MAX_CONTEXT_TOKENS")
    if env_memory_max_context_tokens:
        with contextlib.suppress(ValueError):
            memory_overrides["max_context_tokens"] = int(env_memory_max_context_tokens)

    env_memory_relevance_threshold = os.environ.get(
        "MEMORY_CONTEXT_RELEVANCE_THRESHOLD"
    )
    if env_memory_relevance_threshold:
        with contextlib.suppress(ValueError):
            memory_overrides["context_relevance_threshold"] = float(
                env_memory_relevance_threshold
            )

    # CLI overrides env (CLI takes highest precedence)
    if getattr(args, "memory_available", None) is not None:
        memory_overrides["available"] = args.memory_available
        record_cli("memory.available", args.memory_available, "--memory-available")

    if getattr(args, "memory_default_enabled", None) is not None:
        memory_overrides["default_enabled"] = args.memory_default_enabled
        record_cli(
            "memory.default_enabled",
            args.memory_default_enabled,
            "--memory-default-enabled",
        )

    if getattr(args, "memory_summary_model", None) is not None:
        memory_overrides["summary_model"] = args.memory_summary_model
        record_cli(
            "memory.summary_model",
            args.memory_summary_model,
            "--memory-summary-model",
        )

    if getattr(args, "memory_context_model", None) is not None:
        memory_overrides["context_model"] = args.memory_context_model
        record_cli(
            "memory.context_model",
            args.memory_context_model,
            "--memory-context-model",
        )

    if getattr(args, "memory_summary_prompt", None) is not None:
        memory_overrides["summary_prompt"] = args.memory_summary_prompt
        record_cli(
            "memory.summary_prompt",
            args.memory_summary_prompt,
            "--memory-summary-prompt",
        )

    if getattr(args, "memory_context_prompt", None) is not None:
        memory_overrides["context_prompt"] = args.memory_context_prompt
        record_cli(
            "memory.context_prompt",
            args.memory_context_prompt,
            "--memory-context-prompt",
        )

    if getattr(args, "memory_database_path", None) is not None:
        memory_overrides["database_path"] = args.memory_database_path
        record_cli(
            "memory.database_path",
            args.memory_database_path,
            "--memory-database-path",
        )

    if getattr(args, "memory_session_timeout", None) is not None:
        memory_overrides["session_timeout_minutes"] = args.memory_session_timeout
        record_cli(
            "memory.session_timeout_minutes",
            args.memory_session_timeout,
            "--memory-session-timeout",
        )

    if getattr(args, "memory_retention_days", None) is not None:
        memory_overrides["retention_days"] = args.memory_retention_days
        record_cli(
            "memory.retention_days",
            args.memory_retention_days,
            "--memory-retention-days",
        )

    if getattr(args, "memory_max_context_tokens", None) is not None:
        memory_overrides["max_context_tokens"] = args.memory_max_context_tokens
        record_cli(
            "memory.max_context_tokens",
            args.memory_max_context_tokens,
            "--memory-max-context-tokens",
        )

    if getattr(args, "memory_context_relevance_threshold", None) is not None:
        memory_overrides["context_relevance_threshold"] = (
            args.memory_context_relevance_threshold
        )
        record_cli(
            "memory.context_relevance_threshold",
            args.memory_context_relevance_threshold,
            "--memory-context-relevance-threshold",
        )

    if getattr(args, "memory_single_user_mode", None) is not None:
        memory_overrides["single_user_mode"] = args.memory_single_user_mode
        record_cli(
            "memory.single_user_mode",
            args.memory_single_user_mode,
            "--memory-single-user-mode",
        )

    if getattr(args, "memory_fixed_user_id", None) is not None:
        memory_overrides["fixed_user_id"] = args.memory_fixed_user_id
        record_cli(
            "memory.fixed_user_id",
            args.memory_fixed_user_id,
            "--memory-fixed-user-id",
        )

    if getattr(args, "memory_redaction_patterns", None) is not None:
        memory_overrides["redaction_patterns"] = args.memory_redaction_patterns
        record_cli(
            "memory.redaction_patterns",
            args.memory_redaction_patterns,
            "--memory-redaction-pattern",
        )

    if getattr(args, "memory_disabled_users", None) is not None:
        memory_overrides["disabled_users"] = set(args.memory_disabled_users)
        record_cli(
            "memory.disabled_users",
            list(args.memory_disabled_users),
            "--memory-disable-user",
        )

    if getattr(args, "memory_disabled_clients", None) is not None:
        memory_overrides["disabled_clients"] = set(args.memory_disabled_clients)
        record_cli(
            "memory.disabled_clients",
            list(args.memory_disabled_clients),
            "--memory-disable-client",
        )

    # Add memory overrides to main overrides if any
    if memory_overrides:
        cli_overrides["memory"] = memory_overrides

    # Failure handling configuration
    failure_overrides: dict[str, Any] = {}
    if getattr(args, "disable_failure_handling", False):
        failure_overrides["enabled"] = False
        os.environ["DISABLE_FAILURE_HANDLING"] = "1"
        record_cli("failure_handling.enabled", False, "--disable-failure-handling")

    if getattr(args, "max_silent_wait", None) is not None:
        failure_overrides["max_silent_wait"] = args.max_silent_wait
        os.environ["FAILURE_HANDLING_MAX_SILENT_WAIT"] = str(args.max_silent_wait)
        record_cli(
            "failure_handling.max_silent_wait",
            args.max_silent_wait,
            "--max-silent-wait",
        )

    if getattr(args, "total_timeout_budget", None) is not None:
        failure_overrides["total_timeout_budget"] = args.total_timeout_budget
        os.environ["FAILURE_HANDLING_TOTAL_TIMEOUT_BUDGET"] = str(
            args.total_timeout_budget
        )
        record_cli(
            "failure_handling.total_timeout_budget",
            args.total_timeout_budget,
            "--total-timeout-budget",
        )

    if getattr(args, "keepalive_interval", None) is not None:
        failure_overrides["keepalive_interval"] = args.keepalive_interval
        os.environ["FAILURE_HANDLING_KEEPALIVE_INTERVAL"] = str(args.keepalive_interval)
        record_cli(
            "failure_handling.keepalive_interval",
            args.keepalive_interval,
            "--keepalive-interval",
        )

    if getattr(args, "max_failover_hops", None) is not None:
        failure_overrides["max_failover_hops"] = args.max_failover_hops
        os.environ["FAILURE_HANDLING_MAX_FAILOVER_HOPS"] = str(args.max_failover_hops)
        record_cli(
            "failure_handling.max_failover_hops",
            args.max_failover_hops,
            "--max-failover-hops",
        )

    if getattr(args, "min_retry_wait", None) is not None:
        failure_overrides["min_retry_wait"] = args.min_retry_wait
        os.environ["FAILURE_HANDLING_MIN_RETRY_WAIT"] = str(args.min_retry_wait)
        record_cli(
            "failure_handling.min_retry_wait",
            args.min_retry_wait,
            "--min-retry-wait",
        )

    # Add failure handling overrides to main overrides if any
    if failure_overrides:
        cli_overrides["failure_handling"] = failure_overrides

    # Create new config with CLI overrides if any
    if cli_overrides:
        # Get current config as dict, ensuring full serialization to preserve nested objects
        config_dict = cfg.model_dump(mode="json")

        # Apply CLI overrides
        _merge_dicts(config_dict, cli_overrides)

        # Ensure command_prefix is never None to satisfy Pydantic validation
        if config_dict.get("command_prefix") is None:
            config_dict["command_prefix"] = DEFAULT_COMMAND_PREFIX

        # Create new config
        cfg = AppConfig.model_validate(config_dict)

    # Validate and apply configurations
    cfg = _validate_and_apply_prefix(cfg)
    _apply_feature_flags(cfg)
    # The security flag application is now in main()
    # Finalize derived configuration values
    # Finalize derived configuration values
    # if cfg.anthropic_port is None:
    #     cfg = cfg.model_copy(update={"anthropic_port": cfg.port + 1})

    if return_resolution:
        return cfg, res
    return cfg


def _validate_and_apply_prefix(cfg: AppConfig) -> AppConfig:
    """Validate command prefix configuration and apply defaults safely."""
    if cfg.command_prefix is None:
        return cfg.model_copy(update={"command_prefix": DEFAULT_COMMAND_PREFIX})

    prefix = str(cfg.command_prefix)
    err = validate_command_prefix(prefix)
    if err:
        raise ValueError(f"Invalid command prefix {prefix!r}: {err}")
    return cfg


def _apply_feature_flags(cfg: AppConfig) -> None:
    """Apply other feature flags from cfg."""
    # Apply other feature flags from cfg
    # These flags are now directly applied in apply_cli_args


def _is_admin() -> bool:
    """Cross-platform admin check."""
    if sys.platform != "win32":
        # Unix/Linux systems
        try:
            # Check if running as root (UID 0)
            if hasattr(os, "geteuid") and os.geteuid() == 0:
                return True

            # Check if in sudo or wheel group (enhanced Linux privilege checking)
            import grp
            import pwd

            try:
                # Check sudo group membership
                sudo_group = grp.getgrnam("sudo")
                if os.getgid() in sudo_group.gr_mem:
                    return True
                # Also check by username if available
                current_user = pwd.getpwuid(os.geteuid()).pw_name
                if current_user in sudo_group.gr_mem:
                    return True
            except (KeyError, OSError):
                pass  # sudo group doesn't exist

            try:
                # Check wheel group membership (common on RedHat/CentOS systems)
                wheel_group = grp.getgrnam("wheel")
                if os.getgid() in wheel_group.gr_mem:
                    return True
                # Also check by username if available
                current_user = pwd.getpwuid(os.geteuid()).pw_name
                if current_user in wheel_group.gr_mem:
                    return True
            except (KeyError, OSError):
                pass  # wheel group doesn't exist

            return False
        except (AttributeError, ImportError, OSError):
            # Fallback for systems that don't support these checks
            return False
    else:
        # Windows systems
        try:
            import ctypes

            return (
                hasattr(ctypes, "windll")
                and hasattr(ctypes.windll, "shell32")
                and ctypes.windll.shell32.IsUserAnAdmin() != 0
            )
        except Exception:
            return False


def _has_privilege_functionality() -> bool:
    """Check if the platform supports privilege checking functionality."""
    try:
        if os.name != "nt":
            # Unix/Linux systems should support geteuid()
            return hasattr(os, "geteuid")
        else:
            # Windows systems should support ctypes.windll
            import ctypes

            return hasattr(ctypes, "windll")
    except Exception:
        return False


def _check_privileges() -> None:
    """Refuse to run the server with elevated privileges."""
    if _is_admin():
        if os.name != "nt":
            raise SystemExit("Refusing to run as root user")
        else:
            raise SystemExit("Refusing to run with administrative privileges")


def _daemonize() -> None:
    """Daemonize the process on Unix-like systems."""
    if os.name != "nt":
        if hasattr(os, "fork") and os.fork() > 0:
            sys.exit(0)  # exit first parent

        os.chdir("/")
        if hasattr(os, "setsid"):
            os.setsid()
        os.umask(0)

        if hasattr(os, "fork") and os.fork() > 0:
            sys.exit(0)  # exit second parent
    else:
        # On Windows, we can't daemonize, so we just continue
        pass


def _maybe_run_as_daemon(args: argparse.Namespace, cfg: AppConfig) -> bool:
    """Handle daemon mode if requested. Returns True if we should exit."""
    if not args.daemon:
        return False
    if not cfg.logging.log_file:
        raise SystemExit("--log must be specified when running in daemon mode.")
    if os.name == "nt":
        import subprocess
        import time

        args_list: list[str] = [
            arg for arg in sys.argv[1:] if not arg.startswith("--daemon")
        ]
        command: list[str] = [sys.executable, "-m", "src.core.cli", *args_list]
        creation_flags = getattr(subprocess, "DETACHED_PROCESS", 0)
        subprocess.Popen(command, creationflags=creation_flags, close_fds=True)
        time.sleep(2)
        sys.exit(0)
        return True
    _daemonize()
    return False


def _configure_logging(cfg: AppConfig) -> None:
    """Configure logging based on configuration."""
    from src.core.common.logging_utils import configure_logging_with_environment_tagging

    configure_logging_with_environment_tagging(
        level=getattr(logging, cfg.logging.level.value),
        log_file=cfg.logging.log_file,
        use_colors=cfg.logging.use_colors,
    )


def _with_timestamp_suffix(path: str | None) -> str | None:
    """Append a timestamp suffix (HHMM) to the filename portion of a path."""
    if not path:
        return None
    from datetime import datetime

    timestamp = datetime.now().strftime("%Y%m%d_%H%M")
    p = Path(path)
    # Check if already has a timestamp-like suffix to avoid double appending
    # Check for YYYYMMDD_HHmm at end of stem
    if re.search(r"-\d{8}_\d{4}$", p.stem):
        return str(p)
    new_name = f"{p.stem}-{timestamp}{p.suffix}"
    return str(p.with_name(new_name))


def _apply_pid_suffixes(cfg: AppConfig) -> AppConfig:
    """Return a copy of cfg with timestamp-suffixed log and capture files."""
    # Note: Function name kept as _apply_pid_suffixes for compatibility but implementation changed to timestamp
    updated_logging: dict[str, Any] = {}
    new_log = _with_timestamp_suffix(cfg.logging.log_file)
    if new_log != cfg.logging.log_file:
        updated_logging["log_file"] = new_log
    new_capture = _with_timestamp_suffix(getattr(cfg.logging, "capture_file", None))
    if new_capture != getattr(cfg.logging, "capture_file", None):
        updated_logging["capture_file"] = new_capture
    if not updated_logging:
        return cfg
    new_logging = cfg.logging.model_copy(update=updated_logging)
    return cfg.model_copy(update={"logging": new_logging})


def _enforce_localhost_if_auth_disabled(cfg: AppConfig) -> AppConfig:
    """Enforce localhost binding when authentication is disabled."""
    if not cfg.auth.disable_auth:
        return cfg
    logging.warning("Client authentication is DISABLED")
    if cfg.host != "127.0.0.1":
        logging.warning(
            "Authentication disabled but host is %s. Forcing host to 127.0.0.1 for security.",
            cfg.host,
        )
        cfg = cfg.model_copy(update={"host": "127.0.0.1"})
    return cfg


def _handle_application_build_error(error_msg: str) -> None:
    """Handle application build errors with user-friendly messages."""
    import sys

    # Use sys.stderr.write instead of print to avoid test failures
    sys.stderr.write("\n" + "=" * 60 + "\n")
    sys.stderr.write("ERROR: Failed to start LLM Interactive Proxy\n")
    sys.stderr.write("=" * 60 + "\n")

    if "Stage 'backends' validation error" in error_msg:
        sys.stderr.write(
            "\nThe application failed to start because no working backends were found.\n"
        )
        sys.stderr.write("\nThis usually means one of the following:\n")
        sys.stderr.write("  1. OAuth tokens have expired (most common)\n")
        sys.stderr.write("  2. API keys are missing or invalid\n")
        sys.stderr.write("  3. Network connectivity issues\n")

        # Extract specific backend errors if available
        if "Token expired" in error_msg:
            sys.stderr.write("\nDETECTED ISSUE: OAuth token has expired\n")
            sys.stderr.write("\nTo fix this:\n")
            if "gemini" in error_msg.lower():
                sys.stderr.write("  - Run: gemini auth\n")
                sys.stderr.write("  - Follow the authentication flow in your browser\n")
            elif "qwen" in error_msg.lower():
                sys.stderr.write("  - Run: qwen auth\n")
                sys.stderr.write("  - Follow the authentication flow in your browser\n")
            else:
                sys.stderr.write(
                    "  - Re-authenticate with the appropriate OAuth provider\n"
                )
                sys.stderr.write("  - For Gemini: run 'gemini auth'\n")
                sys.stderr.write("  - For Qwen: run 'qwen auth'\n")
            sys.stderr.write("  - Then try starting the proxy again\n")
        elif "oauth_credentials_unavailable" in error_msg:
            sys.stderr.write("\nDETECTED ISSUE: OAuth credentials not found\n")
            sys.stderr.write("\nTo fix this:\n")
            if "anthropic" in error_msg.lower():
                sys.stderr.write(
                    "  - Authenticate using Claude Code or similar Anthropic OAuth client\n"
                )
                sys.stderr.write("  - Or provide a valid oauth_creds.json file\n")
                sys.stderr.write(
                    "  - Default location: ~/.anthropic/oauth_creentals.json\n"
                )
            elif "openai" in error_msg.lower():
                sys.stderr.write("  - Run: codex login\n")
                sys.stderr.write("  - Or provide a valid auth.json file\n")
                sys.stderr.write("  - Default location: ~/.codex/auth.json\n")
            else:
                sys.stderr.write(
                    "  - Authenticate with the appropriate OAuth provider\n"
                )
                sys.stderr.write("  - For OpenAI: run 'codex login'\n")
                sys.stderr.write(
                    "  - For Anthropic: use Claude Code or similar OAuth client\n"
                )
        elif "api_key is required" in error_msg:
            sys.stderr.write("\nDETECTED ISSUE: Missing API keys\n")
            sys.stderr.write("\nTo fix this:\n")
            sys.stderr.write("  - Set the required environment variables:\n")
            sys.stderr.write("    * OPENROUTER_API_KEY for OpenRouter\n")
            sys.stderr.write("    * GEMINI_API_KEY for Gemini\n")
            sys.stderr.write("    * ANTHROPIC_API_KEY for Anthropic\n")
            sys.stderr.write("    * ZAI_API_KEY for ZAI\n")
            sys.stderr.write(
                "  - Or configure a different backend with --default-backend\n"
            )
            sys.stderr.write("  - Or use OAuth-based backends:\n")
            sys.stderr.write(
                "    * gemini-oauth-plan (uses gemini CLI auth for paid tier)\n"
            )
            sys.stderr.write(
                "    * gemini-oauth-free (uses gemini CLI auth for free tier)\n"
            )
            sys.stderr.write("    * qwen-oauth (uses qwen CLI auth)\n")
            sys.stderr.write("    * anthropic-oauth (uses Claude Code auth)\n")
            sys.stderr.write("    * openai-codex (uses codex CLI auth)\n")
        elif "oauth_credentials_invalid" in error_msg:
            sys.stderr.write(
                "\nDETECTED ISSUE: OAuth credentials are invalid or corrupted\n"
            )
            sys.stderr.write("\nTo fix this:\n")
            sys.stderr.write("  - Re-authenticate to refresh your credentials\n")
            sys.stderr.write("  - For Gemini: run 'gemini auth'\n")
            sys.stderr.write("  - For Qwen: run 'qwen auth'\n")
            sys.stderr.write("  - For OpenAI: run 'codex login'\n")
            sys.stderr.write("  - For Anthropic: re-authenticate with Claude Code\n")
        elif (
            "Failed to load credentials" in error_msg
            or "credentials file not found" in error_msg.lower()
        ):
            sys.stderr.write(
                "\nDETECTED ISSUE: OAuth credentials file missing or corrupted\n"
            )
            sys.stderr.write("\nTo fix this:\n")
            sys.stderr.write(
                "  - Check if you have authenticated with the appropriate CLI tool:\n"
            )
            sys.stderr.write(
                "    * For Gemini: run 'gemini auth' (creates ~/.gemini/oauth_creds.json)\n"
            )
            sys.stderr.write(
                "    * For Qwen: run 'qwen auth' (creates ~/.qwen/oauth_creds.txt)\n"
            )
            sys.stderr.write(
                "    * For OpenAI: run 'codex login' (creates ~/.codex/auth.json)\n"
            )
            sys.stderr.write("    * For Anthropic: authenticate with Claude Code\n")
            sys.stderr.write(
                "  - Verify the credentials files exist and are readable\n"
            )
        else:
            sys.stderr.write("\nTo fix this:\n")
            sys.stderr.write("  - Check your internet connection\n")
            sys.stderr.write("  - Verify your API keys are valid\n")
            sys.stderr.write("  - Try refreshing OAuth tokens:\n")
            sys.stderr.write("    * For Gemini: gemini auth\n")
            sys.stderr.write("    * For Qwen: qwen auth\n")
            sys.stderr.write("    * For OpenAI: codex login\n")
            sys.stderr.write("    * For Anthropic: re-authenticate with Claude Code\n")
            sys.stderr.write("  - Check the logs above for specific error details\n")
    else:
        sys.stderr.write(f"\nUnexpected error during startup: {error_msg}\n")
        sys.stderr.write("\nPlease check the logs above for more details.\n")

    sys.stderr.write(
        "\nFor more help, see the documentation or check your configuration.\n"
    )
    sys.stderr.write("=" * 60 + "\n")


async def main(
    argv: list[str] | None = None,
    build_app_fn: Callable[[AppConfig], FastAPI] | None = None,
) -> None:
    """
    Main entry point with full feature parity to original CLI.

    The complexity of service initialization is now hidden in the staged
    initialization pattern, making this function clean and focused on
    CLI concerns only.
    """
    # No additional console initialization required for Windows terminals.

    # Parse arguments and load configuration
    args: argparse.Namespace = parse_cli_args(argv)
    cfg_result = apply_cli_args(args, return_resolution=True)
    cfg, resolution = cast(tuple[AppConfig, ParameterResolution], cfg_result)
    cfg = _apply_pid_suffixes(cfg)

    # Handle daemon mode early
    if _maybe_run_as_daemon(args, cfg):
        return

    # Configure logging
    _configure_logging(cfg)

    # Apply PID suffixes to log files
    cfg = _apply_pid_suffixes(cfg)

    resolution.log(logging.getLogger("config.resolution"), cfg)

    # Check privileges unless explicitly allowed
    if not args.allow_admin:
        _check_privileges()

    # Enforce security constraints
    cfg = _enforce_localhost_if_auth_disabled(cfg)

    # Build application with comprehensive error handling
    app: FastAPI
    try:
        if build_app_fn:
            app = build_app_fn(cfg)  # For testing
        else:
            app = await build_app_async(cfg)  # Production
    except RuntimeError as e:
        # Handle application build failures with user-friendly messages
        error_msg = str(e)
        _handle_application_build_error(error_msg)
        sys.exit(1)
    except Exception as e:
        logging.error(f"Unexpected error during application startup: {e}")
        sys.stderr.write(f"\nERROR: Failed to start LLM Interactive Proxy: {e}\n")
        sys.stderr.write("Please check your configuration and try again.\n")
        sys.exit(1)

    # Log trusted IPs information if configured
    if cfg.auth.trusted_ips:
        logging.info(
            f"Trusted IPs configured for bypassing authorization: {', '.join(cfg.auth.trusted_ips)}"
        )

    # Check if port is already in use
    if is_port_in_use(cfg.host, cfg.port):
        error_msg = f"Port {cfg.port} is already in use."
        logging.error(error_msg)
        sys.stderr.write(f"\nERROR: {error_msg}\n")
        sys.exit(1)

    # Check if Anthropic port is already in use
    if cfg.anthropic_port and is_port_in_use(cfg.host, cfg.anthropic_port):
        error_msg = f"Anthropic Port {cfg.anthropic_port} is already in use."
        logging.error(error_msg)
        sys.stderr.write(f"\nERROR: {error_msg}\n")
        sys.exit(1)

    # Start the servers
    logging.info(f"Starting uvicorn on {cfg.host}:{cfg.port}")

    servers = []

    # Main server
    main_config = uvicorn.Config(
        app,
        host=cfg.host,
        port=cfg.port,
        log_config=get_uvicorn_logging_config(use_colors=cfg.logging.use_colors),
    )
    main_server = uvicorn.Server(main_config)
    servers.append(main_server.serve())

    # Anthropic server
    if cfg.anthropic_port:
        logging.info(f"Starting Anthropic server on {cfg.host}:{cfg.anthropic_port}")
        # Reuse the main app to avoid double initialization of services
        anthropic_app = await create_anthropic_app_async(cfg, built_app=app)
        anthropic_config = uvicorn.Config(
            anthropic_app,
            host=cfg.host,
            port=cfg.anthropic_port,
            log_config=get_uvicorn_logging_config(use_colors=cfg.logging.use_colors),
        )
        anthropic_server = uvicorn.Server(anthropic_config)
        servers.append(anthropic_server.serve())

    try:
        await asyncio.gather(*servers)
    except KeyboardInterrupt:
        pass
    except Exception as e:
        logging.exception("Server failed: %s", e)
        raise


# Main entry point guard
if __name__ == "__main__":
    with contextlib.suppress(KeyboardInterrupt):
        asyncio.run(main())


# Example of how this enables easy customization for different environments


def build_development_app(config: AppConfig) -> FastAPI:
    """Build app with development-specific configuration."""
    import asyncio

    from src.core.app.stages import (
        BackendStage,
        CommandStage,
        ControllerStage,
        CoreServicesStage,
        InfrastructureStage,
        ProcessorStage,
    )

    # Add development-specific stages or configuration
    builder = (
        ApplicationBuilder()
        .add_stage(InfrastructureStage())
        .add_stage(CoreServicesStage())
        .add_stage(BackendStage())
        .add_stage(CommandStage())
        .add_stage(ProcessorStage())
        .add_stage(ControllerStage())
    )

    return asyncio.run(builder.build(config))


def build_test_app(config: AppConfig) -> FastAPI:
    """Build app with test-specific configuration."""
    import asyncio

    from src.core.app.stages import (
        CommandStage,
        ControllerStage,
        CoreServicesStage,
        InfrastructureStage,
        ProcessorStage,
    )
    from src.core.app.stages.test_stages import MockBackendStage

    # Replace real backends with mocks for testing
    builder = (
        ApplicationBuilder()
        .add_stage(InfrastructureStage())
        .add_stage(CoreServicesStage())
        .add_stage(MockBackendStage())  # Mock backends instead of real ones
        .add_stage(CommandStage())
        .add_stage(ProcessorStage())
        .add_stage(ControllerStage())
    )

    return asyncio.run(builder.build(config))


"""
COMPARISON: Original vs Enhanced CLI

ORIGINAL CLI (complex):
- 570 lines with complex monolithic initialization logic
- Manual dependency ordering and service registration
- Complex global state management
- Difficult to customize for different environments
- Hard to test due to tightly coupled initialization
- Mixed CLI parsing with application building concerns

ENHANCED CLI (clean architecture):
- ~580 lines but with clear separation of concerns
- All application complexity hidden in ApplicationBuilder
- Easy to customize with different stages
- Simple to test with mock stages
- Clear separation between CLI and app initialization
- 100% feature parity with original CLI
- Same command-line interface and behavior
- Enhanced error handling and user-friendly messages

BENEFITS:
1. Maintainability: CLI logic is focused and clear despite same feature set
2. Testability: Easy to inject test-specific builders
3. Flexibility: Easy to create environment-specific variants
4. Debugging: Clear separation between CLI and app initialization
5. Onboarding: New developers can understand CLI logic immediately
6. Architecture: Staged initialization enables better dependency management
7. Extensibility: Easy to add new initialization stages
8. Error Handling: Comprehensive error messages with actionable guidance

FEATURE PARITY ACHIEVED:
[X] All 27 command-line arguments supported
[X] Dynamic backend registry integration
[X] Complete configuration handling
[X] Daemon mode support (Windows & Unix)
[X] Privilege checking and security enforcement
[X] Wire capture configuration
[X] Comprehensive error handling with user guidance
[X] Environment variable management
[X] Trusted IP configuration
[X] All feature flags and toggles
"""
