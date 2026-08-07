from __future__ import annotations

import asyncio
import contextlib
import os
from collections.abc import AsyncGenerator
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest
from pydantic.types import JsonValue
from src.connectors.acp_core.base_connector import ACP_CANCEL_METHODS
from src.connectors.acp_core.types import (
    ACPNotification,
    ACPProcessRuntime,
    AcpStreamPiece,
)
from src.connectors.contracts import ConnectorChatCompletionsRequest
from src.connectors.gemini_cli_acp import GeminiCliAcpConnector
from src.core.common.exceptions import (
    APIConnectionError,
    APITimeoutError,
    BackendError,
    ConfigurationError,
)
from src.core.config.app_config import AppConfig
from src.core.domain.chat import CanonicalChatRequest, ChatMessage
from src.core.domain.responses import ResponseEnvelope, StreamingResponseEnvelope
from src.core.services.translation_service import TranslationService


@pytest.fixture
def temp_workspace(tmp_path: Path) -> Path:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    return workspace


@pytest.fixture
def second_workspace(tmp_path: Path) -> Path:
    workspace = tmp_path / "workspace-two"
    workspace.mkdir()
    return workspace


@pytest.fixture
def connector() -> GeminiCliAcpConnector:
    client = AsyncMock(spec=httpx.AsyncClient)
    return GeminiCliAcpConnector(client, AppConfig(), TranslationService())


def _make_request(
    *,
    stream: bool = False,
    extra_body: dict[str, JsonValue] | None = None,
    options: dict[str, JsonValue] | None = None,
    processed_messages: list[ChatMessage] | None = None,
    model: str = "google/gemini-2.5-flash",
    cancellation_coordinator: Any = None,
    cancellation_token: Any = None,
) -> ConnectorChatCompletionsRequest:
    request = CanonicalChatRequest(
        model=model,
        stream=stream,
        messages=[ChatMessage(role="user", content="hello")],
        extra_body=extra_body,
    )
    return ConnectorChatCompletionsRequest(
        request=request,
        processed_messages=processed_messages
        or [ChatMessage(role="user", content="hello")],
        effective_model=model,
        identity=None,
        cancellation_token=cancellation_token,
        cancellation_coordinator=cancellation_coordinator,
        context=None,
        options=options or {},
    )


def _runtime_locks(runtime: ACPProcessRuntime) -> None:
    assert runtime.process_lock is not None
    assert runtime.request_lock is not None


class TestGeminiCliAcpInitialization:
    async def test_initialize_with_project_dir(
        self, connector: GeminiCliAcpConnector, temp_workspace: Path
    ) -> None:
        with patch.object(connector, "_check_gemini_cli_available", return_value=True):
            await connector.initialize(project_dir=str(temp_workspace))

        assert connector.is_backend_functional() is True
        assert connector._default_project_dir == temp_workspace.resolve()

    async def test_initialize_accepts_workspace_path(
        self, connector: GeminiCliAcpConnector, temp_workspace: Path
    ) -> None:
        with patch.object(connector, "_check_gemini_cli_available", return_value=True):
            await connector.initialize(workspace_path=str(temp_workspace))

        assert connector._default_project_dir == temp_workspace.resolve()

    async def test_initialize_requires_existing_workspace(
        self, connector: GeminiCliAcpConnector, tmp_path: Path
    ) -> None:
        with (
            patch.object(connector, "_check_gemini_cli_available", return_value=True),
            pytest.raises(ConfigurationError),
        ):
            await connector.initialize(project_dir=str(tmp_path / "missing"))

        assert connector.is_backend_functional() is False

    async def test_initialize_without_workspace_config_uses_runtime_project_dir(
        self,
        connector: GeminiCliAcpConnector,
    ) -> None:
        with patch.object(connector, "_check_gemini_cli_available", return_value=True):
            await connector.initialize()

        assert connector.is_backend_functional() is True
        assert connector._default_project_dir is None


