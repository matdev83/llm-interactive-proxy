"""Command-line entry point for the LLM proxy server.

This module is a thin facade that preserves the public API:
- `build_cli_parser`
- `parse_cli_args`
- `apply_cli_args`
- `main`
"""

import argparse
import asyncio
import contextlib
import logging
import os
import sys
from collections.abc import Callable
from typing import Literal, cast, overload

from fastapi import FastAPI

from src.core.app.application_builder import build_app_async
from src.core.config.app_config import AppConfig, load_config
from src.core.config.parameter_resolution import ParameterResolution

# Import backend connectors to ensure they register themselves
from src.core.services import backend_imports  # noqa: F401
from src.core.services.backend_registry import backend_registry

logger = logging.getLogger(__name__)


def build_cli_parser() -> argparse.ArgumentParser:
    """Build the CLI argument parser with full feature parity to original CLI.

    This function delegates to ArgumentParserBuilder for constructing the parser.
    The delegation maintains backward compatibility while organizing argument
    construction by domain.

    Returns:
        Configured ArgumentParser instance with all CLI arguments.
    """
    from src.core.cli_support.argument_parser_builder import ArgumentParserBuilder

    # Pass the module-level backend_registry for backward-compatibility with
    # tests/consumers that patch `src.core.cli.backend_registry`.
    return ArgumentParserBuilder(registry=backend_registry).build()


def parse_cli_args(argv: list[str] | None = None) -> argparse.Namespace:
    """Parse command line arguments with full feature parity to original CLI.

    This function delegates argument parsing to ArgumentParserBuilder and
    validation to CliArgsValidator.

    Args:
        argv: Command line arguments to parse, or None to use sys.argv

    Returns:
        Parsed argument namespace

    Raises:
        ValueError: If validation fails (e.g., invalid LLM assessment configuration)
    """
    from src.core.cli_support.cli_args_validator import CliArgsValidator

    parser = build_cli_parser()
    parsed_args = parser.parse_args(argv)

    # Validate using the new CliArgsValidator
    validator = CliArgsValidator()
    validator.validate(parsed_args)

    return parsed_args


@overload
def apply_cli_args(
    args: argparse.Namespace,
    *,
    return_resolution: Literal[False] = False,
    resolution: ParameterResolution | None = None,
) -> AppConfig: ...


@overload
def apply_cli_args(
    args: argparse.Namespace,
    *,
    return_resolution: Literal[True],
    resolution: ParameterResolution | None = None,
) -> tuple[AppConfig, ParameterResolution]: ...


def apply_cli_args(
    args: argparse.Namespace,
    *,
    return_resolution: bool = False,
    resolution: ParameterResolution | None = None,
) -> AppConfig | tuple[AppConfig, ParameterResolution]:
    """Apply CLI arguments to configuration with full feature parity.

    This function delegates to ConfigurationApplicator for applying arguments.
    The delegation maintains backward compatibility while organizing argument
    application by domain.

    Args:
        args: Parsed command line arguments
        return_resolution: If True, return (config, resolution) tuple
        resolution: Optional pre-existing resolution tracker

    Returns:
        AppConfig if return_resolution is False
        tuple (AppConfig, ParameterResolution) if return_resolution is True
    """
    from src.core.cli_support.configuration_applicator import ConfigurationApplicator

    res = resolution or ParameterResolution()

    # Use the module-level `load_config` symbol for backward compatibility with
    # existing tests that patch `src.core.cli.load_config`.
    config_path = getattr(args, "config_file", None)
    base_cfg = cast(AppConfig, load_config(config_path, resolution=res))

    applicator = ConfigurationApplicator()
    final_cfg = applicator.apply_overrides(args, base_cfg, resolution=res)

    if return_resolution:
        return final_cfg, res
    return final_cfg


def _is_admin() -> bool:
    """Cross-platform admin check.

    DEPRECATED: Use PrivilegeChecker service instead.
    Kept for backward compatibility during refactoring.
    """
    from src.core.cli_support.privilege_checker import PrivilegeChecker

    checker = PrivilegeChecker()
    return checker.is_admin()


def _has_privilege_functionality() -> bool:
    """Check if the platform supports privilege checking functionality.

    DEPRECATED: Use PrivilegeChecker service instead.
    Kept for backward compatibility during refactoring.
    """
    from src.core.cli_support.privilege_checker import PrivilegeChecker

    checker = PrivilegeChecker()
    return checker.has_privilege_functionality()


def _check_privileges() -> None:
    """Refuse to run the server with elevated privileges.

    DEPRECATED: Use PrivilegeChecker.check_and_enforce() instead.
    Kept for backward compatibility during refactoring.
    """
    # Use _is_admin() to maintain backward compatibility with tests that patch it
    if _is_admin():
        if os.name != "nt":
            raise SystemExit("Refusing to run as root user")
        else:
            raise SystemExit("Refusing to run with administrative privileges")


