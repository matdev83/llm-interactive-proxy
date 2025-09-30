import argparse

# type: ignore[unreachable]
import logging
import os
import socket
import sys

import uvicorn

from src.command_prefix import validate_command_prefix
from src.core.config.app_config import AppConfig, LogLevel, load_config

# Import backend connectors to ensure they register themselves
from src.core.services import backend_imports  # noqa: F401


def is_port_in_use(host: str, port: int) -> bool:
    """Check if a port is in use on a given host."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        return s.connect_ex((host, port)) == 0


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
    if hasattr(os, "fork") and hasattr(os, "setsid"):
        if os.fork() > 0:
            sys.exit(0)  # exit first parent

        os.chdir("/")
        if hasattr(os, "setsid"):
            os.setsid()  # type: ignore[attr-defined]
        os.umask(0)

        if os.fork() > 0:
            sys.exit(0)  # exit second parent
    else:
        # On Windows, we can't daemonize, so we just continue
        pass


from src.core.services.backend_registry import (
    backend_registry,  # Updated import path
)

# ... (rest of the file)


def parse_cli_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser: argparse.ArgumentParser = argparse.ArgumentParser(
        description="Run the LLM proxy server"
    )

    # Dynamically get registered backends
    registered_backends: list[str] = backend_registry.get_registered_backends()

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
    parser.add_argument("--openrouter-api-key")
    parser.add_argument("--openrouter-api-base-url")
    parser.add_argument("--gemini-api-key")
    parser.add_argument("--gemini-api-base-url")
    parser.add_argument("--zai-api-key")
    parser.add_argument("--host")
    parser.add_argument("--port", type=int)
    parser.add_argument("--timeout", type=int)
    parser.add_argument("--command-prefix")
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
        "--log-level",
        dest="log_level",
        choices=["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"],
        default="INFO",
        help="Set the logging level (e.g., INFO, DEBUG)",
    )
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
    return parser.parse_args(argv)


def apply_cli_args(args: argparse.Namespace) -> AppConfig:
    # Load base config (YAML only); pass through --config when provided
    cfg: AppConfig = cast(
        AppConfig,
        (
            load_config(args.config_file)
            if getattr(args, "config_file", None)
            else load_config()
        ),
    )

    if args.host is not None:
        cfg.host = args.host
    if args.port is not None:
        cfg.port = args.port
        os.environ["PROXY_PORT"] = str(args.port)
    if args.timeout is not None:
        cfg.proxy_timeout = args.timeout
    if args.command_prefix is not None:
        cfg.command_prefix = args.command_prefix
        os.environ["COMMAND_PREFIX"] = args.command_prefix
    if args.log_file is not None:
        cfg.logging.log_file = args.log_file
    else:
        # Set default log file if none specified
        from pathlib import Path

        default_log_file = "logs/proxy.log"
        # Ensure logs directory exists
        log_dir = Path(default_log_file).parent
        log_dir.mkdir(exist_ok=True)
        cfg.logging.log_file = default_log_file
    if args.log_level is not None:
        cfg.logging.level = LogLevel[args.log_level]
    if getattr(args, "capture_file", None) is not None:
        cfg.logging.capture_file = args.capture_file
    if getattr(args, "capture_max_bytes", None) is not None:
        cfg.logging.capture_max_bytes = args.capture_max_bytes
    if getattr(args, "capture_truncate_bytes", None) is not None:
        cfg.logging.capture_truncate_bytes = args.capture_truncate_bytes
    if getattr(args, "capture_max_files", None) is not None:
        cfg.logging.capture_max_files = args.capture_max_files
    if getattr(args, "capture_rotate_interval_seconds", None) is not None:
        cfg.logging.capture_rotate_interval_seconds = (
            args.capture_rotate_interval_seconds
        )
    if getattr(args, "capture_total_max_bytes", None) is not None:
        cfg.logging.capture_total_max_bytes = args.capture_total_max_bytes

    # Backend-specific keys
    if args.default_backend is not None:
        cfg.backends.default_backend = args.default_backend
        os.environ["LLM_BACKEND"] = args.default_backend

    # Static route configuration
    if getattr(args, "static_route", None) is not None:
        cfg.backends.static_route = args.static_route
        os.environ["STATIC_ROUTE"] = args.static_route
    if args.openrouter_api_key is not None:
        cfg.backends["openrouter"].api_key = args.openrouter_api_key
    if args.openrouter_api_base_url is not None:
        cfg.backends["openrouter"].api_url = args.openrouter_api_base_url
    if args.gemini_api_key is not None:
        cfg.backends["gemini"].api_key = args.gemini_api_key
        os.environ["GEMINI_API_KEY"] = args.gemini_api_key
    if args.gemini_api_base_url is not None:
        cfg.backends["gemini"].api_url = args.gemini_api_base_url
    if args.zai_api_key is not None:
        cfg.backends["zai"].api_key = args.zai_api_key

    # Inverted boolean logic flags
    if args.disable_interactive_mode is not None:
        cfg.session.default_interactive_mode = not args.disable_interactive_mode
        os.environ["DISABLE_INTERACTIVE_MODE"] = (
            "True" if args.disable_interactive_mode else "False"
        )
    if args.disable_auth is not None:
        cfg.auth.disable_auth = args.disable_auth
    if getattr(args, "trusted_ips", None) is not None:
        cfg.auth.trusted_ips = args.trusted_ips
    if args.force_set_project is not None:
        cfg.session.force_set_project = args.force_set_project
        os.environ["FORCE_SET_PROJECT"] = "true" if args.force_set_project else "false"

    # These still rely on environment variables for now
    if args.disable_redact_api_keys_in_prompts is not None:
        cfg.auth.redact_api_keys_in_prompts = (
            not args.disable_redact_api_keys_in_prompts
        )
    if args.disable_interactive_commands is not None:
        cfg.session.disable_interactive_commands = args.disable_interactive_commands
    if args.disable_accounting is not None:
        os.environ["DISABLE_ACCOUNTING"] = (
            "true" if args.disable_accounting else "false"
        )

    _validate_and_apply_prefix(cfg)
    _apply_feature_flags(cfg)
    _apply_security_flags(cfg)
    return cfg


# type: ignore[unreachable]
def _validate_and_apply_prefix(cfg: AppConfig) -> None:
    if cfg.command_prefix is None:
        return  # type: ignore[unreachable]
    err = validate_command_prefix(str(cfg.command_prefix))
    if err:
        raise ValueError(f"Invalid command prefix: {err}")


def _apply_feature_flags(cfg: AppConfig) -> None:
    # Apply other feature flags from cfg
    # These flags are now directly applied in apply_cli_args
    pass


def _apply_security_flags(cfg: AppConfig) -> None:
    if not cfg.auth.disable_auth:
        return
    # Security: Force localhost when auth is disabled via CLI
    if cfg.host != "127.0.0.1":
        logging.warning(
            "Authentication disabled via CLI. Forcing host to 127.0.0.1 for security (was: %s)",
            cfg.host,
        )
    cfg.host = "127.0.0.1"


import argparse
from typing import cast

from fastapi import FastAPI  # Added this import

from src.core.app.application_builder import (
    build_app,  # Using new staged initialization
)
from src.core.config.app_config import AppConfig

# ... (rest of the file)


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
) -> None:
    # Use identical behavior across OS; no platform-specific libs

    args: argparse.Namespace = parse_cli_args(argv)

    cfg: AppConfig = apply_cli_args(args)  # <--- cfg is assigned here

    if _maybe_run_as_daemon(args, cfg):
        return
    _configure_logging(cfg)
    if not args.allow_admin:
        _check_privileges()

    _enforce_localhost_if_auth_disabled(cfg)

    # Allow tests to inject a custom build_app function (mock) by passing
    # `build_app_fn`. The test mocks expect to be called with cfg and
    # the config_file keyword argument.
    app: FastAPI  # Declare app here
    try:
        app = build_app(cfg)
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

    if is_port_in_use(cfg.host, cfg.port):
        error_msg = f"Port {cfg.port} is already in use."
        logging.error(error_msg)
        sys.stderr.write(f"\nERROR: {error_msg}\n")
        sys.exit(1)

    logging.info(f"Starting uvicorn on {cfg.host}:{cfg.port}")
    try:
        uvicorn.run(app, host=cfg.host, port=cfg.port)
    except Exception as e:
        logging.exception("Uvicorn failed to start: %s", e)
        raise


def _maybe_run_as_daemon(args: argparse.Namespace, cfg: AppConfig) -> bool:
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
    _daemonize()
    return True


def _configure_logging(cfg: AppConfig) -> None:
    from src.core.common.logging_utils import configure_logging_with_environment_tagging

    configure_logging_with_environment_tagging(
        level=getattr(logging, cfg.logging.level.value),
        log_file=cfg.logging.log_file,
    )


from src.core.config.app_config import AppConfig


def _enforce_localhost_if_auth_disabled(cfg: AppConfig) -> None:
    if not cfg.auth.disable_auth:
        return
    logging.warning("Client authentication is DISABLED")
    if cfg.host != "127.0.0.1":
        logging.warning(
            "Authentication disabled but host is %s. Forcing host to 127.0.0.1 for security.",
            cfg.host,
        )
        cfg.host = "127.0.0.1"


if __name__ == "__main__":
    main()
