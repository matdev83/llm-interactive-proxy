"""
Simplified CLI implementation using staged initialization.

This demonstrates how the new architecture dramatically simplifies
the main application entry point by hiding complexity in the staged
initialization pattern.
"""

import argparse
import logging
import os
from collections.abc import Callable

import colorama
import uvicorn
from fastapi import FastAPI

from src.core.app.application_builder import ApplicationBuilder, build_app
from src.core.config.app_config import AppConfig, LogLevel, load_config


def parse_cli_args(argv: list[str] | None = None) -> argparse.Namespace:
    """Parse command line arguments - much simpler than the original."""
    parser = argparse.ArgumentParser(description="Run the LLM proxy server")

    # Basic server options
    parser.add_argument("--host", default="localhost", help="Host to bind to")
    parser.add_argument("--port", type=int, default=8000, help="Port to bind to")
    parser.add_argument("--timeout", type=int, help="Request timeout in seconds")

    # Configuration options
    parser.add_argument(
        "--config", dest="config_file", help="Path to configuration file"
    )
    parser.add_argument("--command-prefix", help="Command prefix for in-chat commands")

    # Logging options
    parser.add_argument("--log", dest="log_file", help="Write logs to FILE")
    parser.add_argument(
        "--log-level",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        default="INFO",
        help="Set logging level",
    )

    # Security options
    parser.add_argument(
        "--disable-auth",
        action="store_true",
        help="Disable authentication (forces localhost)",
    )

    # Process options
    parser.add_argument(
        "--daemon", action="store_true", help="Run as daemon (requires --log)"
    )

    return parser.parse_args(argv)


def apply_cli_args(args: argparse.Namespace) -> AppConfig:
    """Apply CLI arguments to configuration - simplified logic."""
    # Load base config
    if args.config_file:
        cfg = load_config(args.config_file)
    else:
        cfg = AppConfig.from_env()

    # Apply CLI overrides
    if args.host:
        cfg.host = args.host
    if args.port:
        cfg.port = args.port
    if args.timeout:
        cfg.proxy_timeout = args.timeout
    if args.command_prefix:
        cfg.command_prefix = args.command_prefix
    if args.log_file:
        cfg.logging.log_file = args.log_file
    if args.log_level:
        cfg.logging.level = LogLevel[args.log_level]

    # Security: force localhost when auth is disabled
    if args.disable_auth:
        cfg.auth.disable_auth = True
        if cfg.host != "127.0.0.1":
            logging.warning(
                f"Auth disabled, forcing host to 127.0.0.1 (was: {cfg.host})"
            )
            cfg.host = "127.0.0.1"

    return cfg


def configure_logging(config: AppConfig) -> None:
    """Configure logging based on configuration."""
    logging.basicConfig(
        level=getattr(logging, config.logging.level.value),
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        filename=config.logging.log_file,
    )


def handle_daemon_mode(args: argparse.Namespace) -> bool:
    """Handle daemon mode if requested. Returns True if we should exit."""
    if not args.daemon:
        return False

    if not args.log_file:
        raise SystemExit("--log must be specified when running in daemon mode.")

    if os.name == "nt":
        # Windows daemon mode
        import subprocess
        import time

        # Remove --daemon from args and restart
        args_list = [arg for arg in sys.argv[1:] if not arg.startswith("--daemon")]
        command = [sys.executable, "-m", "src.core.cli_v2", *args_list]
        subprocess.Popen(
            command, creationflags=subprocess.DETACHED_PROCESS, close_fds=True
        )
        time.sleep(2)
        return True
    else:
        # Unix daemon mode - only available on Unix systems
        if hasattr(os, "fork") and callable(os.fork):
            if os.fork() > 0:
                sys.exit(0)  # exit first parent
        else:
            # Not available on Windows
            raise NotImplementedError("Daemon mode not supported on this platform")

        os.chdir("/")
        # setsid is not available on Windows
        if hasattr(os, "setsid"):
            os.setsid()  # type: ignore[attr-defined]
        os.umask(0)

        if hasattr(os, "fork") and callable(os.fork):
            if os.fork() > 0:
                sys.exit(0)  # exit second parent
        else:
            # Not available on Windows
            raise NotImplementedError("Daemon mode not supported on this platform")

    return False


def main(
    argv: list[str] | None = None,
    build_app_fn: Callable[[AppConfig], FastAPI] | None = None,
) -> None:
    """
    Main entry point - dramatically simplified compared to the original.

    The complexity of service initialization is now hidden in the staged
    initialization pattern, making this function clean and focused on
    CLI concerns only.
    """
    # Initialize colorama on Windows
    if os.name == "nt":
        colorama.init()

    # Parse arguments and load configuration
    args = parse_cli_args(argv)
    config = apply_cli_args(args)

    # Handle daemon mode early
    if handle_daemon_mode(args):
        return

    # Configure logging
    configure_logging(config)

    # Build application - this is now a single, clean call!
    # All the complex dependency injection and service registration
    # is handled by the ApplicationBuilder behind the scenes
    if build_app_fn:
        app = build_app_fn(config)  # For testing
    else:
        app = build_app(config)  # Production

    # Run the server
    logging.info(f"Starting server on {config.host}:{config.port}")
    uvicorn.run(app, host=config.host, port=config.port)


if __name__ == "__main__":
    import sys

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
        .add_stage(CoreServicesStage())
        .add_stage(InfrastructureStage())
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
        .add_stage(CoreServicesStage())
        .add_stage(InfrastructureStage())
        .add_stage(MockBackendStage())  # Mock backends instead of real ones
        .add_stage(CommandStage())
        .add_stage(ProcessorStage())
        .add_stage(ControllerStage())
    )

    return asyncio.run(builder.build(config))


def main_dev() -> None:
    """Development entry point with dev-specific app builder."""
    main(build_app_fn=build_development_app)


def main_test() -> None:
    """Test entry point with test-specific app builder."""
    main(build_app_fn=build_test_app)


"""
COMPARISON: Original vs New CLI

ORIGINAL CLI (complex):
- 327 lines of complex initialization logic
- Manual dependency ordering and service registration
- Complex global state management
- Difficult to customize for different environments
- Hard to test due to tightly coupled initialization

NEW CLI (simple):
- ~150 lines focused on CLI concerns only
- All complexity hidden in ApplicationBuilder
- Easy to customize with different stages
- Simple to test with mock stages
- Clear separation of concerns

BENEFITS:
1. Maintainability: CLI logic is focused and clear
2. Testability: Easy to inject test-specific builders
3. Flexibility: Easy to create environment-specific variants
4. Debugging: Clear separation between CLI and app initialization
5. Onboarding: New developers can understand CLI logic immediately
"""
