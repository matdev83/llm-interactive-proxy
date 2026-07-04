"""OpenAI Codex App Server backend (codex app-server over stdio JSON-RPC).

Launches the Codex CLI in app-server mode over stdio and speaks the Codex
JSON-RPC 2.0 protocol (``initialize`` -> ``initialized`` -> ``thread/start`` ->
``turn/start`` -> stream notifications until ``turn/completed``). This is a
local-agent backend that uses the user's personal Codex login (OAuth-style), so
it is treated as an OAuth connector and is not loaded in production Multi User
Mode.

The connector subclasses :class:`BaseAcpConnector` and overrides only the
Codex-specific pieces (subprocess command, handshake, server-request handling,
event mapper, turn preparation with a deferred history-state commit,
non-streaming accumulation, graceful ``turn/interrupt`` cancellation, and
protocol-specific runtime-state reset). The pooled subprocess lifecycle and the
JSON-RPC stdio transport are inherited from the ACP base. Pure helpers and the
Codex event mapper live in :mod:`src.connectors.codex_helpers` and
:mod:`src.connectors.codex_event_mapper`.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import os
import subprocess
import time
import uuid
from collections.abc import AsyncGenerator
from pathlib import Path
from typing import Any

import httpx

from src.connectors.acp_core.base_connector import BaseAcpConnector
from src.connectors.acp_core.types import (
    ACPNotification,
    AcpStreamPiece,
    CodexAppServerRuntime,
)
from src.connectors.acp_core.workspace_policy import resolve_backend_init_acp_workspace
from src.connectors.base import add_vendor_prefix
from src.connectors.codex_event_mapper import (
    CODEX_TURN_COMPLETED_METHOD,
    CodexEventMapper,
    CodexStreamPiece,
    accumulate_pieces,
)
from src.connectors.codex_helpers import (
    build_codex_app_server_command,
    build_turn_interrupt_payload,
    candidate_codex_executables,
    decide_codex_server_request,
    is_auto_model,
    map_reasoning_effort_to_codex_effort,
    sanitize_approval_summary,
    strip_openai_model_prefix,
)
from src.connectors.codex_helpers import (
    resolve_codex_executable as resolve_codex_executable,
)
from src.connectors.contracts import ConnectorChatCompletionsRequest
from src.core.common.exceptions import (
    APIConnectionError,
    APITimeoutError,
    BackendError,
    ConfigurationError,
)
from src.core.config.app_config import AppConfig
from src.core.domain.chat import (
    CanonicalChatResponse,
    ChatCompletionChoice,
    ChatCompletionChoiceMessage,
)
from src.core.domain.responses import ResponseEnvelope
from src.core.services.translation_service import TranslationService

logger = logging.getLogger(__name__)

CODEX_TURN_INTERRUPT_METHOD = "turn/interrupt"
CODEX_HANDSHAKE_CLIENT_NAME = "llm-interactive-proxy"

# Default model list advertised by this backend (model is "auto" by default and
# resolved server-side by the Codex app-server).
_DEFAULT_CODEX_MODEL_IDS: tuple[str, ...] = (
    "auto",
    "gpt-5.4",
    "gpt-5.3-codex",
    "gpt-5.2",
)


# ---------------------------------------------------------------------------
# Connector
# ---------------------------------------------------------------------------


class OpenAICodexAppServerConnector(BaseAcpConnector[CodexAppServerRuntime]):
    """OpenAI Codex App Server backend (Codex CLI app-server over stdio)."""

    backend_type: str = "openai-codex-app-server"
    VENDOR_PREFIX: str = "openai"
    requires_explicit_workspace: bool = True

    def __init__(
        self,
        client: httpx.AsyncClient,
        config: AppConfig,
        translation_service: TranslationService | None = None,
        **_: Any,
    ) -> None:
        super().__init__(config, translation_service=translation_service)
        self.client = client
        self.name = "openai-codex-app-server"
        self._codex_executable: str = "codex"
        self._progress_mode: str = "text_plus_summaries"
        self._codex_config_overrides: list[str] = []
        self._app_server_extra_args: list[str] = []

    # -- lifecycle / health --------------------------------------------------

    async def initialize(self, **kwargs: Any) -> None:
        try:
            workspace, cfg_err = resolve_backend_init_acp_workspace(
                project_dir=kwargs.get("project_dir"),
                workspace_path=kwargs.get("workspace_path"),
                env_workspace=os.getenv("OPENAI_CODEX_APP_SERVER_WORKSPACE"),
                env_source_label="OPENAI_CODEX_APP_SERVER_WORKSPACE",
                is_usable=self._is_usable_directory,
            )
            if cfg_err:
                raise ConfigurationError(
                    message=cfg_err,
                    details={"error_code": "openai_codex_app_server_workspace_invalid"},
                )
            self._default_project_dir = workspace

            exe_kw = kwargs.get("codex_executable")
            configured_exe = str(exe_kw) if exe_kw else self._codex_executable
            candidates = candidate_codex_executables(configured_exe if exe_kw else None)
            if not candidates:
                raise ConfigurationError(
                    message="Codex CLI (codex) executable not found",
                    details={
                        "configured": configured_exe,
                        "hint": "Install Codex CLI and ensure `codex` is on PATH, "
                        "or set CODEX_BIN to the full path to the codex binary.",
                    },
                )

            configured_model = str(kwargs.get("model") or self._model)
            self._model = strip_openai_model_prefix(configured_model)
            self._process_timeout = float(
                kwargs.get("process_timeout", self._process_timeout)
            )
            self._idle_timeout = float(kwargs.get("idle_timeout", self._idle_timeout))
            self._progress_mode = str(kwargs.get("progress_mode", self._progress_mode))

            overrides = kwargs.get("codex_config_overrides") or []
            if isinstance(overrides, list):
                self._codex_config_overrides = [str(x) for x in overrides]
            else:
                self._codex_config_overrides = []

            extra = (
                kwargs.get("codex_app_server_extra_args")
                or kwargs.get("app_server_extra_args")
                or []
            )
            if isinstance(extra, list):
                self._app_server_extra_args = [str(x) for x in extra]
            else:
                self._app_server_extra_args = []

            # Probe-and-pick: try each candidate; the first that passes BOTH
            # the ``--version`` check and the app-server JSON-RPC probe wins.
            # This catches wrapper collisions (e.g. a ``codex.cmd`` shim that
            # already injects ``--dangerously-bypass-approvals-and-sandbox``):
            # such a wrapper fails the app-server probe, so the loop falls
            # through to the next candidate instead of failing initialization.
            tried: list[str] = []
            chosen: str | None = None
            for candidate in candidates:
                tried.append(candidate)
                if not await self._check_codex_available(candidate):
                    continue
                if await self._probe_app_server(candidate):
                    chosen = candidate
                    break

            if chosen is None:
                raise ConfigurationError(
                    message=(
                        "Codex app-server probe failed: none of the candidate "
                        "executables started a JSON-RPC app-server with the "
                        "configured launch flags "
                        "(--dangerously-bypass-approvals-and-sandbox --search "
                        "app-server --stdio). If `codex` on PATH is a wrapper "
                        "that already injects these flags, set CODEX_BIN or "
                        "`codex_executable` to the raw Codex binary."
                    ),
                    details={
                        "configured": configured_exe,
                        "tried_candidates": tried,
                        "hint": "Set CODEX_BIN to the raw Codex binary, or "
                        "install codex on PATH without wrapper flag injection.",
                    },
                )

            self._codex_executable = chosen
            self._validation_errors = []
            self._initialization_failed = False
            self.is_functional = True
        except Exception:
            self._initialization_failed = True
            self.is_functional = False
            self._validation_errors = ["openai-codex-app-server initialization failed"]
            raise

    async def _check_codex_available(self, executable: str | None = None) -> bool:
        exe = executable if executable is not None else self._codex_executable
        try:
            result = await asyncio.to_thread(
                subprocess.run,
                [exe, "--version"],
                capture_output=True,
                timeout=15,
                check=False,
                shell=False,
            )
            return result.returncode == 0
        except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
            return False

    async def _probe_app_server(self, executable: str) -> bool:
        """Spawn the real app-server command and confirm it speaks JSON-RPC.

        Catches wrapper collisions (e.g. a ``codex.cmd`` shim that already
        injects the global flags): a colliding wrapper exits at CLI parse time,
        so the probe returns False and the caller falls through to the next
        candidate instead of failing on every later chat request. The probe
        process is always terminated in the ``finally`` (no orphan).
        """

        cmd = build_codex_app_server_command(
            executable,
            codex_config_overrides=self._codex_config_overrides,
            app_server_extra_args=self._app_server_extra_args,
        )
        proc: subprocess.Popen[bytes] | None = None
        try:
            try:
                proc = await asyncio.to_thread(
                    subprocess.Popen,
                    cmd,
                    stdin=subprocess.PIPE,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    shell=False,
                    env=os.environ.copy(),
                    creationflags=(
                        subprocess.CREATE_NEW_PROCESS_GROUP if os.name == "nt" else 0
                    ),
                )
            except (OSError, FileNotFoundError, subprocess.SubprocessError):
                return False

            initialize_line = (
                json.dumps(
                    {
                        "jsonrpc": "2.0",
                        "id": 1,
                        "method": "initialize",
                        "params": {
                            "clientInfo": {
                                "name": CODEX_HANDSHAKE_CLIENT_NAME,
                                "version": "1",
                            },
                            "capabilities": {"experimentalApi": True},
                        },
                    },
                    separators=(",", ":"),
                )
                + "\n"
            ).encode("utf-8")

            def _send_init() -> None:
                assert proc is not None
                assert proc.stdin is not None
                proc.stdin.write(initialize_line)
                proc.stdin.flush()

            try:
                await asyncio.to_thread(_send_init)
                assert proc is not None
                stdout = proc.stdout
                assert stdout is not None
                line = await asyncio.wait_for(
                    asyncio.to_thread(stdout.readline),
                    timeout=15.0,
                )
            except (asyncio.TimeoutError, OSError, ValueError):
                return False

            if not line:
                return False
            if proc.poll() is not None:
                return False
            try:
                data = json.loads(line.decode("utf-8"))
            except (json.JSONDecodeError, UnicodeDecodeError):
                return False
            if not isinstance(data, dict):
                return False
            return "result" in data or "error" in data or "jsonrpc" in data
        finally:
            if proc is not None:
                with contextlib.suppress(Exception):
                    await self._terminate_process(proc)
                with contextlib.suppress(Exception):
                    self._cleanup_process(proc)

    def get_available_models(self) -> list[str]:
        return [
            add_vendor_prefix(m, self.VENDOR_PREFIX) for m in _DEFAULT_CODEX_MODEL_IDS
        ]

    # -- command / runtime / protocol-state overrides -----------------------

    async def _build_subprocess_command(
        self, runtime: CodexAppServerRuntime
    ) -> list[str]:
        _ = runtime
        return build_codex_app_server_command(
            self._codex_executable,
            codex_config_overrides=self._codex_config_overrides,
            app_server_extra_args=self._app_server_extra_args,
        )

    def _create_runtime(
        self, project_dir: Path, model: str, client_session_id: str = "default"
    ) -> CodexAppServerRuntime:
        return CodexAppServerRuntime(
            project_dir=project_dir,
            model=model,
            client_session_id=client_session_id,
            process_lock=asyncio.Lock(),
            request_lock=asyncio.Lock(),
            cancellation_lock=asyncio.Lock(),
            cancellation_event=asyncio.Event(),
        )

    def _reset_protocol_runtime_state(self, runtime: CodexAppServerRuntime) -> None:
        runtime.thread_id = None
        runtime.turn_id = None
        runtime.pending_history_state = None

    # -- handshake ----------------------------------------------------------

    async def _perform_handshake(self, runtime: CodexAppServerRuntime) -> None:
        initialize_id = await self._send_jsonrpc_message(
            runtime,
            "initialize",
            {
                "clientInfo": {
                    "name": CODEX_HANDSHAKE_CLIENT_NAME,
                    "version": "1",
                },
                # ``runtimeWorkspaceRoots`` in ``thread/start`` is gated behind
                # the ``experimentalApi`` client capability on real Codex
                # app-servers. Declaring it here is required for ``thread/start``
                # to succeed.
                "capabilities": {"experimentalApi": True},
            },
        )
        initialize_response = await self._await_response(runtime, initialize_id)
        if initialize_response.is_error and initialize_response.error is not None:
            raise BackendError(
                message=f"Codex initialize failed: {initialize_response.error.message}",
                details=initialize_response.error.model_dump(),
            )

        await self._write_json_line(
            runtime,
            {"jsonrpc": "2.0", "method": "initialized", "params": {}},
        )

        thread_params: dict[str, Any] = {
            "cwd": str(runtime.project_dir),
            "runtimeWorkspaceRoots": [str(runtime.project_dir)],
        }
        if not is_auto_model(runtime.model):
            thread_params["model"] = runtime.model
        thread_request_id = await self._send_jsonrpc_message(
            runtime, "thread/start", thread_params
        )
        thread_response = await self._await_response(runtime, thread_request_id)
        if thread_response.is_error and thread_response.error is not None:
            raise BackendError(
                message=f"Codex thread/start failed: {thread_response.error.message}",
                details=thread_response.error.model_dump(),
            )

        result = thread_response.result or {}
        tid = result.get("id")
        if not isinstance(tid, str) or not tid.strip():
            thread_obj = result.get("thread")
            if isinstance(thread_obj, dict):
                tid = thread_obj.get("id")
        if not isinstance(tid, str) or not tid.strip():
            raise BackendError(
                message="Codex thread/start did not return a threadId",
                details={"result": result},
            )

        runtime.thread_id = tid
        runtime.initialized = True

    # -- server requests / approvals ---------------------------------------

    async def _handle_server_request(
        self, runtime: CodexAppServerRuntime, msg: ACPNotification
    ) -> None:
        assert msg.id is not None
        rid = msg.id
        method = msg.method or ""
        params = msg.params if isinstance(msg.params, dict) else {}

        result_payload, accepted = decide_codex_server_request(method, params)
        summary = sanitize_approval_summary(params)
        if accepted:
            if logger.isEnabledFor(logging.INFO):
                logger.info(
                    "Codex approval accepted method=%s %s (project=%s model=%s)",
                    method,
                    summary,
                    runtime.project_dir,
                    runtime.model,
                )
            await self._send_jsonrpc_result(runtime, rid, result_payload)
        else:
            if logger.isEnabledFor(logging.WARNING):
                logger.warning(
                    "Codex approval declined method=%s %s (project=%s model=%s)",
                    method,
                    summary,
                    runtime.project_dir,
                    runtime.model,
                )
            await self._write_json_line(
                runtime,
                {"jsonrpc": "2.0", "id": rid, "result": result_payload},
            )

    # -- turn request preparation ------------------------------------------

    def _resolve_reasoning_effort(
        self, request: ConnectorChatCompletionsRequest
    ) -> str | None:
        canonical = getattr(request.request, "reasoning_effort", None)
        if isinstance(canonical, str) and canonical.strip():
            return canonical

        options = request.options if isinstance(request.options, dict) else None
        extra_body = getattr(request.request, "extra_body", None)
        extra_dict = extra_body if isinstance(extra_body, dict) else None

        for source in (options, extra_dict):
            if not source:
                continue
            direct = source.get("reasoning_effort")
            if isinstance(direct, str) and direct.strip():
                return direct
            for key, value in source.items():
                if (
                    isinstance(key, str)
                    and key.lower() == "reasoning_effort"
                    and isinstance(value, str)
                    and value.strip()
                ):
                    return value
        return None

    async def _prepare_turn_request_locked(
        self,
        runtime: CodexAppServerRuntime,
        request: ConnectorChatCompletionsRequest,
    ) -> tuple[int, str]:
        """Build the ``turn/start`` text and JSON-RPC id under the request lock.

        Spawns + handshakes the Codex thread (killing the child on a failed
        initial handshake), computes the user message and new history state via
        the shared base helper, sends ``turn/start``, and stages
        ``pending_history_state`` (committed only on a successful
        ``turn/completed`` by ``_iter_codex_stream_pieces``). The ``turn/start``
        response is NOT awaited here -- ``_await_response`` would discard
        notifications (``id=None``) arriving before it; the stream iterator
        reads the response (capturing ``turn_id``) alongside notifications.
        """

        await self._cancel_stale_kill_timer(runtime)
        await self._spawn_process(runtime)
        if not (runtime.initialized and runtime.thread_id):
            try:
                await self._perform_handshake(runtime)
            except Exception:
                # A failed handshake leaves a broken child; kill it so the
                # next request respawns a fresh process instead of reusing the
                # half-initialized stdio session.
                await self._kill_runtime(runtime)
                raise

        messages = list(request.processed_messages)
        if not messages:
            raise BackendError(message="No messages found in request")

        user_message, new_history_state = await self._compute_history_and_user_message(
            runtime, messages
        )
        if not user_message:
            raise BackendError(message="No user message found in request")

        turn_params: dict[str, Any] = {
            "threadId": runtime.thread_id,
            "input": [{"type": "text", "text": user_message}],
        }

        reasoning_effort = self._resolve_reasoning_effort(request)
        effort = map_reasoning_effort_to_codex_effort(reasoning_effort)
        if effort is not None:
            turn_params["effort"] = effort

        # ``runtime.model`` stays stripped for the Codex protocol.
        if not is_auto_model(runtime.model):
            turn_params["model"] = runtime.model

        turn_request_id = await self._send_jsonrpc_message(
            runtime, "turn/start", turn_params
        )
        # Stage the new history state; commit only on a successful turn. A
        # failed turn/start response OR a later interrupted/failed turn
        # discards the pending state so ``runtime.history_state`` keeps its
        # prior value and a client retry hits the correct branch.
        runtime.pending_history_state = new_history_state

        requested_model = request.effective_model or add_vendor_prefix(
            runtime.model, self.VENDOR_PREFIX
        )
        return turn_request_id, requested_model

    # -- streaming read loop + SSE chunk builders ---------------------------

    async def _iter_codex_stream_pieces(
        self,
        runtime: CodexAppServerRuntime,
        turn_request_id: int,
        response_model: str,
    ) -> AsyncGenerator[CodexStreamPiece, None]:
        mapper = CodexEventMapper(self._progress_mode)
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

                # The ``turn/start`` response (id == turn_request_id) carries
                # the turn object in ``result``; it is NOT a notification and
                # must not be passed to ``mapper.handle``.
                if response.id == turn_request_id:
                    if response.is_error and response.error is not None:
                        # turn/start rejected: discard the staged pending state
                        # so a client retry hits the correct branch.
                        runtime.pending_history_state = None
                        raise BackendError(
                            message=f"Codex process error: {response.error.message}",
                            details=response.error.model_dump(),
                        )
                    # turn/start accepted: capture the turn id but do NOT commit
                    # pending_history_state yet (acceptance != completion).
                    result = response.result or {}
                    turn_obj = result.get("turn")
                    tid = (
                        turn_obj.get("id")
                        if isinstance(turn_obj, dict)
                        else result.get("id")
                    )
                    if isinstance(tid, str) and tid.strip():
                        runtime.turn_id = tid
                    continue

                if response.is_notification:
                    pieces = mapper.handle(response)
                    has_done = any(p.done for p in pieces)
                    if has_done:
                        # Commit the staged pending_history_state ONLY on a
                        # successful turn; an interrupted/failed turn discards
                        # it so a client retry hits the correct branch.
                        done_piece = next(p for p in pieces if p.done)
                        if (
                            done_piece.finish_reason == "stop"
                            and runtime.pending_history_state is not None
                        ):
                            runtime.history_state = runtime.pending_history_state
                        runtime.pending_history_state = None
                    for piece in pieces:
                        if (
                            piece.done
                            and piece.finish_reason
                            and piece.finish_reason != "stop"
                            and logger.isEnabledFor(logging.WARNING)
                        ):
                            # Streaming cannot raise mid-stream (partial content
                            # already sent); log once so operators can see
                            # interrupted/failed turns. The emitted SSE
                            # finish_reason is mapped to "stop" for OpenAI compat.
                            logger.warning(
                                "Codex stream turn ended with non-stop "
                                "finish_reason (finish_reason=%s project=%s "
                                "model=%s client_session=%s)",
                                piece.finish_reason,
                                runtime.project_dir,
                                runtime.model,
                                runtime.client_session_id,
                            )
                        yield piece
                    if has_done:
                        break
                    continue

                # Stray response with an unrelated id: ignore.
                continue
        except asyncio.TimeoutError as exc:
            raise APITimeoutError(
                message="Timeout waiting for Codex response",
                details={"timeout": self._process_timeout, "model": response_model},
            ) from exc

    async def _iter_stream_pieces(
        self,
        runtime: CodexAppServerRuntime,
        request_id: int,
        response_model: str,
    ) -> AsyncGenerator[AcpStreamPiece, None]:
        """Dispatch the shared stream scaffolding to the Codex stream loop."""

        async for piece in self._iter_codex_stream_pieces(
            runtime, request_id, response_model
        ):
            yield piece

    def _create_sse_chunk_from_piece(
        self, piece: AcpStreamPiece, model: str, chunk_id: str
    ) -> str | None:
        delta: dict[str, Any] = {}
        if piece.content:
            delta["content"] = piece.content
        if piece.reasoning_content:
            delta["reasoning_content"] = piece.reasoning_content
        is_done = isinstance(piece, CodexStreamPiece) and piece.done
        finish_reason: str | None = None
        if is_done:
            # SSE never emits the non-OpenAI "interrupted"/"error" values; map
            # every terminal turn to "stop".
            finish_reason = "stop"
        if not delta and not is_done:
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
                    "finish_reason": finish_reason,
                }
            ],
        }
        return f"data: {json.dumps(payload)}\n\n"

    # -- non-streaming accumulation -----------------------------------------

    async def _collect_non_streaming_response(
        self,
        runtime: CodexAppServerRuntime,
        requested_model: str,
        turn_request_id: int,
        request: ConnectorChatCompletionsRequest,
    ) -> ResponseEnvelope:
        """Accumulate a Codex turn into a :class:`ResponseEnvelope`.

        Raises :class:`BackendError` on a failed turn (``finish_reason ==
        "error"``) so it never returns a 200 with partial content;
        interrupted/unknown turns map to ``finish_reason="stop"``.
        """

        pieces: list[CodexStreamPiece] = []
        finish_reason: str | None = None
        async for piece in self._iter_codex_stream_pieces(
            runtime, turn_request_id, requested_model
        ):
            pieces.append(piece)
            if piece.done:
                finish_reason = piece.finish_reason
        if finish_reason == "error":
            if logger.isEnabledFor(logging.WARNING):
                logger.warning(
                    "Codex turn failed (project=%s model=%s client_session=%s)",
                    runtime.project_dir,
                    runtime.model,
                    runtime.client_session_id,
                )
            raise BackendError(
                message="Codex turn failed",
                details={"status": "failed"},
            )
        full_content, full_reasoning = accumulate_pieces(pieces)
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
                        content=full_content,
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

    # -- cancellation -------------------------------------------------------

    async def _send_turn_interrupt(self, runtime: CodexAppServerRuntime) -> int:
        if runtime.thread_id is None or runtime.turn_id is None:
            raise BackendError(message="Cannot interrupt: no active Codex turn")
        return await self._send_jsonrpc_message(
            runtime,
            CODEX_TURN_INTERRUPT_METHOD,
            build_turn_interrupt_payload(runtime.thread_id, runtime.turn_id),
        )

    async def _attempt_graceful_cancel(
        self,
        runtime: CodexAppServerRuntime,
        request_id: int,
        total_timeout_s: float,
    ) -> bool:
        """Gracefully cancel an in-flight Codex turn.

        Sends ``turn/interrupt``, then drains stdout (handling approval
        requests that arrive during the drain so Codex does not block on an
        unanswered approval). Graceful success is defined as the subprocess
        having ACTUALLY exited (``process.poll() is not None``): receiving
        ``turn/completed`` only signals the turn ended -- the app-server child
        is still alive, and returning True earlier would orphan the PID. If the
        child does not exit after the drain, close stdin (the app-server shuts
        down when stdin closes) and wait briefly; if it still does not exit,
        return False so the caller force-kills.
        """

        process = runtime.process
        if process is None or process.poll() is not None:
            return True
        deadline = time.monotonic() + total_timeout_s
        try:
            await self._send_turn_interrupt(runtime)
        except Exception:
            if logger.isEnabledFor(logging.DEBUG):
                logger.debug(
                    "Codex turn/interrupt failed or not supported",
                    exc_info=True,
                )
        while True:
            if process.poll() is not None:
                return True
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                break
            try:
                response = await asyncio.wait_for(
                    self._read_jsonrpc_message(runtime),
                    timeout=min(remaining, 2.0),
                )
            except (asyncio.TimeoutError, BackendError, APIConnectionError):
                break
            if response is None:
                continue
            if response.is_server_request:
                await self._handle_server_request(runtime, response)
                continue
            if (
                response.is_notification
                and response.method == CODEX_TURN_COMPLETED_METHOD
            ):
                # Turn ended but the child is still alive -- break out and
                # close stdin to actually shut the server down.
                break
        if process.poll() is not None:
            return True
        if process.stdin is not None:
            with contextlib.suppress(OSError, ValueError):
                process.stdin.close()
            await self._wait_for_process_exit(process, timeout_s=5.0)
        return process.poll() is not None


# ---------------------------------------------------------------------------
# Backend registration
# ---------------------------------------------------------------------------

from src.core.services.backend_registry import backend_registry

backend_registry.register_backend(
    "openai-codex-app-server", OpenAICodexAppServerConnector
)
