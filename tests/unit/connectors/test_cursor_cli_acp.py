from __future__ import annotations

import asyncio
import json
import time
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest
from pydantic.types import JsonValue
from src.connectors.acp_core.base_connector import BaseAcpConnector
from src.connectors.acp_core.types import ACPNotification
from src.connectors.contracts import ConnectorChatCompletionsRequest
from src.connectors.cursor_cli_acp import (
    CursorCliAcpConnector,
    build_cursor_agent_acp_command,
    parse_agent_models_listing,
    parse_cursor_acp_models_result,
    resolve_cursor_agent_executable,
)
from src.core.common.exceptions import (
    BackendError,
    ConfigurationError,
    ServiceUnavailableError,
)
from src.core.config.app_config import AppConfig
from src.core.domain.chat import CanonicalChatRequest, ChatMessage
from src.core.domain.responses import (
    ProcessedResponse,
    StreamingResponseEnvelope,
)
from src.core.domain.responses_native_wiring import (
    ACP_RESPONSES_STANDALONE_MODE_KEY,
    ACP_RESPONSES_TEXT_ONLY_MODE_KEY,
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
    async def test_discovery_uses_configured_cursor_api_endpoint(
        self, connector: CursorCliAcpConnector, temp_workspace: Path
    ) -> None:
        connector._cursor_cli_executable = "agent"
        connector._cursor_api_endpoint = "https://cursor.example.test"
        connector._default_project_dir = temp_workspace
        runtime = connector._create_runtime(temp_workspace, "", "model-discovery")
        initialize_response = ACPNotification(id=1, result={"protocolVersion": 1})
        session_response = ACPNotification(id=2, result={"sessionId": "discovery"})
        models_response = ACPNotification(
            id=3,
            result={"models": [{"id": "glm-5.2-max"}]},
        )

        with (
            patch(
                "src.connectors.cursor_cli_acp.CursorCliAcpConnector._create_runtime",
                return_value=runtime,
            ),
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
                    side_effect=[initialize_response, session_response, models_response]
                ),
            ),
            patch.object(connector, "_kill_runtime", AsyncMock()) as kill_runtime,
        ):
            models = await connector._discover_models()

        assert models == ["cursor/glm-5.2-max"]
        assert [call.args[1] for call in send_jsonrpc.await_args_list] == [
            "initialize",
            "session/new",
            "cursor/list_available_models",
        ]
        kill_runtime.assert_awaited_once_with(runtime)

    def test_acp_parser_ignores_display_only_entries(self) -> None:
        result = {
            "models": [
                {"id": "glm-5.2-max", "name": "GLM 5.2 Max"},
                {"name": "CLI-only display entry"},
                "cursor/grok-4.5-xhigh",
                {"modelId": "glm-5.2-max"},
            ]
        }

        assert parse_cursor_acp_models_result(result) == [
            "cursor/glm-5.2-max",
            "cursor/grok-4.5-xhigh",
        ]

    async def test_acp_discovery_does_not_use_cli_models_listing(
        self, connector: CursorCliAcpConnector, temp_workspace: Path
    ) -> None:
        connector._default_project_dir = temp_workspace
        connector._cursor_cli_executable = "agent"

        with (
            patch.object(connector, "_spawn_process", AsyncMock()),
            patch.object(
                connector,
                "_send_jsonrpc_message",
                AsyncMock(side_effect=[1, 2, 3]),
            ),
            patch.object(
                connector,
                "_await_response",
                AsyncMock(
                    side_effect=[
                        ACPNotification(id=1, result={}),
                        ACPNotification(id=2, result={"sessionId": "discovery"}),
                        ACPNotification(
                            id=3,
                            result={"models": [{"id": "acp-only"}]},
                        ),
                    ]
                ),
            ),
            patch.object(connector, "_kill_runtime", AsyncMock()),
            patch(
                "src.connectors.cursor_cli_acp.subprocess.run",
                side_effect=AssertionError("standalone CLI discovery must not run"),
            ),
        ):
            assert await connector._discover_models() == ["cursor/acp-only"]

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

    async def test_get_available_models_async_caches_empty_discovery_within_ttl(
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
            return []

        with patch.object(connector, "_discover_models", side_effect=fake_discover):
            assert await connector.get_available_models_async() == []
            assert await connector.get_available_models_async() == []

        assert calls == 1

    async def test_get_available_models_async_retries_empty_discovery_after_ttl(
        self, connector: CursorCliAcpConnector, temp_workspace: Path
    ) -> None:
        connector._cursor_cli_executable = str(temp_workspace / "agent")
        connector._models_cache_ttl_seconds = 3600.0
        connector.is_functional = True
        connector._initialization_failed = False
        connector._validation_errors = []
        connector._models_cache_fetched_at = time.monotonic() - 3601
        calls = 0

        async def fake_discover() -> list[str]:
            nonlocal calls
            calls += 1
            return ["cursor/model"]

        with patch.object(connector, "_discover_models", side_effect=fake_discover):
            assert await connector.get_available_models_async() == ["cursor/model"]

        assert calls == 1

    async def test_force_refresh_retries_cached_empty_discovery(
        self, connector: CursorCliAcpConnector, temp_workspace: Path
    ) -> None:
        connector._cursor_cli_executable = str(temp_workspace / "agent")
        connector._models_cache_ttl_seconds = 3600.0
        connector._cached_models = []
        connector._models_cache_fetched_at = time.monotonic()
        calls = 0

        async def fake_discover() -> list[str]:
            nonlocal calls
            calls += 1
            return ["cursor/model"]

        with patch.object(connector, "_discover_models", side_effect=fake_discover):
            await connector._ensure_models_discovered(force=True)

        assert calls == 1
        assert connector.get_available_models() == ["cursor/model"]

    async def test_get_available_models_async_caches_discovery_failure_within_ttl(
        self, connector: CursorCliAcpConnector, temp_workspace: Path
    ) -> None:
        connector._cursor_cli_executable = str(temp_workspace / "agent")
        connector._models_cache_ttl_seconds = 3600.0
        connector.is_functional = True
        connector._initialization_failed = False
        connector._validation_errors = []
        calls = 0

        async def failed_discover() -> list[str]:
            nonlocal calls
            calls += 1
            raise RuntimeError("discovery unavailable")

        with patch.object(connector, "_discover_models", side_effect=failed_discover):
            assert await connector.get_available_models_async() == []
            assert await connector.get_available_models_async() == []

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
            mode="ask",
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
        assert cmd[cmd.index("--mode") + 1] == "ask"
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

    async def test_initialize_without_workspace_config_is_rejected(
        self, connector: CursorCliAcpConnector, temp_workspace: Path
    ) -> None:
        fake = str(temp_workspace / "fake-agent")
        Path(fake).write_text("noop", encoding="utf-8")
        with (
            patch.object(connector, "_check_agent_available", return_value=True),
            patch.object(connector, "_discover_models", return_value=["cursor/x"]),
            pytest.raises(ConfigurationError),
        ):
            await connector.initialize(cursor_cli_executable=fake)

        assert connector.is_backend_functional() is False

    async def test_initialize_rejects_relative_dot_workspace_path(
        self, connector: CursorCliAcpConnector, temp_workspace: Path
    ) -> None:
        fake = str(temp_workspace / "fake-agent")
        Path(fake).write_text("noop", encoding="utf-8")
        with (
            patch.object(connector, "_check_agent_available", return_value=True),
            patch.object(connector, "_discover_models", return_value=["cursor/x"]),
            pytest.raises(ConfigurationError),
        ):
            await connector.initialize(
                cursor_cli_executable=fake,
                workspace_path=".",
            )

        assert connector.is_backend_functional() is False

    async def test_permission_requests_are_always_rejected_for_text_only_mode(
        self, connector: CursorCliAcpConnector, temp_workspace: Path
    ) -> None:
        connector._auto_accept = True
        runtime = connector._create_runtime(temp_workspace, "glm-5.2-max")
        runtime.responses_text_only_mode = True
        runtime.process = MagicMock()
        runtime.process.stdin = MagicMock()
        written: list[bytes] = []

        def capture_write(data: bytes) -> int:
            written.append(data)
            return len(data)

        runtime.process.stdin.write.side_effect = capture_write
        runtime.process.stdin.flush = MagicMock()

        await connector._handle_server_request(
            runtime,
            ACPNotification(method="session/request_permission", id=77, params={}),
        )

        payload = json.loads(written[-1].decode("utf-8"))
        assert payload["result"]["outcome"]["optionId"] == "reject-once"


class TestCursorCliAcpRuntimeReuse:
    async def test_failed_standalone_turn_retires_runtime_from_pool(
        self, connector: CursorCliAcpConnector, temp_workspace: Path
    ) -> None:
        request = _make_request(
            extra_body={
                ACP_RESPONSES_TEXT_ONLY_MODE_KEY: True,
                ACP_RESPONSES_STANDALONE_MODE_KEY: True,
            }
        )
        kill_mock = AsyncMock()

        with (
            patch.object(
                BaseAcpConnector,
                "_prepare_turn_request_locked",
                new=AsyncMock(side_effect=BackendError(message="handshake failed")),
            ),
            patch.object(connector, "_kill_runtime", kill_mock),
        ):
            for index in range(3):
                runtime = connector._create_runtime(
                    temp_workspace,
                    "glm-5.2-max",
                    f"acp-responses-failed-{index}",
                )
                key = connector._build_runtime_key(
                    temp_workspace,
                    "glm-5.2-max",
                    runtime.client_session_id,
                    responses_text_only=True,
                )
                runtime.responses_standalone_mode = True
                async with connector._runtime_pool_lock:
                    connector._runtimes[key] = runtime

                with pytest.raises(BackendError, match="handshake failed"):
                    await connector._prepare_turn_request_locked(runtime, request)

                assert key not in connector._runtimes

        assert kill_mock.await_count == 3

    async def test_standalone_responses_runtime_is_expired_after_turn(
        self, connector: CursorCliAcpConnector, temp_workspace: Path
    ) -> None:
        runtime = connector._create_runtime(
            temp_workspace,
            "glm-5.2-max",
            "acp-responses-standalone",
        )
        runtime.responses_text_only_mode = True
        runtime.responses_standalone_mode = True
        key = connector._build_runtime_key(
            temp_workspace,
            "glm-5.2-max",
            runtime.client_session_id,
            responses_text_only=True,
        )
        async with connector._runtime_pool_lock:
            connector._runtimes[key] = runtime

        with patch.object(connector, "_kill_runtime", AsyncMock()) as kill_mock:
            await connector._schedule_stale_kill_after_turn(runtime)

        kill_mock.assert_awaited_once_with(runtime)
        assert key not in connector._runtimes

    def test_runtime_key_ignores_proxy_session_id(
        self, connector: CursorCliAcpConnector, temp_workspace: Path
    ) -> None:
        first = connector._build_runtime_key(temp_workspace, "composer-2", "b-leg-1")
        second = connector._build_runtime_key(temp_workspace, "composer-2", "b-leg-2")

        assert first == second

    def test_responses_text_only_runtime_is_isolated_from_legacy_chat(
        self, connector: CursorCliAcpConnector, temp_workspace: Path
    ) -> None:
        legacy = connector._build_runtime_key(temp_workspace, "glm-5.2-max", "default")
        responses = connector._build_runtime_key(
            temp_workspace,
            "glm-5.2-max",
            "responses-text-only",
            responses_text_only=True,
        )

        assert legacy != responses

    def test_client_session_id_cannot_select_responses_runtime_mode(
        self, connector: CursorCliAcpConnector, temp_workspace: Path
    ) -> None:
        legacy = connector._build_runtime_key(
            temp_workspace,
            "glm-5.2-max",
            "default",
            responses_text_only=False,
        )
        client_collision = connector._build_runtime_key(
            temp_workspace,
            "glm-5.2-max",
            "responses-text-only",
        )

        assert client_collision == legacy

    def test_responses_runtime_key_is_scoped_to_conversation(
        self, connector: CursorCliAcpConnector, temp_workspace: Path
    ) -> None:
        first = connector._build_runtime_key(
            temp_workspace,
            "glm-5.2-max",
            "conversation-a",
            responses_text_only=True,
        )
        first_retry = connector._build_runtime_key(
            temp_workspace,
            "glm-5.2-max",
            "conversation-a",
            responses_text_only=True,
        )
        second = connector._build_runtime_key(
            temp_workspace,
            "glm-5.2-max",
            "conversation-b",
            responses_text_only=True,
        )

        assert first == first_retry
        assert first != second

    async def test_responses_text_only_runtime_command_uses_ask_mode(
        self, connector: CursorCliAcpConnector, temp_workspace: Path
    ) -> None:
        connector._cursor_cli_executable = "agent"
        runtime = connector._create_runtime(
            temp_workspace,
            "glm-5.2-max",
            "responses-text-only",
        )
        runtime.responses_text_only_mode = True

        command = await connector._build_subprocess_command(runtime)

        assert command[command.index("--mode") + 1] == "ask"
        assert command[command.index("--model") + 1] == "glm-5.2-max"

    async def test_unadvertised_exact_model_is_rejected_without_substitution(
        self, connector: CursorCliAcpConnector, temp_workspace: Path
    ) -> None:
        connector.is_functional = True
        connector._initialization_failed = False
        connector._validation_errors = []
        connector._default_project_dir = temp_workspace
        connector._cached_models = ["cursor/glm-5.2-max"]
        connector._models_cache_fetched_at = time.monotonic()

        with pytest.raises(BackendError) as exc_info:
            await connector._acquire_runtime(
                _make_request(model="cursor/grok-4.5-xhigh")
            )

        assert exc_info.value.details["code"] == "cursor_model_unavailable"
        assert exc_info.value.details["requested_model"] == "cursor/grok-4.5-xhigh"
        assert "glm-5.2-max" not in exc_info.value.message

    async def test_history_change_does_not_restart_shared_cursor_runtime(
        self, connector: CursorCliAcpConnector, temp_workspace: Path
    ) -> None:
        runtime = connector._create_runtime(temp_workspace, "composer-2")
        first_messages = [ChatMessage(role="user", content="first")]
        second_messages = [ChatMessage(role="user", content="second")]

        first_text, first_state = await connector._compute_history_and_user_message(
            runtime, first_messages
        )
        runtime.history_state = first_state
        second_text, _ = await connector._compute_history_and_user_message(
            runtime, second_messages
        )

        assert "first" in first_text
        assert second_text == "second"

    async def test_instruction_override_is_sent_on_continuation(
        self, connector: CursorCliAcpConnector, temp_workspace: Path
    ) -> None:
        runtime = connector._create_runtime(temp_workspace, "composer-2")
        first_messages = [
            ChatMessage(role="system", content="Use the original instructions."),
            ChatMessage(role="user", content="first"),
        ]
        second_messages = [
            ChatMessage(role="system", content="Use the replacement instructions."),
            ChatMessage(role="assistant", content="first answer"),
            ChatMessage(role="user", content="second"),
        ]

        _, first_state = await connector._compute_history_and_user_message(
            runtime, first_messages
        )
        runtime.history_state = first_state
        second_text, _ = await connector._compute_history_and_user_message(
            runtime, second_messages
        )

        assert "Use the replacement instructions." in second_text
        assert "second" in second_text

    async def test_instruction_override_reaches_session_prompt_payload(
        self, connector: CursorCliAcpConnector, temp_workspace: Path
    ) -> None:
        runtime = connector._create_runtime(temp_workspace, "composer-2")
        runtime.session_id = "cursor-session-1"
        first_messages = [
            ChatMessage(role="system", content="Use the original instructions."),
            ChatMessage(role="user", content="first"),
        ]
        second_messages = [
            ChatMessage(role="system", content="Use the replacement instructions."),
            ChatMessage(role="assistant", content="first answer"),
            ChatMessage(role="user", content="second"),
        ]
        request_one = _make_request(processed_messages=first_messages)
        request_two = _make_request(processed_messages=second_messages)

        with (
            patch.object(connector, "_spawn_process", AsyncMock()),
            patch.object(connector, "_initialize_runtime", AsyncMock()),
            patch.object(
                connector,
                "_send_jsonrpc_message",
                AsyncMock(side_effect=[1, 2]),
            ) as send_jsonrpc,
        ):
            await connector._prepare_turn_request_locked(runtime, request_one)
            await connector._prepare_turn_request_locked(runtime, request_two)

        prompts = [
            call.args[2]["prompt"][0]["text"] for call in send_jsonrpc.await_args_list
        ]
        assert "Use the replacement instructions." in prompts[1]
        assert "second" in prompts[1]


class TestCursorCliAcpProtocol:
    async def test_prepare_prompt_uses_existing_auth_without_interactive_login(
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
                AsyncMock(side_effect=[1, 2, 3]),
            ) as send_jsonrpc,
            patch.object(
                connector,
                "_await_response",
                AsyncMock(
                    side_effect=[
                        ACPNotification(id=1, result={"protocolVersion": 1}),
                        ACPNotification(id=2, result={"sessionId": "sid-1"}),
                    ]
                ),
            ),
        ):
            prompt_request_id, requested_model = (
                await connector._prepare_turn_request_locked(runtime, _make_request())
            )

        assert prompt_request_id == 3
        assert requested_model == "cursor/composer-2"
        assert runtime.session_id == "sid-1"
        assert runtime.initialized is True

        methods = [c.args[1] for c in send_jsonrpc.await_args_list]
        assert methods == [
            "initialize",
            "session/new",
            "session/prompt",
        ]

    async def test_prepare_prompt_records_standalone_responses_marker(
        self, connector: CursorCliAcpConnector, temp_workspace: Path
    ) -> None:
        runtime = connector._create_runtime(
            temp_workspace, "composer-2", "acp-responses-one-shot"
        )
        runtime.process = MagicMock()
        request = _make_request(
            extra_body={
                ACP_RESPONSES_TEXT_ONLY_MODE_KEY: True,
                ACP_RESPONSES_STANDALONE_MODE_KEY: True,
            }
        )

        with (
            patch.object(connector, "_spawn_process", AsyncMock()),
            patch.object(
                connector,
                "_send_jsonrpc_message",
                AsyncMock(side_effect=[1, 2, 3]),
            ),
            patch.object(
                connector,
                "_await_response",
                AsyncMock(
                    side_effect=[
                        ACPNotification(id=1, result={"protocolVersion": 1}),
                        ACPNotification(id=2, result={"sessionId": "sid-1"}),
                    ]
                ),
            ),
        ):
            await connector._prepare_turn_request_locked(runtime, request)

        assert runtime.responses_text_only_mode is True
        assert runtime.responses_standalone_mode is True

    def test_is_server_request(self) -> None:
        assert ACPNotification(
            method="session/request_permission", id=9, params={}
        ).is_server_request
        assert not ACPNotification(id=1, result={"ok": True}).is_server_request
        assert not ACPNotification(method="session/update", params={}).is_server_request

    async def test_handle_server_request_permission_auto_accepts_for_legacy_chat(
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
                "_prepare_turn_request_locked",
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
