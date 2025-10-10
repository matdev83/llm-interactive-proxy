"""
Enhanced CLI implementation using staged initialization with 100% feature parity.

This demonstrates how the new architecture provides the same functionality as the original
CLI while maintaining clean separation of concerns through staged initialization.
"""

import argparse
import logging
import os
import socket
import sys
from collections.abc import Callable, Sequence
from typing import Any, cast

import uvicorn
from fastapi import FastAPI

from src.command_prefix import validate_command_prefix
from src.core.app.application_builder import ApplicationBuilder, build_app
from src.core.common.uvicorn_logging import UVICORN_LOGGING_CONFIG
from src.core.config.app_config import AppConfig, LogLevel, load_config
from src.core.config.parameter_resolution import ParameterResolution, ParameterSource

# Import backend connectors to ensure they register themselves
from src.core.services import backend_imports  # noqa: F401
from src.core.services.backend_registry import backend_registry


def is_port_in_use(host: str, port: int) -> bool:
    """Check if a port is in use on a given host."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        return s.connect_ex((host, port)) == 0


def _normalize_api_key_value(value: str | Sequence[str]) -> list[str]:
    """Normalize CLI-supplied API key values into the expected list format."""

    if isinstance(value, str):
        cleaned = value.strip()
        return [cleaned] if cleaned else []

    return [
        item
        for item in value
        if isinstance(item, str) and item.strip()
    ]


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
        help="Force all requests to use this backend:model combination (e.g., gemini-cli-oauth-personal:gemini-2.5-pro)",
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
            import re

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

    # API Keys and URLs
    parser.add_argument("--openrouter-api-key")
    parser.add_argument("--openrouter-api-base-url")
    parser.add_argument("--gemini-api-key")
    parser.add_argument("--gemini-api-base-url")
    parser.add_argument("--zai-api-key")

    # Basic server options
    parser.add_argument("--host")
    parser.add_argument("--port", type=int)
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
        help="Write logs to FILE (default: logs/proxy.log)",
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
    compression_group = parser.add_mutually_exclusive_group()
    compression_group.add_argument(
        "--enable-pytest-compression",
        action="store_const",
        const=True,
        dest="pytest_compression_enabled",
        default=None,
        help="Enable pytest output compression (overrides config)",
    )
    compression_group.add_argument(
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

    return parser


def parse_cli_args(argv: list[str] | None = None) -> argparse.Namespace:
    """Parse command line arguments with full feature parity to original CLI."""
    parser = build_cli_parser()
    return parser.parse_args(argv)


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

    # Basic server configuration
    if args.host is not None:
        cfg.host = args.host
        record_cli("host", args.host, "--host")
    if args.port is not None:
        cfg.port = args.port
        os.environ["PROXY_PORT"] = str(args.port)
        record_cli("port", args.port, "--port")
    if args.timeout is not None:
        cfg.proxy_timeout = args.timeout
        record_cli("proxy_timeout", args.timeout, "--timeout")
    if args.command_prefix is not None:
        cfg.command_prefix = args.command_prefix
        os.environ["COMMAND_PREFIX"] = args.command_prefix
        record_cli("command_prefix", args.command_prefix, "--command-prefix")

    # Context window override
    if args.force_context_window is not None:
        cfg.context_window_override = args.force_context_window
        os.environ["FORCE_CONTEXT_WINDOW"] = str(args.force_context_window)
        record_cli(
            "context_window_override",
            args.force_context_window,
            "--force-context-window",
        )

    # Thinking budget override (for reasoning/thinking tokens)
    if args.thinking_budget is not None:
        # Store in environment for the translation layer to pick up
        os.environ["THINKING_BUDGET"] = str(args.thinking_budget)
        record_cli("cli.thinking_budget", args.thinking_budget, "--thinking-budget")

    # Logging configuration
    if args.log_file is not None:
        cfg.logging.log_file = args.log_file
        record_cli("logging.log_file", args.log_file, "--log")
    elif cfg.logging.log_file is None:
        # Set default log file only if none specified in config or CLI
        from pathlib import Path

        default_log_file = "logs/proxy.log"
        # Ensure logs directory exists
        log_dir = Path(default_log_file).parent
        log_dir.mkdir(exist_ok=True)
        cfg.logging.log_file = default_log_file
    if args.log_level is not None:
        cfg.logging.level = LogLevel[args.log_level]
        record_cli("logging.level", cfg.logging.level.value, "--log-level")

    # Wire capture configuration
    if getattr(args, "capture_file", None) is not None:
        cfg.logging.capture_file = args.capture_file
        record_cli("logging.capture_file", args.capture_file, "--capture-file")
    if getattr(args, "capture_max_bytes", None) is not None:
        cfg.logging.capture_max_bytes = args.capture_max_bytes
        record_cli(
            "logging.capture_max_bytes", args.capture_max_bytes, "--capture-max-bytes"
        )
    if getattr(args, "capture_truncate_bytes", None) is not None:
        cfg.logging.capture_truncate_bytes = args.capture_truncate_bytes
        record_cli(
            "logging.capture_truncate_bytes",
            args.capture_truncate_bytes,
            "--capture-truncate-bytes",
        )
    if getattr(args, "capture_max_files", None) is not None:
        cfg.logging.capture_max_files = args.capture_max_files
        record_cli(
            "logging.capture_max_files", args.capture_max_files, "--capture-max-files"
        )
    if getattr(args, "capture_rotate_interval_seconds", None) is not None:
        cfg.logging.capture_rotate_interval_seconds = (
            args.capture_rotate_interval_seconds
        )
        record_cli(
            "logging.capture_rotate_interval_seconds",
            args.capture_rotate_interval_seconds,
            "--capture-rotate-interval",
        )
    if getattr(args, "capture_total_max_bytes", None) is not None:
        cfg.logging.capture_total_max_bytes = args.capture_total_max_bytes
        record_cli(
            "logging.capture_total_max_bytes",
            args.capture_total_max_bytes,
            "--capture-total-max-bytes",
        )

    # Backend-specific configuration
    if args.default_backend is not None:
        cfg.backends.default_backend = args.default_backend
        os.environ["LLM_BACKEND"] = args.default_backend
        record_cli(
            "backends.default_backend", args.default_backend, "--default-backend"
        )

    # Static route configuration
    if getattr(args, "static_route", None) is not None:
        cfg.backends.static_route = args.static_route
        os.environ["STATIC_ROUTE"] = args.static_route
        record_cli("backends.static_route", args.static_route, "--static-route")

    # Model aliases configuration (CLI overrides config file)
    if getattr(args, "model_aliases", None) is not None:
        from src.core.config.app_config import ModelAliasRule

        # Convert CLI tuples to ModelAliasRule objects
        cli_aliases = [
            ModelAliasRule(pattern=pattern, replacement=replacement)
            for pattern, replacement in args.model_aliases
        ]
        cfg.model_aliases = cli_aliases
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

    # API keys and URLs
    if args.openrouter_api_key is not None:
        cfg.backends["openrouter"].api_key = _normalize_api_key_value(
            args.openrouter_api_key
        )
        record_cli(
            "backends.openrouter.api_key",
            cfg.backends["openrouter"].api_key,
            "--openrouter-api-key",
        )
    if args.openrouter_api_base_url is not None:
        cfg.backends["openrouter"].api_url = args.openrouter_api_base_url
        record_cli(
            "backends.openrouter.api_url",
            args.openrouter_api_base_url,
            "--openrouter-api-base-url",
        )
    if args.gemini_api_key is not None:
        cfg.backends["gemini"].api_key = _normalize_api_key_value(
            args.gemini_api_key
        )
        if cfg.backends["gemini"].api_key:
            os.environ["GEMINI_API_KEY"] = cfg.backends["gemini"].api_key[0]
        else:
            os.environ.pop("GEMINI_API_KEY", None)
        record_cli(
            "backends.gemini.api_key",
            cfg.backends["gemini"].api_key,
            "--gemini-api-key",
        )
    if args.gemini_api_base_url is not None:
        cfg.backends["gemini"].api_url = args.gemini_api_base_url
        record_cli(
            "backends.gemini.api_url",
            args.gemini_api_base_url,
            "--gemini-api-base-url",
        )
    if args.zai_api_key is not None:
        cfg.backends["zai"].api_key = _normalize_api_key_value(args.zai_api_key)
        record_cli(
            "backends.zai.api_key",
            cfg.backends["zai"].api_key,
            "--zai-api-key",
        )

    # Feature flags (inverted boolean logic)
    if args.disable_interactive_mode is not None:
        cfg.session.default_interactive_mode = not args.disable_interactive_mode
        os.environ["DISABLE_INTERACTIVE_MODE"] = (
            "True" if args.disable_interactive_mode else "False"
        )
        record_cli(
            "session.default_interactive_mode",
            cfg.session.default_interactive_mode,
            "--disable-interactive-mode",
        )
    if args.disable_auth is not None:
        cfg.auth.disable_auth = args.disable_auth
        record_cli("auth.disable_auth", args.disable_auth, "--disable-auth")
    if getattr(args, "trusted_ips", None) is not None:
        cfg.auth.trusted_ips = args.trusted_ips
        record_cli("auth.trusted_ips", args.trusted_ips, "--trusted-ip")
    if args.force_set_project is not None:
        cfg.session.force_set_project = args.force_set_project
        os.environ["FORCE_SET_PROJECT"] = "true" if args.force_set_project else "false"
        record_cli(
            "session.force_set_project", args.force_set_project, "--force-set-project"
        )
    if getattr(args, "project_dir_resolution_model", None) is not None:
        cfg.session.project_dir_resolution_model = (
            args.project_dir_resolution_model
        )
        record_cli(
            "session.project_dir_resolution_model",
            args.project_dir_resolution_model,
            "--project-dir-resolution-model",
        )

    # These still rely on environment variables for now
    if args.disable_redact_api_keys_in_prompts is not None:
        cfg.auth.redact_api_keys_in_prompts = (
            not args.disable_redact_api_keys_in_prompts
        )
        record_cli(
            "auth.redact_api_keys_in_prompts",
            cfg.auth.redact_api_keys_in_prompts,
            "--disable-redact-api-keys-in-prompts",
        )
    if args.disable_interactive_commands is not None:
        cfg.session.disable_interactive_commands = args.disable_interactive_commands
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
        cfg.strict_command_detection = args.strict_command_detection
        record_cli(
            "strict_command_detection",
            args.strict_command_detection,
            "--strict-command-detection",
        )

    brute_force_cfg = getattr(cfg.auth, "brute_force_protection", None)
    if brute_force_cfg is not None:
        if getattr(args, "brute_force_protection_enabled", None) is not None:
            brute_force_cfg.enabled = bool(args.brute_force_protection_enabled)
            record_cli(
                "auth.brute_force_protection.enabled",
                brute_force_cfg.enabled,
                "--enable/disable-brute-force-protection",
            )
        if getattr(args, "auth_max_failed_attempts", None) is not None:
            brute_force_cfg.max_failed_attempts = max(
                1, int(args.auth_max_failed_attempts)
            )
            record_cli(
                "auth.brute_force_protection.max_failed_attempts",
                brute_force_cfg.max_failed_attempts,
                "--auth-max-failed-attempts",
            )
        if getattr(args, "auth_brute_force_ttl", None) is not None:
            brute_force_cfg.ttl_seconds = max(1, int(args.auth_brute_force_ttl))
            record_cli(
                "auth.brute_force_protection.ttl_seconds",
                brute_force_cfg.ttl_seconds,
                "--auth-brute-force-ttl",
            )
        if getattr(args, "auth_initial_block_seconds", None) is not None:
            brute_force_cfg.initial_block_seconds = max(
                1, int(args.auth_initial_block_seconds)
            )
            record_cli(
                "auth.brute_force_protection.initial_block_seconds",
                brute_force_cfg.initial_block_seconds,
                "--auth-brute-force-initial-block",
            )
        if getattr(args, "auth_block_multiplier", None) is not None:
            multiplier = float(args.auth_block_multiplier)
            brute_force_cfg.block_multiplier = multiplier if multiplier > 1 else 1.0
            record_cli(
                "auth.brute_force_protection.block_multiplier",
                brute_force_cfg.block_multiplier,
                "--auth-brute-force-multiplier",
            )
        if getattr(args, "auth_max_block_seconds", None) is not None:
            brute_force_cfg.max_block_seconds = max(1, int(args.auth_max_block_seconds))
            record_cli(
                "auth.brute_force_protection.max_block_seconds",
                brute_force_cfg.max_block_seconds,
                "--auth-brute-force-max-block",
            )

    # Pytest compression flag
    if args.pytest_compression_enabled is not None:
        cfg.session.pytest_compression_enabled = args.pytest_compression_enabled
        record_cli(
            "session.pytest_compression_enabled",
            args.pytest_compression_enabled,
            "--enable/disable-pytest-compression",
        )

    # Pytest full-suite steering flag
    if getattr(args, "pytest_full_suite_steering_enabled", None) is not None:
        cfg.session.pytest_full_suite_steering_enabled = (
            args.pytest_full_suite_steering_enabled
        )
        cfg.session.tool_call_reactor.pytest_full_suite_steering_enabled = (
            args.pytest_full_suite_steering_enabled
        )
        record_cli(
            "session.pytest_full_suite_steering_enabled",
            args.pytest_full_suite_steering_enabled,
            "--enable/disable-pytest-full-suite-steering",
        )

    # Planning phase configuration
    if getattr(args, "enable_planning_phase", None) is not None:
        cfg.session.planning_phase.enabled = args.enable_planning_phase
        record_cli(
            "session.planning_phase.enabled",
            args.enable_planning_phase,
            "--enable-planning-phase",
        )
    if getattr(args, "planning_phase_strong_model", None) is not None:
        cfg.session.planning_phase.strong_model = args.planning_phase_strong_model
        record_cli(
            "session.planning_phase.strong_model",
            args.planning_phase_strong_model,
            "--planning-phase-strong-model",
        )
    if getattr(args, "planning_phase_max_turns", None) is not None:
        cfg.session.planning_phase.max_turns = max(1, args.planning_phase_max_turns)
        record_cli(
            "session.planning_phase.max_turns",
            cfg.session.planning_phase.max_turns,
            "--planning-phase-max-turns",
        )
    if getattr(args, "planning_phase_max_file_writes", None) is not None:
        cfg.session.planning_phase.max_file_writes = max(
            1, args.planning_phase_max_file_writes
        )
        record_cli(
            "session.planning_phase.max_file_writes",
            cfg.session.planning_phase.max_file_writes,
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
        existing_overrides = cfg.session.planning_phase.overrides or {}
        if not isinstance(existing_overrides, dict):
            existing_overrides = {}
        existing_overrides.update(overrides_updates)
        cfg.session.planning_phase.overrides = existing_overrides
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
    if getattr(args, "edit_precision_enabled", None) is not None:
        cfg.edit_precision.enabled = args.edit_precision_enabled
        record_cli(
            "edit_precision.enabled",
            args.edit_precision_enabled,
            "--enable/disable-edit-precision",
        )
    if getattr(args, "edit_precision_temperature", None) is not None:
        cfg.edit_precision.temperature = max(0.0, args.edit_precision_temperature)
        record_cli(
            "edit_precision.temperature",
            cfg.edit_precision.temperature,
            "--edit-precision-temperature",
        )
    if getattr(args, "edit_precision_min_top_p", None) is not None:
        cfg.edit_precision.min_top_p = max(0.0, args.edit_precision_min_top_p)
        record_cli(
            "edit_precision.min_top_p",
            cfg.edit_precision.min_top_p,
            "--edit-precision-min-top-p",
        )
    if getattr(args, "edit_precision_override_top_p", None) is not None:
        cfg.edit_precision.override_top_p = args.edit_precision_override_top_p
        record_cli(
            "edit_precision.override_top_p",
            args.edit_precision_override_top_p,
            "--edit-precision-override-top-p",
        )
    if getattr(args, "edit_precision_override_top_k", None) is not None:
        cfg.edit_precision.override_top_k = args.edit_precision_override_top_k
        record_cli(
            "edit_precision.override_top_k",
            args.edit_precision_override_top_k,
            "--edit-precision-override-top-k",
        )
    if getattr(args, "edit_precision_target_top_k", None) is not None:
        cfg.edit_precision.target_top_k = (
            args.edit_precision_target_top_k
            if args.edit_precision_target_top_k > 0
            else None
        )
        record_cli(
            "edit_precision.target_top_k",
            cfg.edit_precision.target_top_k,
            "--edit-precision-target-top-k",
        )
    if getattr(args, "edit_precision_exclude_agents_regex", None) is not None:
        cfg.edit_precision.exclude_agents_regex = (
            args.edit_precision_exclude_agents_regex
        )
        record_cli(
            "edit_precision.exclude_agents_regex",
            args.edit_precision_exclude_agents_regex,
            "--edit-precision-exclude-agents",
        )

    # Validate and apply configurations
    _validate_and_apply_prefix(cfg)
    _apply_feature_flags(cfg)
    _apply_security_flags(cfg)
    if return_resolution:
        return cfg, res
    return cfg


def _validate_and_apply_prefix(cfg: AppConfig) -> None:
    """Validate and apply command prefix configuration."""
    if cfg.command_prefix is None:
        return
    err = validate_command_prefix(str(cfg.command_prefix))
    if err:
        raise ValueError(f"Invalid command prefix: {err}")


def _apply_feature_flags(cfg: AppConfig) -> None:
    """Apply other feature flags from cfg."""
    # Apply other feature flags from cfg
    # These flags are now directly applied in apply_cli_args


def _apply_security_flags(cfg: AppConfig) -> None:
    """Apply security-related configuration."""
    if not cfg.auth.disable_auth:
        return
    logging.warning("Client authentication is DISABLED")
    if cfg.host != "127.0.0.1":
        logging.warning(
            "Authentication disabled but host is %s. Forcing host to 127.0.0.1 for security.",
            cfg.host,
        )
        cfg.host = "127.0.0.1"


def _check_privileges() -> None:
    """Refuse to run the server with elevated privileges."""
    if os.name != "nt":
        if hasattr(os, "geteuid") and os.geteuid() == 0:
            raise SystemExit("Refusing to run as root user")
    else:  # Windows
        try:
            import ctypes

            if (
                hasattr(ctypes, "windll")
                and hasattr(ctypes.windll, "shell32")
                and ctypes.windll.shell32.IsUserAnAdmin() != 0
            ):
                raise SystemExit("Refusing to run with administrative privileges")
        except Exception:
            pass


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
    )


def _enforce_localhost_if_auth_disabled(cfg: AppConfig) -> None:
    """Enforce localhost binding when authentication is disabled."""
    if not cfg.auth.disable_auth:
        return
    logging.warning("Client authentication is DISABLED")
    if cfg.host != "127.0.0.1":
        logging.warning(
            "Authentication disabled but host is %s. Forcing host to 127.0.0.1 for security.",
            cfg.host,
        )
        cfg.host = "127.0.0.1"


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
                    "  - Default location: ~/.anthropic/oauth_creds.json\n"
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
            sys.stderr.write("    * gemini-cli-oauth-personal (uses gemini CLI auth)\n")
            sys.stderr.write("    * qwen-oauth (uses qwen CLI auth)\n")
            sys.stderr.write("    * anthropic-oauth (uses Claude Code auth)\n")
            sys.stderr.write("    * openai-oauth (uses codex CLI auth)\n")
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
                "    * For Qwen: run 'qwen auth' (creates ~/.qwen/oauth_creds.json)\n"
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


def main(
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

    # Handle daemon mode early
    if _maybe_run_as_daemon(args, cfg):
        return

    # Configure logging
    _configure_logging(cfg)

    resolution.log(logging.getLogger("config.resolution"), cfg)

    # Check privileges unless explicitly allowed
    if not args.allow_admin:
        _check_privileges()

    # Enforce security constraints
    _enforce_localhost_if_auth_disabled(cfg)

    # Build application with comprehensive error handling
    app: FastAPI
    try:
        if build_app_fn:
            app = build_app_fn(cfg)  # For testing
        else:
            app = build_app(cfg)  # Production
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

    # Start the server
    logging.info(f"Starting uvicorn on {cfg.host}:{cfg.port}")
    try:
        # Start uvicorn with the configured host/port using uvicorn defaults
        uvicorn.run(
            app, host=cfg.host, port=cfg.port, log_config=UVICORN_LOGGING_CONFIG
        )
    except Exception as e:
        logging.exception("Uvicorn failed to start: %s", e)
        raise


if __name__ == "__main__":
    main()


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
