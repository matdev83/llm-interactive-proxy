"""
Server Lifecycle Manager service.

This module handles server port checking, daemonization, and server startup coordination.
It isolates these system-level operations from the main CLI entry point.
"""

import argparse
import asyncio
import errno
import logging
import os
import socket
import sys
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import TYPE_CHECKING

import uvicorn
from fastapi import FastAPI

from src.anthropic_server import create_anthropic_app_async
from src.core.cli_support.error_handler import ErrorHandler
from src.core.cli_support.logging_configurator import LoggingConfigurator
from src.core.cli_support.privilege_checker import PrivilegeChecker
from src.core.cli_support.protocols import (
    ErrorHandlerProtocol,
    LoggingConfiguratorProtocol,
    PrivilegeCheckerProtocol,
)
from src.core.common.uvicorn_logging import get_uvicorn_logging_config
from src.core.config.app_config import AppConfig
from src.core.interfaces.access_mode_validator_interface import IAccessModeValidator

if TYPE_CHECKING:
    from src.core.config.parameter_resolution import ParameterResolution

logger = logging.getLogger(__name__)


class ServerLifecycleManager:
    """Manages server lifecycle events including port checks, daemonization, and startup."""

    def __init__(
        self,
        *,
        privilege_checker: PrivilegeCheckerProtocol | None = None,
        logging_configurator: LoggingConfiguratorProtocol | None = None,
        error_handler: ErrorHandlerProtocol | None = None,
        access_mode_validator: IAccessModeValidator | None = None,
        build_app_async_fn: Callable[[AppConfig], Awaitable[FastAPI]] | None = None,
    ) -> None:
        from src.core.app.application_builder import build_app_async
        from src.core.services.access_mode_validator import AccessModeValidator

        self._privilege_checker = privilege_checker or PrivilegeChecker()
        self._logging_configurator = logging_configurator or LoggingConfigurator()
        self._error_handler = error_handler or ErrorHandler()
        self._access_mode_validator = access_mode_validator or AccessModeValidator()
        self._build_app_async_fn = build_app_async_fn or build_app_async

    async def run(
        self,
        args: argparse.Namespace,
        cfg: AppConfig,
        *,
        resolution: "ParameterResolution | None" = None,
        build_app_fn: Callable[[AppConfig], FastAPI] | None = None,
        enforce_localhost_fn: Callable[[AppConfig], AppConfig] | None = None,
    ) -> None:
        """Coordinate startup steps and run servers (Requirement 2.1)."""
        cfg = self._logging_configurator.apply_pid_suffixes(cfg)

        if self.handle_daemon_mode(args, cfg):
            return

        try:
            self._logging_configurator.configure(cfg)
        except Exception as exc:
            raise ValueError(f"Logging configuration failed: {exc}") from exc

        startup_params = self._resolve_startup_params(args)
        logger.info("CLI startup params: %s", startup_params)

        # Log access mode at INFO level (Requirement 1.5)
        access_mode = cfg.access_mode.mode.value
        mode_display = access_mode.replace("_", " ").title()
        logger.info(f"Starting LLM Proxy in {mode_display} Mode")

        # Log Quality Verifier configuration at startup (helps confirm it is enabled).
        try:
            qv_model = getattr(cfg.session, "quality_verifier_model", None)
            if qv_model:
                logger.info(
                    "Quality Verifier enabled (model=%s frequency=%s)",
                    qv_model,
                    getattr(cfg.session, "quality_verifier_frequency", 10),
                )
            else:
                if logger.isEnabledFor(logging.DEBUG):
                    logger.debug("Quality Verifier disabled (no model configured)")
        except Exception:
            # Fail-open: logging only.
            pass

        if resolution is not None:
            resolution.log(logging.getLogger("config.resolution"), cfg)

        self._privilege_checker.check_privileges(
            allow_admin=bool(getattr(args, "allow_admin", False))
        )

        # Validate access mode rules (Requirement 2.1-2.4, 5.1-5.6, 7.1-7.4, 8.1-8.3, 9.1-9.5)
        try:
            self._access_mode_validator.validate(cfg, args)
        except ValueError as exc:
            self._error_handler.handle_build_error(str(exc))
            raise SystemExit(1) from exc

        if enforce_localhost_fn is not None:
            cfg = enforce_localhost_fn(cfg)

        try:
            if build_app_fn is not None:
                app = build_app_fn(cfg)
            else:
                app = await self._build_app_async_fn(cfg)
        except RuntimeError as exc:
            self._error_handler.handle_build_error(str(exc))
            raise SystemExit(1) from exc
        except SystemExit:
            raise
        except Exception as exc:
            self._error_handler.handle_exception(exc)
            raise SystemExit(1) from exc

        if cfg.auth.trusted_ips:
            logging.info(
                "Trusted IPs configured for bypassing authorization: %s",
                ", ".join(cfg.auth.trusted_ips),
            )

        self.check_ports(cfg)
        await self.start_servers(app, cfg)

    @staticmethod
    def _resolve_startup_params(args: argparse.Namespace) -> list[str]:
        """Resolve startup CLI parameters for startup logging."""
        raw_params = getattr(args, "_raw_cli_params", None)
        if isinstance(raw_params, list | tuple):
            return [str(param) for param in raw_params]

        return [str(param) for param in sys.argv[1:]]

    def is_port_in_use(self, host: str, port: int) -> bool:
        """Check if a port is in use on a given host."""
        if host in {"0.0.0.0", "::", ""}:
            return self._is_port_in_use_wildcard(host, port)

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

    def _is_port_in_use_wildcard(self, host: str, port: int) -> bool:
        """Check port availability for wildcard bind addresses.

        Connecting to wildcard addresses like 0.0.0.0 is not meaningful; instead,
        probe by attempting to bind and detecting address-in-use errors.
        """

        def _bind_probe(family: int, sockaddr: object) -> bool:
            try:
                with socket.socket(family, socket.SOCK_STREAM) as sock:
                    sock.bind(sockaddr)  # type: ignore[arg-type]
                return False
            except OSError as exc:
                winerror = getattr(exc, "winerror", None)
                if exc.errno == errno.EADDRINUSE or winerror == 10048:
                    return True

                logger.debug(
                    "Wildcard port bind probe failed for %s:%s using family %s: %s",
                    host,
                    port,
                    family,
                    exc,
                )
                return False

        in_use = False

        if host in {"0.0.0.0", ""}:
            in_use = in_use or _bind_probe(socket.AF_INET, ("0.0.0.0", port))

        if host in {"::", ""}:
            in_use = in_use or _bind_probe(socket.AF_INET6, ("::", port))

        return in_use

    def daemonize(self) -> None:
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
            # On Windows, we can't daemonize in this way
            pass

    def handle_daemon_mode(self, args: argparse.Namespace, cfg: AppConfig) -> bool:
        """
        Handle daemon mode if requested.

        Returns:
            True if the process should exit (because it spawned a daemon),
            False if normal execution should continue.
        """
        if not args.daemon:
            return False

        if not cfg.logging.log_file:
            sys.exit("--log must be specified when running in daemon mode.")

        if os.name == "nt":
            import subprocess
            import time

            daemon_process = None
            try:
                args_list: list[str] = [
                    arg for arg in sys.argv[1:] if not arg.startswith("--daemon")
                ]
                command: list[str] = [sys.executable, "-m", "src.core.cli", *args_list]
                creation_flags = getattr(subprocess, "DETACHED_PROCESS", 0)
                daemon_process = subprocess.Popen(
                    command,
                    creationflags=creation_flags,
                    close_fds=True,
                    shell=False,
                )

                if daemon_process.poll() is not None:
                    self._error_handler.handle_build_error(
                        "Failed to start daemon process"
                    )
                    raise SystemExit(1)

                time.sleep(2)
                sys.exit(0)
                # This line is unreachable but keeps static analysis happy about return type consistency
                return True
            except Exception as e:
                logger.warning(
                    "Failed to daemonize process, attempting cleanup: %s",
                    e,
                    exc_info=True,
                )
                # Cleanup daemon process on any exception to prevent resource leaks
                # This handles cases where unexpected errors occur between Popen and poll
                if daemon_process is not None and daemon_process.poll() is None:
                    try:
                        daemon_process.terminate()
                        try:
                            daemon_process.wait(timeout=5)
                        except subprocess.TimeoutExpired:
                            daemon_process.kill()
                            daemon_process.wait(timeout=5)
                    except Exception as cleanup_err:
                        logger.warning(
                            "Failed to cleanup daemon process: %s",
                            cleanup_err,
                            exc_info=True,
                        )
                raise

        self.daemonize()

        return False

    def check_ports(self, cfg: AppConfig) -> None:
        """
        Verify that required ports are available.
        Exits the application if ports are in use.
        """
        # Check if port is already in use
        if self.is_port_in_use(cfg.host, cfg.port):
            error_msg = f"Port {cfg.port} is already in use."
            self._error_handler.handle_build_error(error_msg)
            raise SystemExit(1)

        # Check if Anthropic port is already in use
        if cfg.anthropic_port and self.is_port_in_use(cfg.host, cfg.anthropic_port):
            error_msg = f"Anthropic Port {cfg.anthropic_port} is already in use."
            self._error_handler.handle_build_error(error_msg)
            raise SystemExit(1)

    async def start_servers(self, app: FastAPI, cfg: AppConfig) -> None:
        """
        Start the Uvicorn servers.

        Args:
            app: The built FastAPI application.
            cfg: The application configuration.
        """
        logging.info(f"Starting uvicorn on {cfg.host}:{cfg.port}")

        servers = []

        uvicorn_log_file = None
        if cfg.logging.log_file:
            # Write Uvicorn logs to the same file as application logs.
            # This matches user expectation for --log/logging.log_file to contain the full story
            # (access + uvicorn + application diagnostics).
            uvicorn_log_file = cfg.logging.log_file
            Path(uvicorn_log_file).parent.mkdir(parents=True, exist_ok=True)

        # Main server
        main_config = uvicorn.Config(
            app,
            host=cfg.host,
            port=cfg.port,
            log_config=get_uvicorn_logging_config(
                use_colors=cfg.logging.use_colors,
                log_level=getattr(getattr(cfg.logging, "level", None), "value", "INFO"),
                log_file=uvicorn_log_file,
                console_stream=getattr(cfg.logging, "console_stream", "stderr"),
            ),
        )
        main_server = uvicorn.Server(main_config)
        servers.append(main_server.serve())

        # Anthropic server
        if cfg.anthropic_port:
            logging.info(
                f"Starting Anthropic server on {cfg.host}:{cfg.anthropic_port}"
            )
            # Reuse the main app to avoid double initialization of services
            anthropic_app = await create_anthropic_app_async(cfg, built_app=app)
            anthropic_config = uvicorn.Config(
                anthropic_app,
                host=cfg.host,
                port=cfg.anthropic_port,
                log_config=get_uvicorn_logging_config(
                    use_colors=cfg.logging.use_colors,
                    log_level=getattr(
                        getattr(cfg.logging, "level", None), "value", "INFO"
                    ),
                    log_file=uvicorn_log_file,
                    console_stream=getattr(cfg.logging, "console_stream", "stderr"),
                ),
            )
            anthropic_server = uvicorn.Server(anthropic_config)
            servers.append(anthropic_server.serve())

        try:
            await asyncio.gather(*servers)
        except KeyboardInterrupt:
            # Allow clean exit on Ctrl+C
            if logger.isEnabledFor(logging.INFO):
                logger.info("Server interrupted by user (Ctrl+C)")
        except Exception as e:
            logging.exception("Server failed: %s", e)
            raise
