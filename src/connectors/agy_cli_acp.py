"""Antigravity CLI (agy) backend via experimental ACP wrapper."""

from __future__ import annotations

import asyncio
import logging
import os
import shutil
import subprocess
from collections.abc import Sequence
from pathlib import Path
from typing import Any

import httpx

from src.connectors.acp_core.base_connector import BaseAcpConnector
from src.connectors.acp_core.types import ACPNotification, ACPProcessRuntime
from src.connectors.acp_core.workspace_policy import resolve_backend_init_acp_workspace
from src.connectors.base import strip_vendor_prefix
from src.core.common.exceptions import BackendError, ConfigurationError
from src.core.config.app_config import AppConfig
from src.core.services.translation_service import TranslationService

logger = logging.getLogger(__name__)

ACP_PROTOCOL_VERSION = 1


def canonicalize_agy_model_id(native_id: str) -> str | None:
    """Collapse an agy-native effort variant into a canonical provider model ID."""
    model = native_id.strip()
    if not model or any(char.isspace() for char in model):
        return None
    for suffix in ("-low", "-medium", "-high"):
        if model.endswith(suffix):
            model = model[: -len(suffix)]
            break
    if model.endswith("-thinking"):
        model = model[: -len("-thinking")]

    if model.startswith("gemini-"):
        return f"google/{model}"
    if model.startswith("claude-"):
        parts = model.split("-")
        for index in range(1, len(parts) - 1):
            if parts[index].isdigit() and parts[index + 1].isdigit():
                parts[index] = f"{parts[index]}.{parts[index + 1]}"
                del parts[index + 1]
                break
        return f"anthropic/{'-'.join(parts)}"
    if model.startswith("gpt-"):
        return f"openai/{model}"
    return None


def parse_agy_models_catalog(stdout: str) -> list[str]:
    """Parse and deduplicate canonical identities from ``agy models`` output."""
    models: list[str] = []
    seen: set[str] = set()
    for line in stdout.splitlines():
        canonical = canonicalize_agy_model_id(line)
        if canonical is None or canonical in seen:
            continue
        seen.add(canonical)
        models.append(canonical)
    return models


def resolve_agy_executable(configured: str | None) -> str | None:
    for candidate in (
        (configured or "").strip(),
        os.environ.get("AGY_BINARY", "").strip(),
        "agy",
        "agy.exe",
        "agy.cmd",
    ):
        if not candidate:
            continue
        path = Path(candidate)
        if path.is_file():
            return str(path.resolve())
        resolved = shutil.which(candidate)
        if resolved:
            return resolved
    return None


def resolve_agy_acp_wrapper_executable(configured: str | None) -> str | None:
    """Resolve go-agy-acp-wrapper binary suitable for subprocess.Popen."""
    for candidate in (
        (configured or "").strip(),
        os.environ.get("AGY_ACP_WRAPPER_BIN", "").strip(),
    ):
        if not candidate:
            continue
        p = Path(candidate)
        if p.is_file():
            return str(p.resolve())
        resolved = shutil.which(candidate)
        if resolved:
            return resolved
    for name in ("go-agy-acp-wrapper", "go-agy-acp-wrapper.exe"):
        resolved = shutil.which(name)
        if resolved:
            return resolved
    return None


def build_agy_acp_wrapper_command(
    executable: str,
    *,
    agy_binary: str | None,
    model: str | None,
    timeout_seconds: int | None,
    skip_permissions: bool,
    extra_args: Sequence[str] | None,
) -> list[str]:
    cmd = [executable]
    if agy_binary:
        cmd.extend(["--agy-binary", agy_binary])
    if model and model != "auto":
        cmd.extend(["--model", model])
    if timeout_seconds is not None and timeout_seconds > 0:
        cmd.extend(["--timeout-seconds", str(timeout_seconds)])
    cmd.append("--skip-permissions" if skip_permissions else "--no-skip-permissions")
    if extra_args:
        cmd.extend(list(extra_args))
    return cmd


