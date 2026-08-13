from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest
from pydantic.types import JsonValue
from src.connectors.acp_core.types import ACPNotification
from src.connectors.agy_cli_acp import (
    DEFAULT_AGY_PROCESS_TIMEOUT_SECONDS,
    AgyCliAcpConnector,
    AgyCliConfiguredModelEnumerator,
    build_agy_acp_wrapper_command,
    build_agy_model_catalog_command,
    canonicalize_agy_model_id,
    parse_agy_models_catalog,
    parse_wrapper_model_catalog,
    resolve_agy_acp_wrapper_executable,
    run_agy_model_catalog_probe,
)
from src.connectors.contracts import ConnectorChatCompletionsRequest
from src.core.common.exceptions import ConfigurationError
from src.core.config.app_config import AppConfig, BackendConfig
from src.core.domain.chat import CanonicalChatRequest, ChatMessage
from src.core.services.model_capability_index import ModelCapabilityIndex
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
    async def test_wrapper_probe_does_not_require_asyncio_subprocess_support(
        self,
    ) -> None:
        process = MagicMock()
        process.communicate.return_value = (b"google/gemini-3.6-flash\n", b"")
        process.returncode = 0

        with (
            patch(
                "asyncio.create_subprocess_exec",
                AsyncMock(side_effect=NotImplementedError),
            ),
            patch(
                "src.connectors.agy_cli_acp.subprocess.Popen",
                return_value=process,
            ) as popen,
        ):
            result = await run_agy_model_catalog_probe(
                ["go-agy-acp-wrapper.exe", "--list-models"],
                timeout=1,
            )

        assert result == (0, b"google/gemini-3.6-flash\n", b"")
        popen.assert_called_once_with(
            ["go-agy-acp-wrapper.exe", "--list-models"],
            stdout=-1,
            stderr=-1,
            shell=False,
        )

    def test_parse_models_catalog_collapses_effort_variants(self) -> None:
        assert parse_agy_models_catalog(
            "gemini-3.6-flash-high\n"
            "gemini-3.6-flash-medium\n"
            "gemini-3.6-flash-low\n"
            "claude-opus-4-6-thinking\n"
            "gpt-oss-120b-medium\n"
        ) == [
            "google/gemini-3.6-flash",
            "anthropic/claude-opus-4.6",
            "openai/gpt-oss-120b",
        ]

    def test_canonicalize_rejects_unknown_family(self) -> None:
        assert canonicalize_agy_model_id("future-model-high") is None

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

    def test_build_wrapper_catalog_command(self) -> None:
        assert build_agy_model_catalog_command(
            r"C:\tools\go-agy-acp-wrapper.exe",
            agy_binary=r"C:\tools\agy.exe",
        ) == [
            r"C:\tools\go-agy-acp-wrapper.exe",
            "--list-models",
            "--agy-binary",
            r"C:\tools\agy.exe",
        ]

    def test_parse_wrapper_catalog_accepts_only_canonical_models(self) -> None:
        assert parse_wrapper_model_catalog(
            "google/gemini-3.6-flash\n"
            "anthropic/claude-opus-4.6\n"
            "google/gemini-3.6-flash\n"
            "gemini-3.6-flash-high\n"
            "invalid model\n"
        ) == [
            "google/gemini-3.6-flash",
            "anthropic/claude-opus-4.6",
        ]

    def test_resolve_wrapper_prefers_existing_file(self, tmp_path: Path) -> None:
        exe = tmp_path / "go-agy-acp-wrapper.exe"
        exe.write_text("noop", encoding="utf-8")
        assert resolve_agy_acp_wrapper_executable(str(exe)) == str(exe.resolve())

    def test_connector_default_process_timeout_is_four_hours(
        self, connector: AgyCliAcpConnector
    ) -> None:
        assert connector._process_timeout == DEFAULT_AGY_PROCESS_TIMEOUT_SECONDS
        assert DEFAULT_AGY_PROCESS_TIMEOUT_SECONDS == 14400.0


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
                models=["google/gemini-3.5-flash-medium"],
            )
        assert connector.is_backend_functional() is True
        assert connector._default_project_dir == temp_workspace.resolve()
        assert connector._model == "google/gemini-3.5-flash-medium"
        assert connector._process_timeout == DEFAULT_AGY_PROCESS_TIMEOUT_SECONDS

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
            await connector.initialize(
                wrapper_executable=fake,
                models=["google/gemini-3.5-flash"],
            )
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

    def test_available_models_are_empty_before_initialization(
        self, connector: AgyCliAcpConnector
    ) -> None:
        assert connector.get_available_models() == []

    async def test_initialize_discovers_models_when_not_configured(
        self,
        connector: AgyCliAcpConnector,
        temp_workspace: Path,
    ) -> None:
        fake = str(temp_workspace / "go-agy-acp-wrapper.exe")
        Path(fake).write_text("noop", encoding="utf-8")
        with (
            patch.object(connector, "_check_wrapper_available", return_value=True),
            patch.object(
                connector,
                "_discover_models",
                AsyncMock(return_value=["google/gemini-3.6-flash"]),
            ) as discover,
        ):
            await connector.initialize(wrapper_executable=fake)

        discover.assert_awaited_once()
        assert connector.get_available_models() == ["google/gemini-3.6-flash"]

    async def test_discover_models_uses_wrapper_catalog_command(
        self,
        connector: AgyCliAcpConnector,
    ) -> None:
        connector._wrapper_executable = r"C:\tools\go-agy-acp-wrapper.exe"
        connector._agy_binary = r"C:\tools\agy.exe"
        with patch.object(
            connector,
            "_run_probe",
            AsyncMock(
                return_value=(
                    0,
                    b"google/gemini-3.6-flash\nanthropic/claude-opus-4.6\n",
                    b"",
                )
            ),
        ) as run_probe:
            models = await connector._discover_models()

        run_probe.assert_awaited_once_with(
            [
                r"C:\tools\go-agy-acp-wrapper.exe",
                "--list-models",
                "--agy-binary",
                r"C:\tools\agy.exe",
            ],
            timeout=15,
        )
        assert models == [
            "google/gemini-3.6-flash",
            "anthropic/claude-opus-4.6",
        ]

    async def test_available_models_preserve_explicit_configuration(
        self,
        connector: AgyCliAcpConnector,
        temp_workspace: Path,
    ) -> None:
        fake = str(temp_workspace / "go-agy-acp-wrapper.exe")
        Path(fake).write_text("noop", encoding="utf-8")
        with patch.object(connector, "_check_wrapper_available", return_value=True):
            await connector.initialize(
                wrapper_executable=fake,
                models=[
                    "google/gemini-3.5-flash-high",
                    "anthropic/claude-sonnet-4.6-thinking",
                ],
            )

        assert connector.get_available_models() == [
            "google/gemini-3.5-flash-high",
            "anthropic/claude-sonnet-4.6-thinking",
        ]