class TestGeminiCliAcpHelpers:
    def test_extract_user_message_last_user_wins(
        self, connector: GeminiCliAcpConnector
    ) -> None:
        messages = [
            {"role": "user", "content": "first"},
            {"role": "assistant", "content": "ignored"},
            {"role": "user", "content": [{"text": "second"}, {"content": "message"}]},
        ]

        assert connector._extract_user_message_as_string(messages) == "second message"

    def test_available_models_are_empty_without_explicit_configuration(
        self, connector: GeminiCliAcpConnector
    ) -> None:
        assert connector.get_available_models() == []

    async def test_available_models_preserve_explicit_configuration(
        self, connector: GeminiCliAcpConnector
    ) -> None:
        with patch.object(connector, "_check_gemini_cli_available", return_value=True):
            await connector.initialize(
                models=["google/gemini-3.1-pro-preview", "gemini-2.5-flash"]
            )

        assert connector.get_available_models() == [
            "google/gemini-3.1-pro-preview",
            "gemini-2.5-flash",
        ]

    async def test_acquire_runtime_uses_project_dir_override_from_options(
        self,
        connector: GeminiCliAcpConnector,
        temp_workspace: Path,
        second_workspace: Path,
    ) -> None:
        connector._default_project_dir = temp_workspace

        runtime = await connector._acquire_runtime(
            _make_request(options={"project_dir": str(second_workspace)})
        )

        _runtime_locks(runtime)
        assert runtime.project_dir == second_workspace.resolve()

    async def test_acquire_runtime_rejects_unusable_override(
        self, connector: GeminiCliAcpConnector, temp_workspace: Path, tmp_path: Path
    ) -> None:
        connector._default_project_dir = temp_workspace

        with pytest.raises(BackendError):
            await connector._acquire_runtime(
                _make_request(options={"project_dir": str(tmp_path / "missing")})
            )


class TestGeminiCliAcpProtocol:
    async def test_prepare_prompt_uses_current_acp_methods(
        self, connector: GeminiCliAcpConnector, temp_workspace: Path
    ) -> None:
        connector._default_project_dir = temp_workspace
        runtime = connector._create_runtime(temp_workspace, "gemini-2.5-flash")
        runtime.process = MagicMock()

        with (
            patch.object(connector, "_spawn_process", AsyncMock()),
            patch.object(
                connector,
                "_send_jsonrpc_message",
                AsyncMock(side_effect=[1, 2, 3]),
            ) as send_jsonrpc,
            patch.object(
                connector,
                "_await_response",
                AsyncMock(
                    side_effect=[
                        ACPNotification(id=1, result={"protocolVersion": 1}),
                        ACPNotification(id=2, result={"sessionId": "session-123"}),
                    ]
                ),
            ),
        ):
            prompt_request_id, requested_model = (
                await connector._prepare_turn_request_locked(runtime, _make_request())
            )

        assert prompt_request_id == 3
        assert requested_model == "google/gemini-2.5-flash"
        assert runtime.session_id == "session-123"
        assert runtime.initialized is True

        sent_calls = send_jsonrpc.await_args_list
        assert sent_calls[0].args[1] == "initialize"
        assert sent_calls[1].args[1] == "session/new"
        assert sent_calls[2].args[1] == "session/prompt"
        assert sent_calls[2].args[2]["sessionId"] == "session-123"
        assert sent_calls[2].args[2]["prompt"] == [{"type": "text", "text": "hello"}]

    async def test_iter_acp_stream_pieces_reads_session_update_chunks(
        self, connector: GeminiCliAcpConnector, temp_workspace: Path
    ) -> None:
        runtime = connector._create_runtime(temp_workspace, "gemini-2.5-flash")
        runtime.session_id = "session-123"

        responses = iter(
            [
                ACPNotification(
                    method="session/update",
                    params={
                        "sessionId": "session-123",
                        "update": {
                            "sessionUpdate": "agent_message_chunk",
                            "content": {"type": "text", "text": "Hello"},
                        },
                    },
                ),
                ACPNotification(
                    method="session/update",
                    params={
                        "sessionId": "session-123",
                        "update": {
                            "sessionUpdate": "agent_thought_chunk",
                            "content": {"type": "text", "text": "ignored"},
                        },
                    },
                ),
                ACPNotification(
                    method="session/update",
                    params={
                        "sessionId": "session-123",
                        "update": {
                            "sessionUpdate": "agent_thought_chunk",
                            "content": {
                                "type": "text",
                                "text": "ignored cumulative",
                                "textDelta": " more",
                            },
                        },
                    },
                ),
                ACPNotification(id=7, result={"stopReason": "end_turn"}),
            ]
        )

        async def _read(_: ACPProcessRuntime) -> ACPNotification:
            return next(responses)

        with patch.object(connector, "_read_jsonrpc_message", side_effect=_read):
            fragments = [
                chunk
                async for chunk in connector._iter_acp_stream_pieces(
                    runtime, 7, "google/gemini-2.5-flash"
                )
            ]

        assert fragments == [
            AcpStreamPiece(content="Hello"),
            AcpStreamPiece(content="Thinking:\nignored"),
            AcpStreamPiece(content=" more"),
            AcpStreamPiece(content="\n\n"),
        ]