class AgyCliAcpConnector(BaseAcpConnector[ACPProcessRuntime]):
    """Experimental Antigravity CLI backend through go-agy-acp-wrapper."""

    backend_type: str = "agy-cli-acp"
    VENDOR_PREFIX: str = "agy"
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
        self.name = "agy-cli-acp"
        self._wrapper_executable = "go-agy-acp-wrapper"
        self._agy_binary: str | None = None
        self._model = "google/gemini-3.5-flash"
        self._configured_models: list[str] = []
        self._skip_permissions = True
        self._mcp_servers: list[Any] = []
        self._extra_wrapper_args: list[str] = []

    async def initialize(self, **kwargs: Any) -> None:
        try:
            workspace, cfg_err = resolve_backend_init_acp_workspace(
                project_dir=kwargs.get("project_dir"),
                workspace_path=kwargs.get("workspace_path"),
                env_workspace=os.getenv("AGY_CLI_WORKSPACE"),
                env_source_label="AGY_CLI_WORKSPACE",
                is_usable=self._is_usable_directory,
            )
            if cfg_err:
                raise ConfigurationError(
                    message=cfg_err,
                    details={"error_code": "agy_cli_acp_workspace_invalid"},
                )
            self._default_project_dir = workspace

            wrapper = kwargs.get("wrapper_executable") or kwargs.get(
                "agy_acp_wrapper_executable"
            )
            self._wrapper_executable = str(wrapper or self._wrapper_executable)
            agy_binary = kwargs.get("agy_binary") or os.environ.get("AGY_BINARY")
            self._agy_binary = str(agy_binary).strip() if agy_binary else None
            configured_model = str(kwargs.get("model") or self._model)
            self._model = strip_vendor_prefix(configured_model, self.VENDOR_PREFIX)
            configured_models = kwargs.get("models")
            self._configured_models = (
                [
                    str(model).strip()
                    for model in configured_models
                    if str(model).strip()
                ]
                if isinstance(configured_models, list)
                else []
            )
            self._skip_permissions = bool(
                kwargs.get("skip_permissions", self._skip_permissions)
            )
            self._process_timeout = float(
                kwargs.get("process_timeout", self._process_timeout)
            )
            self._idle_timeout = float(kwargs.get("idle_timeout", self._idle_timeout))
            mcp = kwargs.get("mcp_servers", [])
            self._mcp_servers = mcp if isinstance(mcp, list) else []
            extra = kwargs.get("wrapper_extra_args") or kwargs.get(
                "agy_acp_wrapper_extra_args"
            )
            if isinstance(extra, list):
                self._extra_wrapper_args = [str(x) for x in extra]
            elif isinstance(extra, str) and extra.strip():
                self._extra_wrapper_args = [extra.strip()]
            else:
                self._extra_wrapper_args = []

            resolved = resolve_agy_acp_wrapper_executable(self._wrapper_executable)
            if resolved is None:
                raise ConfigurationError(
                    message="go-agy-acp-wrapper executable not found",
                    details={
                        "configured": self._wrapper_executable,
                        "hint": "Build go-agy-acp-wrapper and put it on PATH, "
                        "or set AGY_ACP_WRAPPER_BIN / wrapper_executable.",
                    },
                )
            self._wrapper_executable = resolved

            if not await self._check_wrapper_available():
                raise ConfigurationError(
                    message=f"go-agy-acp-wrapper not callable: {self._wrapper_executable}",
                    details={"executable": self._wrapper_executable},
                )

            if not self._configured_models:
                self._configured_models = await self._discover_models()

            self._validation_errors = []
            self._initialization_failed = False
            self.is_functional = True
        except Exception:
            self._initialization_failed = True
            self.is_functional = False
            self._validation_errors = ["agy-cli-acp initialization failed"]
            raise

    async def _discover_models(self) -> list[str]:
        binary = resolve_agy_executable(self._agy_binary)
        if binary is None:
            logger.warning("agy model discovery skipped: agy executable not found")
            return []

        def run_models() -> subprocess.CompletedProcess[str]:
            return subprocess.run(
                [binary, "models"],
                capture_output=True,
                text=True,
                timeout=15,
                check=False,
                shell=False,
            )

        try:
            result = await asyncio.to_thread(run_models)
        except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
            logger.warning("agy model discovery failed", exc_info=True)
            return []
        if result.returncode != 0:
            logger.warning(
                "agy model discovery exited with code %s: %s",
                result.returncode,
                (result.stderr or "").strip(),
            )
            return []
        return parse_agy_models_catalog(result.stdout or "")

    async def _check_wrapper_available(self) -> bool:
        try:
            result = await asyncio.to_thread(
                subprocess.run,
                [self._wrapper_executable, "--version"],
                capture_output=True,
                timeout=10,
                check=False,
                shell=False,
            )
            return result.returncode == 0
        except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
            return False

    async def _build_subprocess_command(self, runtime: ACPProcessRuntime) -> list[str]:
        timeout = int(self._process_timeout) if self._process_timeout > 0 else None
        return build_agy_acp_wrapper_command(
            self._wrapper_executable,
            agy_binary=self._agy_binary,
            model=runtime.model,
            timeout_seconds=timeout,
            skip_permissions=self._skip_permissions,
            extra_args=self._extra_wrapper_args,
        )

    def _create_runtime(
        self, project_dir: Path, model: str, client_session_id: str = "default"
    ) -> ACPProcessRuntime:
        return ACPProcessRuntime(
            project_dir=project_dir,
            model=model,
            client_session_id=client_session_id,
            process_lock=asyncio.Lock(),
            request_lock=asyncio.Lock(),
            cancellation_lock=asyncio.Lock(),
            cancellation_event=asyncio.Event(),
        )

    async def _perform_handshake(self, runtime: ACPProcessRuntime) -> None:
        initialize_id = await self._send_jsonrpc_message(
            runtime,
            "initialize",
            {
                "protocolVersion": ACP_PROTOCOL_VERSION,
                "clientCapabilities": {
                    "fs": {"readTextFile": False, "writeTextFile": False},
                    "terminal": False,
                },
                "clientInfo": {
                    "name": "llm-interactive-proxy",
                    "version": "1",
                },
            },
        )
        initialize_response = await self._await_response(runtime, initialize_id)
        if initialize_response.is_error and initialize_response.error is not None:
            raise BackendError(
                message=f"agy ACP initialize failed: {initialize_response.error.message}",
                details=initialize_response.error.model_dump(),
            )

        auth_id = await self._send_jsonrpc_message(
            runtime,
            "authenticate",
            {"methodId": "agy"},
        )
        auth_response = await self._await_response(runtime, auth_id)
        if auth_response.is_error and auth_response.error is not None:
            raise BackendError(
                message=f"agy ACP authenticate failed: {auth_response.error.message}",
                details=auth_response.error.model_dump(),
            )

        session_new_id = await self._send_jsonrpc_message(
            runtime,
            "session/new",
            {
                "cwd": str(runtime.project_dir),
                "mcpServers": list(self._mcp_servers),
            },
        )
        session_new_response = await self._await_response(runtime, session_new_id)
        if session_new_response.is_error and session_new_response.error is not None:
            raise BackendError(
                message=f"agy ACP session/new failed: {session_new_response.error.message}",
                details=session_new_response.error.model_dump(),
            )

        session_result = session_new_response.result or {}
        session_id = session_result.get("sessionId")
        if not isinstance(session_id, str) or not session_id.strip():
            raise BackendError(
                message="agy ACP session/new did not return a sessionId",
                details={"result": session_result},
            )

        runtime.session_id = session_id
        runtime.initialized = True

    async def _prepare_turn_request_locked(
        self,
        runtime: ACPProcessRuntime,
        request: Any,
    ) -> tuple[int, str]:
        # The effort option is session-scoped, so establish the ACP session before
        # sending session/set_config_option. The base implementation's repeated
        # spawn/initialize calls are idempotent.
        await self._spawn_process(runtime)
        await self._initialize_runtime(runtime)

        effort = getattr(request.request, "reasoning_effort", None)
        if not effort:
            extra_body = getattr(request.request, "extra_body", None)
            if isinstance(extra_body, dict):
                effort = extra_body.get("reasoning_effort")
        if isinstance(effort, str) and effort.strip():
            config_id = await self._send_jsonrpc_message(
                runtime,
                "session/set_config_option",
                {
                    "sessionId": runtime.session_id,
                    "configId": "reasoning_effort",
                    "value": effort.strip().lower(),
                },
            )
            response = await self._await_response(runtime, config_id)
            if response.is_error and response.error is not None:
                raise BackendError(
                    message=f"agy ACP reasoning effort failed: {response.error.message}",
                    details=response.error.model_dump(),
                )
        return await super()._prepare_turn_request_locked(runtime, request)

    async def _handle_server_request(
        self, runtime: ACPProcessRuntime, msg: ACPNotification
    ) -> None:
        assert msg.id is not None
        method = msg.method or ""
        if method.startswith("agy/"):
            if logger.isEnabledFor(logging.WARNING):
                logger.warning(
                    "Unhandled agy ACP extension %s; replying empty result",
                    method,
                )
            await self._send_jsonrpc_result(runtime, msg.id, {})
            return
        await self._write_json_line(
            runtime,
            {
                "jsonrpc": "2.0",
                "id": msg.id,
                "error": {"code": -32601, "message": f"Method not handled: {method}"},
            },
        )

    def get_available_models(self) -> list[str]:
        return list(self._configured_models)


from src.core.services.backend_registry import backend_registry

backend_registry.register_backend("agy-cli-acp", AgyCliAcpConnector)
