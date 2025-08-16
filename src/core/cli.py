import argparse
import logging
import os
import sys
from collections.abc import Callable
from typing import Any

import colorama
import uvicorn

from src.command_prefix import validate_command_prefix
from src.core.config_adapter import _load_config


def _check_privileges() -> None:
    """Refuse to run the server with elevated privileges."""
    if os.name != "nt":
        if hasattr(os, "geteuid") and os.geteuid() == 0:
            raise SystemExit("Refusing to run as root user")
    else:  # Windows
        try:
            import ctypes

            if ctypes.windll.shell32.IsUserAnAdmin() != 0:
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


def parse_cli_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the LLM proxy server")
    parser.add_argument(
        "--default-backend",
        dest="default_backend",
        choices=["openrouter", "gemini", "anthropic", "qwen-oauth", "zai"],
        default=os.getenv("LLM_BACKEND"),
        help="Default backend when multiple backends are functional",
    )
    parser.add_argument(
        "--backend",
        dest="default_backend",
        choices=["openrouter", "gemini", "anthropic", "qwen-oauth", "zai"],
        help=argparse.SUPPRESS,
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
        help="Write logs to FILE",
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
    return parser.parse_args(argv)


def apply_cli_args(args: argparse.Namespace) -> dict[str, Any]:
    _apply_env_mappings(args)
    _validate_and_apply_prefix(args)
    _apply_feature_flags(args)
    _apply_security_flags(args)
    return _load_config()


def _apply_env_mappings(args: argparse.Namespace) -> None:
    mappings = {
        "default_backend": "LLM_BACKEND",
        "openrouter_api_key": "OPENROUTER_API_KEY",
        "openrouter_api_base_url": "OPENROUTER_API_BASE_URL",
        "gemini_api_key": "GEMINI_API_KEY",
        "gemini_api_base_url": "GEMINI_API_BASE_URL",
        "zai_api_key": "ZAI_API_KEY",
        "host": "PROXY_HOST",
        "port": "PROXY_PORT",
        "timeout": "PROXY_TIMEOUT",
        "command_prefix": "COMMAND_PREFIX",
        "disable_interactive_mode": "DISABLE_INTERACTIVE_MODE",
        "disable_auth": "DISABLE_AUTH",
        "force_set_project": "FORCE_SET_PROJECT",
        "disable_interactive_commands": "DISABLE_INTERACTIVE_COMMANDS",
        "disable_accounting": "DISABLE_ACCOUNTING",
    }
    for attr, env_name in mappings.items():
        value = getattr(args, attr)
        if value is not None:
            os.environ[env_name] = str(value)


def _validate_and_apply_prefix(args: argparse.Namespace) -> None:
    if args.command_prefix is None:
        return
    err = validate_command_prefix(str(args.command_prefix))
    if err:
        raise ValueError(f"Invalid command prefix: {err}")


def _apply_feature_flags(args: argparse.Namespace) -> None:
    # Force enable all new SOLID architecture components
    os.environ["USE_NEW_SESSION_SERVICE"] = "true"
    os.environ["USE_NEW_COMMAND_SERVICE"] = "true"
    os.environ["USE_NEW_BACKEND_SERVICE"] = "true"
    os.environ["USE_NEW_REQUEST_PROCESSOR"] = "true"
    os.environ["ENABLE_DUAL_MODE"] = "true"
    
    # Apply other feature flags from args
    if getattr(args, "disable_redact_api_keys_in_prompts", None):
        os.environ["REDACT_API_KEYS_IN_PROMPTS"] = "false"
    if getattr(args, "force_set_project", None):
        os.environ["FORCE_SET_PROJECT"] = "true"
    if getattr(args, "disable_interactive_commands", None):
        os.environ["DISABLE_INTERACTIVE_COMMANDS"] = "true"
    if getattr(args, "disable_accounting", None):
        os.environ["DISABLE_ACCOUNTING"] = "true"


def _apply_security_flags(args: argparse.Namespace) -> None:
    if not getattr(args, "disable_auth", None):
        return
    os.environ["DISABLE_AUTH"] = "true"
    # Security: Force localhost when auth is disabled via CLI
    if getattr(args, "host", None) and args.host != "127.0.0.1":
        logging.warning(
            "Authentication disabled via CLI. Forcing host to 127.0.0.1 for security (was: %s)",
            args.host,
        )
    os.environ["PROXY_HOST"] = "127.0.0.1"


def main(
    argv: list[str] | None = None,
    build_app_fn: Callable[[dict[str, Any] | None], Any] | None = None,
) -> None:
    if os.name == "nt":
        colorama.init()

    args = parse_cli_args(argv)

    if _maybe_run_as_daemon(args):
        return

    cfg = apply_cli_args(args)
    _configure_logging(args)
    if not args.allow_admin:
        _check_privileges()

    _enforce_localhost_if_auth_disabled(cfg)

    if build_app_fn is None:
        from src.main import build_app as build_app_fn  # type: ignore[assignment]

    config_file = getattr(args, "config_file", None)
    if build_app_fn is not None:
        app = build_app_fn(cfg, config_file=config_file)  # type: ignore[call-arg]
        uvicorn.run(app, host=cfg["proxy_host"], port=cfg["proxy_port"])


def _maybe_run_as_daemon(args: argparse.Namespace) -> bool:
    if not args.daemon:
        return False
    if not args.log_file:
        raise SystemExit("--log must be specified when running in daemon mode.")
    if os.name == "nt":
        import subprocess
        import time

        args_list = [arg for arg in sys.argv[1:] if not arg.startswith("--daemon")]
        command = [sys.executable, "-m", "src.core.cli", *args_list]
        subprocess.Popen(
            command,
            creationflags=subprocess.DETACHED_PROCESS,
            close_fds=True,
        )
        time.sleep(2)
        sys.exit(0)
    _daemonize()
    return True


def _configure_logging(args: argparse.Namespace) -> None:
    logging.basicConfig(
        level=getattr(logging, args.log_level),
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        filename=args.log_file,
    )


def _enforce_localhost_if_auth_disabled(cfg: dict[str, Any]) -> None:
    if not cfg.get("disable_auth"):
        return
    logging.warning("Client authentication is DISABLED")
    if cfg.get("proxy_host") != "127.0.0.1":
        logging.warning(
            "Authentication disabled but host is %s. Forcing host to 127.0.0.1 for security.",
            cfg.get("proxy_host"),
        )
        cfg["proxy_host"] = "127.0.0.1"


if __name__ == "__main__":
    main()
