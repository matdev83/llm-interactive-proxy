"""
Server Lifecycle Manager service.

This module handles server port checking, daemonization, and server startup coordination.
It isolates these system-level operations from the main CLI entry point.
"""

import argparse
import asyncio
import logging
import os
import socket
import sys

import uvicorn
from fastapi import FastAPI

from src.anthropic_server import create_anthropic_app_async
from src.core.common.uvicorn_logging import get_uvicorn_logging_config
from src.core.config.app_config import AppConfig

logger = logging.getLogger(__name__)


class ServerLifecycleManager:
    """Manages server lifecycle events including port checks, daemonization, and startup."""

    def is_port_in_use(self, host: str, port: int) -> bool:
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

    def _daemonize(self) -> None:
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

            args_list: list[str] = [
                arg for arg in sys.argv[1:] if not arg.startswith("--daemon")
            ]
            command: list[str] = [sys.executable, "-m", "src.core.cli", *args_list]
            creation_flags = getattr(subprocess, "DETACHED_PROCESS", 0)
            subprocess.Popen(command, creationflags=creation_flags, close_fds=True)
            time.sleep(2)
            sys.exit(0)
            # This line is unreachable but keeps static analysis happy about return type consistency
            return True

        self._daemonize()
        return False

    def check_ports(self, cfg: AppConfig) -> None:
        """
        Verify that required ports are available.
        Exits the application if ports are in use.
        """
        # Check if port is already in use
        if self.is_port_in_use(cfg.host, cfg.port):
            error_msg = f"Port {cfg.port} is already in use."
            logger.error(error_msg)
            sys.stderr.write(f"\nERROR: {error_msg}\n")
            sys.exit(1)

        # Check if Anthropic port is already in use
        if cfg.anthropic_port and self.is_port_in_use(cfg.host, cfg.anthropic_port):
            error_msg = f"Anthropic Port {cfg.anthropic_port} is already in use."
            logger.error(error_msg)
            sys.stderr.write(f"\nERROR: {error_msg}\n")
            sys.exit(1)

    async def start_servers(self, app: FastAPI, cfg: AppConfig) -> None:
        """
        Start the Uvicorn servers.

        Args:
            app: The built FastAPI application.
            cfg: The application configuration.
        """
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
                    use_colors=cfg.logging.use_colors
                ),
            )
            anthropic_server = uvicorn.Server(anthropic_config)
            servers.append(anthropic_server.serve())

        try:
            await asyncio.gather(*servers)
        except KeyboardInterrupt:
            # Allow clean exit on Ctrl+C
            pass
        except Exception as e:
            logging.exception("Server failed: %s", e)
            raise
