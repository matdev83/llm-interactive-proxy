from __future__ import annotations

import asyncio
import contextlib
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

from src.connectors.acp_core.transcript import ACPTranscriptSerializer
from src.connectors.acp_core.types import (
    ACPNotification,
    ACPProcessRuntime,
    ACPSessionUpdate,
    ACPUpdateContent,
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
ACP_CANCEL_METHODS = ("session/cancel", "session/stop", "session/end")
ACP_GRACEFUL_CANCEL_TIMEOUT_SECONDS = 12.0


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
        self._runtimes: dict[tuple[str, str], ACPProcessRuntime] = {}

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
        return path.exists() and path.is_dir() and os.access(path, os.R_OK)

    def _build_runtime_key(self, project_dir: Path, model: str) -> tuple[str, str]:
        return (str(project_dir), model)

    def _create_runtime(self, project_dir: Path, model: str) -> ACPProcessRuntime:
        return ACPProcessRuntime(
            project_dir=project_dir,
            model=model,
            process_lock=asyncio.Lock(),
            request_lock=asyncio.Lock(),
            cancellation_lock=asyncio.Lock(),
            cancellation_event=asyncio.Event(),
        )

    async def _acquire_runtime(
        self, request: ConnectorChatCompletionsRequest
    ) -> ACPProcessRuntime:
        project_dir = self._resolve_project_dir_for_request(request)
        requested_model = strip_vendor_prefix(
            request.effective_model or self._model,
            self.VENDOR_PREFIX,
        )
        runtime_key = self._build_runtime_key(project_dir, requested_model)

        async with self._runtime_pool_lock:
            runtime = self._runtimes.get(runtime_key)
            if runtime is None:
                runtime = self._create_runtime(project_dir, requested_model)
                self._runtimes[runtime_key] = runtime

        await self._reap_idle_runtime(runtime)
        return runtime

    def _resolve_project_dir_override(
        self, request: ConnectorChatCompletionsRequest
    ) -> str | None:
        candidates: list[dict[str, Any]] = []
        extra_body = getattr(request.request, "extra_body", None)
        if isinstance(extra_body, dict):
            candidates.append(extra_body)
        if isinstance(request.options, dict):
            candidates.append(request.options)

        for candidate in candidates:
            for key in ("project_dir", "workspace_path", "cwd", "project"):
                value = candidate.get(key)
                if isinstance(value, str) and value.strip():
                    return value
        return None

    def _resolve_project_dir_for_request(
        self, request: ConnectorChatCompletionsRequest
    ) -> Path:
        override = self._resolve_project_dir_override(request)
        if override is not None:
            candidate = Path(override).expanduser().resolve()
            if self._is_usable_directory(candidate):
                return candidate
            if logger.isEnabledFor(logging.DEBUG):
                logger.debug(
                    "Ignoring unusable ACP project_dir override: %s",
                    override,
                )

        if self._default_project_dir is None:
            raise ConfigurationError(
                message=f"{self.backend_type} backend has no default project directory configured"
            )

        return self._default_project_dir

    async def _reap_idle_runtime(self, runtime: ACPProcessRuntime) -> None:
        if self._idle_timeout <= 0:
            return
        if runtime.request_lock is None or runtime.request_lock.locked():
            return
        if runtime.process is None:
            return
        if runtime.last_activity <= 0:
            return
        if (time.monotonic() - runtime.last_activity) < self._idle_timeout:
            return
        await self._kill_runtime(runtime)

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
                runtime.history_injected = False
            except Exception as exc:
                if new_process is not None:
                    self._cleanup_process(new_process)
                runtime.process = None
                runtime.initialized = False
                runtime.session_id = None
                runtime.history_injected = False
                raise APIConnectionError(
                    message=f"Failed to start ACP process: {exc}",
                    details={
                        "project_dir": str(runtime.project_dir),
                        "model": runtime.model,
                    },
                ) from exc

    async def _kill_runtime(self, runtime: ACPProcessRuntime) -> None:
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
        runtime.history_injected = False

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

    def _extract_text_fragment(self, response: ACPNotification) -> str | None:
        if response.method != ACP_UPDATE_METHOD or response.params is None:
            return None
        update = ACPSessionUpdate(**response.params)
        if update.update.get("sessionUpdate") != ACP_AGENT_MESSAGE_CHUNK:
            return None
        content = update.update.get("content")
        if not isinstance(content, dict):
            return None
        normalized_content = ACPUpdateContent(**content)
        if normalized_content.type != "text":
            return None
        return normalized_content.text

    async def _iter_text_fragments(
        self,
        runtime: ACPProcessRuntime,
        prompt_request_id: int,
        response_model: str,
    ) -> AsyncGenerator[str, None]:
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
                    break

                text = self._extract_text_fragment(response)
                if text:
                    yield text
        except asyncio.TimeoutError as exc:
            raise APITimeoutError(
                message="Timeout waiting for ACP response",
                details={"timeout": self._process_timeout, "model": response_model},
            ) from exc

    def _create_sse_chunk(self, text: str, model: str, chunk_id: str) -> str:
        payload = {
            "id": chunk_id,
            "object": "chat.completion.chunk",
            "created": int(time.time()),
            "model": model,
            "choices": [
                {
                    "index": 0,
                    "delta": {"content": text},
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
            async for text in self._iter_text_fragments(
                runtime, prompt_request_id, requested_model
            ):
                yield ProcessedResponse(
                    content=self._create_sse_chunk(text, requested_model, chunk_id)
                )
        finally:
            yield ProcessedResponse(content=self._create_sse_done_chunk())

    async def _prepare_prompt_request_locked(
        self,
        runtime: ACPProcessRuntime,
        request: ConnectorChatCompletionsRequest,
    ) -> tuple[int, str]:
        await self._spawn_process(runtime)
        await self._initialize_runtime(runtime)

        if not runtime.history_injected:
            user_message = ACPTranscriptSerializer.serialize(request.processed_messages)
            runtime.history_injected = True
        else:
            user_message = self._extract_user_message_as_string(
                request.processed_messages
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
                async for text in self._iter_text_fragments(
                    runtime, prompt_request_id, requested_model
                ):
                    fragments.append(text)
                full_response = "".join(fragments)

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
