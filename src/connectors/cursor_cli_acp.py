"""Cursor CLI backend using Agent Client Protocol (ACP) over stdio JSON-RPC."""

from __future__ import annotations

import asyncio
import logging
import os
import re
import shutil
import subprocess
import time
from collections.abc import Sequence
from pathlib import Path
from typing import Any

import httpx

from src.connectors.acp_core.base_connector import BaseAcpConnector
from src.connectors.acp_core.types import ACPNotification, ACPProcessRuntime
from src.connectors.base import add_vendor_prefix, strip_vendor_prefix
from src.core.common.exceptions import BackendError, ConfigurationError
from src.core.config.app_config import AppConfig
from src.core.services.translation_service import TranslationService

logger = logging.getLogger(__name__)

_ANSI_ESCAPE_RE = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]")

# Fallback when `agent models` cannot be parsed (CLI or auth issues).
_DEFAULT_CURSOR_MODEL_IDS: tuple[str, ...] = (
    "composer-2",
    "composer-2-fast",
    "auto",
    "gpt-5.2",
    "gpt-5.3-codex",
    "claude-4.6-opus-high-thinking",
)

ACP_PROTOCOL_VERSION = 1


def _strip_ansi(text: str) -> str:
    return _ANSI_ESCAPE_RE.sub("", text)


def parse_agent_models_listing(stdout: str) -> list[str]:
    """Parse `agent models` human-readable output into model id strings."""
    models: list[str] = []
    seen: set[str] = set()
    for raw_line in stdout.splitlines():
        line = _strip_ansi(raw_line).strip()
        if not line or line.lower().startswith("loading"):
            continue
        if " - " not in line:
            continue
        left, _right = line.split(" - ", 1)
        model_id = left.strip()
        if not model_id or model_id in seen:
            continue
        if " " in model_id:
            continue
        seen.add(model_id)
        models.append(model_id)
    return models


def resolve_cursor_agent_executable(configured: str | None) -> str | None:
    """Resolve path to Cursor CLI launcher suitable for ``subprocess.Popen`` (no shell)."""
    for candidate in (
        (configured or "").strip(),
        os.environ.get("CURSOR_AGENT_BIN", "").strip(),
    ):
        if not candidate:
            continue
        p = Path(candidate)
        if p.is_file():
            return str(p.resolve())
        resolved = shutil.which(candidate)
        if resolved:
            return resolved
    resolved = shutil.which("agent")
    if resolved:
        return resolved
    if os.name == "nt":
        resolved = shutil.which("agent.cmd")
        if resolved:
            return resolved
    return None


def build_cursor_agent_acp_command(
    executable: str,
    *,
    model: str | None,
    trust_workspace: bool,
    extra_args: Sequence[str] | None,
    cursor_api_endpoint: str | None,
) -> list[str]:
    cmd: list[str] = [executable]
    if cursor_api_endpoint:
        cmd.extend(["-e", cursor_api_endpoint])
    if model:
        cmd.extend(["--model", model])
    if trust_workspace:
        cmd.append("--trust")
    if extra_args:
        cmd.extend(list(extra_args))
    cmd.append("acp")
    return cmd


