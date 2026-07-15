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
from typing import Any, cast

import httpx

from src.connectors.acp_core.base_connector import BaseAcpConnector
from src.connectors.acp_core.transcript import ACPTranscriptSerializer
from src.connectors.acp_core.types import (
    ACPNotification,
    ACPProcessRuntime,
    HistoryState,
)
from src.connectors.acp_core.workspace_policy import (
    first_workspace_hint_str,
    resolve_backend_init_acp_workspace,
)
from src.connectors.base import add_vendor_prefix, strip_vendor_prefix
from src.connectors.contracts import ConnectorChatCompletionsRequest
from src.core.common.exceptions import BackendError, ConfigurationError
from src.core.config.app_config import AppConfig
from src.core.domain.chat import ChatMessage
from src.core.domain.responses_native_wiring import (
    ACP_RESPONSES_STANDALONE_MODE_KEY,
    ACP_RESPONSES_TEXT_ONLY_MODE_KEY,
)
from src.core.services.translation_service import TranslationService

logger = logging.getLogger(__name__)

_ANSI_ESCAPE_RE = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]")

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


def parse_cursor_acp_models_result(result: object) -> list[str]:
    """Extract model identifiers returned by Cursor's ACP capability method.

    ``cursor/list_available_models`` has had more than one result shape in
    Cursor Agent releases.  Keep parsing deliberately limited to identifier
    fields from the capability response; display names or the standalone
    ``agent models`` output are not treated as ACP capabilities.
    """

    if not isinstance(result, dict):
        return []

    values: list[object] = []
    for key in ("models", "availableModels", "modelIds", "available_models"):
        candidate = result.get(key)
        if isinstance(candidate, list):
            values.extend(candidate)

    models: list[str] = []
    seen: set[str] = set()
    for value in values:
        raw_id: object
        if isinstance(value, str):
            raw_id = value
        elif isinstance(value, dict):
            raw_id = next(
                (
                    value.get(key)
                    for key in ("id", "modelId", "model_id")
                    if isinstance(value.get(key), str)
                ),
                None,
            )
        else:
            continue

        if not isinstance(raw_id, str):
            continue
        model_id = raw_id.strip()
        if not model_id or any(char.isspace() for char in model_id):
            continue
        normalized = add_vendor_prefix(
            strip_vendor_prefix(model_id, "cursor"),
            "cursor",
        )
        if normalized in seen:
            continue
        seen.add(normalized)
        models.append(normalized)
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
    mode: str | None = None,
) -> list[str]:
    cmd: list[str] = [executable]
    if cursor_api_endpoint:
        cmd.extend(["-e", cursor_api_endpoint])
    if model:
        cmd.extend(["--model", model])
    if mode:
        cmd.extend(["--mode", mode])
    if trust_workspace:
        cmd.append("--trust")
    if extra_args:
        cmd.extend(list(extra_args))
    cmd.append("acp")
    return cmd


