from __future__ import annotations

import asyncio
import os
from collections.abc import AsyncGenerator
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest
from pydantic.types import JsonValue
from src.connectors.contracts import ConnectorChatCompletionsRequest
from src.connectors.gemini_cli_acp import GeminiCliAcpConnector
from src.connectors.gemini_cli_acp_types import ACPNotification, GeminiCliRuntime
from src.core.common.exceptions import (
    APIConnectionError,
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
        cancellation_token=None,
        cancellation_coordinator=None,
        context=None,
        options=options or {},
    )


def _runtime_locks(runtime: GeminiCliRuntime) -> None:
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

    def test_available_models_use_shared_gemini_catalog(
        self, connector: GeminiCliAcpConnector
    ) -> None:
        models = connector.get_available_models()

        assert "google/gemini-3-flash-preview" in models
        assert "google/gemini-3.1-pro-preview" in models

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

    async def test_acquire_runtime_ignores_invalid_override_and_uses_default(
        self, connector: GeminiCliAcpConnector, temp_workspace: Path, tmp_path: Path
    ) -> None:
        connector._default_project_dir = temp_workspace

        runtime = await connector._acquire_runtime(
            _make_request(options={"project_dir": str(tmp_path / "missing")})
        )

        assert runtime.project_dir == temp_workspace.resolve()


class TestGeminiCliAcpProtocol:
    async def test_prepare_prompt_uses_current_acp_methods(
        self, connector: GeminiCliAcpConnector, temp_workspace: Path
    ) -> None:
        connector._default_project_dir = temp_workspace
        runtime = connector._create_runtime(temp_workspace, "gemini-2.5-flash")
        runtime.process = MagicMock()

        with (
            patch.object(connector, "_spawn_gemini_cli_process", AsyncMock()),
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
                await connector._prepare_prompt_request_locked(runtime, _make_request())
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

    async def test_iter_text_fragments_reads_session_update_chunks(
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
                ACPNotification(id=7, result={"stopReason": "end_turn"}),
            ]
        )

        async def _read(_: GeminiCliRuntime) -> ACPNotification:
            return next(responses)

        with patch.object(connector, "_read_jsonrpc_message", side_effect=_read):
            fragments = [
                chunk
                async for chunk in connector._iter_text_fragments(
                    runtime, 7, "google/gemini-2.5-flash"
                )
            ]

        assert fragments == ["Hello"]


class TestGeminiCliAcpChatCompletions:
    async def test_non_streaming_chat_completions(
        self, connector: GeminiCliAcpConnector, temp_workspace: Path
    ) -> None:
        connector.is_functional = True
        connector._default_project_dir = temp_workspace
        runtime = connector._create_runtime(temp_workspace, "gemini-2.5-flash")

        async def _mock_iter(
            _: GeminiCliRuntime, __: int, ___: str
        ) -> AsyncGenerator[str, None]:
            yield "Hello"
            yield " world"

        with (
            patch.object(
                connector, "_acquire_runtime", AsyncMock(return_value=runtime)
            ),
            patch.object(
                connector,
                "_prepare_prompt_request_locked",
                AsyncMock(return_value=(5, "google/gemini-2.5-flash")),
            ),
            patch.object(connector, "_iter_text_fragments", side_effect=_mock_iter),
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
            _: GeminiCliRuntime, __: int, ___: str
        ) -> AsyncGenerator[str, None]:
            yield "chunk-1"
            yield "chunk-2"

        chunks: list[str] = []
        with (
            patch.object(
                connector, "_acquire_runtime", AsyncMock(return_value=runtime)
            ),
            patch.object(
                connector,
                "_prepare_prompt_request_locked",
                AsyncMock(return_value=(5, "google/gemini-2.5-flash")),
            ),
            patch.object(connector, "_iter_text_fragments", side_effect=_mock_iter),
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
            _: GeminiCliRuntime, __: int, ___: str
        ) -> AsyncGenerator[str, None]:
            nonlocal invocation
            invocation += 1
            if invocation == 1:
                started_stream.set()
                yield "stream-1"
                await release_stream.wait()
                yield "stream-2"
                return
            yield "second-request"

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
                "_prepare_prompt_request_locked",
                AsyncMock(return_value=(5, "google/gemini-2.5-flash")),
            ),
            patch.object(connector, "_iter_text_fragments", side_effect=_mock_iter),
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
        ) -> GeminiCliRuntime:
            project_dir = request.options.get("project_dir")
            if project_dir == str(second_workspace):
                return runtime_two
            return runtime_one

        async def _prepare_prompt(
            runtime: GeminiCliRuntime,
            request: ConnectorChatCompletionsRequest,
        ) -> tuple[int, str]:
            return (1, request.effective_model)

        async def _mock_iter(
            runtime: GeminiCliRuntime, __: int, ___: str
        ) -> AsyncGenerator[str, None]:
            if runtime is runtime_one:
                stream_started.set()
                yield "first"
                await release_stream.wait()
                return
            yield "second"

        with (
            patch.object(connector, "_acquire_runtime", side_effect=_acquire_runtime),
            patch.object(
                connector,
                "_prepare_prompt_request_locked",
                side_effect=_prepare_prompt,
            ),
            patch.object(connector, "_iter_text_fragments", side_effect=_mock_iter),
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
            patch.object(connector, "_spawn_gemini_cli_process", AsyncMock()),
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

        with patch("subprocess.Popen", return_value=mock_process):
            await connector._spawn_gemini_cli_process(runtime)

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
            patch("subprocess.Popen", return_value=mock_process),
            pytest.raises(APIConnectionError),
        ):
            await connector._spawn_gemini_cli_process(runtime)

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
