from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import os
import subprocess
import time
import uuid
from collections.abc import AsyncGenerator, Sequence
from pathlib import Path
from typing import Any

import httpx

from src.connectors.base import add_vendor_prefix, strip_vendor_prefix
from src.connectors.contracts import ConnectorChatCompletionsRequest
from src.core.common.exceptions import (
    APIConnectionError,
    APITimeoutError,
    BackendError,
    ConfigurationError,
    ServiceUnavailableError,
)
from src.core.config.app_config import AppConfig
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
from src.core.services.backend_registry import backend_registry
from src.core.services.translation_service import TranslationService

from .gemini import GeminiBackend
from .gemini_base.config import get_shared_gemini_fallback_models
from .gemini_cli_acp_types import (
    ACPNotification,
    ACPSessionUpdate,
    ACPUpdateContent,
    GeminiCliRuntime,
)

logger = logging.getLogger(__name__)

DEFAULT_PROCESS_TIMEOUT = 300.0
DEFAULT_IDLE_TIMEOUT = 30.0
MAX_RESPONSE_LINE_SIZE = 10 * 1024 * 1024
ACP_PROTOCOL_VERSION = 1
ACP_UPDATE_METHOD = "session/update"
ACP_AGENT_MESSAGE_CHUNK = "agent_message_chunk"