class TestGeminiCliAcpChatCompletions:
    async def test_non_streaming_chat_completions_include_visible_thinking_blocks(
        self, connector: GeminiCliAcpConnector, temp_workspace: Path
    ) -> None:
        connector.is_functional = True
        connector._default_project_dir = temp_workspace
        runtime = connector._create_runtime(temp_workspace, "gemini-2.5-flash")

        async def _mock_iter(
            _: ACPProcessRuntime, __: int, ___: str
        ) -> AsyncGenerator[AcpStreamPiece, None]:
            yield AcpStreamPiece(content="Thinking:\nplanning…\n")
            yield AcpStreamPiece(content="\n\n")
            yield AcpStreamPiece(
                content="---\n```text\n"
                "Tool: read_file\n"
                "Input size: 2 bytes\n"
                "Started: 2026-01-01T00:00:00+00:00\n"
                "Ended: 2026-01-01T00:00:01+00:00 (0.000 s)\n"
                "Output size: 4 bytes\n"
                "```\n"
            )
            yield AcpStreamPiece(content="Hello")
            yield AcpStreamPiece(content=" world")

        with (
            patch.object(
                connector, "_acquire_runtime", AsyncMock(return_value=runtime)
            ),
            patch.object(
                connector,
                "_prepare_turn_request_locked",
                AsyncMock(return_value=(5, "google/gemini-2.5-flash")),
            ),
            patch.object(connector, "_iter_acp_stream_pieces", side_effect=_mock_iter),
        ):
            response = await connector.chat_completions(_make_request())

        assert isinstance(response, ResponseEnvelope)
        assert isinstance(response.content, dict)
        message = response.content["choices"][0]["message"]
        c = message["content"]
        assert "Thinking:\nplanning…" in c
        assert "Hello" in c and "world" in c
        assert "Tool: read_file" in c
        assert "Input size:" in c
        assert "reasoning_content" not in message

    async def test_non_streaming_chat_completions(
        self, connector: GeminiCliAcpConnector, temp_workspace: Path
    ) -> None:
        connector.is_functional = True
        connector._default_project_dir = temp_workspace
        runtime = connector._create_runtime(temp_workspace, "gemini-2.5-flash")

        async def _mock_iter(
            _: ACPProcessRuntime, __: int, ___: str
        ) -> AsyncGenerator[AcpStreamPiece, None]:
            yield AcpStreamPiece(content="Hello")
            yield AcpStreamPiece(content=" world")

        with (
            patch.object(
                connector, "_acquire_runtime", AsyncMock(return_value=runtime)
            ),
            patch.object(
                connector,
                "_prepare_turn_request_locked",
                AsyncMock(return_value=(5, "google/gemini-2.5-flash")),
            ),
            patch.object(connector, "_iter_acp_stream_pieces", side_effect=_mock_iter),
        ):
            response = await connector.chat_completions(_make_request())

        assert isinstance(response, ResponseEnvelope)
        assert response.status_code == 200
        assert isinstance(response.content, dict)
        assert response.content["choices"][0]["message"]["content"] == "Hello world"

    async def test_streaming_chat_completions(
        self, connector: GeminiCliAcpConnector, temp_workspace: Path
    ) -> None:
        connector.is_functional = True
        connector._default_project_dir = temp_workspace
        runtime = connector._create_runtime(temp_workspace, "gemini-2.5-flash")

        async def _mock_iter(
            _: ACPProcessRuntime, __: int, ___: str
        ) -> AsyncGenerator[AcpStreamPiece, None]:
            yield AcpStreamPiece(content="chunk-1")
            yield AcpStreamPiece(content="chunk-2")

        chunks: list[str] = []
        with (
            patch.object(
                connector, "_acquire_runtime", AsyncMock(return_value=runtime)
            ),
            patch.object(
                connector,
                "_prepare_turn_request_locked",
                AsyncMock(return_value=(5, "google/gemini-2.5-flash")),
            ),
            patch.object(connector, "_iter_acp_stream_pieces", side_effect=_mock_iter),
        ):
            response = await connector.chat_completions(_make_request(stream=True))
            assert isinstance(response, StreamingResponseEnvelope)
            assert response.content is not None
            async for item in response.content:
                assert isinstance(item.content, str)
                chunks.append(item.content)

        assert any("chunk-1" in chunk for chunk in chunks)
        assert chunks[-1] == "data: [DONE]\n\n"

    async def test_streaming_blocks_second_request_until_stream_finishes(
        self, connector: GeminiCliAcpConnector, temp_workspace: Path
    ) -> None:
        connector.is_functional = True
        connector._default_project_dir = temp_workspace
        runtime = connector._create_runtime(temp_workspace, "gemini-2.5-flash")
        started_stream = asyncio.Event()
        release_stream = asyncio.Event()
        invocation = 0

        async def _mock_iter(
            _: ACPProcessRuntime, __: int, ___: str
        ) -> AsyncGenerator[AcpStreamPiece, None]:
            nonlocal invocation
            invocation += 1
            if invocation == 1:
                started_stream.set()
                yield AcpStreamPiece(content="stream-1")
                await release_stream.wait()
                yield AcpStreamPiece(content="stream-2")
                return
            yield AcpStreamPiece(content="second-request")

        async def _consume(
            response: StreamingResponseEnvelope,
        ) -> list[str]:
            values: list[str] = []
            assert response.content is not None
            async for item in response.content:
                assert isinstance(item.content, str)
                values.append(item.content)
            return values

        with (
            patch.object(
                connector, "_acquire_runtime", AsyncMock(return_value=runtime)
            ),
            patch.object(
                connector,
                "_prepare_turn_request_locked",
                AsyncMock(return_value=(5, "google/gemini-2.5-flash")),
            ),
            patch.object(connector, "_iter_acp_stream_pieces", side_effect=_mock_iter),
        ):
            first_response = await connector.chat_completions(
                _make_request(stream=True)
            )
            assert isinstance(first_response, StreamingResponseEnvelope)
            consumer_task = asyncio.create_task(_consume(first_response))
            await asyncio.wait_for(started_stream.wait(), timeout=1)

            second_task = asyncio.create_task(
                connector.chat_completions(_make_request())
            )
            await asyncio.sleep(0.05)
            assert second_task.done() is False

            release_stream.set()
            first_chunks = await consumer_task
            second_response = await second_task

        assert any("stream-1" in chunk for chunk in first_chunks)
        assert isinstance(second_response, ResponseEnvelope)
        assert isinstance(second_response.content, dict)
        assert (
            second_response.content["choices"][0]["message"]["content"]
            == "second-request"
        )

    async def test_different_projects_use_independent_runtime_locks(
        self,
        connector: GeminiCliAcpConnector,
        temp_workspace: Path,
        second_workspace: Path,
    ) -> None:
        connector.is_functional = True
        connector._default_project_dir = temp_workspace
        runtime_one = connector._create_runtime(temp_workspace, "gemini-2.5-flash")
        runtime_two = connector._create_runtime(second_workspace, "gemini-2.5-flash")
        release_stream = asyncio.Event()
        stream_started = asyncio.Event()

        async def _acquire_runtime(
            request: ConnectorChatCompletionsRequest,
        ) -> ACPProcessRuntime:
            project_dir = request.options.get("project_dir")
            if project_dir == str(second_workspace):
                return runtime_two
            return runtime_one

        async def _prepare_prompt(
            runtime: ACPProcessRuntime,
            request: ConnectorChatCompletionsRequest,
        ) -> tuple[int, str]:
            return (1, request.effective_model)

        async def _mock_iter(
            runtime: ACPProcessRuntime, __: int, ___: str
        ) -> AsyncGenerator[AcpStreamPiece, None]:
            if runtime is runtime_one:
                stream_started.set()
                yield AcpStreamPiece(content="first")
                await release_stream.wait()
                return
            yield AcpStreamPiece(content="second")

        with (
            patch.object(connector, "_acquire_runtime", side_effect=_acquire_runtime),
            patch.object(
                connector,
                "_prepare_turn_request_locked",
                side_effect=_prepare_prompt,
            ),
            patch.object(connector, "_iter_acp_stream_pieces", side_effect=_mock_iter),
        ):
            stream_response = await connector.chat_completions(
                _make_request(stream=True)
            )
            assert isinstance(stream_response, StreamingResponseEnvelope)
            consumer_task: asyncio.Task[Any] = asyncio.create_task(
                anext(stream_response.content)  # type: ignore[arg-type]
            )
            await asyncio.wait_for(stream_started.wait(), timeout=1)

            second_response = await connector.chat_completions(
                _make_request(options={"project_dir": str(second_workspace)})
            )
            release_stream.set()
            await consumer_task

        assert isinstance(second_response, ResponseEnvelope)
        assert isinstance(second_response.content, dict)
        assert second_response.content["choices"][0]["message"]["content"] == "second"

    async def test_request_without_user_message_raises(
        self, connector: GeminiCliAcpConnector, temp_workspace: Path
    ) -> None:
        connector.is_functional = True
        connector._default_project_dir = temp_workspace
        runtime = connector._create_runtime(temp_workspace, "gemini-2.5-flash")

        with (
            patch.object(
                connector, "_acquire_runtime", AsyncMock(return_value=runtime)
            ),
            patch.object(connector, "_spawn_process", AsyncMock()),
            patch.object(connector, "_initialize_runtime", AsyncMock()),
            pytest.raises(BackendError),
        ):
            await connector.chat_completions(
                _make_request(
                    processed_messages=[ChatMessage(role="assistant", content="x")]
                )
            )