class CursorCliAcpConnector(BaseAcpConnector):
    """Cursor CLI backend using Agent Client Protocol over stdio."""

    backend_type: str = "cursor-cli-acp"
    VENDOR_PREFIX: str = "cursor"
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
        self.name = "cursor-cli-acp"
        self._cursor_cli_executable: str = "agent"
        self._model = "composer-2"
        self._auto_accept = True
        self._trust_workspace = True
        self._mcp_servers: list[Any] = []
        self._cursor_api_endpoint: str | None = None
        self._extra_cli_args: list[str] = []
        self._cached_models: list[str] = []
        self._models_cache_fetched_at: float = 0.0
        self._models_cache_ttl_seconds: float = 3600.0
        self._extension_response_log: set[str] = set()

    def _ensure_mutable_state(self) -> None:
        if not hasattr(self, "_mcp_servers") or self._mcp_servers is None:
            self._mcp_servers = []

    async def initialize(self, **kwargs: Any) -> None:
        self._ensure_mutable_state()
        try:
            configured_project_dir = (
                kwargs.get("project_dir")
                or kwargs.get("workspace_path")
                or os.getenv("CURSOR_CLI_WORKSPACE")
            )
            if not configured_project_dir:
                raise ConfigurationError(
                    message=(
                        "cursor-cli-acp requires project_dir, workspace_path, "
                        "or CURSOR_CLI_WORKSPACE (no implicit server cwd default)."
                    ),
                    details={
                        "error_code": "cursor_cli_acp_workspace_required",
                    },
                )
            project_dir = Path(str(configured_project_dir)).resolve()
            if not self._is_usable_directory(project_dir):
                raise ConfigurationError(
                    message=(
                        "Project directory does not exist or is not readable: "
                        f"{configured_project_dir}"
                    ),
                    details={"project_dir": str(configured_project_dir)},
                )

            self._default_project_dir = project_dir
            exe_kw = kwargs.get("cursor_cli_executable") or kwargs.get(
                "agent_executable"
            )
            self._cursor_cli_executable = str(exe_kw or self._cursor_cli_executable)
            configured_model = str(kwargs.get("model") or self._model)
            self._model = strip_vendor_prefix(configured_model, self.VENDOR_PREFIX)
            self._auto_accept = bool(kwargs.get("auto_accept", self._auto_accept))
            self._trust_workspace = bool(
                kwargs.get("trust_workspace", self._trust_workspace)
            )
            self._process_timeout = float(
                kwargs.get("process_timeout", self._process_timeout)
            )
            self._idle_timeout = float(kwargs.get("idle_timeout", self._idle_timeout))
            self._models_cache_ttl_seconds = max(
                0.0,
                float(
                    kwargs.get(
                        "cursor_models_cache_ttl_seconds",
                        self._models_cache_ttl_seconds,
                    )
                ),
            )
            mcp = kwargs.get("mcp_servers", [])
            if isinstance(mcp, list):
                self._mcp_servers = mcp
            else:
                self._mcp_servers = []
            endpoint = kwargs.get("cursor_api_endpoint") or kwargs.get(
                "cursor_api_base_url"
            )
            self._cursor_api_endpoint = (
                str(endpoint).strip()
                if isinstance(endpoint, str) and endpoint
                else None
            )
            extra = kwargs.get("cursor_cli_extra_args") or kwargs.get(
                "cursor_extra_cli_args"
            )
            if isinstance(extra, list):
                self._extra_cli_args = [str(x) for x in extra]
            elif isinstance(extra, str) and extra.strip():
                self._extra_cli_args = [extra.strip()]
            else:
                self._extra_cli_args = []

            resolved = resolve_cursor_agent_executable(self._cursor_cli_executable)
            if resolved is None:
                raise ConfigurationError(
                    message="Cursor CLI (agent) executable not found",
                    details={
                        "configured": self._cursor_cli_executable,
                        "hint": "Install Cursor CLI and ensure `agent` is on PATH, "
                        "or set CURSOR_AGENT_BIN to the full path to agent.cmd / agent.",
                    },
                )
            self._cursor_cli_executable = resolved

            if not await self._check_agent_available():
                raise ConfigurationError(
                    message=f"Cursor CLI not callable: {self._cursor_cli_executable}",
                    details={"executable": self._cursor_cli_executable},
                )

            await self._ensure_models_discovered(force=True)
            self._validation_errors = []
            self._initialization_failed = False
            self.is_functional = True
        except Exception:
            self._initialization_failed = True
            self.is_functional = False
            self._validation_errors = ["cursor-cli-acp initialization failed"]
            raise

    async def _check_agent_available(self) -> bool:
        try:
            result = await asyncio.to_thread(
                subprocess.run,
                [self._cursor_cli_executable, "--version"],
                capture_output=True,
                timeout=15,
                check=False,
                shell=False,
            )
            return result.returncode == 0
        except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
            return False

    async def _discover_models(self) -> list[str]:
        try:
            result = await asyncio.to_thread(
                subprocess.run,
                [self._cursor_cli_executable, "models"],
                capture_output=True,
                text=True,
                timeout=60,
                check=False,
                shell=False,
                env=os.environ.copy(),
            )
        except (subprocess.TimeoutExpired, OSError):
            return [
                add_vendor_prefix(m, self.VENDOR_PREFIX)
                for m in _DEFAULT_CURSOR_MODEL_IDS
            ]

        if result.returncode != 0 or not result.stdout:
            return [
                add_vendor_prefix(m, self.VENDOR_PREFIX)
                for m in _DEFAULT_CURSOR_MODEL_IDS
            ]

        raw = parse_agent_models_listing(result.stdout)
        if not raw:
            raw = list(_DEFAULT_CURSOR_MODEL_IDS)
        return [add_vendor_prefix(m, self.VENDOR_PREFIX) for m in raw]

    async def _ensure_models_discovered(self, *, force: bool = False) -> None:
        """Populate ``_cached_models`` by running ``agent models`` (same pipeline as init).

        Skips subprocess when cache is fresh (within TTL) unless ``force`` is True.
        TTL 0 means refresh on every call.
        """
        exe = getattr(self, "_cursor_cli_executable", None)
        if not isinstance(exe, str) or not exe.strip():
            return

        now = time.monotonic()
        if (
            self._cached_models
            and not force
            and self._models_cache_ttl_seconds > 0
            and (now - self._models_cache_fetched_at) < self._models_cache_ttl_seconds
        ):
            return

        self._cached_models = await self._discover_models()
        self._models_cache_fetched_at = now

    async def get_available_models_async(self) -> list[str]:
        """Return model ids with ``cursor/`` prefix, refreshing from CLI when cache is stale.

        Used by :class:`ModelCapabilityIndex` for live enumeration; mirrors
        ``subprocess [agent, models]`` + :func:`parse_agent_models_listing`.
        """
        if self.is_backend_functional():
            await self._ensure_models_discovered(force=False)
        return self.get_available_models()

    def get_available_models(self) -> list[str]:
        if self._cached_models:
            return list(self._cached_models)
        return [
            add_vendor_prefix(m, self.VENDOR_PREFIX) for m in _DEFAULT_CURSOR_MODEL_IDS
        ]

    async def _build_acp_command(self, runtime: ACPProcessRuntime) -> list[str]:
        return build_cursor_agent_acp_command(
            self._cursor_cli_executable,
            model=runtime.model,
            trust_workspace=self._trust_workspace,
            extra_args=self._extra_cli_args,
            cursor_api_endpoint=self._cursor_api_endpoint,
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
                message=f"Cursor CLI initialize failed: {initialize_response.error.message}",
                details=initialize_response.error.model_dump(),
            )

        auth_id = await self._send_jsonrpc_message(
            runtime,
            "authenticate",
            {"methodId": "cursor_login"},
        )
        auth_response = await self._await_response(runtime, auth_id)
        if auth_response.is_error and auth_response.error is not None:
            raise BackendError(
                message=f"Cursor CLI authenticate failed: {auth_response.error.message}",
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
                message=f"Cursor CLI session/new failed: {session_new_response.error.message}",
                details=session_new_response.error.model_dump(),
            )

        session_result = session_new_response.result or {}
        session_id = session_result.get("sessionId")
        if not isinstance(session_id, str) or not session_id.strip():
            raise BackendError(
                message="Cursor CLI session/new did not return a sessionId",
                details={"result": session_result},
            )

        runtime.session_id = session_id
        runtime.initialized = True

    def _permission_option_id(self) -> str:
        if self._auto_accept:
            return "allow-always"
        return "reject-once"

    async def _handle_server_request(
        self, runtime: ACPProcessRuntime, msg: ACPNotification
    ) -> None:
        assert msg.id is not None
        rid = msg.id
        method = msg.method or ""

        if method == "session/request_permission":
            await self._send_jsonrpc_result(
                runtime,
                rid,
                {
                    "outcome": {
                        "outcome": "selected",
                        "optionId": self._permission_option_id(),
                    }
                },
            )
            return

        if method == "cursor/ask_question":
            if method not in self._extension_response_log:
                self._extension_response_log.add(method)
                if logger.isEnabledFor(logging.INFO):
                    logger.info(
                        "ACP extension %s: auto-skipping (headless proxy)", method
                    )
            await self._send_jsonrpc_result(
                runtime,
                rid,
                {"outcome": {"outcome": "skipped", "reason": "proxy_auto_skip"}},
            )
            return

        if method == "cursor/create_plan":
            if method not in self._extension_response_log:
                self._extension_response_log.add(method)
                if logger.isEnabledFor(logging.INFO):
                    logger.info(
                        "ACP extension %s: auto-rejecting (headless proxy)", method
                    )
            await self._send_jsonrpc_result(
                runtime,
                rid,
                {"outcome": {"outcome": "rejected", "reason": "proxy_auto_reject"}},
            )
            return

        if method.startswith("cursor/"):
            if method not in self._extension_response_log:
                self._extension_response_log.add(method)
                if logger.isEnabledFor(logging.WARNING):
                    logger.warning(
                        "Unhandled Cursor ACP extension %s; replying empty result",
                        method,
                    )
            await self._send_jsonrpc_result(runtime, rid, {})
            return

        if logger.isEnabledFor(logging.WARNING):
            logger.warning(
                "Unhandled inbound JSON-RPC request method=%s id=%s; replying error",
                method,
                rid,
            )
        await self._write_json_line(
            runtime,
            {
                "jsonrpc": "2.0",
                "id": rid,
                "error": {"code": -32601, "message": f"Method not handled: {method}"},
            },
        )


from src.core.services.backend_registry import backend_registry

backend_registry.register_backend("cursor-cli-acp", CursorCliAcpConnector)