class TestAgyCliConfiguredModelEnumerator:
    async def test_enumerates_wrapper_canonical_catalog(self, tmp_path: Path) -> None:
        wrapper = tmp_path / "go-agy-acp-wrapper.exe"
        wrapper.write_text("fixture", encoding="utf-8")
        enumerator = AgyCliConfiguredModelEnumerator()

        with patch(
            "src.connectors.agy_cli_acp.run_agy_model_catalog_probe",
            AsyncMock(
                return_value=(
                    0,
                    b"google/gemini-3.6-flash\nopenai/gpt-oss-120b\n",
                    b"",
                )
            ),
        ):
            result = await enumerator.enumerate(
                "agy-cli-acp.default",
                BackendConfig(
                    connector="agy-cli-acp",
                    extra={
                        "wrapper_executable": str(wrapper),
                        "agy_binary": "agy.exe",
                    },
                ),
            )

        assert result.models == (
            "google/gemini-3.6-flash",
            "openai/gpt-oss-120b",
        )
        assert result.source == "agy_wrapper"
        assert result.instance_pinned is True

        index = ModelCapabilityIndex(
            ModelCapabilityIndex.build_snapshot(
                {"agy-cli-acp.default": result.models},
                generation=1,
                instance_route_policy={
                    "agy-cli-acp.default": "instance_pinned",
                },
            )
        )
        assert index.get_candidates("agy-cli-acp:google/gemini-3.6-flash") == [
            "agy-cli-acp.default"
        ]
