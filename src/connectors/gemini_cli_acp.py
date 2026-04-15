from __future__ import annotations

import asyncio
import logging
import os
import subprocess
from pathlib import Path
from typing import Any

import httpx

from src.connectors.acp_core.base_connector import BaseAcpConnector
from src.connectors.acp_core.types import ACPNotification, ACPProcessRuntime
from src.connectors.base import add_vendor_prefix, strip_vendor_prefix
from src.core.common.exceptions import BackendError, ConfigurationError
from src.core.config.app_config import AppConfig
from src.core.services.translation_service import TranslationService

from .gemini_base.command_resolution import build_gemini_cli_command
from .gemini_base.config import get_shared_gemini_fallback_models

logger = logging.getLogger(__name__)

ACP_PROTOCOL_VERSION = 1


class GeminiCliAcpConnector(BaseAcpConnector):
    """Gemini CLI backend using Agent Control Protocol over stdio."""

    backend_type: str = "gemini-cli-acp"
    VENDOR_PREFIX: str = "google"
    requires_explicit_workspace: bool = True

    def __init__(
        self,
        client: httpx.AsyncClient,
        config: AppConfig,
        translation_service: TranslationService,
        **_: Any,
    ) -> None:
        super().__init__(config, translation_service=translation_service)
        self.client = client
        self.name = "gemini-cli-acp"
        self._gemini_cli_executable = "gemini"
        self._model = "gemini-2.5-flash"
        self._auto_accept = True

    async def initialize(self, **kwargs: Any) -> None:
        try:
            configured_project_dir = (
                kwargs.get("project_dir")
                or kwargs.get("workspace_path")
                or os.getenv("GEMINI_CLI_WORKSPACE")
            )
            if not configured_project_dir:
                raise ConfigurationError(
                    message=(
                        "gemini-cli-acp requires project_dir, workspace_path, "
                        "or GEMINI_CLI_WORKSPACE (no implicit server cwd default)."
                    ),
                    details={
                        "error_code": "gemini_cli_acp_workspace_required",
                    },
                )
            project_dir = Path(str(configured_project_dir)).resolve()
            if not self._is_usable_directory(project_dir):
                raise ConfigurationError(
                    message=f"Project directory does not exist or is not readable: {configured_project_dir}",
                    details={"project_dir": str(configured_project_dir)},
                )

            self._default_project_dir = project_dir
            self._gemini_cli_executable = str(
                kwargs.get("gemini_cli_executable") or self._gemini_cli_executable
            )
            configured_model = str(kwargs.get("model") or self._model)
            self._model = strip_vendor_prefix(configured_model, self.VENDOR_PREFIX)
            self._auto_accept = bool(kwargs.get("auto_accept", self._auto_accept))
            self._process_timeout = float(
                kwargs.get("process_timeout", self._process_timeout)
            )
            self._idle_timeout = float(kwargs.get("idle_timeout", self._idle_timeout))

            if not await self._check_gemini_cli_available():
                raise ConfigurationError(
                    message=f"gemini-cli executable not found: {self._gemini_cli_executable}",
                    details={
                        "executable": self._gemini_cli_executable,
                        "hint": "Install with: npm install -g @google/gemini-cli",
                    },
                )

            self._validation_errors = []
            self._initialization_failed = False
            self.is_functional = True
        except Exception:
            self._initialization_failed = True
            self.is_functional = False
            self._validation_errors = ["gemini-cli-acp initialization failed"]
            raise

    async def _check_gemini_cli_available(self) -> bool:
        try:
            command = build_gemini_cli_command(
                [self._gemini_cli_executable, "--version"]
            )
            result = await asyncio.to_thread(
                subprocess.run,
                command,
                capture_output=True,
                timeout=5,
                check=False,
                shell=False,
            )
            return result.returncode == 0
        except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
            return False

    async def _build_acp_command(self, runtime: ACPProcessRuntime) -> list[str]:
        cmd = build_gemini_cli_command(
            [
                self._gemini_cli_executable,
                "--experimental-acp",
                "--model",
                runtime.model,
            ]
        )
        if self._auto_accept:
            cmd.append("-y")
        return cmd

    async def _perform_handshake(self, runtime: ACPProcessRuntime) -> None:
        initialize_id = await self._send_jsonrpc_message(
            runtime,
            "initialize",
            {
                "protocolVersion": ACP_PROTOCOL_VERSION,
                "clientCapabilities": {},
                "clientInfo": {
                    "name": "llm-interactive-proxy",
                    "version": "dev",
                },
            },
        )
        initialize_response = await self._await_response(runtime, initialize_id)
        if initialize_response.is_error and initialize_response.error is not None:
            raise BackendError(
                message=f"gemini-cli initialize failed: {initialize_response.error.message}",
                details=initialize_response.error.model_dump(),
            )

        session_new_id = await self._send_jsonrpc_message(
            runtime,
            "session/new",
            {"cwd": str(runtime.project_dir), "mcpServers": []},
        )
        session_new_response = await self._await_response(runtime, session_new_id)
        if session_new_response.is_error and session_new_response.error is not None:
            raise BackendError(
                message=f"gemini-cli session/new failed: {session_new_response.error.message}",
                details=session_new_response.error.model_dump(),
            )

        session_result = session_new_response.result or {}
        session_id = session_result.get("sessionId")
        if not isinstance(session_id, str) or not session_id.strip():
            raise BackendError(
                message="gemini-cli session/new did not return a sessionId",
                details={"result": session_result},
            )

        runtime.session_id = session_id
        runtime.initialized = True

    async def _handle_server_request(
        self, runtime: ACPProcessRuntime, msg: ACPNotification
    ) -> None:
        # gemini-cli-acp historically did not handle server requests
        pass

    def get_available_models(self) -> list[str]:
        raw_models = get_shared_gemini_fallback_models()
        return [add_vendor_prefix(model, self.VENDOR_PREFIX) for model in raw_models]


from src.core.services.backend_registry import backend_registry

backend_registry.register_backend("gemini-cli-acp", GeminiCliAcpConnector)