class GeminiCliAcpConnector(GeminiBackend):
    """Gemini CLI backend using Agent Control Protocol over stdio."""

    backend_type: str = "gemini-cli-acp"

    def __init__(
        self,
        client: httpx.AsyncClient,
        config: AppConfig,
        translation_service: TranslationService,
        **_: Any,
    ) -> None:
        super().__init__(client, config, translation_service)
        self.name = "gemini-cli-acp"
        self.is_functional = False
        self._initialization_failed = False
        self._validation_errors: list[str] = []
        self._default_project_dir: Path | None = None
        self._gemini_cli_executable = "gemini"
        self._model = "gemini-2.5-flash"
        self._auto_accept = True
        self._process_timeout = DEFAULT_PROCESS_TIMEOUT
        self._idle_timeout = DEFAULT_IDLE_TIMEOUT
        self._runtime_pool_lock = asyncio.Lock()
        self._runtimes: dict[tuple[str, str], GeminiCliRuntime] = {}

    @property
    def has_static_credentials(self) -> bool:
        return False

    def is_backend_functional(self) -> bool:
        return (
            self.is_functional
            and not self._initialization_failed
            and len(self._validation_errors) == 0
        )

    def get_validation_errors(self) -> list[str]:
        return self._validation_errors.copy()

    async def initialize(self, **kwargs: Any) -> None:
        try:
            configured_project_dir = (
                kwargs.get("project_dir")
                or kwargs.get("workspace_path")
                or os.getenv("GEMINI_CLI_WORKSPACE")
                or os.getcwd()
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
            result = await asyncio.to_thread(
                subprocess.run,
                [self._gemini_cli_executable, "--version"],
                capture_output=True,
                timeout=5,
                check=False,
                shell=False,
            )
            return result.returncode == 0
        except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
            return False

    @staticmethod
    def _is_usable_directory(path: Path) -> bool:
        return path.exists() and path.is_dir() and os.access(path, os.R_OK)

    def _build_runtime_key(self, project_dir: Path, model: str) -> tuple[str, str]:
        return (str(project_dir), model)

    def _create_runtime(self, project_dir: Path, model: str) -> GeminiCliRuntime:
        return GeminiCliRuntime(
            project_dir=project_dir,
            model=model,
            process_lock=asyncio.Lock(),
            request_lock=asyncio.Lock(),
        )

    async def _acquire_runtime(
        self, request: ConnectorChatCompletionsRequest
    ) -> GeminiCliRuntime:
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
                    "Ignoring unusable Gemini ACP project_dir override: %s",
                    override,
                )

        if self._default_project_dir is None:
            raise ConfigurationError(
                message="gemini-cli-acp backend has no default project directory configured"
            )

        return self._default_project_dir

    async def _reap_idle_runtime(self, runtime: GeminiCliRuntime) -> None:
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

    async def _spawn_gemini_cli_process(self, runtime: GeminiCliRuntime) -> None:
        assert runtime.process_lock is not None
        async with runtime.process_lock:
            process = runtime.process
            if process is not None and process.poll() is None:
                return

            cmd = [
                self._gemini_cli_executable,
                "--experimental-acp",
                "--model",
                runtime.model,
            ]
            if self._auto_accept:
                cmd.append("-y")

            new_process: subprocess.Popen[bytes] | None = None
            try:
                new_process = subprocess.Popen(
                    cmd,
                    stdin=subprocess.PIPE,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    cwd=str(runtime.project_dir),
                    shell=False,
                    creationflags=(
                        subprocess.CREATE_NEW_PROCESS_GROUP if os.name == "nt" else 0
                    ),
                )
                runtime.process = new_process
                await asyncio.sleep(0.1)
                if new_process.poll() is not None:
                    stderr = await self._read_stderr(new_process)
                    raise BackendError(
                        message="gemini-cli process failed to start",
                        details={
                            "stderr": stderr,
                            "project_dir": str(runtime.project_dir),
                            "model": runtime.model,
                        },
                    )
                runtime.last_activity = time.monotonic()
                runtime.initialized = False
                runtime.session_id = None
                runtime.message_id = 0
            except Exception as exc:
                if new_process is not None:
                    self._cleanup_process(new_process)
                runtime.process = None
                runtime.initialized = False
                runtime.session_id = None
                raise APIConnectionError(
                    message=f"Failed to start gemini-cli: {exc}",
                    details={
                        "executable": self._gemini_cli_executable,
                        "project_dir": str(runtime.project_dir),
                        "model": runtime.model,
                    },
                ) from exc

    async def _kill_runtime(self, runtime: GeminiCliRuntime) -> None:
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
        runtime: GeminiCliRuntime,
        process: subprocess.Popen[bytes] | None = None,
    ) -> None:
        self._cleanup_process(process or runtime.process)
        runtime.process = None
        runtime.initialized = False
        runtime.session_id = None
        runtime.message_id = 0
        runtime.last_activity = 0.0

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

    def _get_next_message_id(self, runtime: GeminiCliRuntime) -> int:
        runtime.message_id += 1
        return runtime.message_id

    async def _send_jsonrpc_message(
        self,
        runtime: GeminiCliRuntime,
        method: str,
        params: dict[str, Any],
    ) -> int:
        process = runtime.process
        if process is None or process.stdin is None:
            raise BackendError(message="gemini-cli process not running")

        message_id = self._get_next_message_id(runtime)
        payload = {
            "jsonrpc": "2.0",
            "method": method,
            "params": params,
            "id": message_id,
        }
        encoded = (json.dumps(payload) + "\n").encode("utf-8")

        def _write() -> None:
            assert process.stdin is not None
            process.stdin.write(encoded)
            process.stdin.flush()

        try:
            await asyncio.to_thread(_write)
            runtime.last_activity = time.monotonic()
            return message_id
        except Exception as exc:
            raise APIConnectionError(
                message=f"Failed to communicate with gemini-cli: {exc}"
            ) from exc

    async def _read_jsonrpc_message(
        self, runtime: GeminiCliRuntime
    ) -> ACPNotification | None:
        process = runtime.process
        if process is None or process.stdout is None:
            raise BackendError(message="gemini-cli process not running")

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
                        message="gemini-cli process exited unexpectedly",
                        details={
                            "stderr": stderr,
                            "project_dir": str(runtime.project_dir),
                            "model": runtime.model,
                        },
                    )
                return None
            if len(line) > MAX_RESPONSE_LINE_SIZE:
                raise BackendError(message="Response too large from gemini-cli")
            runtime.last_activity = time.monotonic()
            data = json.loads(line.decode("utf-8"))
            if not isinstance(data, dict):
                raise BackendError(message="Invalid non-object JSON response")
            return ACPNotification(**data)
        except json.JSONDecodeError as exc:
            raise BackendError(
                message="Invalid JSON response from gemini-cli",
                details={"error": str(exc)},
            ) from exc
        except BackendError:
            raise
        except Exception as exc:
            raise APIConnectionError(
                message=f"Failed to read from gemini-cli: {exc}"
            ) from exc

    async def _await_response(
        self,
        runtime: GeminiCliRuntime,
        request_id: int,
    ) -> ACPNotification:
        deadline = time.monotonic() + self._process_timeout
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise APITimeoutError(
                    message="Timeout waiting for gemini-cli response",
                    details={"timeout": self._process_timeout, "model": runtime.model},
                )

            response = await asyncio.wait_for(
                self._read_jsonrpc_message(runtime),
                timeout=remaining,
            )
            if response is None:
                continue
            if response.id != request_id:
                continue
            return response

    async def _initialize_runtime(self, runtime: GeminiCliRuntime) -> None:
        if runtime.initialized and runtime.session_id:
            return

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
        runtime: GeminiCliRuntime,
        prompt_request_id: int,
        response_model: str,
    ) -> AsyncGenerator[str, None]:
        try:
            while True:
                response = await asyncio.wait_for(
                    self._read_jsonrpc_message(runtime),
                    timeout=self._process_timeout,
                )
                if response is None:
                    continue

                if response.id == prompt_request_id:
                    if response.is_error and response.error is not None:
                        raise BackendError(
                            message=f"gemini-cli error: {response.error.message}",
                            details=response.error.model_dump(),
                        )
                    break

                text = self._extract_text_fragment(response)
                if text:
                    yield text
        except asyncio.TimeoutError as exc:
            raise APITimeoutError(
                message="Timeout waiting for gemini-cli response",
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
        runtime: GeminiCliRuntime,
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
        runtime: GeminiCliRuntime,
        request: ConnectorChatCompletionsRequest,
    ) -> tuple[int, str]:
        await self._spawn_gemini_cli_process(runtime)
        await self._initialize_runtime(runtime)

        user_message = self._extract_user_message_as_string(request.processed_messages)
        if not user_message:
            raise BackendError(message="No user message found in request")

        requested_model = request.effective_model or add_vendor_prefix(
            runtime.model,
            self.VENDOR_PREFIX,
        )
        prompt_request_id = await self._send_jsonrpc_message(
            runtime,
            "session/prompt",
            {
                "sessionId": runtime.session_id,
                "prompt": [{"type": "text", "text": user_message}],
                "messageId": str(uuid.uuid4()),
            },
        )
        return prompt_request_id, requested_model

    async def _stream_response_with_lock(
        self,
        runtime: GeminiCliRuntime,
        requested_model: str,
        prompt_request_id: int,
    ) -> AsyncGenerator[ProcessedResponse, None]:
        try:
            async for chunk in self._stream_response(
                runtime, requested_model, prompt_request_id
            ):
                yield chunk
        finally:
            await self._release_runtime_request_lock(runtime)

    async def _release_runtime_request_lock(self, runtime: GeminiCliRuntime) -> None:
        if runtime.request_lock is not None and runtime.request_lock.locked():
            runtime.request_lock.release()

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
                message="gemini-cli-acp backend not initialized",
                details={"initialization_failed": self._initialization_failed},
            )

        runtime = await self._acquire_runtime(request)
        if runtime.request_lock is None:
            raise BackendError(message="Gemini ACP runtime is missing request lock")

        if bool(getattr(request.request, "stream", False)):
            await runtime.request_lock.acquire()
            try:
                prompt_request_id, requested_model = (
                    await self._prepare_prompt_request_locked(runtime, request)
                )
            except Exception:
                runtime.request_lock.release()
                raise
            return StreamingResponseEnvelope(
                content=self._stream_response_with_lock(
                    runtime, requested_model, prompt_request_id
                ),
                media_type="text/event-stream",
                headers={},
                cancel_callback=lambda: self._release_runtime_request_lock(runtime),
            )

        async with runtime.request_lock:
            prompt_request_id, requested_model = (
                await self._prepare_prompt_request_locked(runtime, request)
            )
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

    def get_available_models(self) -> list[str]:
        raw_models = get_shared_gemini_fallback_models()
        return [add_vendor_prefix(model, self.VENDOR_PREFIX) for model in raw_models]

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

    async def __aenter__(self) -> GeminiCliAcpConnector:
        return self

    async def __aexit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        _ = exc_type, exc_val, exc_tb
        await self.shutdown()


backend_registry.register_backend("gemini-cli-acp", GeminiCliAcpConnector)
