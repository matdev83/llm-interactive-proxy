from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest
from pydantic.types import JsonValue
from src.connectors.acp_core.types import ACPNotification
from src.connectors.agy_cli_acp import (
    AgyCliAcpConnector,
    build_agy_acp_wrapper_command,
    resolve_agy_acp_wrapper_executable,
)
from src.connectors.contracts import ConnectorChatCompletionsRequest
from src.core.common.exceptions import ConfigurationError
from src.core.config.app_config import AppConfig
from src.core.domain.chat import CanonicalChatRequest, ChatMessage
from src.core.services.translation_service import TranslationService


@pytest.fixture
def temp_workspace(tmp_path: Path) -> Path:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    return workspace


@pytest.fixture
def connector() -> AgyCliAcpConnector:
    client = AsyncMock(spec=httpx.AsyncClient)
    return AgyCliAcpConnector(client, AppConfig(), TranslationService())


def _make_request(
    *,
    stream: bool = False,
    options: dict[str, JsonValue] | None = None,
    model: str = "google/gemini-3.5-flash-high",
) -> ConnectorChatCompletionsRequest:
    request = CanonicalChatRequest(
        model=model,
        stream=stream,
        messages=[ChatMessage(role="user", content="hello")],
    )
    return ConnectorChatCompletionsRequest(
        request=request,
        processed_messages=[ChatMessage(role="user", content="hello")],
        effective_model=model,
        identity=None,
        cancellation_token=None,
        cancellation_coordinator=None,
        context=None,
        options=options or {},
    )


class TestAgyCliAcpHelpers:
    def test_build_agy_acp_wrapper_command_full(self) -> None:
        cmd = build_agy_acp_wrapper_command(
            r"C:\tools\go-agy-acp-wrapper.exe",
            agy_binary="agy.exe",
            model="google/gemini-3.5-flash-medium",
            timeout_seconds=123,
            skip_permissions=True,
            extra_args=["--foo"],
        )
        assert cmd == [
            r"C:\tools\go-agy-acp-wrapper.exe",
            "--agy-binary",
            "agy.exe",
            "--model",
            "google/gemini-3.5-flash-medium",
            "--timeout-seconds",
            "123",
            "--skip-permissions",
            "--foo",
        ]

    def test_build_agy_acp_wrapper_command_auto_model_uses_wrapper_default(
        self,
    ) -> None:
        cmd = build_agy_acp_wrapper_command(
            "go-agy-acp-wrapper",
            agy_binary=None,
            model="auto",
            timeout_seconds=None,
            skip_permissions=False,
            extra_args=None,
        )
        assert cmd == ["go-agy-acp-wrapper", "--no-skip-permissions"]

    def test_resolve_wrapper_prefers_existing_file(self, tmp_path: Path) -> None:
        exe = tmp_path / "go-agy-acp-wrapper.exe"
        exe.write_text("noop", encoding="utf-8")
        assert resolve_agy_acp_wrapper_executable(str(exe)) == str(exe.resolve())


class TestAgyCliAcpInitialization:
    async def test_initialize_with_project_dir(
        self, connector: AgyCliAcpConnector, temp_workspace: Path
    ) -> None:
        fake = str(temp_workspace / "go-agy-acp-wrapper.exe")
        Path(fake).write_text("noop", encoding="utf-8")
        with patch.object(connector, "_check_wrapper_available", return_value=True):
            await connector.initialize(
                project_dir=str(temp_workspace),
                wrapper_executable=fake,
                agy_binary="agy.exe",
                model="google/gemini-3.5-flash-medium",
            )
        assert connector.is_backend_functional() is True
        assert connector._default_project_dir == temp_workspace.resolve()
        assert connector._model == "google/gemini-3.5-flash-medium"

    async def test_initialize_requires_existing_workspace(
        self, connector: AgyCliAcpConnector, tmp_path: Path
    ) -> None:
        with (
            patch.object(connector, "_check_wrapper_available", return_value=True),
            pytest.raises(ConfigurationError),
        ):
            await connector.initialize(project_dir=str(tmp_path / "missing"))
        assert connector.is_backend_functional() is False

    async def test_initialize_without_workspace_uses_runtime_project_dir(
        self, connector: AgyCliAcpConnector, temp_workspace: Path
    ) -> None:
        fake = str(temp_workspace / "go-agy-acp-wrapper.exe")
        Path(fake).write_text("noop", encoding="utf-8")
        with patch.object(connector, "_check_wrapper_available", return_value=True):
            await connector.initialize(wrapper_executable=fake)
        assert connector.is_backend_functional() is True
        assert connector._default_project_dir is None


class TestAgyCliAcpProtocol:
    async def test_prepare_prompt_sends_initialize_authenticate_session(
        self, connector: AgyCliAcpConnector, temp_workspace: Path
    ) -> None:
        connector._default_project_dir = temp_workspace
        runtime = connector._create_runtime(
            temp_workspace, "google/gemini-3.5-flash-medium"
        )
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
                await connector._prepare_turn_request_locked(
                    runtime,
                    _make_request(model="google/gemini-3.5-flash-medium"),
                )
            )

        assert prompt_request_id == 4
        assert requested_model == "google/gemini-3.5-flash-medium"
        assert runtime.session_id == "sid-1"
        assert runtime.initialized is True
        assert [c.args[1] for c in send_jsonrpc.await_args_list] == [
            "initialize",
            "authenticate",
            "session/new",
            "session/prompt",
        ]
        assert send_jsonrpc.await_args_list[1].args[2] == {"methodId": "agy"}

    async def test_handle_agy_extension_replies_empty_result(
        self, connector: AgyCliAcpConnector, temp_workspace: Path
    ) -> None:
        runtime = connector._create_runtime(temp_workspace, "auto")
        runtime.process = MagicMock()
        runtime.process.stdin = MagicMock()
        written: list[bytes] = []

        def capture_write(data: bytes) -> int:
            written.append(data)
            return len(data)

        runtime.process.stdin.write.side_effect = capture_write
        runtime.process.stdin.flush = MagicMock()

        await connector._handle_server_request(
            runtime, ACPNotification(method="agy/unknown", id=7, params={})
        )
        payload = json.loads(written[-1].decode("utf-8"))
        assert payload["id"] == 7
        assert payload["result"] == {}


class TestAgyCliAcpRuntime:
    async def test_acquire_runtime_uses_project_dir_override(
        self,
        connector: AgyCliAcpConnector,
        temp_workspace: Path,
        tmp_path: Path,
    ) -> None:
        other = tmp_path / "other"
        other.mkdir()
        connector._default_project_dir = temp_workspace
        runtime = await connector._acquire_runtime(
            _make_request(options={"project_dir": str(other)})
        )
        assert runtime.project_dir == other.resolve()

    def test_available_models_are_prefixed(self, connector: AgyCliAcpConnector) -> None:
        models = connector.get_available_models()
        assert "google/gemini-3.5-flash-high" in models
        assert "google/gemini-3.5-flash-medium" in models
        assert "google/gemini-3.5-flash-low" in models
        assert "google/gemini-3.1-pro" in models
        assert "anthropic/claude-sonnet-4.6-thinking" in models
        assert "anthropic/claude-opus-4.6-thinking" in models
