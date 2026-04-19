from __future__ import annotations

import asyncio
import contextlib
import hashlib
import json
import logging
import os
import subprocess
import time
import uuid
from abc import ABC, abstractmethod
from collections.abc import AsyncGenerator, AsyncIterator, Sequence
from pathlib import Path
from typing import Any

from src.connectors.acp_core.tool_markdown import (
    acp_tool_payload_should_emit,
    coalesce_acp_tool_call_update_session_dict,
    extract_tool_correlation_key,
    extract_tool_input,
    extract_tool_name,
    extract_tool_output,
    format_acp_tool_completion_summary,
    is_terminal_tool_status,
    iter_coalesced_acp_tool_session_dicts,
    payload_utf8_byte_length,
    utc_now_iso,
)
from src.connectors.acp_core.transcript import ACPTranscriptSerializer
from src.connectors.acp_core.types import (
    ACPNotification,
    ACPProcessRuntime,
    ACPSessionUpdate,
    AcpStreamPiece,
    AcpToolStreamAccum,
    ACPUpdateContent,
    HistoryState,
)
from src.connectors.acp_core.workspace_policy import (
    ACP_MISSING_PROJECT_WORKSPACE_CODE,
    first_usable_workspace_dir,
    first_workspace_hint_str,
    is_usable_workspace_directory,
)
from src.connectors.base import LLMBackend, add_vendor_prefix, strip_vendor_prefix
from src.connectors.contracts import ConnectorChatCompletionsRequest
from src.connectors.mixins.usage_calculation_mixin import UsageCalculationMixin
from src.core.common.exceptions import (
    APIConnectionError,
    APITimeoutError,
    BackendError,
    ConfigurationError,
    ServiceUnavailableError,
)
from src.core.domain.chat import (
    CanonicalChatResponse,
    ChatCompletionChoice,
    ChatCompletionChoiceMessage,
    ChatMessage,
)
from src.core.domain.responses import (
    ProcessedResponse,
    ResponseEnvelope,
    StreamingResponseEnvelope,
)
from src.core.services.streaming.processed_stream_idle_keepalive import (
    wrap_processed_stream_with_idle_keepalive,
)

logger = logging.getLogger(__name__)

DEFAULT_PROCESS_TIMEOUT = 300.0
DEFAULT_IDLE_TIMEOUT = 30.0
MAX_RESPONSE_LINE_SIZE = 10 * 1024 * 1024
ACP_UPDATE_METHOD = "session/update"
ACP_AGENT_MESSAGE_CHUNK = "agent_message_chunk"
ACP_AGENT_THOUGHT_CHUNK = "agent_thought_chunk"
ACP_CANCEL_METHODS = ("session/cancel", "session/stop", "session/end")
ACP_GRACEFUL_CANCEL_TIMEOUT_SECONDS = 12.0
# Idle delay after a completed chat turn before terminating the pooled ACP subprocess.
STALE_ACP_AGENT_KILL_DELAY_SECONDS = 3600.0
# Increment when the canonicalization used for ACP history prefix hashes changes.
HISTORY_PREFIX_HASH_VERSION = 2


def _canonical_chat_message_for_history_hash(message: ChatMessage) -> dict[str, Any]:
    """Return stable identity fields for divergence detection.

    Uses :meth:`ChatMessage.to_dict` so fields such as ``metadata`` that are not
    part of the visible transcript do not spuriously invalidate the prefix hash.
    """

    return message.to_dict()


