import argparse
import logging
import os
import sys

import colorama
import uvicorn

# Import backend connectors to ensure they register themselves
from src.core.services import backend_imports  # noqa: F401

from src.command_prefix import validate_command_prefix
from src.core.config.app_config import AppConfig, LogLevel, load_config


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


from src.core.services.backend_registry_service import backend_registry # Added this import

# ... (rest of the file)

def parse_cli_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the LLM proxy server")
    
    # Dynamically get registered backends
    registered_backends = backend_registry.get_registered_backends()

    parser.add_argument(
        "--default-backend",
        dest="default_backend",
        choices=registered_backends, # Dynamically populated
        default=os.getenv("LLM_BACKEND"),
        help="Default backend when multiple backends are functional",
    )
    parser.add_argument(
        "--backend",
        dest="default_backend",
        choices=registered_backends, # Dynamically populated
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
        "--log", dest="log_file", metavar="FILE", help="Write logs to FILE"
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


def apply_cli_args(args: argparse.Namespace) -> AppConfig:
    cfg: AppConfig = cast(AppConfig, load_config())

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
    if args.log_level is not None:
        cfg.logging.level = LogLevel[args.log_level]

    # Backend-specific keys
    if args.default_backend is not None:
        cfg.backends.default_backend = args.default_backend
        os.environ["LLM_BACKEND"] = args.default_backend
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


def _validate_and_apply_prefix(cfg: AppConfig) -> None:
    if cfg.command_prefix is None:
        return
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
from collections.abc import Callable  # Added cast to this import
from typing import cast

from fastapi import FastAPI  # Added this import

from src.core.app.application_factory import build_app  # Moved this import to the top
from src.core.config.app_config import AppConfig

# ... (rest of the file)


from collections.abc import Callable


def main(
    argv: list[str] | None = None,
    build_app_fn: Callable[[AppConfig, str | None], FastAPI] | None = None,
) -> None:
    if os.name == "nt":
        colorama.init()

    args = parse_cli_args(argv)

    cfg = apply_cli_args(args)  # <--- cfg is assigned here

    if _maybe_run_as_daemon(args, cfg):
        return
    _configure_logging(cfg)
    if not args.allow_admin:
        _check_privileges()

    _enforce_localhost_if_auth_disabled(cfg)

    # Allow tests to inject a custom build_app function (mock) by passing
    # `build_app_fn`. The test mocks expect to be called with cfg and
    # the config_file keyword argument.
    if build_app_fn is not None:
        app = build_app_fn(cfg, args.config_file)
    else:
        app, _ = build_app(cfg)

    uvicorn.run(app, host=cfg.host, port=cfg.port)


def _maybe_run_as_daemon(args: argparse.Namespace, cfg: AppConfig) -> bool:
    if not args.daemon:
        return False
    if not cfg.logging.log_file:
        raise SystemExit("--log must be specified when running in daemon mode.")
    if os.name == "nt":
        import subprocess
        import time

        args_list = [arg for arg in sys.argv[1:] if not arg.startswith("--daemon")]
        command = [sys.executable, "-m", "src.core.cli", *args_list]
        subprocess.Popen(
            command, creationflags=subprocess.DETACHED_PROCESS, close_fds=True
        )
        time.sleep(2)
        sys.exit(0)
    _daemonize()
    return True


def _configure_logging(cfg: AppConfig) -> None:
    logging.basicConfig(
        level=getattr(logging, cfg.logging.level.value),
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        filename=cfg.logging.log_file,
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
