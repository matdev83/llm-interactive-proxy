from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest
from pydantic.types import JsonValue
from src.connectors.acp_core.types import ACPError, ACPNotification
from src.connectors.contracts import ConnectorChatCompletionsRequest
from src.connectors.eve_acp import (
    EveAcpConnector,
    EveConfiguredModelEnumerator,
    build_eve_acp_command,
    canonicalize_eve_model_id,
    ensure_default_eve_agent,
    resolve_eve_agent_path,
    resolve_eve_executable,
)
from src.core.common.exceptions import BackendError, ConfigurationError
from src.core.config.app_config import AppConfig, BackendConfig
from src.core.domain.chat import CanonicalChatRequest, ChatMessage
from src.core.services.translation_service import TranslationService


@pytest.fixture
def temp_workspace(tmp_path: Path) -> Path:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    return workspace


@pytest.fixture
def connector() -> EveAcpConnector:
    client = AsyncMock(spec=httpx.AsyncClient)
    return EveAcpConnector(client, AppConfig(), TranslationService())


def _make_request(
    *,
    stream: bool = False,
    extra_body: dict[str, JsonValue] | None = None,
    options: dict[str, JsonValue] | None = None,
    processed_messages: list[ChatMessage] | None = None,
    model: str = "eve/auto",
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


class TestEveAcpHelpers:
    def test_canonicalize_eve_model_id(self) -> None:
        assert canonicalize_eve_model_id("auto") == "zai/glm-5.2"
        assert canonicalize_eve_model_id("") == "zai/glm-5.2"
        assert canonicalize_eve_model_id("glm-5.2") == "zai/glm-5.2"
        assert canonicalize_eve_model_id("glm5.2") == "zai/glm-5.2"
        assert canonicalize_eve_model_id("eve/glm-5.2") == "zai/glm-5.2"
        assert canonicalize_eve_model_id("eve/zai/glm-5.2") == "zai/glm-5.2"
        assert canonicalize_eve_model_id("claude-3-7-sonnet") == "claude-3-7-sonnet"

    def test_build_eve_acp_command_default(self) -> None:
        cmd = build_eve_acp_command("eve")
        assert cmd == ["eve", "acp"]

    def test_build_eve_acp_command_with_args(self) -> None:
        cmd = build_eve_acp_command(
            "C:/bin/eve.exe",
            extra_args=["--scope", "my-team"],
        )
        assert cmd == [
            "C:/bin/eve.exe",
            "acp",
            "--scope",
            "my-team",
        ]

    def test_resolve_eve_executable_from_configured_file(self, tmp_path: Path) -> None:
        fake_bin = tmp_path / "eve.cmd"
        fake_bin.write_text("@echo off", encoding="utf-8")
        resolved = resolve_eve_executable(str(fake_bin))
        assert resolved == str(fake_bin.resolve())

    def test_resolve_eve_executable_from_env(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        fake_bin = tmp_path / "custom_eve"
        fake_bin.write_text("#!/bin/sh", encoding="utf-8")
        monkeypatch.setenv("EVE_BINARY", str(fake_bin))
        resolved = resolve_eve_executable(None)
        assert resolved == str(fake_bin.resolve())

    def test_resolve_eve_executable_fallback_which(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("EVE_BINARY", raising=False)
        monkeypatch.delenv("EVE_EXECUTABLE", raising=False)
        with patch("shutil.which", return_value="/usr/local/bin/eve"):
            resolved = resolve_eve_executable("eve")
            assert resolved == "/usr/local/bin/eve"

    def test_resolve_eve_agent_path_configured(self, tmp_path: Path) -> None:
        agent_dir = tmp_path / "custom_agent"
        (agent_dir / "agent").mkdir(parents=True)
        (agent_dir / "agent" / "agent.ts").write_text(
            "export default {}", encoding="utf-8"
        )
        resolved = resolve_eve_agent_path(str(agent_dir))
        assert resolved == agent_dir.resolve()

    def test_ensure_default_eve_agent_already_exists(self, tmp_path: Path) -> None:
        agent_dir = tmp_path / "existing_agent"
        (agent_dir / "agent").mkdir(parents=True)
        (agent_dir / "agent" / "agent.ts").write_text(
            "export default {}", encoding="utf-8"
        )
        (agent_dir / "package.json").write_text("{}", encoding="utf-8")

        result = ensure_default_eve_agent("eve", target_path=agent_dir)
        assert result == agent_dir.resolve()

    def test_ensure_default_eve_agent_creates_structure(self, tmp_path: Path) -> None:
        target_dir = tmp_path / "new_agent"
        with patch("subprocess.run") as mock_run:

            def fake_init(*args: Any, **kwargs: Any) -> Any:
                target_dir.mkdir(parents=True, exist_ok=True)
                (target_dir / "package.json").write_text("{}", encoding="utf-8")
                return type("ProcessResult", (), {"returncode": 0})()

            mock_run.side_effect = fake_init
            result = ensure_default_eve_agent("eve", target_path=target_dir)

        assert result == target_dir.resolve()
        assert (target_dir / "agent" / "agent.ts").is_file()
        assert (target_dir / "agent" / "tools" / "ask_question.ts").is_file()
        assert (target_dir / "agent" / "tools" / "read_file.ts").is_file()
        assert (target_dir / "agent" / "tools" / "bash.ts").is_file()
        instructions = (target_dir / "agent" / "instructions.md").read_text(
            encoding="utf-8"
        )
        assert "Orchestrator Tool Separation" in instructions
        assert "orchestrating (parent) platform" in instructions

    def test_ensure_default_eve_agent_failure(self, tmp_path: Path) -> None:
        target_dir = tmp_path / "fail_agent"
        with patch(
            "subprocess.run",
            return_value=type(
                "ProcessResult", (), {"returncode": 1, "stderr": b"error"}
            )(),
        ):
            result = ensure_default_eve_agent("eve", target_path=target_dir)
            assert result is None


class TestEveAcpInitialization:
    async def test_initialize_success(
        self, connector: EveAcpConnector, temp_workspace: Path
    ) -> None:
        with patch.object(connector, "_check_eve_available", return_value=True):
            await connector.initialize(
                project_dir=str(temp_workspace),
                eve_executable="eve",
                model="eve/claude-3.7-sonnet",
                models=["eve/claude-3.7-sonnet", "eve/gpt-4o"],
                permission_policy="allow",
                yolo=True,
                process_timeout=600,
                idle_timeout=90,
                tool_pacing_ms=3000,
                turn_pacing_delay_seconds=3.0,
                extra_args=["--trace"],
                env={"MY_VAR": "val"},
            )

        assert connector.is_backend_functional() is True
        assert connector._default_project_dir == temp_workspace.resolve()
        assert connector._model == "claude-3.7-sonnet"
        assert connector._configured_models == ["claude-3.7-sonnet", "gpt-4o"]
        assert connector._permission_policy == "allow"
        assert connector._yolo is True
        assert connector._process_timeout == 600.0
        assert connector._idle_timeout == 90.0
        assert connector._tool_pacing_ms == 3000
        assert connector._turn_pacing_delay_seconds == 3.0
        assert connector._extra_args == ["--trace"]
        assert connector._custom_env == {"MY_VAR": "val"}

    async def test_initialize_auto_provisions_agent(
        self, connector: EveAcpConnector, temp_workspace: Path, tmp_path: Path
    ) -> None:
        fake_agent_dir = tmp_path / "mock_agent"
        with (
            patch.object(connector, "_check_eve_available", return_value=True),
            patch("src.connectors.eve_acp.resolve_eve_agent_path", return_value=None),
            patch(
                "src.connectors.eve_acp.ensure_default_eve_agent",
                return_value=fake_agent_dir,
            ),
        ):
            await connector.initialize(
                project_dir=str(temp_workspace),
                eve_executable="eve",
            )

        assert connector.is_backend_functional() is True
        assert connector._agent_path == fake_agent_dir

    async def test_initialize_executable_not_found(
        self, connector: EveAcpConnector, temp_workspace: Path
    ) -> None:
        with (
            patch.object(connector, "_check_eve_available", return_value=False),
            pytest.raises(ConfigurationError) as exc_info,
        ):
            await connector.initialize(
                project_dir=str(temp_workspace),
                eve_executable="non_existent_eve",
            )

        assert "eve executable not found" in str(exc_info.value)
        assert connector.is_backend_functional() is False
        assert connector._initialization_failed is True

    async def test_initialize_invalid_workspace(
        self, connector: EveAcpConnector, tmp_path: Path
    ) -> None:
        missing = tmp_path / "non_existent_workspace_dir"
        with (
            patch.object(connector, "_check_eve_available", return_value=True),
            pytest.raises(ConfigurationError),
        ):
            await connector.initialize(project_dir=str(missing))

        assert connector.is_backend_functional() is False


class TestEveAcpProtocol:
    async def test_handshake_success(
        self, connector: EveAcpConnector, temp_workspace: Path
    ) -> None:
        runtime = connector._create_runtime(temp_workspace, "auto")

        async def _mock_send(rt: Any, method: str, params: dict[str, Any]) -> int:
            if method == "initialize":
                return 1
            if method == "session/new":
                return 2
            return 3

        async def _mock_await(rt: Any, msg_id: int) -> ACPNotification:
            if msg_id == 1:
                return ACPNotification(id=1, result={"protocolVersion": 1})
            if msg_id == 2:
                return ACPNotification(id=2, result={"sessionId": "sess-eve-12345"})
            return ACPNotification(id=msg_id, result={})

        with (
            patch.object(connector, "_send_jsonrpc_message", side_effect=_mock_send),
            patch.object(connector, "_await_response", side_effect=_mock_await),
        ):
            await connector._perform_handshake(runtime)

        assert runtime.session_id == "sess-eve-12345"
        assert runtime.initialized is True

    async def test_handshake_initialize_error(
        self, connector: EveAcpConnector, temp_workspace: Path
    ) -> None:
        runtime = connector._create_runtime(temp_workspace, "auto")

        with (
            patch.object(connector, "_send_jsonrpc_message", return_value=1),
            patch.object(
                connector,
                "_await_response",
                return_value=ACPNotification(
                    id=1,
                    error=ACPError(code=-32600, message="Invalid protocol version"),
                ),
            ),
            pytest.raises(BackendError) as exc_info,
        ):
            await connector._perform_handshake(runtime)

        assert "eve initialize failed" in str(exc_info.value)

    async def test_handshake_session_new_missing_session_id(
        self, connector: EveAcpConnector, temp_workspace: Path
    ) -> None:
        runtime = connector._create_runtime(temp_workspace, "auto")

        async def _mock_await(rt: Any, msg_id: int) -> ACPNotification:
            if msg_id == 1:
                return ACPNotification(id=1, result={"protocolVersion": 1})
            return ACPNotification(id=msg_id, result={})

        with (
            patch.object(connector, "_send_jsonrpc_message", side_effect=[1, 2]),
            patch.object(connector, "_await_response", side_effect=_mock_await),
            pytest.raises(BackendError) as exc_info,
        ):
            await connector._perform_handshake(runtime)

        assert "did not return a valid sessionId" in str(exc_info.value)


class TestEveAcpServerRequests:
    async def test_handle_permission_request_allow(
        self, connector: EveAcpConnector, temp_workspace: Path
    ) -> None:
        connector._permission_policy = "allow"
        runtime = connector._create_runtime(temp_workspace, "auto")

        msg = ACPNotification(
            method="session/request_permission",
            id=10,
            params={"sessionId": "s1", "tool": "exec"},
        )

        with patch.object(connector, "_send_jsonrpc_result", AsyncMock()) as send_mock:
            await connector._handle_server_request(runtime, msg)

        send_mock.assert_called_once_with(
            runtime,
            10,
            {"outcome": {"outcome": "selected", "optionId": "allow-always"}},
        )

    async def test_handle_permission_request_deny(
        self, connector: EveAcpConnector, temp_workspace: Path
    ) -> None:
        connector._permission_policy = "deny"
        runtime = connector._create_runtime(temp_workspace, "auto")

        msg = ACPNotification(
            method="session/request_permission",
            id=11,
            params={"sessionId": "s1", "tool": "exec"},
        )

        with patch.object(connector, "_send_jsonrpc_result", AsyncMock()) as send_mock:
            await connector._handle_server_request(runtime, msg)

        send_mock.assert_called_once_with(
            runtime,
            11,
            {"outcome": {"outcome": "selected", "optionId": "reject-once"}},
        )

    async def test_handle_eve_extension(
        self, connector: EveAcpConnector, temp_workspace: Path
    ) -> None:
        runtime = connector._create_runtime(temp_workspace, "auto")

        msg = ACPNotification(
            method="eve/custom_event",
            id=12,
            params={},
        )

        with patch.object(connector, "_send_jsonrpc_result", AsyncMock()) as send_mock:
            await connector._handle_server_request(runtime, msg)

        send_mock.assert_called_once_with(runtime, 12, {})

    async def test_handle_unknown_method(
        self, connector: EveAcpConnector, temp_workspace: Path
    ) -> None:
        runtime = connector._create_runtime(temp_workspace, "auto")

        msg = ACPNotification(
            method="unknown/method",
            id=13,
            params={},
        )

        with patch.object(connector, "_write_json_line", AsyncMock()) as write_mock:
            await connector._handle_server_request(runtime, msg)

        write_mock.assert_called_once_with(
            runtime,
            {
                "jsonrpc": "2.0",
                "id": 13,
                "error": {
                    "code": -32601,
                    "message": "Method not handled: unknown/method",
                },
            },
        )


class TestEveAcpRuntimeAndEnv:
    def test_subprocess_env_injection(
        self,
        connector: EveAcpConnector,
        temp_workspace: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setenv("LLM_PROXY_HOP_COUNT", "2")
        connector._custom_env = {"CUSTOM_VAR": "custom_val"}
        runtime = connector._create_runtime(temp_workspace, "auto")

        env = connector._subprocess_env(runtime)
        assert env["LLM_PROXY_CALLER_BACKEND"] == "eve-acp"
        assert env["LLM_PROXY_ORIGIN_BACKEND"] == "eve-acp"
        assert env["EVE_TARGET_WORKSPACE"] == str(temp_workspace)
        assert env["EVE_TOOL_PACING_MS"] == "2000"
        assert env["LLM_PROXY_HOP_COUNT"] == "3"
        assert env["CUSTOM_VAR"] == "custom_val"

    async def test_spawn_uses_isolated_agent_root_without_reusing_server_url(
        self, connector: EveAcpConnector, tmp_path: Path
    ) -> None:
        agent_root = tmp_path / "agent"
        (agent_root / "agent").mkdir(parents=True)
        (agent_root / "agent" / "agent.ts").write_text(
            "export default {}", encoding="utf-8"
        )
        (agent_root / "package.json").write_text("{}", encoding="utf-8")
        state_file = agent_root / ".eve" / "dev-server-state.v1.json"
        state_file.parent.mkdir()
        state_file.write_text('{"url":"http://127.0.0.1:3661/"}', encoding="utf-8")
        connector._agent_path = agent_root
        runtime = connector._create_runtime(tmp_path / "workspace", "auto")

        process = MagicMock()
        process.poll.return_value = None
        process.pid = 4321
        process.stdin = None
        process.stdout = None
        process.stderr = None

        with (
            patch.object(
                connector,
                "_build_subprocess_command",
                AsyncMock(return_value=["eve", "acp"]),
            ) as command_mock,
            patch(
                "src.connectors.eve_acp.subprocess.Popen", return_value=process
            ) as popen_mock,
            patch.object(connector, "_terminate_process", AsyncMock()),
        ):
            await connector._spawn_process(runtime)

        command_mock.assert_awaited_once_with(runtime)
        assert command_mock.await_args is not None
        assert popen_mock.call_args is not None
        assert popen_mock.call_args.args[0] == ["eve", "acp"]
        spawn_cwd = Path(popen_mock.call_args.kwargs["cwd"])
        assert spawn_cwd.parent == agent_root.resolve()
        assert spawn_cwd.name.startswith("acp-runtime-")
        assert (spawn_cwd / "agent" / "agent.ts").is_file()
        assert not (spawn_cwd / "node_modules").exists()
        # A stale state file from the old shared-server implementation is not
        # consulted or deleted; the new app root gets its own state file.
        assert state_file.is_file()

        await connector._kill_runtime(runtime)
        assert not spawn_cwd.exists()

    def test_oversized_prompt_is_bounded_before_acp_dispatch(
        self, connector: EveAcpConnector, temp_workspace: Path
    ) -> None:
        connector._max_prompt_bytes = 600
        runtime = connector._create_runtime(temp_workspace, "auto")
        messages = [
            ChatMessage(role="user", content="old request"),
            ChatMessage(role="assistant", content="stale output " * 500),
            ChatMessage(role="user", content="latest request must survive"),
        ]

        bounded = connector._fit_prompt_to_transport_limit(
            runtime, messages, "oversized transcript " + ("x" * 1000)
        )

        assert len(bounded.encode("utf-8")) <= 600
        assert "Older transcript entries were omitted" in bounded
        assert "latest request must survive" in bounded

    def test_available_models(self, connector: EveAcpConnector) -> None:
        connector._model = "auto"
        assert connector.get_available_models() == ["eve/auto"]

        connector._configured_models = ["claude-3-7-sonnet", "gpt-4o"]
        assert connector.get_available_models() == [
            "eve/claude-3-7-sonnet",
            "eve/gpt-4o",
        ]


class TestEveConfiguredModelEnumerator:
    async def test_enumerates_unavailable_when_executable_missing(self) -> None:
        enumerator = EveConfiguredModelEnumerator()
        cfg = BackendConfig(connector="eve-acp")
        with patch("src.connectors.eve_acp.resolve_eve_executable", return_value=None):
            res = await enumerator.enumerate("eve-acp.default", cfg)
        assert res.status == "unavailable"
        assert res.error_code == "executable_not_found"

    async def test_enumerates_configured_models(self) -> None:
        enumerator = EveConfiguredModelEnumerator()
        cfg = BackendConfig(
            connector="eve-acp",
            models=["claude-3.7-sonnet", "eve/gpt-4o"],
        )
        with patch(
            "src.connectors.eve_acp.resolve_eve_executable", return_value="/bin/eve"
        ):
            res = await enumerator.enumerate("eve-acp.default", cfg)
        assert res.status == "available"
        assert res.models == ("eve/claude-3.7-sonnet", "eve/gpt-4o")
        assert res.instance_pinned is True

    async def test_enumerates_default_model(self) -> None:
        enumerator = EveConfiguredModelEnumerator()
        cfg = BackendConfig(
            connector="eve-acp",
            extra={"model": "claude-3.7-sonnet"},
        )
        with patch(
            "src.connectors.eve_acp.resolve_eve_executable", return_value="/bin/eve"
        ):
            res = await enumerator.enumerate("eve-acp.default", cfg)
        assert res.status == "available"
        assert "eve/claude-3.7-sonnet" in res.models
        assert "eve/auto" in res.models
        assert res.instance_pinned is True

    async def test_enumerates_auto_when_empty(self) -> None:
        enumerator = EveConfiguredModelEnumerator()
        cfg = BackendConfig(connector="eve-acp")
        with patch(
            "src.connectors.eve_acp.resolve_eve_executable", return_value="/bin/eve"
        ):
            res = await enumerator.enumerate("eve-acp.default", cfg)
        assert res.status == "available"
        assert "eve/zai/glm-5.2" in res.models
        assert "eve/glm-5.2" in res.models
        assert "eve/auto" in res.models
        assert res.instance_pinned is True


class TestEveAcpRateLimitHandling:
    def test_is_rate_limit_error_detection(self) -> None:
        from src.connectors.acp_core.base_connector import is_rate_limit_error

        assert (
            is_rate_limit_error(
                "Failed after 3 attempts. Last error: GatewayRateLimitError: Free tier requests on this model are rate-limited."
            )
            is True
        )
        assert is_rate_limit_error("HTTP 429 Too Many Requests") is True
        assert is_rate_limit_error("rate limit exceeded, please retry later") is True
        assert is_rate_limit_error("quota exceeded for resource") is True
        assert is_rate_limit_error("syntax error in python file") is False
        assert is_rate_limit_error(None) is False

    async def test_iter_acp_stream_pieces_retries_on_rate_limit(
        self, connector: EveAcpConnector, temp_workspace: Path
    ) -> None:
        from src.connectors.acp_core.types import (
            ACPError,
            ACPNotification,
            ACPProcessRuntime,
        )

        runtime = ACPProcessRuntime(
            project_dir=temp_workspace,
            model="zai/glm-5.2",
            session_id="sess-123",
            last_prompt_params={
                "sessionId": "sess-123",
                "prompt": [{"type": "text", "text": "hello"}],
                "messageId": "msg-1",
            },
        )

        # First prompt request id: 1
        # Response 1: GatewayRateLimitError on id 1
        # Retry prompt request id: 2
        # Response 2: Success on id 2
        rate_limit_response = ACPNotification(
            id=1,
            error=ACPError(
                code=-32000,
                message="Failed after 3 attempts. Last error: GatewayRateLimitError: Free tier requests on this model are rate-limited.",
            ),
        )
        success_response = ACPNotification(id=2, result={})

        read_queue: asyncio.Queue[ACPNotification | None] = asyncio.Queue()
        await read_queue.put(rate_limit_response)
        await read_queue.put(success_response)

        async def mock_read(_rt: Any) -> ACPNotification | None:
            return await read_queue.get()

        send_calls: list[tuple[str, dict[str, Any]]] = []

        async def mock_send(
            _rt: Any, method: str, params: dict[str, Any] | None = None
        ) -> int:
            send_calls.append((method, params or {}))
            return 2  # Return next id

        connector._rate_limit_backoff_delays = (0.01,)
        with (
            patch.object(connector, "_read_jsonrpc_message", side_effect=mock_read),
            patch.object(connector, "_send_jsonrpc_message", side_effect=mock_send),
        ):
            pieces = []
            async for piece in connector._iter_acp_stream_pieces(
                runtime, prompt_request_id=1, response_model="zai/glm-5.2"
            ):
                pieces.append(piece)

        # Verified retry was sent
        assert len(send_calls) == 1
        assert send_calls[0][0] == "session/prompt"
        assert send_calls[0][1]["sessionId"] == "sess-123"
        # Backoff notice piece was yielded
        assert any(
            piece.content and "Rate limit encountered" in piece.content
            for piece in pieces
        )

    async def test_iter_acp_stream_pieces_retries_transient_glm_promo_503(
        self, connector: EveAcpConnector, temp_workspace: Path
    ) -> None:
        from src.connectors.acp_core.types import ACPProcessRuntime

        runtime = ACPProcessRuntime(
            project_dir=temp_workspace,
            model="zai/glm-5.2",
            session_id="sess-123",
            last_prompt_params={
                "sessionId": "sess-123",
                "prompt": [{"type": "text", "text": "hello"}],
                "messageId": "msg-1",
            },
        )
        service_unavailable_response = ACPNotification(
            id=1,
            error=ACPError(
                code=-32002,
                message="Failed after 3 attempts. Last error: GatewayInternalServerError: Service temporarily unavailable. Please try again shortly.",
                data={
                    "code": "MODEL_CALL_FAILED",
                    "details": {"detail": '{"statusCode":503}'},
                },
            ),
        )
        success_response = ACPNotification(id=2, result={})
        read_queue: asyncio.Queue[ACPNotification | None] = asyncio.Queue()
        await read_queue.put(service_unavailable_response)
        await read_queue.put(success_response)

        async def mock_read(_rt: Any) -> ACPNotification | None:
            return await read_queue.get()

        send_calls: list[tuple[str, dict[str, Any]]] = []

        async def mock_send(
            _rt: Any, method: str, params: dict[str, Any] | None = None
        ) -> int:
            send_calls.append((method, params or {}))
            return 2

        connector._promo_retry_backoff_delays = (0.01,)
        with (
            patch.object(connector, "_read_jsonrpc_message", side_effect=mock_read),
            patch.object(connector, "_send_jsonrpc_message", side_effect=mock_send),
        ):
            pieces = []
            async for piece in connector._iter_acp_stream_pieces(
                runtime, prompt_request_id=1, response_model="zai/glm-5.2"
            ):
                pieces.append(piece)

        assert len(send_calls) == 1
        assert send_calls[0][0] == "session/prompt"
        assert send_calls[0][1]["sessionId"] == "sess-123"
        assert any(
            piece.content
            and "Eve GLM 5.2 promo is temporarily unavailable" in piece.content
            for piece in pieces
        )

    def test_promo_retry_does_not_apply_to_other_models(
        self, connector: EveAcpConnector, temp_workspace: Path
    ) -> None:
        runtime = connector._create_runtime(temp_workspace, "zai/glm-5.1")
        error = ACPError(
            code=-32002,
            message="GatewayInternalServerError: Service temporarily unavailable",
            data={"details": {"statusCode": 503}},
        )

        assert (
            connector._acp_transient_error_retry_delays(runtime, "zai/glm-5.1", error)
            == ()
        )
