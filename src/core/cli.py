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
from typing import Literal, overload

from fastapi import FastAPI

from src.core.app.application_builder import build_app_async
from src.core.common.session_continuity_warnings import topic_similarity_enabled_warning
from src.core.config.app_config import AppConfig, load_config
from src.core.config.parameter_resolution import ParameterResolution

# Early access mode detection for OAuth connector filtering
# Parse access mode flags BEFORE importing backend connectors to allow
# filtering OAuth connectors in Multi User Mode during auto-discovery
_early_access_mode = "single_user"  # Default
if "--multi-user-mode" in sys.argv:
    _early_access_mode = "multi_user"
elif "--single-user-mode" in sys.argv:
    _early_access_mode = "single_user"

# Set environment variable for connector auto-discovery to check
os.environ["LLM_PROXY_ACCESS_MODE"] = _early_access_mode

# Import backend connectors to ensure they register themselves
# OAuth connectors will be filtered in Multi User Mode based on environment variable
from src.core.services import backend_imports
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
        ValueError: If validation fails
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
    base_cfg: AppConfig = load_config(config_path, resolution=res)

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

    ServerLifecycleManager().daemonize()


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


def _warn_if_topic_similarity_matching_enabled(cfg: AppConfig) -> AppConfig:
    """Warn if topic similarity session matching is enabled.

    Topic similarity is an inherently weaker continuity signal and can increase the
    risk of cross-session merges when multiple independent sessions work on the same
    codebase. This is disabled by default and should only be enabled by operators who
    understand the trade-offs.

    Returns cfg unchanged.
    """
    try:
        continuity = cfg.session.session_continuity
    except Exception:
        return cfg

    if getattr(continuity, "enable_topic_similarity_matching", False):
        logging.warning(topic_similarity_enabled_warning())

    return cfg


def _warn_if_b2bua_unsafe_heuristic_inference_enabled(cfg: AppConfig) -> AppConfig:
    """Warn when unsafe legacy B2BUA inference mode is enabled."""
    try:
        b2bua_cfg = cfg.session.b2bua
    except Exception:
        return cfg

    if getattr(b2bua_cfg, "enabled", False) and getattr(
        b2bua_cfg, "enable_unsafe_heuristic_session_inference", False
    ):
        logging.warning(
            "session.b2bua.enable_unsafe_heuristic_session_inference=true. "
            "Unsafe legacy session inference can merge unrelated conversations. "
            "Prefer explicit client session identifiers."
        )

    return cfg


def _validate_b2bua_runtime_configuration(cfg: AppConfig) -> AppConfig:
    """Validate startup-time B2BUA deployment constraints."""
    try:
        b2bua_cfg = cfg.session.b2bua
    except Exception:
        return cfg

    if not getattr(b2bua_cfg, "enabled", False):
        return cfg

    deployment_mode = getattr(b2bua_cfg, "deployment_mode", "single-process")
    persistent_store_enabled = getattr(
        b2bua_cfg, "persistent_mapping_store_enabled", False
    )

    if deployment_mode == "multi-worker" and not persistent_store_enabled:
        raise ValueError(
            "B2BUA multi-worker mode requires persistent mapping store "
            "(set session.b2bua.persistent_mapping_store_enabled=true)."
        )

    return cfg


def _warn_if_quality_verifier_frequency_too_low(cfg: AppConfig) -> AppConfig:
    """Warn if Quality Verifier frequency is configured very aggressively.

    Very low frequencies can significantly increase latency and usage cost because
    Quality Verifier adds at least one extra backend call (and sometimes a second
    correction call). Overly frequent steering can also degrade quality by causing
    the execution model to chase verifier preferences rather than the task.

    Returns cfg unchanged.
    """
    try:
        session_cfg = cfg.session
        quality_verifier_model = getattr(session_cfg, "quality_verifier_model", None)
        quality_verifier_frequency = int(
            getattr(session_cfg, "quality_verifier_frequency", 10) or 10
        )
    except Exception:
        return cfg

    if not quality_verifier_model:
        return cfg

    if quality_verifier_frequency < 5:
        logging.warning(
            "Quality Verifier frequency is set to %s (< 5). This can noticeably increase latency "
            "and usage cost due to extra verification/correction calls. It can also cause 'oversteering' "
            "of the execution model, which may reduce (not improve) overall output quality.",
            quality_verifier_frequency,
        )

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
        raw_params = argv if argv is not None else sys.argv[1:]

        # Parse arguments
        args: argparse.Namespace = parse_cli_args(argv)
        args._raw_cli_params = list(raw_params)

        cfg_result = apply_cli_args(args, return_resolution=True)
        cfg, resolution = cfg_result
        cfg = _warn_if_topic_similarity_matching_enabled(cfg)
        cfg = _warn_if_quality_verifier_frequency_too_low(cfg)
        cfg = _warn_if_b2bua_unsafe_heuristic_inference_enabled(cfg)
        cfg = _validate_b2bua_runtime_configuration(cfg)

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

# Keep deprecated functions for backward compatibility with tests
_DEPRECATED_EXPORTS = (
    backend_imports,
    _is_admin,
    _has_privilege_functionality,
    _check_privileges,
    _daemonize,
    _maybe_run_as_daemon,
    _configure_logging,
    _with_timestamp_suffix,
    _apply_pid_suffixes,
    _handle_application_build_error,
)