class TestGeminiCliAcpProcessManagement:
    async def test_spawn_process_success(
        self, connector: GeminiCliAcpConnector, temp_workspace: Path
    ) -> None:
        runtime = connector._create_runtime(temp_workspace, "gemini-2.5-flash")
        mock_process = MagicMock()
        mock_process.poll.return_value = None
        mock_process.stdin = MagicMock()
        mock_process.stdout = MagicMock()
        mock_process.stderr = MagicMock()

        with (
            patch(
                "src.connectors.gemini_cli_acp.build_gemini_cli_command",
                return_value=[
                    "gemini",
                    "--experimental-acp",
                    "--model",
                    "gemini-2.5-flash",
                    "-y",
                ],
            ) as build_command,
            patch("subprocess.Popen", return_value=mock_process),
        ):
            await connector._spawn_process(runtime)

        build_command.assert_called_once_with(
            [
                "gemini",
                "--experimental-acp",
                "--model",
                "gemini-2.5-flash",
            ]
        )
        assert runtime.process is mock_process

    async def test_spawn_process_failure_raises_without_leaking_process(
        self, connector: GeminiCliAcpConnector, temp_workspace: Path
    ) -> None:
        runtime = connector._create_runtime(temp_workspace, "gemini-2.5-flash")
        mock_process = MagicMock()
        mock_process.poll.return_value = 1
        mock_process.stdin = MagicMock()
        mock_process.stdout = MagicMock()
        mock_process.stderr = MagicMock()
        mock_process.stderr.read.return_value = b"boom"

        with (
            patch(
                "src.connectors.gemini_cli_acp.build_gemini_cli_command",
                return_value=[
                    "gemini",
                    "--experimental-acp",
                    "--model",
                    "gemini-2.5-flash",
                    "-y",
                ],
            ),
            patch("subprocess.Popen", return_value=mock_process),
            pytest.raises(APIConnectionError),
        ):
            await connector._spawn_process(runtime)

        assert runtime.process is None
        mock_process.stdin.close.assert_called_once()
        mock_process.stdout.close.assert_called_once()
        mock_process.stderr.close.assert_called_once()

    async def test_kill_runtime_cleans_up(
        self, connector: GeminiCliAcpConnector, temp_workspace: Path
    ) -> None:
        runtime = connector._create_runtime(temp_workspace, "gemini-2.5-flash")
        mock_process = MagicMock()
        mock_process.poll.return_value = None
        mock_process.stdin = MagicMock()
        mock_process.stdout = MagicMock()
        mock_process.stderr = MagicMock()
        runtime.process = mock_process

        with patch("subprocess.run") as run_mock:
            await connector._kill_runtime(runtime)

        if os.name == "nt":
            run_mock.assert_called_once()
        else:
            mock_process.terminate.assert_called_once()
        mock_process.stdin.close.assert_called_once()
        mock_process.stdout.close.assert_called_once()
        mock_process.stderr.close.assert_called_once()
        assert runtime.process is None