class CursorCliAcpConnector(BaseAcpConnector[ACPProcessRuntime]):
    """Cursor CLI backend using Agent Client Protocol over stdio."""

    backend_type: str = "cursor-cli-acp"
    VENDOR_PREFIX: str = "cursor"
    # Cursor's CLI process is authenticated once and then reused across proxy
    # request/session identifiers.  Those identifiers are B2BUA attempt ids,
    # not Cursor conversation identities.
    requires_explicit_workspace: bool = False

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
        if not hasattr(self, "_mcp_servers"):
            self._mcp_servers = []

    async def initialize(self, **kwargs: Any) -> None:
        self._ensure_mutable_state()
        try:
            workspace, cfg_err = resolve_backend_init_acp_workspace(
                project_dir=kwargs.get("project_dir"),
                workspace_path=kwargs.get("workspace_path"),
                env_workspace=os.getenv("CURSOR_CLI_WORKSPACE"),
                env_source_label="CURSOR_CLI_WORKSPACE",
                is_usable=self._is_usable_directory,
            )
            if cfg_err:
                raise ConfigurationError(
                    message=cfg_err,
                    details={"error_code": "cursor_cli_acp_workspace_invalid"},
                )
            if workspace is None:  # pyright: ignore[reportUnnecessaryComparison]
                raise ConfigurationError(
                    message=(
                        "cursor-cli-acp requires an explicit absolute workspace path "
                        "via project_dir, workspace_path, or CURSOR_CLI_WORKSPACE"
                    ),
                    details={"error_code": "cursor_cli_acp_workspace_required"},
                )
            self._default_project_dir = workspace
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
        """Discover models accepted by the running Cursor ACP server.

        The human-readable ``agent models`` command describes the normal CLI
        surface and may include models that ACP rejects.  Probe ACP itself so
        the catalog never advertises a route that fails only at turn startup.
        """

        workspace = getattr(self, "_default_project_dir", None)
        if not isinstance(workspace, Path):
            logger.warning("Cursor ACP model discovery skipped without workspace")
            return []

        runtime = self._create_runtime(workspace, "", "model-discovery")
        runtime.responses_text_only_mode = True
        try:
            await self._spawn_process(runtime)

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
                        "name": "llm-interactive-proxy-model-discovery",
                        "version": "1",
                    },
                },
            )
            initialize_response = await self._await_response(runtime, initialize_id)
            if initialize_response.is_error:
                logger.warning(
                    "Cursor ACP initialize failed during model discovery: %s",
                    initialize_response.error,
                )
                return []

            session_new_id = await self._send_jsonrpc_message(
                runtime,
                "session/new",
                {
                    "cwd": str(runtime.project_dir),
                    "mcpServers": list(self._mcp_servers),
                },
            )
            session_new_response = await self._await_response(runtime, session_new_id)
            if session_new_response.is_error:
                logger.warning(
                    "Cursor ACP session/new failed during model discovery: %s",
                    session_new_response.error,
                )
                return []
            session_result = session_new_response.result or {}
            session_id = session_result.get("sessionId")

            list_models_id = await self._send_jsonrpc_message(
                runtime,
                "cursor/list_available_models",
                {"sessionId": session_id} if isinstance(session_id, str) else {},
            )
            models_response = await self._await_response(runtime, list_models_id)
            if models_response.is_error:
                logger.warning(
                    "Cursor ACP model capability request failed: %s",
                    models_response.error,
                )
                return []
            return parse_cursor_acp_models_result(models_response.result)
        except Exception:
            logger.warning("Cursor ACP capability discovery failed", exc_info=True)
            return []
        finally:
            # Discovery is a short-lived capability probe, never a pooled
            # conversation.  Always reap it, including startup/protocol errors.
            await self._kill_runtime(runtime)

    async def _ensure_models_discovered(self, *, force: bool = False) -> None:
        """Populate ``_cached_models`` via a live ACP capability probe.

        Skips subprocess when cache is fresh (within TTL) unless ``force`` is True.
        TTL 0 means refresh on every call.
        """
        exe = getattr(self, "_cursor_cli_executable", None)
        if not isinstance(exe, str) or not exe.strip():
            return

        now = time.monotonic()
        # ``_models_cache_fetched_at`` is the discovery-attempt sentinel.  It
        # is updated even when the CLI returns no models or fails, so an empty
        # result is cached for the same TTL as a successful result.  Checking
        # ``_cached_models`` here would retry a failing discovery on every
        # request and can block callers for the full subprocess timeout.
        if (
            self._models_cache_fetched_at > 0
            and not force
            and self._models_cache_ttl_seconds > 0
            and (now - self._models_cache_fetched_at) < self._models_cache_ttl_seconds
        ):
            return

        try:
            self._cached_models = await self._discover_models()
        except Exception:
            # A failed capability probe is a negative discovery result.  Cache
            # it for the configured TTL so every request does not launch a
            # subprocess that can block for the full discovery timeout.
            logger.warning(
                "Cursor ACP model discovery failed; caching an empty result",
                exc_info=True,
            )
            self._cached_models = []
        self._models_cache_fetched_at = time.monotonic()

    async def get_available_models_async(self) -> list[str]:
        """Return ACP-accepted model ids, refreshing the capability cache."""
        if self.is_backend_functional():
            await self._ensure_models_discovered(force=False)
        return self.get_available_models()

    def get_available_models(self) -> list[str]:
        return list(self._cached_models)

    async def _acquire_runtime(
        self, request: ConnectorChatCompletionsRequest
    ) -> ACPProcessRuntime:
        await self._ensure_models_discovered(force=False)
        requested_model = strip_vendor_prefix(
            request.effective_model or self._model,
            self.VENDOR_PREFIX,
        )
        advertised = add_vendor_prefix(requested_model, self.VENDOR_PREFIX)
        if advertised not in self._cached_models:
            raise BackendError(
                message=f"Cursor ACP model is not currently available: {advertised}",
                details={
                    "code": "cursor_model_unavailable",
                    "requested_model": advertised,
                },
            )
        return await super()._acquire_runtime(request)

    def _resolve_project_dir_for_request(
        self, request: ConnectorChatCompletionsRequest
    ) -> Path:
        extra_body: object = getattr(request.request, "extra_body", None)
        extra_dict = cast(dict[str, Any] | None, extra_body)
        options = cast(dict[str, Any] | None, request.options)
        hint = first_workspace_hint_str(extra_dict, options)
        if hint is not None:
            raise BackendError(
                message=(
                    "cursor-cli-acp does not accept per-request workspace selection; "
                    "configure one trusted absolute workspace for this backend instance"
                ),
                details={"code": "cursor_cli_acp_dynamic_workspace_forbidden"},
            )
        if self._default_project_dir is None:
            raise ConfigurationError(
                message="cursor-cli-acp has no trusted workspace configured"
            )
        return self._default_project_dir

    def _build_runtime_key(
        self,
        project_dir: Path,
        model: str,
        client_session_id: str,
        *,
        responses_text_only: bool = False,
    ) -> tuple[str, str, str]:
        """Reuse one Cursor child per workspace/model and execution mode."""
        mode_key = (
            f"responses-text-only:{client_session_id}"
            if responses_text_only
            else "default"
        )
        return super()._build_runtime_key(project_dir, model, mode_key)

    def _is_responses_text_only_request(
        self, request: ConnectorChatCompletionsRequest
    ) -> bool:
        extra_body = getattr(request.request, "extra_body", None)
        return bool(
            isinstance(extra_body, dict)
            and extra_body.get(ACP_RESPONSES_TEXT_ONLY_MODE_KEY) is True
        )

    def _resolve_client_session_id(
        self, request: ConnectorChatCompletionsRequest
    ) -> str:
        extra_body = getattr(request.request, "extra_body", None)
        if (
            isinstance(extra_body, dict)
            and extra_body.get(ACP_RESPONSES_TEXT_ONLY_MODE_KEY) is True
        ):
            raw = getattr(request.request, "session_id", None)
            if isinstance(raw, str) and raw.strip():
                return raw.strip()
        return super()._resolve_client_session_id(request)

    async def _compute_history_and_user_message(
        self,
        runtime: ACPProcessRuntime,
        messages: Sequence[Any],
    ) -> tuple[str, HistoryState]:
        """Keep the pre-session-isolation Cursor transcript behavior.

        Cursor's ACP child is shared across proxy request/session identifiers;
        send the full transcript only when that child is first started, then
        send the latest user message on subsequent turns.  The generic ACP
        divergence reset would otherwise restart Cursor and re-authenticate it
        whenever a new B2BUA attempt has a different message prefix.
        """
        if runtime.history_state is None:
            return (
                ACPTranscriptSerializer.serialize(messages),
                HistoryState(message_count=len(messages), prefix_hash="cursor-shared"),
            )

        latest_user_message = self._extract_user_message_as_string(messages)
        instruction_lines: list[str] = []
        for message in messages:
            if isinstance(message, ChatMessage):
                role = message.role
                content = message.content
            elif isinstance(message, dict):
                role = str(message.get("role", ""))
                content = message.get("content")
            else:
                role = str(getattr(message, "role", ""))
                content = getattr(message, "content", "")

            if role.casefold() not in {"system", "developer"}:
                continue
            instruction = self._stringify_message_content(content).strip()
            if instruction:
                instruction_lines.append(
                    f"**{role.capitalize()} instruction:** {instruction}"
                )

        if instruction_lines:
            # Cursor's ACP continuation API accepts one prompt string and does
            # not receive the canonical ``system_prompt`` field. Re-send the
            # current instruction prefix with each incremental turn so a new
            # Responses ``instructions`` value is honored by the existing
            # subprocess conversation.
            prompt = (
                "[System Note: Apply these current instructions for this turn. "
                "They override any earlier instructions.]\n\n"
                + "\n".join(instruction_lines)
                + "\n\n[Current Request]\n"
                + latest_user_message
            )
        else:
            prompt = latest_user_message

        return (
            prompt,
            HistoryState(message_count=len(messages), prefix_hash="cursor-shared"),
        )

    def _stale_acp_kill_enabled(self) -> bool:
        """Keep the authenticated Cursor ACP child alive across idle periods."""
        return False

    async def _build_subprocess_command(self, runtime: ACPProcessRuntime) -> list[str]:
        return build_cursor_agent_acp_command(
            self._cursor_cli_executable,
            model=runtime.model,
            trust_workspace=self._trust_workspace,
            extra_args=self._extra_cli_args,
            cursor_api_endpoint=self._cursor_api_endpoint,
            mode="ask" if runtime.responses_text_only_mode else None,
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
                message=f"Cursor CLI initialize failed: {initialize_response.error.message}",
                details=initialize_response.error.model_dump(),
            )

        # Cursor resolves credentials from its existing `agent login` state or
        # CURSOR_API_KEY. Calling ACP `authenticate(cursor_login)` here forces an
        # interactive browser flow even when the child is already authenticated.
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

    async def _prepare_turn_request_locked(
        self,
        runtime: ACPProcessRuntime,
        request: ConnectorChatCompletionsRequest,
    ) -> tuple[int, str]:
        extra_body = getattr(request.request, "extra_body", None)
        runtime.responses_text_only_mode = bool(
            isinstance(extra_body, dict)
            and extra_body.get(ACP_RESPONSES_TEXT_ONLY_MODE_KEY) is True
        )
        runtime.responses_standalone_mode = bool(
            runtime.responses_text_only_mode
            and isinstance(extra_body, dict)
            and extra_body.get(ACP_RESPONSES_STANDALONE_MODE_KEY) is True
        )
        try:
            return await super()._prepare_turn_request_locked(runtime, request)
        except BaseException:
            # Startup, handshake, and session/prompt preparation all happen
            # before BaseAcpConnector gets a chance to schedule its normal
            # post-turn retirement.  Responses turns use one-shot runtimes,
            # so leaving a failed runtime in the pool would orphan its child
            # process and make every failed request consume another slot.
            if runtime.responses_standalone_mode:
                await self._retire_standalone_runtime(runtime)
            raise

    async def _retire_standalone_runtime(self, runtime: ACPProcessRuntime) -> None:
        """Kill and remove an ephemeral Responses runtime after preparation fails."""

        try:
            await self._kill_runtime(runtime)
        except asyncio.CancelledError:
            raise
        except Exception:
            # Preserve the preparation error for the caller while still
            # retiring the unusable pool entry below.
            logger.warning(
                "Failed to terminate standalone Cursor ACP runtime after turn preparation failure",
                exc_info=True,
            )
        finally:
            await self._remove_runtime_from_pool(runtime)

    async def _remove_runtime_from_pool(self, runtime: ACPProcessRuntime) -> None:
        """Remove a retired runtime slot without disturbing other conversations."""

        async with self._runtime_pool_lock:
            retired_keys = [
                key for key, candidate in self._runtimes.items() if candidate is runtime
            ]
            for key in retired_keys:
                self._runtimes.pop(key, None)

    async def _schedule_stale_kill_after_turn(self, runtime: ACPProcessRuntime) -> None:
        """Retire one-shot Responses runtimes immediately after their turn.

        Cursor ACP keeps stale-kill scheduling disabled for authenticated pooled
        sessions.  Responses requests use a unique internal conversation key and
        replay stored transcript history, so every Responses runtime is one-shot.
        Explicitly kill and remove those marked ephemeral after each turn.
        """

        if runtime.responses_standalone_mode:
            try:
                await self._kill_runtime(runtime)
            finally:
                # Pool retirement must not depend on process termination being
                # fully successful.  A failed kill still leaves the runtime
                # unusable for a one-shot Responses turn and retaining its pool
                # entry would make every standalone request accumulate state.
                await self._remove_runtime_from_pool(runtime)
            return
        await super()._schedule_stale_kill_after_turn(runtime)

    async def _cancel_active_request(
        self,
        runtime: ACPProcessRuntime,
        prompt_request_id: int,
    ) -> None:
        try:
            await super()._cancel_active_request(runtime, prompt_request_id)
        finally:
            if runtime.responses_standalone_mode:
                await self._remove_runtime_from_pool(runtime)

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
                        "optionId": (
                            "reject-once"
                            if runtime.responses_text_only_mode
                            else self._permission_option_id()
                        ),
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