def _hash_chat_messages_prefix_stable(
    messages: Sequence[ChatMessage],
    end_exclusive: int,
) -> str:
    """SHA-256 hex digest of the first ``end_exclusive`` messages (conversation prefix)."""

    if end_exclusive <= 0:
        return hashlib.sha256(b"").hexdigest()
    slice_msgs = messages[:end_exclusive]
    payload = [_canonical_chat_message_for_history_hash(m) for m in slice_msgs]
    canonical = json.dumps(
        {"m": payload, "v": HISTORY_PREFIX_HASH_VERSION},
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


class _RuntimeCancellable:
    __slots__ = ("_connector", "_runtime", "_prompt_request_id")

    def __init__(
        self,
        connector: BaseAcpConnector,
        runtime: ACPProcessRuntime,
        prompt_request_id: int,
    ) -> None:
        self._connector = connector
        self._runtime = runtime
        self._prompt_request_id = prompt_request_id

    def cancel(self) -> None:
        if self._runtime.cancellation_event is not None:
            self._runtime.cancellation_event.set()
        if self._runtime.cancellation_lock is None:
            return
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return
        task = loop.create_task(
            self._connector._cancel_active_request(
                self._runtime,
                self._prompt_request_id,
            )
        )
        task.add_done_callback(lambda t: t.exception() if not t.cancelled() else None)


class BaseAcpConnector(LLMBackend, UsageCalculationMixin, ABC):
    """Base class for ACP-based connectors."""

    VENDOR_PREFIX: str
    requires_explicit_workspace: bool = False

    def __init__(
        self, config: Any, translation_service: Any = None, **kwargs: Any
    ) -> None:
        super().__init__(config)
        self.translation_service = translation_service
        self.is_functional = False
        self._initialization_failed = False
        self._validation_errors: list[str] = []
        self._default_project_dir: Path | None = None
        self._model = "auto"
        self._process_timeout = DEFAULT_PROCESS_TIMEOUT
        self._idle_timeout = DEFAULT_IDLE_TIMEOUT
        self._runtime_pool_lock = asyncio.Lock()
        self._runtimes: dict[tuple[str, str, str], ACPProcessRuntime] = {}

    @property
    def has_static_credentials(self) -> bool:
        return False

    def is_backend_functional(self) -> bool:
        return (
            self.is_functional
            and not self._initialization_failed
            and len(self._validation_errors) == 0
        )

    def _is_backend_functional_internal(self) -> bool:
        return self.is_backend_functional()

    def get_validation_errors(self) -> list[str]:
        return self._validation_errors.copy()

    def _resolve_stream_keepalive_interval(self) -> float:
        """Seconds between idle keepalive chunks while waiting for ACP subprocess output."""
        cfg = getattr(self, "config", None)
        failure_handling = getattr(cfg, "failure_handling", None)
        interval = getattr(failure_handling, "keepalive_interval", None)
        if isinstance(interval, int | float) and float(interval) > 0:
            return float(interval)
        return 12.0

    def _stale_acp_kill_enabled(self) -> bool:
        return not bool(getattr(self.config, "disable_stale_acp_agent_kills", False))

    def _stale_acp_kill_delay_seconds(self) -> float:
        return STALE_ACP_AGENT_KILL_DELAY_SECONDS

    async def _cancel_stale_kill_timer(self, runtime: ACPProcessRuntime) -> None:
        task = runtime.stale_kill_task
        if task is None:
            return
        current = asyncio.current_task()
        if task is current:
            runtime.stale_kill_task = None
            return
        if not task.done():
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task
        runtime.stale_kill_task = None

    async def _schedule_stale_kill_after_turn(self, runtime: ACPProcessRuntime) -> None:
        await self._cancel_stale_kill_timer(runtime)
        if not self._stale_acp_kill_enabled():
            return
        delay = self._stale_acp_kill_delay_seconds()
        if logger.isEnabledFor(logging.INFO):
            logger.info(
                "Scheduling stale ACP agent kill in %.0fs (backend=%s project=%s "
                "model=%s client_session=%s)",
                delay,
                self.backend_type,
                runtime.project_dir,
                runtime.model,
                runtime.client_session_id,
            )
        connector = self
        runtime_ref = runtime

        async def _run() -> None:
            try:
                await asyncio.sleep(delay)
            except asyncio.CancelledError:
                return
            if not connector._stale_acp_kill_enabled():
                return
            proc = runtime_ref.process
            if proc is None or proc.poll() is not None:
                return
            req_lock = runtime_ref.request_lock
            if req_lock is not None and req_lock.locked():
                if logger.isEnabledFor(logging.INFO):
                    logger.info(
                        "Stale ACP kill skipped: request in progress (backend=%s pid=%s)",
                        connector.backend_type,
                        getattr(proc, "pid", None),
                    )
                return
            if logger.isEnabledFor(logging.INFO):
                logger.info(
                    "Stale ACP agent idle timeout: terminating process (backend=%s "
                    "pid=%s project=%s model=%s client_session=%s)",
                    connector.backend_type,
                    getattr(proc, "pid", None),
                    runtime_ref.project_dir,
                    runtime_ref.model,
                    runtime_ref.client_session_id,
                )
            await connector._kill_runtime(runtime_ref)

        runtime.stale_kill_task = asyncio.create_task(_run())

    @abstractmethod
    async def _build_acp_command(self, runtime: ACPProcessRuntime) -> list[str]:
        """Build the command to spawn the ACP process."""

    @abstractmethod
    async def _perform_handshake(self, runtime: ACPProcessRuntime) -> None:
        """Perform the ACP handshake (initialize, authenticate, session/new)."""

    @abstractmethod
    async def _handle_server_request(
        self, runtime: ACPProcessRuntime, msg: ACPNotification
    ) -> None:
        """Handle server-initiated JSON-RPC requests (e.g., permissions)."""

    @staticmethod
    def _is_usable_directory(path: Path) -> bool:
        return is_usable_workspace_directory(path)

    def _build_runtime_key(
        self, project_dir: Path, model: str, client_session_id: str
    ) -> tuple[str, str, str]:
        return (str(project_dir), model, client_session_id)

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

    @staticmethod
    def _resolve_client_session_id(request: ConnectorChatCompletionsRequest) -> str:
        """Resolve the logical client session used to key ACP subprocess pools.

        When neither ``ConnectorRequestContext.session_id`` nor
        ``request.request.session_id`` is set, callers share the pool key
        ``"default"`` (one ACP runtime per ``(project_dir, model)`` for all
        such traffic). Upstream layers should set a stable session id when
        isolation between clients or tabs is required.
        """

        sid: str | None = None
        if request.context is not None and request.context.session_id:
            sid = request.context.session_id
        if not sid:
            raw = getattr(request.request, "session_id", None)
            if isinstance(raw, str) and raw.strip():
                sid = raw
        if isinstance(sid, str) and sid.strip():
            return sid.strip()
        return "default"

    @staticmethod
    def _hash_messages_prefix(
        messages: Sequence[ChatMessage], end_exclusive: int
    ) -> str:
        return _hash_chat_messages_prefix_stable(messages, end_exclusive)

    async def _acquire_runtime(
        self, request: ConnectorChatCompletionsRequest
    ) -> ACPProcessRuntime:
        project_dir = self._resolve_project_dir_for_request(request)
        requested_model = strip_vendor_prefix(
            request.effective_model or self._model,
            self.VENDOR_PREFIX,
        )
        client_session_id = self._resolve_client_session_id(request)
        runtime_key = self._build_runtime_key(
            project_dir, requested_model, client_session_id
        )

        async with self._runtime_pool_lock:
            runtime = self._runtimes.get(runtime_key)
            if runtime is None:
                runtime = self._create_runtime(
                    project_dir, requested_model, client_session_id
                )
                self._runtimes[runtime_key] = runtime

        return await self._reap_idle_runtime(runtime_key, runtime)

    def _resolve_project_dir_for_request(
        self, request: ConnectorChatCompletionsRequest
    ) -> Path:
        extra_body = getattr(request.request, "extra_body", None)
        extra_dict = extra_body if isinstance(extra_body, dict) else None
        options = request.options if isinstance(request.options, dict) else None

        usable = first_usable_workspace_dir(
            extra_dict,
            options,
            is_usable=is_usable_workspace_directory,
        )
        if usable is not None:
            return usable

        if self.requires_explicit_workspace:
            hint = first_workspace_hint_str(extra_dict, options)
            if hint is not None:
                raise BackendError(
                    message=f"Unusable ACP workspace directory: {hint}",
                    details={
                        "code": ACP_MISSING_PROJECT_WORKSPACE_CODE,
                        "hint": hint,
                    },
                )
            raise BackendError(
                message=(
                    "ACP backend requires an explicit workspace directory "
                    "(session project_dir or request project_dir/workspace_path/cwd/project)."
                ),
                details={"code": ACP_MISSING_PROJECT_WORKSPACE_CODE},
            )

        hint = first_workspace_hint_str(extra_dict, options)
        if hint is not None and logger.isEnabledFor(logging.DEBUG):
            logger.debug(
                "Ignoring unusable ACP project_dir override: %s",
                hint,
            )

        if self._default_project_dir is None:
            raise ConfigurationError(
                message=f"{self.backend_type} backend has no default project directory configured"
            )

        return self._default_project_dir

    async def _reap_idle_runtime(
        self,
        runtime_key: tuple[str, str, str],
        runtime: ACPProcessRuntime,
    ) -> ACPProcessRuntime:
        """Drop idle subprocesses and swap in a fresh :class:`ACPProcessRuntime` slot.

        Replacing the pool entry (instead of only clearing ``runtime.process``)
        avoids unbounded growth of dead :class:`ACPProcessRuntime` objects while
        ensuring concurrent acquirers always resolve to the canonical instance
        currently registered for ``runtime_key``.
        """

        if self._idle_timeout <= 0:
            return runtime
        if runtime.request_lock is None or runtime.request_lock.locked():
            return runtime
        if runtime.process is None:
            return runtime
        if runtime.last_activity <= 0:
            return runtime
        if (time.monotonic() - runtime.last_activity) < self._idle_timeout:
            return runtime

        await self._kill_runtime(runtime)

        async with self._runtime_pool_lock:
            current = self._runtimes.get(runtime_key)
            if current is runtime:
                replacement = self._create_runtime(
                    runtime.project_dir,
                    runtime.model,
                    runtime.client_session_id,
                )
                self._runtimes[runtime_key] = replacement
                return replacement
            if current is not None:
                return current
        return runtime

    async def _spawn_process(self, runtime: ACPProcessRuntime) -> None:
        assert runtime.process_lock is not None
        async with runtime.process_lock:
            process = runtime.process
            if process is not None and process.poll() is None:
                return

            cmd = await self._build_acp_command(runtime)

            new_process: subprocess.Popen[bytes] | None = None
            try:
                new_process = subprocess.Popen(
                    cmd,
                    stdin=subprocess.PIPE,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    cwd=str(runtime.project_dir),
                    shell=False,
                    env=os.environ.copy(),
                    creationflags=(
                        subprocess.CREATE_NEW_PROCESS_GROUP if os.name == "nt" else 0
                    ),
                )
                runtime.process = new_process
                await asyncio.sleep(0.1)
                if new_process.poll() is not None:
                    stderr = await self._read_stderr(new_process)
                    raise BackendError(
                        message="ACP process failed to start",
                        details={
                            "stderr": stderr,
                            "project_dir": str(runtime.project_dir),
                            "model": runtime.model,
                            "command": cmd,
                        },
                    )
                runtime.last_activity = time.monotonic()
                runtime.initialized = False
                runtime.session_id = None
                runtime.message_id = 0
                runtime.history_state = None
            except Exception as exc:
                if new_process is not None:
                    self._cleanup_process(new_process)
                runtime.process = None
                runtime.initialized = False
                runtime.session_id = None
                runtime.history_state = None
                raise APIConnectionError(
                    message=f"Failed to start ACP process: {exc}",
                    details={
                        "project_dir": str(runtime.project_dir),
                        "model": runtime.model,
                    },
                ) from exc

    async def _kill_runtime(self, runtime: ACPProcessRuntime) -> None:
        await self._cancel_stale_kill_timer(runtime)
        assert runtime.process_lock is not None
        async with runtime.process_lock:
            process = runtime.process
            if process is None:
                return

            try:
                await self._terminate_process(process)
            finally:
                self._cleanup_runtime_state(runtime, process)

    async def _kill_all_runtimes(self) -> None:
        async with self._runtime_pool_lock:
            runtimes = list(self._runtimes.values())
            self._runtimes.clear()

        for runtime in runtimes:
            await self._kill_runtime(runtime)

    def _cleanup_runtime_state(
        self,
        runtime: ACPProcessRuntime,
        process: subprocess.Popen[bytes] | None = None,
    ) -> None:
        self._cleanup_process(process or runtime.process)
        runtime.process = None
        runtime.initialized = False
        runtime.session_id = None
        runtime.message_id = 0
        runtime.last_activity = 0.0
        runtime.history_state = None

    def _cleanup_process(self, process: subprocess.Popen[bytes] | None = None) -> None:
        if process is None:
            return

        for stream_name in ("stdin", "stdout", "stderr"):
            stream = getattr(process, stream_name, None)
            if stream is None:
                continue
            with contextlib.suppress(OSError, ValueError):
                stream.close()

    async def _read_stderr(self, process: subprocess.Popen[bytes]) -> str:
        if process.stderr is None:
            return ""
        stderr_bytes = await asyncio.to_thread(process.stderr.read)
        return stderr_bytes.decode("utf-8", errors="replace")

    async def _terminate_process(self, process: subprocess.Popen[bytes]) -> None:
        if process.poll() is not None:
            return

        if os.name == "nt":
            with contextlib.suppress(Exception):
                process.terminate()
            try:
                await asyncio.to_thread(
                    subprocess.run,
                    ["taskkill", "/PID", str(process.pid), "/T", "/F"],
                    capture_output=True,
                    check=False,
                    shell=False,
                )
            finally:
                with contextlib.suppress(subprocess.TimeoutExpired):
                    await asyncio.to_thread(lambda: process.wait(timeout=5))
            return

        process.terminate()
        try:
            await asyncio.to_thread(lambda: process.wait(timeout=5))
        except subprocess.TimeoutExpired:
            process.kill()
            with contextlib.suppress(subprocess.TimeoutExpired):
                await asyncio.to_thread(lambda: process.wait(timeout=5))

    def _get_next_message_id(self, runtime: ACPProcessRuntime) -> int:
        runtime.message_id += 1
        return runtime.message_id

    async def _write_json_line(
        self, runtime: ACPProcessRuntime, payload: dict[str, Any]
    ) -> None:
        process = runtime.process
        if process is None or process.stdin is None:
            raise BackendError(message="ACP process not running")
        encoded = (json.dumps(payload, separators=(",", ":")) + "\n").encode("utf-8")

        def _write() -> None:
            assert process.stdin is not None
            process.stdin.write(encoded)
            process.stdin.flush()

        await asyncio.to_thread(_write)
        runtime.last_activity = time.monotonic()

    async def _send_jsonrpc_message(
        self,
        runtime: ACPProcessRuntime,
        method: str,
        params: dict[str, Any],
    ) -> int:
        message_id = self._get_next_message_id(runtime)
        payload = {
            "jsonrpc": "2.0",
            "method": method,
            "params": params,
            "id": message_id,
        }
        try:
            await self._write_json_line(runtime, payload)
            return message_id
        except Exception as exc:
            raise APIConnectionError(
                message=f"Failed to communicate with ACP process: {exc}"
            ) from exc

    async def _send_jsonrpc_result(
        self, runtime: ACPProcessRuntime, request_id: int, result: dict[str, Any]
    ) -> None:
        await self._write_json_line(
            runtime,
            {"jsonrpc": "2.0", "id": request_id, "result": result},
        )

    async def _read_jsonrpc_message(
        self, runtime: ACPProcessRuntime
    ) -> ACPNotification | None:
        process = runtime.process
        if process is None or process.stdout is None:
            raise BackendError(message="ACP process not running")

        def _read_limited() -> bytes:
            assert process.stdout is not None
            return bytes(process.stdout.readline(MAX_RESPONSE_LINE_SIZE + 1))

        try:
            line = await asyncio.to_thread(_read_limited)
            if not line:
                if process.poll() is not None:
                    stderr = await self._read_stderr(process)
                    self._cleanup_runtime_state(runtime, process)
                    raise BackendError(
                        message="ACP process exited unexpectedly",
                        details={
                            "stderr": stderr,
                            "project_dir": str(runtime.project_dir),
                            "model": runtime.model,
                        },
                    )
                return None
            if len(line) > MAX_RESPONSE_LINE_SIZE:
                raise BackendError(message="Response too large from ACP process")
            runtime.last_activity = time.monotonic()
            data = json.loads(line.decode("utf-8"))
            if not isinstance(data, dict):
                raise BackendError(message="Invalid non-object JSON response")
            return ACPNotification(**data)
        except json.JSONDecodeError as exc:
            raise BackendError(
                message="Invalid JSON response from ACP process",
                details={"error": str(exc)},
            ) from exc
        except BackendError:
            raise
        except Exception as exc:
            raise APIConnectionError(
                message=f"Failed to read from ACP process: {exc}"
            ) from exc

    async def _await_response(
        self,
        runtime: ACPProcessRuntime,
        request_id: int,
    ) -> ACPNotification:
        deadline = time.monotonic() + self._process_timeout
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise APITimeoutError(
                    message="Timeout waiting for ACP response",
                    details={"timeout": self._process_timeout, "model": runtime.model},
                )

            response = await asyncio.wait_for(
                self._read_jsonrpc_message(runtime),
                timeout=remaining,
            )
            if response is None:
                continue
            if response.is_server_request:
                await self._handle_server_request(runtime, response)
                continue
            if response.id != request_id:
                continue
            return response

    async def _initialize_runtime(self, runtime: ACPProcessRuntime) -> None:
        if runtime.initialized and runtime.session_id:
            return
        await self._perform_handshake(runtime)

    def _extract_user_message_as_string(
        self, processed_messages: Sequence[ChatMessage | dict[str, Any] | str | Any]
    ) -> str:
        last_user_message = ""

        for message in processed_messages:
            role = ""
            content: Any = ""

            if isinstance(message, ChatMessage):
                role = message.role
                content = message.content
            elif isinstance(message, dict):
                role = str(message.get("role", ""))
                content = message.get("content")
                if content in (None, "") and "parts" in message:
                    content = message.get("parts")
            elif isinstance(message, str):
                role = "user"
                content = message
            else:
                role = str(getattr(message, "role", ""))
                content = getattr(message, "content", "")

            normalized = self._stringify_message_content(content)
            if role == "user" and normalized:
                last_user_message = normalized

        return last_user_message

    def _stringify_message_content(self, content: Any) -> str:
        if content is None:
            return ""
        if isinstance(content, str):
            return content
        if isinstance(content, Sequence) and not isinstance(
            content, str | bytes | bytearray
        ):
            parts: list[str] = []
            for item in content:
                if isinstance(item, str):
                    parts.append(item)
                    continue
                if isinstance(item, dict):
                    text = item.get("text")
                    nested = item.get("content")
                    if isinstance(text, str):
                        parts.append(text)
                    elif isinstance(nested, str):
                        parts.append(nested)
                else:
                    item_text = getattr(item, "text", None)
                    if isinstance(item_text, str):
                        parts.append(item_text)
            return " ".join(part for part in parts if part)
        return str(content)

    @staticmethod
    def _text_from_acp_content_block(content: Any) -> str | None:
        """Extract human-readable text from a session/update ``content`` block."""
        if isinstance(content, dict):
            td = content.get("textDelta")
            if isinstance(td, str) and td:
                return td
            raw_text = content.get("text")
            if content.get("type") == "text" and isinstance(raw_text, str):
                return raw_text
            try:
                normalized = ACPUpdateContent(**content)
            except Exception:
                return None
            if normalized.type == "text" and isinstance(normalized.text, str):
                return normalized.text
        return None

    @staticmethod
    def _open_thinking_block(text: str) -> str:
        """Open a visible thinking block for clients that cannot segment reasoning."""

        return f"Thinking:\n{text}"

    @staticmethod
    def _append_thinking_block(text: str) -> str:
        """Append incremental text inside an already-open thinking block."""

        return text

    @staticmethod
    def _close_thinking_block() -> str:
        """Close a visible thinking block before ordinary content resumes."""

        return "\n\n"

    def _thinking_content_piece(
        self, runtime: ACPProcessRuntime, text: str
    ) -> AcpStreamPiece:
        if runtime.acp_thinking_block_open:
            return AcpStreamPiece(content=self._append_thinking_block(text))
        runtime.acp_thinking_block_open = True
        return AcpStreamPiece(content=self._open_thinking_block(text))

    def _prepend_thinking_close_if_needed(
        self, runtime: ACPProcessRuntime, pieces: list[AcpStreamPiece]
    ) -> list[AcpStreamPiece]:
        if not runtime.acp_thinking_block_open:
            return pieces
        for index, piece in enumerate(pieces):
            if piece.content is None:
                continue
            pieces[index] = AcpStreamPiece(
                content=f"{self._close_thinking_block()}{piece.content}",
                reasoning_content=piece.reasoning_content,
            )
            runtime.acp_thinking_block_open = False
            return pieces
        return pieces

    def _acp_progress_reasoning_line(
        self, session_update_kind: str, update: dict[str, Any]
    ) -> str | None:
        """Build a short progress line for plan/mode style updates (reasoning channel)."""
        if session_update_kind == "plan":
            title = update.get("title")
            if isinstance(title, str) and title.strip():
                return f"[plan] {title.strip()}\n"
            return "[plan]\n"
        if session_update_kind == "current_mode_update":
            mode = update.get("modeId") or update.get("mode")
            if isinstance(mode, str) and mode:
                return f"[mode] {mode}\n"
            return "[mode]\n"
        return None

    def _resolve_tool_stream_key(
        self,
        runtime: ACPProcessRuntime,
        tc: dict[str, Any],
        *,
        for_new_invocation: bool,
    ) -> str:
        ck = extract_tool_correlation_key(tc)
        if ck:
            return ck
        if for_new_invocation:
            runtime.acp_anon_tool_seq += 1
            key = f"__anon__:{runtime.acp_anon_tool_seq}"
            runtime.acp_last_anon_stream_key = key
            return key
        if runtime.acp_last_anon_stream_key:
            return runtime.acp_last_anon_stream_key
        runtime.acp_anon_tool_seq += 1
        key = f"__anon__:{runtime.acp_anon_tool_seq}"
        runtime.acp_last_anon_stream_key = key
        return key

    @staticmethod
    def _acp_update_tool_sizes_from_merged(
        acc: AcpToolStreamAccum, merged: dict[str, Any]
    ) -> None:
        inp = extract_tool_input(merged)
        acc.last_input_bytes = max(acc.last_input_bytes, payload_utf8_byte_length(inp))
        out = extract_tool_output(merged)
        if out is not None:
            acc.last_output_bytes = max(
                acc.last_output_bytes, payload_utf8_byte_length(out)
            )

    def _ensure_acp_tool_accum(
        self, runtime: ACPProcessRuntime, key: str, tool_name: str
    ) -> AcpToolStreamAccum:
        acc = runtime.acp_tool_stream_accum.get(key)
        if acc is None:
            acc = AcpToolStreamAccum(tool_name=tool_name)
            acc.started_wall_iso = utc_now_iso()
            acc.started_perf = time.perf_counter()
            runtime.acp_tool_stream_accum[key] = acc
        elif tool_name and tool_name != "tool":
            acc.tool_name = tool_name
        return acc

    @staticmethod
    def _acp_mark_tool_ended_now(acc: AcpToolStreamAccum) -> None:
        if acc.ended_wall_iso is None:
            acc.ended_wall_iso = utc_now_iso()
        if acc.ended_perf is None:
            acc.ended_perf = time.perf_counter()

    def _acp_try_emit_tool_summary(
        self, acc: AcpToolStreamAccum
    ) -> list[AcpStreamPiece]:
        if acc.summary_emitted or not acc.started_wall_iso:
            return []
        self._acp_mark_tool_ended_now(acc)
        end_wall = acc.ended_wall_iso or utc_now_iso()
        end_perf = acc.ended_perf if acc.ended_perf is not None else time.perf_counter()
        started_perf = acc.started_perf if acc.started_perf > 0 else end_perf
        elapsed = max(0.0, end_perf - started_perf)
        text = format_acp_tool_completion_summary(
            acc.tool_name,
            input_bytes=acc.last_input_bytes,
            output_bytes=acc.last_output_bytes,
            started_iso=acc.started_wall_iso,
            ended_iso=end_wall,
            elapsed_s=elapsed,
        )
        acc.summary_emitted = True
        acc.pending_terminal_summary = False
        return [AcpStreamPiece(content=text)]

    def _acp_terminal_summary_pieces(
        self,
        acc: AcpToolStreamAccum,
        merged: dict[str, Any],
        status_str: str | None,
        *,
        allow_defer: bool,
    ) -> list[AcpStreamPiece]:
        pieces: list[AcpStreamPiece] = []
        if (
            acc.pending_terminal_summary
            and not acc.summary_emitted
            and (
                extract_tool_output(merged) is not None
                or acc.last_output_bytes > 0
                or acc.last_input_bytes > 0
            )
        ):
            pieces.extend(self._acp_try_emit_tool_summary(acc))
        if not acc.summary_emitted and is_terminal_tool_status(status_str):
            no_output = (
                extract_tool_output(merged) is None and acc.last_output_bytes == 0
            )
            no_input = extract_tool_input(merged) is None and acc.last_input_bytes == 0
            correlated = extract_tool_correlation_key(merged) is not None
            if allow_defer and no_output and no_input and correlated:
                acc.pending_terminal_summary = True
            else:
                pieces.extend(self._acp_try_emit_tool_summary(acc))
        return pieces

    @staticmethod
    def _acp_tool_call_payload_is_multi_dict_list(upd: dict[str, Any]) -> bool:
        nested = (
            upd.get("toolCall") or upd.get("tool_call") or upd.get("toolInvocation")
        )
        if not isinstance(nested, list):
            return False
        return sum(1 for x in nested if isinstance(x, dict)) > 1

    def _acp_pieces_for_tool_call(
        self, runtime: ACPProcessRuntime, upd: dict[str, Any]
    ) -> list[AcpStreamPiece]:
        out: list[AcpStreamPiece] = []
        batch_multi = self._acp_tool_call_payload_is_multi_dict_list(upd)
        for merged in iter_coalesced_acp_tool_session_dicts(upd):
            if not merged or not acp_tool_payload_should_emit(merged):
                continue
            key = self._resolve_tool_stream_key(
                runtime, merged, for_new_invocation=True
            )
            name = extract_tool_name(merged)
            acc = self._ensure_acp_tool_accum(runtime, key, name)
            self._acp_update_tool_sizes_from_merged(acc, merged)
            status_raw = merged.get("status") or merged.get("state")
            status_str = status_raw.strip() if isinstance(status_raw, str) else None
            pieces = self._acp_terminal_summary_pieces(
                # Batched multi-tool payloads lack a stable follow-up edge per item, so
                # empty terminal entries emit immediately instead of waiting for an update.
                acc,
                merged,
                status_str,
                allow_defer=not batch_multi,
            )
            out.extend(pieces)
        return out

    def _acp_pieces_for_tool_call_update(
        self, runtime: ACPProcessRuntime, upd: dict[str, Any]
    ) -> list[AcpStreamPiece]:
        merged = coalesce_acp_tool_call_update_session_dict(upd)
        if not merged:
            return []
        key = self._resolve_tool_stream_key(runtime, merged, for_new_invocation=False)
        if (
            key not in runtime.acp_tool_stream_accum
            and not acp_tool_payload_should_emit(merged)
        ):
            return []
        name = extract_tool_name(merged)
        acc = self._ensure_acp_tool_accum(runtime, key, name)
        self._acp_update_tool_sizes_from_merged(acc, merged)
        status_raw = merged.get("status") or merged.get("state")
        status_str = status_raw.strip() if isinstance(status_raw, str) else None
        return self._acp_terminal_summary_pieces(
            acc, merged, status_str, allow_defer=True
        )

    def _flush_incomplete_acp_tool_streams(
        self, runtime: ACPProcessRuntime
    ) -> list[AcpStreamPiece]:
        """Emit summaries for tools still missing a final summary (incl. deferred terminal)."""
        out: list[AcpStreamPiece] = []
        for _key, acc in list(runtime.acp_tool_stream_accum.items()):
            if acc.summary_emitted or not acc.started_wall_iso:
                continue
            self._acp_mark_tool_ended_now(acc)
            out.extend(self._acp_try_emit_tool_summary(acc))
        return out

    def _session_update_to_stream_pieces(
        self, response: ACPNotification, runtime: ACPProcessRuntime
    ) -> list[AcpStreamPiece]:
        """Map a ``session/update`` JSON-RPC notification to zero or more stream pieces."""
        if response.method != ACP_UPDATE_METHOD or response.params is None:
            return []
        try:
            envelope = ACPSessionUpdate(**response.params)
        except Exception:
            if logger.isEnabledFor(logging.DEBUG):
                logger.debug(
                    "ACP session/update params could not be parsed",
                    exc_info=True,
                )
            return []
        upd = envelope.update
        kind = upd.get("sessionUpdate")
        if not isinstance(kind, str):
            return []

        text = self._text_from_acp_content_block(upd.get("content"))

        if kind == ACP_AGENT_MESSAGE_CHUNK:
            if text:
                return self._prepend_thinking_close_if_needed(
                    runtime,
                    [AcpStreamPiece(content=text)],
                )
            return []
        if kind == ACP_AGENT_THOUGHT_CHUNK:
            if text:
                return [self._thinking_content_piece(runtime, text)]
            return []
        if kind == "tool_call":
            return self._prepend_thinking_close_if_needed(
                runtime,
                self._acp_pieces_for_tool_call(runtime, upd),
            )
        if kind == "tool_call_update":
            return self._prepend_thinking_close_if_needed(
                runtime,
                self._acp_pieces_for_tool_call_update(runtime, upd),
            )

        progress = self._acp_progress_reasoning_line(kind, upd)
        if progress:
            return [self._thinking_content_piece(runtime, progress)]
        return []

    def _session_update_to_stream_piece(
        self, response: ACPNotification, runtime: ACPProcessRuntime
    ) -> AcpStreamPiece | None:
        """Back-compat helper merging multiple ``content`` / ``reasoning`` pieces."""
        pieces = self._session_update_to_stream_pieces(response, runtime)
        if not pieces:
            return None
        if len(pieces) == 1:
            return pieces[0]
        content_parts = [p.content for p in pieces if p.content is not None]
        reasoning_parts = [
            p.reasoning_content for p in pieces if p.reasoning_content is not None
        ]
        return AcpStreamPiece(
            content="".join(content_parts) if content_parts else None,
            reasoning_content="".join(reasoning_parts) if reasoning_parts else None,
        )

    async def _iter_acp_stream_pieces(
        self,
        runtime: ACPProcessRuntime,
        prompt_request_id: int,
        response_model: str,
    ) -> AsyncGenerator[AcpStreamPiece, None]:
        runtime.acp_tool_stream_accum.clear()
        runtime.acp_anon_tool_seq = 0
        runtime.acp_last_anon_stream_key = None
        runtime.acp_thinking_block_open = False
        try:
            while True:
                if runtime.cancellation_event is not None:
                    read_task = asyncio.create_task(self._read_jsonrpc_message(runtime))
                    cancel_task = asyncio.create_task(runtime.cancellation_event.wait())
                    try:
                        done, pending = await asyncio.wait(
                            {read_task, cancel_task},
                            return_when=asyncio.FIRST_COMPLETED,
                            timeout=self._process_timeout,
                        )
                    except asyncio.CancelledError:
                        read_task.cancel()
                        cancel_task.cancel()
                        with contextlib.suppress(asyncio.CancelledError):
                            await read_task
                        with contextlib.suppress(asyncio.CancelledError):
                            await cancel_task
                        raise
                    if not done:
                        for t in pending:
                            t.cancel()
                            with contextlib.suppress(asyncio.CancelledError):
                                await t
                        raise asyncio.TimeoutError()
                    for t in pending:
                        t.cancel()
                        with contextlib.suppress(asyncio.CancelledError):
                            await t

                    if cancel_task in done:
                        return
                    response = read_task.result()
                else:
                    response = await asyncio.wait_for(
                        self._read_jsonrpc_message(runtime),
                        timeout=self._process_timeout,
                    )

                if response is None:
                    continue

                if response.is_server_request:
                    await self._handle_server_request(runtime, response)
                    continue

                if response.id == prompt_request_id:
                    if response.is_error and response.error is not None:
                        raise BackendError(
                            message=f"ACP process error: {response.error.message}",
                            details=response.error.model_dump(),
                        )
                    if runtime.acp_thinking_block_open:
                        runtime.acp_thinking_block_open = False
                        yield AcpStreamPiece(content=self._close_thinking_block())
                    for flush_piece in self._flush_incomplete_acp_tool_streams(runtime):
                        if flush_piece.content or flush_piece.reasoning_content:
                            yield flush_piece
                    break

                for piece in self._session_update_to_stream_pieces(response, runtime):
                    if piece.content is not None or piece.reasoning_content is not None:
                        yield piece
        except asyncio.TimeoutError as exc:
            raise APITimeoutError(
                message="Timeout waiting for ACP response",
                details={"timeout": self._process_timeout, "model": response_model},
            ) from exc

    def _create_sse_chunk_from_piece(
        self, piece: AcpStreamPiece, model: str, chunk_id: str
    ) -> str | None:
        delta: dict[str, Any] = {}
        if piece.content:
            delta["content"] = piece.content
        if piece.reasoning_content:
            delta["reasoning_content"] = piece.reasoning_content
        if not delta:
            return None
        payload = {
            "id": chunk_id,
            "object": "chat.completion.chunk",
            "created": int(time.time()),
            "model": model,
            "choices": [
                {
                    "index": 0,
                    "delta": delta,
                    "finish_reason": None,
                }
            ],
        }
        return f"data: {json.dumps(payload)}\n\n"

    @staticmethod
    def _create_sse_done_chunk() -> str:
        return "data: [DONE]\n\n"

    async def _stream_response(
        self,
        runtime: ACPProcessRuntime,
        requested_model: str,
        prompt_request_id: int,
    ) -> AsyncGenerator[ProcessedResponse, None]:
        chunk_id = str(uuid.uuid4())
        try:
            async for piece in self._iter_acp_stream_pieces(
                runtime, prompt_request_id, requested_model
            ):
                sse = self._create_sse_chunk_from_piece(
                    piece, requested_model, chunk_id
                )
                if sse is not None:
                    yield ProcessedResponse(content=sse)
        finally:
            yield ProcessedResponse(content=self._create_sse_done_chunk())

    async def _prepare_prompt_request_locked(
        self,
        runtime: ACPProcessRuntime,
        request: ConnectorChatCompletionsRequest,
    ) -> tuple[int, str]:
        """Build ``session/prompt`` text and JSON-RPC id under ``runtime.request_lock``.

        History is tracked with :class:`HistoryState` so we can send a compact
        tail transcript on append-only turns, resend the full transcript after
        detected divergence, or send only the last user line on idempotent retries.
        """

        await self._cancel_stale_kill_timer(runtime)
        await self._spawn_process(runtime)
        await self._initialize_runtime(runtime)

        messages = list(request.processed_messages)
        if not messages:
            raise BackendError(message="No messages found in request")

        state = runtime.history_state
        new_history_state: HistoryState
        user_message: str

        # First prompt for this subprocess: full Markdown transcript + state seed.
        if state is None:
            user_message = ACPTranscriptSerializer.serialize(messages)
            new_history_state = HistoryState(
                message_count=len(messages),
                prefix_hash=self._hash_messages_prefix(messages, len(messages)),
            )
        else:
            n = state.message_count
            prefix_hash = state.prefix_hash
            diverged = (
                len(messages) < n
                or self._hash_messages_prefix(messages, n) != prefix_hash
            )

            # Prefix edit, branch switch, or truncated history vs. what ACP saw.
            if diverged:
                if logger.isEnabledFor(logging.INFO):
                    logger.info(
                        "ACP history diverged or shrank; resetting agent process "
                        "(project=%s model=%s client_session=%s)",
                        runtime.project_dir,
                        runtime.model,
                        runtime.client_session_id,
                    )
                await self._kill_runtime(runtime)
                await self._spawn_process(runtime)
                await self._initialize_runtime(runtime)
                user_message = ACPTranscriptSerializer.serialize(messages)
                new_history_state = HistoryState(
                    message_count=len(messages),
                    prefix_hash=self._hash_messages_prefix(messages, len(messages)),
                )
            # Same message list as last successful prompt (e.g. client retry).
            elif len(messages) == n:
                user_message = self._extract_user_message_as_string(messages)
                new_history_state = state
            # Append-only: agent already saw messages[:n]; ship incremental context.
            else:
                user_message = ACPTranscriptSerializer.serialize_tail(messages, n)
                if not user_message.strip():
                    user_message = self._extract_user_message_as_string(messages)
                new_history_state = HistoryState(
                    message_count=len(messages),
                    prefix_hash=self._hash_messages_prefix(messages, len(messages)),
                )

        if not user_message:
            raise BackendError(message="No user message found in request")

        requested_model = request.effective_model or add_vendor_prefix(
            runtime.model,
            self.VENDOR_PREFIX,
        )
        prompt_params: dict[str, Any] = {
            "sessionId": runtime.session_id,
            "prompt": [{"type": "text", "text": user_message}],
            "messageId": str(uuid.uuid4()),
        }
        prompt_request_id = await self._send_jsonrpc_message(
            runtime,
            "session/prompt",
            prompt_params,
        )
        runtime.history_state = new_history_state
        return prompt_request_id, requested_model

    async def _stream_response_with_lock(
        self,
        runtime: ACPProcessRuntime,
        requested_model: str,
        prompt_request_id: int,
    ) -> AsyncGenerator[ProcessedResponse, None]:
        try:
            async for chunk in self._stream_response(
                runtime, requested_model, prompt_request_id
            ):
                yield chunk
        finally:
            if runtime.cancellation_event is not None:
                runtime.cancellation_event.clear()
            await self._schedule_stale_kill_after_turn(runtime)
            await self._release_runtime_request_lock(runtime)

    async def _release_runtime_request_lock(self, runtime: ACPProcessRuntime) -> None:
        if runtime.request_lock is not None and runtime.request_lock.locked():
            runtime.request_lock.release()

    async def _wait_for_process_exit(
        self,
        process: subprocess.Popen[bytes],
        timeout_s: float,
    ) -> bool:
        if process.poll() is not None:
            return True
        try:
            await asyncio.wait_for(
                asyncio.to_thread(process.wait),
                timeout=timeout_s,
            )
            return True
        except asyncio.TimeoutError:
            return False
        except Exception:
            return process.poll() is not None

    async def _attempt_graceful_acp_cancel(
        self,
        runtime: ACPProcessRuntime,
        request_id: int,
        total_timeout_s: float,
    ) -> bool:
        process = runtime.process
        if process is None or process.poll() is not None:
            return True

        deadline = time.monotonic() + total_timeout_s
        for method in ACP_CANCEL_METHODS:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return False
            try:
                await self._send_jsonrpc_message(
                    runtime,
                    method,
                    {
                        "sessionId": runtime.session_id,
                        "requestId": request_id,
                        "messageId": str(request_id),
                    },
                )
            except Exception:
                if logger.isEnabledFor(logging.DEBUG):
                    logger.debug("ACP cancel method %s failed or not supported", method)
                continue

            exited = await self._wait_for_process_exit(
                process,
                timeout_s=min(remaining, 1.5),
            )
            if exited:
                return True

        if process.stdin is not None:
            with contextlib.suppress(OSError, ValueError):
                process.stdin.close()
            remaining = deadline - time.monotonic()
            if remaining > 0 and await self._wait_for_process_exit(
                process,
                timeout_s=min(remaining, 3.0),
            ):
                return True

        return process.poll() is not None

    async def _cancel_active_request(
        self,
        runtime: ACPProcessRuntime,
        prompt_request_id: int,
    ) -> None:
        if runtime.cancellation_event is not None:
            runtime.cancellation_event.set()

        try:
            if runtime.cancellation_lock is None:
                await self._kill_runtime(runtime)
                await self._release_runtime_request_lock(runtime)
                return

            async with runtime.cancellation_lock:
                process = runtime.process
                if process is None or process.poll() is not None:
                    await self._release_runtime_request_lock(runtime)
                    return

                if logger.isEnabledFor(logging.INFO):
                    logger.info(
                        "Cancelling active ACP request (pid=%s), "
                        "attempting graceful ACP cancellation then process kill",
                        process.pid,
                    )

                graceful_cancelled = await self._attempt_graceful_acp_cancel(
                    runtime,
                    request_id=prompt_request_id,
                    total_timeout_s=ACP_GRACEFUL_CANCEL_TIMEOUT_SECONDS,
                )

                if graceful_cancelled:
                    if logger.isEnabledFor(logging.INFO):
                        logger.info(
                            "ACP process (pid=%s) exited gracefully after cancellation",
                            process.pid,
                        )
                    self._cleanup_runtime_state(runtime, process)
                else:
                    if logger.isEnabledFor(logging.WARNING):
                        logger.warning(
                            "ACP process (pid=%s) did not exit gracefully, force-killing",
                            process.pid,
                        )
                    await self._kill_runtime(runtime)

                await self._release_runtime_request_lock(runtime)
        finally:
            if runtime.cancellation_event is not None:
                runtime.cancellation_event.clear()

    async def chat_completions(  # type: ignore[override]
        self,
        request: ConnectorChatCompletionsRequest,
    ) -> ResponseEnvelope | StreamingResponseEnvelope:
        if (
            request.cancellation_coordinator is not None
            and request.cancellation_token is not None
        ):
            request.cancellation_coordinator.ensure_not_cancelled(
                request.cancellation_token
            )
        if not self.is_backend_functional():
            raise ServiceUnavailableError(
                message=f"{self.backend_type} backend not initialized",
                details={"initialization_failed": self._initialization_failed},
            )

        runtime = await self._acquire_runtime(request)
        if runtime.request_lock is None:
            raise BackendError(message="ACP runtime is missing request lock")

        # Streaming holds the per-runtime lock for the full SSE response so idle reap
        # cannot swap the pool entry until the stream completes (see ``_reap_idle_runtime``).
        if bool(getattr(request.request, "stream", False)):
            await runtime.request_lock.acquire()
            try:
                prompt_request_id, requested_model = (
                    await self._prepare_prompt_request_locked(runtime, request)
                )
            except Exception:
                runtime.request_lock.release()
                raise

            async def _cancel_streaming_request() -> None:
                await self._cancel_active_request(runtime, prompt_request_id)

            stream_id: str | None = getattr(request.request, "session_id", None)
            if not stream_id and request.context is not None:
                stream_id = request.context.session_id

            async def _stream_with_keepalive() -> AsyncIterator[ProcessedResponse]:
                inner = self._stream_response_with_lock(
                    runtime, requested_model, prompt_request_id
                )
                async for chunk in wrap_processed_stream_with_idle_keepalive(
                    inner,
                    keepalive_interval=self._resolve_stream_keepalive_interval(),
                    idle_timeout=None,
                    stream_id=stream_id,
                    model_name=requested_model,
                    on_idle_timeout=None,
                ):
                    yield chunk

            return StreamingResponseEnvelope(
                content=_stream_with_keepalive(),
                media_type="text/event-stream",
                headers={},
                cancel_callback=_cancel_streaming_request,
            )

        async with runtime.request_lock:
            prompt_request_id, requested_model = (
                await self._prepare_prompt_request_locked(runtime, request)
            )
            cancellable_registered = False
            if (
                request.cancellation_coordinator is not None
                and request.cancellation_token is not None
            ):
                cancellable = _RuntimeCancellable(self, runtime, prompt_request_id)
                request.cancellation_coordinator.register_cancellable(
                    request.cancellation_token, cancellable
                )
                cancellable_registered = True
            try:
                fragments: list[str] = []
                reasoning_fragments: list[str] = []
                async for piece in self._iter_acp_stream_pieces(
                    runtime, prompt_request_id, requested_model
                ):
                    if piece.content:
                        fragments.append(piece.content)
                    if piece.reasoning_content:
                        reasoning_fragments.append(piece.reasoning_content)
                full_response = "".join(fragments)
                full_reasoning = (
                    "".join(reasoning_fragments) if reasoning_fragments else None
                )

                response = CanonicalChatResponse(
                    id=str(uuid.uuid4()),
                    object="chat.completion",
                    created=int(time.time()),
                    model=requested_model,
                    choices=[
                        ChatCompletionChoice(
                            index=0,
                            message=ChatCompletionChoiceMessage(
                                role="assistant",
                                content=full_response,
                                reasoning_content=full_reasoning,
                            ),
                            finish_reason="stop",
                        )
                    ],
                )
                envelope = ResponseEnvelope(
                    content=response.model_dump(exclude_none=True),
                    headers={},
                    status_code=200,
                )
                return self.ensure_usage_in_response(
                    envelope, list(request.processed_messages), requested_model
                )
            finally:
                if (
                    cancellable_registered
                    and request.cancellation_coordinator is not None
                    and request.cancellation_token is not None
                ):
                    request.cancellation_coordinator.cleanup(request.cancellation_token)
                await self._schedule_stale_kill_after_turn(runtime)

    async def shutdown(self) -> None:
        await self._kill_all_runtimes()

    def __del__(self) -> None:
        runtimes = getattr(self, "_runtimes", None)
        if not isinstance(runtimes, dict):
            return
        for runtime in runtimes.values():
            process = getattr(runtime, "process", None)
            if process is None:
                continue
            try:
                if process.poll() is None:
                    if os.name == "nt":
                        subprocess.run(
                            ["taskkill", "/PID", str(process.pid), "/T", "/F"],
                            capture_output=True,
                            check=False,
                            shell=False,
                        )
                    else:
                        process.terminate()
                    with contextlib.suppress(subprocess.TimeoutExpired):
                        process.wait(timeout=5)
            except Exception:
                pass
            finally:
                self._cleanup_process(process)

    async def __aenter__(self) -> BaseAcpConnector:
        return self

    async def __aexit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        _ = exc_type, exc_val, exc_tb
        await self.shutdown()