class TestGeminiCliAcpCancellation:
    async def test_cancel_callback_triggers_graceful_then_kill(
        self, connector: GeminiCliAcpConnector, temp_workspace: Path
    ) -> None:
        runtime = connector._create_runtime(temp_workspace, "gemini-2.5-flash")
        runtime.session_id = "session-abc"
        mock_process = MagicMock()
        mock_process.poll.return_value = None
        mock_process.stdin = MagicMock()
        mock_process.stdout = MagicMock()
        mock_process.stderr = MagicMock()
        mock_process.pid = 12345
        runtime.process = mock_process
        await runtime.request_lock.acquire()

        send_calls: list[str] = []

        async def _mock_send(
            rt: ACPProcessRuntime, method: str, params: dict[str, Any]
        ) -> int:
            send_calls.append(method)
            return rt.message_id

        async def _mock_wait(process: Any, timeout_s: float) -> bool:
            return False

        with (
            patch.object(connector, "_send_jsonrpc_message", side_effect=_mock_send),
            patch.object(connector, "_wait_for_process_exit", side_effect=_mock_wait),
            patch.object(connector, "_kill_runtime", AsyncMock()) as kill_mock,
        ):
            await connector._cancel_active_request(runtime, prompt_request_id=5)

        assert send_calls == list(ACP_CANCEL_METHODS)
        kill_mock.assert_called_once_with(runtime)
        assert runtime.request_lock.locked() is False

    async def test_cancel_callback_skips_kill_if_process_exits_gracefully(
        self, connector: GeminiCliAcpConnector, temp_workspace: Path
    ) -> None:
        runtime = connector._create_runtime(temp_workspace, "gemini-2.5-flash")
        runtime.session_id = "session-abc"
        mock_process = MagicMock()
        mock_process.poll.return_value = None
        mock_process.stdin = MagicMock()
        mock_process.stdout = MagicMock()
        mock_process.stderr = MagicMock()
        mock_process.pid = 12345
        runtime.process = mock_process
        await runtime.request_lock.acquire()

        async def _mock_send(
            rt: ACPProcessRuntime, method: str, params: dict[str, Any]
        ) -> int:
            return rt.message_id

        async def _mock_wait(process: Any, timeout_s: float) -> bool:
            return True

        with (
            patch.object(connector, "_send_jsonrpc_message", side_effect=_mock_send),
            patch.object(connector, "_wait_for_process_exit", side_effect=_mock_wait),
            patch.object(connector, "_kill_runtime", AsyncMock()) as kill_mock,
            patch.object(connector, "_cleanup_runtime_state") as cleanup_mock,
        ):
            await connector._cancel_active_request(runtime, prompt_request_id=5)

        kill_mock.assert_not_called()
        cleanup_mock.assert_called_once()
        assert runtime.request_lock.locked() is False

    async def test_cancel_callback_is_idempotent(
        self, connector: GeminiCliAcpConnector, temp_workspace: Path
    ) -> None:
        runtime = connector._create_runtime(temp_workspace, "gemini-2.5-flash")
        runtime.session_id = "session-abc"
        mock_process = MagicMock()
        mock_process.poll.side_effect = [None, None, 0]
        mock_process.stdin = MagicMock()
        mock_process.stdout = MagicMock()
        mock_process.stderr = MagicMock()
        mock_process.pid = 12345
        runtime.process = mock_process
        await runtime.request_lock.acquire()

        async def _mock_send(
            rt: ACPProcessRuntime, method: str, params: dict[str, Any]
        ) -> int:
            return rt.message_id

        async def _mock_wait(process: Any, timeout_s: float) -> bool:
            return False

        with (
            patch.object(connector, "_send_jsonrpc_message", side_effect=_mock_send),
            patch.object(connector, "_wait_for_process_exit", side_effect=_mock_wait),
            patch.object(connector, "_kill_runtime", AsyncMock()),
        ):
            await connector._cancel_active_request(runtime, prompt_request_id=5)
            await connector._cancel_active_request(runtime, prompt_request_id=5)

        assert runtime.request_lock.locked() is False

    async def test_cancel_callback_noop_if_process_already_dead(
        self, connector: GeminiCliAcpConnector, temp_workspace: Path
    ) -> None:
        runtime = connector._create_runtime(temp_workspace, "gemini-2.5-flash")
        runtime.process = None
        await runtime.request_lock.acquire()

        with (patch.object(connector, "_kill_runtime", AsyncMock()) as kill_mock,):
            await connector._cancel_active_request(runtime, prompt_request_id=5)

        kill_mock.assert_not_called()
        assert runtime.request_lock.locked() is False

    async def test_streaming_cancel_callback_uses_cancel_active_request(
        self, connector: GeminiCliAcpConnector, temp_workspace: Path
    ) -> None:
        connector.is_functional = True
        connector._default_project_dir = temp_workspace
        runtime = connector._create_runtime(temp_workspace, "gemini-2.5-flash")

        async def _mock_iter(
            _: ACPProcessRuntime, __: int, ___: str
        ) -> AsyncGenerator[AcpStreamPiece, None]:
            yield AcpStreamPiece(content="chunk-1")

        with (
            patch.object(
                connector, "_acquire_runtime", AsyncMock(return_value=runtime)
            ),
            patch.object(
                connector,
                "_prepare_turn_request_locked",
                AsyncMock(return_value=(5, "google/gemini-2.5-flash")),
            ),
            patch.object(connector, "_iter_acp_stream_pieces", side_effect=_mock_iter),
            patch.object(
                connector, "_cancel_active_request", AsyncMock()
            ) as cancel_mock,
        ):
            response = await connector.chat_completions(_make_request(stream=True))
            assert isinstance(response, StreamingResponseEnvelope)
            assert response.cancel_callback is not None
            assert asyncio.iscoroutinefunction(response.cancel_callback)
            result = response.cancel_callback()
            assert asyncio.iscoroutine(result)
            await result

        cancel_mock.assert_called_once_with(runtime, 5, expected_generation=1)

    async def test_non_streaming_registers_cancellable(
        self, connector: GeminiCliAcpConnector, temp_workspace: Path
    ) -> None:
        connector.is_functional = True
        connector._default_project_dir = temp_workspace
        runtime = connector._create_runtime(temp_workspace, "gemini-2.5-flash")

        async def _mock_iter(
            _: ACPProcessRuntime, __: int, ___: str
        ) -> AsyncGenerator[AcpStreamPiece, None]:
            yield AcpStreamPiece(content="Hello")

        mock_coordinator = MagicMock()
        mock_coordinator.register_cancellable = MagicMock()
        mock_coordinator.cleanup = MagicMock()

        with (
            patch.object(
                connector, "_acquire_runtime", AsyncMock(return_value=runtime)
            ),
            patch.object(
                connector,
                "_prepare_turn_request_locked",
                AsyncMock(return_value=(5, "google/gemini-2.5-flash")),
            ),
            patch.object(connector, "_iter_acp_stream_pieces", side_effect=_mock_iter),
        ):
            response = await connector.chat_completions(
                _make_request(
                    cancellation_coordinator=mock_coordinator,
                    cancellation_token="session-key-1",
                )
            )

        assert isinstance(response, ResponseEnvelope)
        mock_coordinator.register_cancellable.assert_called_once()
        mock_coordinator.cleanup.assert_called_once_with("session-key-1")

    async def test_attempt_graceful_cancel_closes_stdin_as_fallback(
        self, connector: GeminiCliAcpConnector, temp_workspace: Path
    ) -> None:
        runtime = connector._create_runtime(temp_workspace, "gemini-2.5-flash")
        runtime.session_id = "session-abc"
        mock_process = MagicMock()
        mock_process.poll.return_value = None
        mock_stdin = MagicMock()
        mock_process.stdin = mock_stdin
        mock_process.stdout = MagicMock()
        mock_process.stderr = MagicMock()
        runtime.process = mock_process

        async def _mock_send_raises(
            rt: ACPProcessRuntime, method: str, params: dict[str, Any]
        ) -> int:
            raise BrokenPipeError("stdin closed")

        async def _mock_wait(process: Any, timeout_s: float) -> bool:
            return False

        with (
            patch.object(
                connector,
                "_send_jsonrpc_message",
                side_effect=_mock_send_raises,
            ),
            patch.object(connector, "_wait_for_process_exit", side_effect=_mock_wait),
        ):
            result = await connector._attempt_graceful_cancel(
                runtime, request_id=5, total_timeout_s=2.0
            )

        assert result is False
        mock_stdin.close.assert_called()

    async def test_cancellation_event_stops_iter_acp_stream_pieces(
        self, connector: GeminiCliAcpConnector, temp_workspace: Path
    ) -> None:
        runtime = connector._create_runtime(temp_workspace, "gemini-2.5-flash")
        runtime.session_id = "session-123"
        assert runtime.cancellation_event is not None

        read_count = 0

        async def _mock_read(
            rt: ACPProcessRuntime,
        ) -> ACPNotification:
            nonlocal read_count
            read_count += 1
            await asyncio.sleep(0.05)
            return ACPNotification(
                method="session/update",
                params={
                    "sessionId": "session-123",
                    "update": {
                        "sessionUpdate": "agent_message_chunk",
                        "content": {"type": "text", "text": "chunk"},
                    },
                },
            )

        async def _set_event_after_delay() -> None:
            await asyncio.sleep(0.15)
            runtime.cancellation_event.set()

        cancel_task = asyncio.create_task(_set_event_after_delay())
        try:
            with (
                patch.object(
                    connector, "_read_jsonrpc_message", side_effect=_mock_read
                ),
            ):
                fragments = [
                    chunk
                    async for chunk in connector._iter_acp_stream_pieces(
                        runtime, 99, "google/gemini-2.5-flash"
                    )
                ]
        finally:
            cancel_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await cancel_task

        assert read_count >= 1
        assert len(fragments) >= 1
        assert all(
            isinstance(f, AcpStreamPiece) and f.content == "chunk" for f in fragments
        )

    async def test_cancellation_branch_honors_process_timeout(
        self, connector: GeminiCliAcpConnector, temp_workspace: Path
    ) -> None:
        runtime = connector._create_runtime(temp_workspace, "gemini-2.5-flash")
        assert runtime.cancellation_event is not None
        connector._process_timeout = 0.05

        block_event = asyncio.Event()

        async def _mock_read(_: ACPProcessRuntime) -> ACPNotification:
            await block_event.wait()
            raise AssertionError("unreachable")

        with (
            patch.object(connector, "_read_jsonrpc_message", side_effect=_mock_read),
            pytest.raises(APITimeoutError),
        ):
            await asyncio.wait_for(
                connector._iter_acp_stream_pieces(
                    runtime, 99, "google/gemini-2.5-flash"
                ).__anext__(),
                timeout=1.0,
            )

    async def test_runtime_respawns_after_cancellation(
        self, connector: GeminiCliAcpConnector, temp_workspace: Path
    ) -> None:
        runtime = connector._create_runtime(temp_workspace, "gemini-2.5-flash")
        runtime.session_id = "session-abc"
        mock_process = MagicMock()
        mock_process.poll.return_value = None
        mock_process.stdin = MagicMock()
        mock_process.stdout = MagicMock()
        mock_process.stderr = MagicMock()
        mock_process.pid = 99999
        runtime.process = mock_process
        await runtime.request_lock.acquire()

        async def _mock_send(
            rt: ACPProcessRuntime, method: str, params: dict[str, Any]
        ) -> int:
            return rt.message_id

        async def _mock_wait(process: Any, timeout_s: float) -> bool:
            return False

        with (
            patch.object(connector, "_send_jsonrpc_message", side_effect=_mock_send),
            patch.object(connector, "_wait_for_process_exit", side_effect=_mock_wait),
            patch.object(connector, "_terminate_process", AsyncMock()),
        ):
            await connector._cancel_active_request(runtime, prompt_request_id=5)

        assert runtime.process is None
        assert runtime.initialized is False
        assert runtime.session_id is None
        assert runtime.cancellation_event is not None
        assert runtime.cancellation_event.is_set() is False
