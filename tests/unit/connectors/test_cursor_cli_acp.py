from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest
from pydantic.types import JsonValue
from src.connectors.acp_core.types import ACPNotification
from src.connectors.contracts import ConnectorChatCompletionsRequest
from src.connectors.cursor_cli_acp import (
    CursorCliAcpConnector,
    build_cursor_agent_acp_command,
    parse_agent_models_listing,
    resolve_cursor_agent_executable,
)
from src.core.common.exceptions import ConfigurationError, ServiceUnavailableError
from src.core.config.app_config import AppConfig
from src.core.domain.chat import CanonicalChatRequest, ChatMessage
from src.core.domain.responses import (
    ProcessedResponse,
    StreamingResponseEnvelope,
)
from src.core.services.translation_service import TranslationService


@pytest.fixture
def temp_workspace(tmp_path: Path) -> Path:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    return workspace


@pytest.fixture
def connector() -> CursorCliAcpConnector:
    client = AsyncMock(spec=httpx.AsyncClient)
    return CursorCliAcpConnector(client, AppConfig(), TranslationService())


def _make_request(
    *,
    stream: bool = False,
    extra_body: dict[str, JsonValue] | None = None,
    options: dict[str, JsonValue] | None = None,
    processed_messages: list[ChatMessage] | None = None,
    model: str = "cursor/composer-2",
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


class TestCursorCliAcpModelCache:
    async def test_get_available_models_async_refreshes_when_ttl_zero(
        self, connector: CursorCliAcpConnector, temp_workspace: Path
    ) -> None:
        connector._cursor_cli_executable = str(temp_workspace / "agent")
        connector._models_cache_ttl_seconds = 0.0
        connector.is_functional = True
        connector._initialization_failed = False
        connector._validation_errors = []
        calls = 0

        async def fake_discover() -> list[str]:
            nonlocal calls
            calls += 1
            return [f"cursor/model-{calls}"]

        with patch.object(connector, "_discover_models", side_effect=fake_discover):
            first = await connector.get_available_models_async()
            second = await connector.get_available_models_async()

        assert first == ["cursor/model-1"]
        assert second == ["cursor/model-2"]
        assert calls == 2

    async def test_get_available_models_async_skips_within_ttl(
        self, connector: CursorCliAcpConnector, temp_workspace: Path
    ) -> None:
        connector._cursor_cli_executable = str(temp_workspace / "agent")
        connector._models_cache_ttl_seconds = 3600.0
        connector.is_functional = True
        connector._initialization_failed = False
        connector._validation_errors = []
        calls = 0

        async def fake_discover() -> list[str]:
            nonlocal calls
            calls += 1
            return ["cursor/only"]

        with patch.object(connector, "_discover_models", side_effect=fake_discover):
            assert await connector.get_available_models_async() == ["cursor/only"]
            assert await connector.get_available_models_async() == ["cursor/only"]

        assert calls == 1


class TestCursorCliAcpHelpers:
    def test_parse_agent_models_listing(self) -> None:
        raw = """Loading models…
Available models

composer-2 - Composer 2  (current)
gpt-5.2 - GPT-5.2
"""
        ids = parse_agent_models_listing(raw)
        assert ids == ["composer-2", "gpt-5.2"]

    def test_build_cursor_agent_acp_command(self) -> None:
        cmd = build_cursor_agent_acp_command(
            r"C:\agent\agent.cmd",
            model="composer-2",
            trust_workspace=True,
            extra_args=["--foo"],
            cursor_api_endpoint="https://api.example",
        )
        assert cmd[0] == r"C:\agent\agent.cmd"
        assert cmd[:4] == [
            r"C:\agent\agent.cmd",
            "-e",
            "https://api.example",
            "--model",
        ]
        assert "composer-2" in cmd
        assert "--trust" in cmd
        assert "--foo" in cmd
        assert cmd[-1] == "acp"

    def test_resolve_cursor_agent_executable_prefers_existing_file(
        self, tmp_path: Path
    ) -> None:
        exe = tmp_path / "my-agent.bat"
        exe.write_text("@echo off\n", encoding="utf-8")
        resolved = resolve_cursor_agent_executable(str(exe))
        assert resolved == str(exe.resolve())


class TestCursorCliAcpInitialization:
    async def test_initialize_with_project_dir(
        self, connector: CursorCliAcpConnector, temp_workspace: Path
    ) -> None:
        fake = str(temp_workspace / "fake-agent")
        Path(fake).write_text("noop", encoding="utf-8")
        with (
            patch.object(connector, "_check_agent_available", return_value=True),
            patch.object(connector, "_discover_models", return_value=["cursor/a"]),
        ):
            await connector.initialize(
                project_dir=str(temp_workspace),
                cursor_cli_executable=fake,
            )

        assert connector.is_backend_functional() is True
        assert connector._default_project_dir == temp_workspace.resolve()

    async def test_initialize_requires_workspace(
        self, connector: CursorCliAcpConnector, tmp_path: Path
    ) -> None:
        with (
            patch.object(connector, "_check_agent_available", return_value=True),
            patch.object(connector, "_discover_models", return_value=["cursor/x"]),
            pytest.raises(ConfigurationError),
        ):
            await connector.initialize(project_dir=str(tmp_path / "missing"))

        assert connector.is_backend_functional() is False

    async def test_initialize_without_workspace_config_uses_runtime_project_dir(
        self, connector: CursorCliAcpConnector, temp_workspace: Path
    ) -> None:
        fake = str(temp_workspace / "fake-agent")
        Path(fake).write_text("noop", encoding="utf-8")
        with (
            patch.object(connector, "_check_agent_available", return_value=True),
            patch.object(connector, "_discover_models", return_value=["cursor/x"]),
        ):
            await connector.initialize(cursor_cli_executable=fake)

        assert connector.is_backend_functional() is True
        assert connector._default_project_dir is None

    async def test_initialize_ignores_dot_workspace_path(
        self, connector: CursorCliAcpConnector, temp_workspace: Path
    ) -> None:
        fake = str(temp_workspace / "fake-agent")
        Path(fake).write_text("noop", encoding="utf-8")
        with (
            patch.object(connector, "_check_agent_available", return_value=True),
            patch.object(connector, "_discover_models", return_value=["cursor/x"]),
        ):
            await connector.initialize(
                cursor_cli_executable=fake,
                workspace_path=".",
            )

        assert connector.is_backend_functional() is True
        assert connector._default_project_dir is None


class TestCursorCliAcpProtocol:
    async def test_prepare_prompt_sends_initialize_authenticate_session(
        self, connector: CursorCliAcpConnector, temp_workspace: Path
    ) -> None:
        connector._default_project_dir = temp_workspace
        runtime = connector._create_runtime(temp_workspace, "composer-2")
        runtime.process = MagicMock()

        with (
            patch.object(connector, "_spawn_process", AsyncMock()),
            patch.object(
                connector,
                "_send_jsonrpc_message",
                AsyncMock(side_effect=[1, 2, 3, 4]),
            ) as send_jsonrpc,
            patch.object(
                connector,
                "_await_response",
                AsyncMock(
                    side_effect=[
                        ACPNotification(id=1, result={"protocolVersion": 1}),
                        ACPNotification(id=2, result={}),
                        ACPNotification(id=3, result={"sessionId": "sid-1"}),
                    ]
                ),
            ),
        ):
            prompt_request_id, requested_model = (
                await connector._prepare_prompt_request_locked(runtime, _make_request())
            )

        assert prompt_request_id == 4
        assert requested_model == "cursor/composer-2"
        assert runtime.session_id == "sid-1"
        assert runtime.initialized is True

        methods = [c.args[1] for c in send_jsonrpc.await_args_list]
        assert methods == [
            "initialize",
            "authenticate",
            "session/new",
            "session/prompt",
        ]

    def test_is_server_request(self) -> None:
        assert ACPNotification(
            method="session/request_permission", id=9, params={}
        ).is_server_request
        assert not ACPNotification(id=1, result={"ok": True}).is_server_request
        assert not ACPNotification(method="session/update", params={}).is_server_request

    async def test_handle_server_request_permission_auto_accept(
        self, connector: CursorCliAcpConnector, temp_workspace: Path
    ) -> None:
        connector._auto_accept = True
        runtime = connector._create_runtime(temp_workspace, "composer-2")
        runtime.process = MagicMock()
        runtime.process.stdin = MagicMock()

        written: list[bytes] = []

        def capture_write(data: bytes) -> int:
            written.append(data)
            return len(data)

        runtime.process.stdin.write.side_effect = capture_write
        runtime.process.stdin.flush = MagicMock()

        msg = ACPNotification(method="session/request_permission", id=42, params={})
        await connector._handle_server_request(runtime, msg)

        line = written[-1].decode("utf-8").strip()
        payload = json.loads(line)
        assert payload["jsonrpc"] == "2.0"
        assert payload["id"] == 42
        assert payload["result"]["outcome"]["optionId"] == "allow-always"

    async def test_handle_cursor_ask_question_skipped(
        self, connector: CursorCliAcpConnector, temp_workspace: Path
    ) -> None:
        runtime = connector._create_runtime(temp_workspace, "composer-2")
        runtime.process = MagicMock()
        runtime.process.stdin = MagicMock()
        written: list[bytes] = []

        def capture_write(data: bytes) -> int:
            written.append(data)
            return len(data)

        runtime.process.stdin.write.side_effect = capture_write
        runtime.process.stdin.flush = MagicMock()

        msg = ACPNotification(method="cursor/ask_question", id=7, params={})
        await connector._handle_server_request(runtime, msg)

        line = written[-1].decode("utf-8").strip()
        payload = json.loads(line)
        assert payload["id"] == 7
        assert payload["result"]["outcome"]["outcome"] == "skipped"


class TestCursorCliAcpChatCompletions:
    async def test_chat_completions_not_initialized(
        self, connector: CursorCliAcpConnector
    ) -> None:
        with pytest.raises(ServiceUnavailableError):
            await connector.chat_completions(_make_request())

    async def test_streaming_yields_done(
        self, connector: CursorCliAcpConnector, temp_workspace: Path
    ) -> None:
        connector.is_functional = True
        connector._initialization_failed = False
        connector._validation_errors = []
        connector._default_project_dir = temp_workspace

        runtime = connector._create_runtime(temp_workspace, "composer-2")
        runtime.request_lock = asyncio.Lock()

        async def fake_prepare(*_: Any, **__: Any) -> tuple[int, str]:
            return 99, "cursor/composer-2"

        async def fake_stream(*_: Any, **__: Any):
            yield ProcessedResponse(content='data: {"x":1}\n\n')

        with (
            patch.object(
                connector,
                "_acquire_runtime",
                AsyncMock(return_value=runtime),
            ),
            patch.object(
                connector,
                "_prepare_prompt_request_locked",
                new=fake_prepare,
            ),
            patch.object(
                connector,
                "_stream_response_with_lock",
                new=fake_stream,
            ),
        ):
            out = await connector.chat_completions(_make_request(stream=True))

        assert isinstance(out, StreamingResponseEnvelope)


class TestCursorCliAcpRuntime:
    def test_runtime_locks(
        self, connector: CursorCliAcpConnector, temp_workspace: Path
    ):
        rt = connector._create_runtime(temp_workspace, "composer-2")
        assert rt.process_lock is not None
        assert rt.request_lock is not None
