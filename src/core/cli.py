import argparse
import logging
import os
import sys
from typing import Any, Callable, Dict, Optional

import uvicorn

from src.command_prefix import validate_command_prefix
from src.core.config import _load_config


def _check_privileges() -> None:
    """Refuse to run the server with elevated privileges."""
    if os.name != "nt":
        if hasattr(os, "geteuid") and os.geteuid() == 0:
            raise SystemExit("Refusing to run as root user")
    else:  # Windows
        try:
            import ctypes

            if ctypes.windll.shell32.IsUserAnAdmin() != 0:
                raise SystemExit(
                    "Refusing to run with administrative privileges")
        except Exception:
            pass


def parse_cli_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the LLM proxy server")
    parser.add_argument(
        "--default-backend",
        dest="default_backend",
        choices=["openrouter", "gemini", "gemini-cli-direct"],
        default=os.getenv("LLM_BACKEND"),
        help="Default backend when multiple backends are functional",
    )
    parser.add_argument(
        "--backend",
        dest="default_backend",
        choices=["openrouter", "gemini", "gemini-cli-direct"],
        help=argparse.SUPPRESS,
    )
    parser.add_argument("--openrouter-api-key")
    parser.add_argument("--openrouter-api-base-url")
    parser.add_argument("--gemini-api-key")
    parser.add_argument("--gemini-api-base-url")
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
    return parser.parse_args(argv)


def apply_cli_args(args: argparse.Namespace) -> Dict[str, Any]:
    mappings = {
        "default_backend": "LLM_BACKEND",
        "openrouter_api_key": "OPENROUTER_API_KEY",
        "openrouter_api_base_url": "OPENROUTER_API_BASE_URL",
        "gemini_api_key": "GEMINI_API_KEY",
        "gemini_api_base_url": "GEMINI_API_BASE_URL",
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
    if args.command_prefix is not None:
        err = validate_command_prefix(str(args.command_prefix))
        if err:
            raise ValueError(f"Invalid command prefix: {err}")
    if getattr(args, "disable_redact_api_keys_in_prompts", None):
        os.environ["REDACT_API_KEYS_IN_PROMPTS"] = "false"
    if getattr(args, "disable_auth", None):
        os.environ["DISABLE_AUTH"] = "true"
        # Security: Force localhost when auth is disabled via CLI
        if getattr(args, "host", None) and args.host != "127.0.0.1":
            logging.warning(
                "Authentication disabled via CLI. Forcing host to 127.0.0.1 for security (was: %s)",
                args.host
            )
        os.environ["PROXY_HOST"] = "127.0.0.1"
    if getattr(args, "force_set_project", None):
        os.environ["FORCE_SET_PROJECT"] = "true"
    if getattr(args, "disable_interactive_commands", None):
        os.environ["DISABLE_INTERACTIVE_COMMANDS"] = "true"
    if getattr(args, "disable_accounting", None):
        os.environ["DISABLE_ACCOUNTING"] = "true"
    return _load_config()


def main(
    argv: list[str] | None = None,
    build_app_fn: Optional[Callable[[Dict[str, Any] | None], Any]] = None,
) -> None:
    args = parse_cli_args(argv)
    cfg = apply_cli_args(args)
    logging.basicConfig(
        level=getattr(logging, args.log_level),
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        filename=args.log_file,
    )
    _check_privileges()

    # Security: Ensure localhost-only binding when authentication is disabled
    if cfg.get("disable_auth"):
        logging.warning("Client authentication is DISABLED")
        if cfg.get("proxy_host") != "127.0.0.1":
            logging.warning(
                "Authentication disabled but host is %s. Forcing host to 127.0.0.1 for security.",
                cfg.get("proxy_host")
            )
            cfg["proxy_host"] = "127.0.0.1"

    if build_app_fn is None:
        from src.main import build_app as build_app_fn

    app = build_app_fn(cfg, config_file=args.config_file)
    uvicorn.run(app, host=cfg["proxy_host"], port=cfg["proxy_port"])