def _daemonize() -> None:
    """Backward-compatible wrapper for daemonization on POSIX."""
    from src.core.cli_support.server_lifecycle_manager import ServerLifecycleManager

    ServerLifecycleManager()._daemonize()


def _maybe_run_as_daemon(args: argparse.Namespace, cfg: AppConfig) -> bool:
    """Backward-compatible daemon mode handler.

    Returns True if the process should exit after spawning a daemon.
    """
    if not getattr(args, "daemon", False):
        return False

    if not cfg.logging.log_file:
        sys.exit("--log must be specified when running in daemon mode.")

    if os.name == "nt":
        from src.core.cli_support.server_lifecycle_manager import ServerLifecycleManager

        return ServerLifecycleManager().handle_daemon_mode(args, cfg)

    _daemonize()
    return False


def is_port_in_use(host: str, port: int) -> bool:
    """Check if a port is in use.

    Delegates to ServerLifecycleManager.
    Kept for backward compatibility.
    """
    from src.core.cli_support.server_lifecycle_manager import ServerLifecycleManager

    manager = ServerLifecycleManager()
    return manager.is_port_in_use(host, port)


def _configure_logging(cfg: AppConfig) -> None:
    """Configure logging based on configuration.

    This function delegates to LoggingConfigurator for logging setup.
    The delegation maintains backward compatibility while organizing logging
    configuration into a dedicated service.

    Args:
        cfg: Application configuration containing logging settings.
    """
    from src.core.cli_support.logging_configurator import LoggingConfigurator

    configurator = LoggingConfigurator()
    configurator.configure(cfg)


def _with_timestamp_suffix(path: str | None) -> str | None:
    """Append a timestamp suffix (HHMM) to the filename portion of a path.

    This function delegates to LoggingConfigurator for timestamp suffix logic.
    The delegation maintains backward compatibility while organizing logging
    configuration into a dedicated service.

    Args:
        path: The file path to suffix, or None.

    Returns:
        The path with timestamp suffix appended, or None if input was None.
    """
    from src.core.cli_support.logging_configurator import LoggingConfigurator

    configurator = LoggingConfigurator()
    return configurator.apply_timestamp_suffix(path)


def _apply_pid_suffixes(cfg: AppConfig) -> AppConfig:
    """Return a copy of cfg with timestamp-suffixed log and capture files.

    This function delegates to LoggingConfigurator for timestamp suffix logic.
    The delegation maintains backward compatibility while organizing logging
    configuration into a dedicated service.

    Note: Function name kept as _apply_pid_suffixes for compatibility but
    implementation applies timestamps.

    Args:
        cfg: Application configuration to update.

    Returns:
        A new AppConfig with timestamp-suffixed log and capture file paths.
    """
    from src.core.cli_support.logging_configurator import LoggingConfigurator

    configurator = LoggingConfigurator()
    return configurator.apply_pid_suffixes(cfg)


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
    """Handle application build errors with user-friendly messages.

    This function delegates to ErrorHandler for formatting and output.
    The delegation maintains backward compatibility while organizing error
    handling into a dedicated service.

    Args:
        error_msg: The error message from an application build failure.
    """
    from src.core.cli_support.error_handler import ErrorHandler

    handler = ErrorHandler()
    handler.handle_build_error(error_msg)


async def main(
    argv: list[str] | None = None,
    build_app_fn: Callable[[AppConfig], FastAPI] | None = None,
) -> None:
    """Main entry point (async)."""
    from src.core.cli_support.error_handler import ErrorHandler
    from src.core.cli_support.logging_configurator import LoggingConfigurator
    from src.core.cli_support.privilege_checker import PrivilegeChecker
    from src.core.cli_support.server_lifecycle_manager import ServerLifecycleManager

    error_handler = ErrorHandler()
    try:
        # Parse arguments
        args: argparse.Namespace = parse_cli_args(argv)

        cfg_result = apply_cli_args(args, return_resolution=True)
        cfg, resolution = cast(tuple[AppConfig, ParameterResolution], cfg_result)

        server_manager = ServerLifecycleManager(
            privilege_checker=PrivilegeChecker(),
            logging_configurator=LoggingConfigurator(),
            error_handler=error_handler,
            build_app_async_fn=build_app_async,
        )

        await server_manager.run(
            args,
            cfg,
            resolution=resolution,
            build_app_fn=build_app_fn,
            enforce_localhost_fn=_enforce_localhost_if_auth_disabled,
        )

    except (SystemExit, KeyboardInterrupt):
        # Let control flow exceptions propagate normally
        raise
    except Exception as e:
        # Catch only application startup errors (not control flow)
        # Log with full stack trace for debugging
        logger.exception("Application startup failed: %s", e)
        error_handler.handle_exception(e)
        raise SystemExit(1) from e


# Main entry point guard
if __name__ == "__main__":
    with contextlib.suppress(KeyboardInterrupt):
        asyncio.run(main())
