"""Unit tests for the OpenAI Codex App Server connector.

Covers pure helpers, the event mapper, the approval decision function, the
JSON-RPC transport (with a fake process), the strict handshake order,
workspace validation, cancellation primitives, the non-streaming accumulation
helper, and the async subprocess lifecycle (spawn/kill/reap/streaming/
cancellation/chat_completions) exercised entirely via fakes and mocks -- no
real Codex subprocess is spawned here.
"""

from __future__ import annotations

import asyncio
import json
import os
from collections.abc import AsyncGenerator, Sequence
from pathlib import Path
from typing import Any, cast
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest
from pydantic.types import JsonValue
from src.connectors.acp_core.base_connector import _hash_chat_messages_prefix_stable
from src.connectors.acp_core.transcript import ACPTranscriptSerializer
from src.connectors.acp_core.types import ACPNotification, HistoryState
from src.connectors.acp_core.workspace_policy import ACP_MISSING_PROJECT_WORKSPACE_CODE
from src.connectors.codex_helpers import candidate_codex_executables
from src.connectors.contracts import (
    ConnectorChatCompletionsRequest,
    ConnectorRequestContext,
)
from src.connectors.openai_codex.catalog.interfaces import ICodexModelCatalog
from src.connectors.openai_codex.catalog.parser import CodexCatalogParser
from src.connectors.openai_codex_app_server import (
    CodexAppServerRuntime,
    CodexEventMapper,
    CodexStreamPiece,
    OpenAICodexAppServerConnector,
    accumulate_pieces,
    build_codex_app_server_command,
    build_turn_interrupt_payload,
    decide_codex_server_request,
    is_auto_model,
    map_reasoning_effort_to_codex_effort,
    resolve_codex_executable,
    sanitize_approval_summary,
    strip_openai_model_prefix,
)
from src.core.common.exceptions import (
    APIConnectionError,
    BackendError,
    ConfigurationError,
    ServiceUnavailableError,
)
from src.core.config.app_config import AppConfig
from src.core.domain.chat import CanonicalChatRequest, ChatMessage
from src.core.domain.responses import ResponseEnvelope, StreamingResponseEnvelope
from src.core.services.translation_service import TranslationService

from tests.unit.connectors.openai_codex.catalog.conftest import make_raw_catalog

# ---------------------------------------------------------------------------
# Fakes
# ---------------------------------------------------------------------------


class FakeStdin:
    """Records bytes written by the transport; ``flush`` is a no-op."""

    def __init__(self) -> None:
        self.writes: list[bytes] = []
        self._closed = False

    def write(self, data: bytes) -> int:
        self.writes.append(data)
        return len(data)

    def flush(self) -> None:
        pass

    def close(self) -> None:
        self._closed = True


class FakeStdout:
    """Pops pre-queued bytes lines from ``readline``."""

    def __init__(self, lines: Sequence[bytes]) -> None:
        self._lines: list[bytes] = list(lines)
        self._closed = False

    def readline(self, size: int = -1) -> bytes:
        _ = size
        if self._lines:
            return self._lines.pop(0)
        return b""

    def close(self) -> None:
        self._closed = True


class FakeStderr:
    def __init__(self) -> None:
        self._closed = False

    def read(self) -> bytes:
        return b""

    def close(self) -> None:
        self._closed = True


class FakeProcess:
    """Minimal subprocess-like process backed by in-memory buffers."""

    def __init__(self, stdout_lines: Sequence[bytes]) -> None:
        self.stdin = FakeStdin()
        self.stdout = FakeStdout(stdout_lines)
        self.stderr = FakeStderr()
        self.pid = 4242
        self._poll: int | None = None
        self.terminated = False
        self.killed = False
        self.wait_calls: list[float | None] = []

    def poll(self) -> int | None:
        return self._poll

    def terminate(self) -> None:
        self.terminated = True
        self._poll = 0

    def kill(self) -> None:
        self.killed = True
        self._poll = 0

    def wait(self, timeout: float | None = None) -> int:
        self.wait_calls.append(timeout)
        return self._poll or 0


class ExitOnCloseStdin(FakeStdin):
    """``FakeStdin`` whose ``close()`` simulates the Codex child exiting.

    The Codex app-server shuts down when stdin closes; this fake models that
    by flipping the owning process's ``poll()`` to ``0`` on close so the real
    ``_wait_for_process_exit`` returns ``True`` via its early-return path.
    """

    def __init__(self, process: FakeProcess) -> None:
        super().__init__()
        self._process = process

    def close(self) -> None:
        super().close()
        self._process._poll = 0


def _make_runtime(
    project_dir: Path,
    *,
    model: str = "auto",
    stdout_lines: Sequence[bytes] | None = None,
    thread_id: str | None = None,
    turn_id: str | None = None,
) -> CodexAppServerRuntime:
    runtime = CodexAppServerRuntime(project_dir=project_dir, model=model)
    runtime.process_lock = asyncio.Lock()
    runtime.request_lock = asyncio.Lock()
    runtime.cancellation_lock = asyncio.Lock()
    runtime.cancellation_event = asyncio.Event()
    if stdout_lines is not None:
        runtime.process = FakeProcess(stdout_lines)
    runtime.thread_id = thread_id
    runtime.turn_id = turn_id
    return runtime


def _make_request(
    *,
    stream: bool = False,
    extra_body: dict[str, JsonValue] | None = None,
    options: dict[str, JsonValue] | None = None,
    processed_messages: list[ChatMessage] | None = None,
    model: str = "openai/auto",
    session_id: str | None = None,
    reasoning_effort: str | None = None,
    verbosity: str | None = None,
) -> ConnectorChatCompletionsRequest:
    request = CanonicalChatRequest(
        model=model,
        stream=stream,
        messages=[ChatMessage(role="user", content="hello")],
        extra_body=extra_body,
        reasoning_effort=reasoning_effort,
        verbosity=verbosity,
    )
    context: ConnectorRequestContext | None = None
    if session_id is not None:
        context = ConnectorRequestContext(
            request_id=None, session_id=session_id, client_host=None
        )
    return ConnectorChatCompletionsRequest(
        request=request,
        processed_messages=(
            processed_messages
            if processed_messages is not None
            else [ChatMessage(role="user", content="hello")]
        ),
        effective_model=model,
        identity=None,
        cancellation_token=None,
        cancellation_coordinator=None,
        context=context,
        options=options or {},
    )


@pytest.fixture
def connector() -> OpenAICodexAppServerConnector:
    from src.core.di.container import ServiceCollection
    from src.core.di.services import set_service_provider

    services = ServiceCollection()
    # Register a fake discovered catalog (mirrors CodexModelCatalogStage) so the
    # connector resolves a deterministic catalog from DI.
    services.add_instance(
        cast(type, ICodexModelCatalog),
        CodexCatalogParser().parse(make_raw_catalog()),
    )
    set_service_provider(services.build_service_provider())
    client = AsyncMock(spec=httpx.AsyncClient)
    return OpenAICodexAppServerConnector(client, AppConfig(), TranslationService())


@pytest.fixture
def temp_workspace(tmp_path: Path) -> Path:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    return workspace


def _decode_writes(runtime: CodexAppServerRuntime) -> list[dict[str, Any]]:
    assert isinstance(runtime.process, FakeProcess)
    return [json.loads(w.decode("utf-8").strip()) for w in runtime.process.stdin.writes]


def _last_turn_start_input_text(runtime: CodexAppServerRuntime) -> str:
    """Return the ``text`` payload of the most recent ``turn/start`` write."""
    writes = _decode_writes(runtime)
    turn_starts = [w for w in writes if w.get("method") == "turn/start"]
    assert turn_starts, f"no turn/start write found; writes={writes!r}"
    return str(turn_starts[-1]["params"]["input"][0]["text"])


# ---------------------------------------------------------------------------
# Command builder
# ---------------------------------------------------------------------------


class TestBuildCodexAppServerCommand:
    def test_global_flags_before_app_server(self) -> None:
        cmd = build_codex_app_server_command("/usr/local/bin/codex")
        assert cmd[0] == "/usr/local/bin/codex"
        idx_dangerous = cmd.index("--dangerously-bypass-approvals-and-sandbox")
        idx_search = cmd.index("--search")
        idx_app_server = cmd.index("app-server")
        assert idx_dangerous < idx_app_server
        assert idx_search < idx_app_server

    def test_stdio_present_after_app_server(self) -> None:
        cmd = build_codex_app_server_command("codex")
        idx_app_server = cmd.index("app-server")
        idx_stdio = cmd.index("--stdio")
        assert idx_stdio > idx_app_server
        assert cmd[-1] == "--stdio"

    def test_config_overrides_inserted_as_pairs(self) -> None:
        cmd = build_codex_app_server_command(
            "codex",
            codex_config_overrides=["model_reasoning_effort=high", "foo=bar"],
        )
        assert cmd[-3] == "-c"
        assert cmd[-2] == "foo=bar"
        assert cmd[-1] == "--stdio"
        # Both override pairs sit between app-server and --stdio.
        idx_app_server = cmd.index("app-server")
        idx_stdio = cmd.index("--stdio")
        assert (
            cmd[idx_app_server + 1 : idx_stdio]
            == [
                "-c",
                "model_reasoning_effort=high",
                "-c",
                "foo=bar",
                "--stdio",
            ][:-1]
        )

    def test_extra_args_appended(self) -> None:
        cmd = build_codex_app_server_command(
            "codex",
            app_server_extra_args=["--verbose", "--debug"],
        )
        assert cmd[-3:] == ["--stdio", "--verbose", "--debug"]

    def test_model_not_in_command(self) -> None:
        cmd = build_codex_app_server_command("codex")
        assert "--model" not in cmd
        assert "gpt-5.4" not in cmd


# ---------------------------------------------------------------------------
# Executable resolution
# ---------------------------------------------------------------------------


class TestResolveCodexExecutable:
    def test_configured_existing_file_returns_resolved(self, tmp_path: Path) -> None:
        exe = tmp_path / "codex-bin"
        exe.write_text("#!/bin/sh\n", encoding="utf-8")
        resolved = resolve_codex_executable(str(exe))
        assert resolved == str(exe.resolve())

    def test_configured_missing_falls_back_to_env(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        env_exe = tmp_path / "env-codex"
        env_exe.write_text("#!/bin/sh\n", encoding="utf-8")
        monkeypatch.setenv("CODEX_BIN", str(env_exe))
        resolved = resolve_codex_executable(str(tmp_path / "does-not-exist"))
        assert resolved == str(env_exe.resolve())

    def test_path_fallback_via_which(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("CODEX_BIN", raising=False)

        def fake_which(name: str) -> str | None:
            if name == "codex":
                return "/fake/bin/codex"
            return None

        monkeypatch.setattr("src.connectors.codex_helpers.shutil.which", fake_which)
        resolved = resolve_codex_executable(None)
        assert resolved == "/fake/bin/codex"

    def test_missing_entirely_returns_none(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("CODEX_BIN", raising=False)
        monkeypatch.delenv("APPDATA", raising=False)
        monkeypatch.delenv("LOCALAPPDATA", raising=False)
        monkeypatch.setattr("src.connectors.codex_helpers.shutil.which", lambda _: None)
        # Point Path.home() at the empty tmp_path so the POSIX candidates
        # (~/.local/bin/codex, ~/.npm-global/bin/codex) cannot resolve to a
        # real user home that happens to contain a codex binary.
        monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
        assert resolve_codex_executable(None) is None


# ---------------------------------------------------------------------------
# Cross-platform candidate enumeration
# ---------------------------------------------------------------------------


class TestCandidateCodexExecutables:
    """candidate_codex_executables: ordered, de-duplicated, cross-platform."""

    def test_returns_configured_first_then_env_then_which(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        configured = tmp_path / "configured-codex"
        configured.write_text("#!/bin/sh\n", encoding="utf-8")
        env_exe = tmp_path / "env-codex"
        env_exe.write_text("#!/bin/sh\n", encoding="utf-8")
        which_exe = tmp_path / "which-codex"
        which_exe.write_text("#!/bin/sh\n", encoding="utf-8")

        monkeypatch.setenv("CODEX_BIN", str(env_exe))
        monkeypatch.delenv("APPDATA", raising=False)
        monkeypatch.delenv("LOCALAPPDATA", raising=False)
        monkeypatch.setattr(
            "src.connectors.codex_helpers.shutil.which",
            lambda name: str(which_exe) if name == "codex" else None,
        )
        monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))

        candidates = candidate_codex_executables(str(configured))

        # Configured is first, then CODEX_BIN, then which("codex").
        assert candidates[0] == str(configured.resolve())
        assert candidates[1] == str(env_exe.resolve())
        assert candidates[2] == str(which_exe)

    def test_deduplicates_by_resolved_path(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # The same file reachable via two sources must appear only once.
        exe = tmp_path / "codex"
        exe.write_text("#!/bin/sh\n", encoding="utf-8")
        monkeypatch.setenv("CODEX_BIN", str(exe))
        monkeypatch.delenv("APPDATA", raising=False)
        monkeypatch.delenv("LOCALAPPDATA", raising=False)
        # which("codex") returns the same absolute path as configured.
        monkeypatch.setattr(
            "src.connectors.codex_helpers.shutil.which",
            lambda name: str(exe) if name == "codex" else None,
        )
        monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))

        candidates = candidate_codex_executables(str(exe))

        # The configured, CODEX_BIN, and which hits all resolve to the same
        # real path -> exactly one entry.
        assert candidates == [str(exe.resolve())]

    def test_no_hardcoded_personal_paths(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # Every returned candidate must be sourced from the inputs we control
        # (configured, CODEX_BIN, shutil.which, APPDATA, LOCALAPPDATA,
        # Path.home) -- never a literal like C:\Users\<name>\... or
        # /Users/<name>/... . We set every input to a path under tmp_path and
        # then assert every candidate's real path is in the allowed set. A
        # hardcoded personal path would not be in the allowed set and would
        # fail the assertion. (We cannot assert "no <name> substring" because
        # tmp_path itself may contain the user name on the dev machine.)
        configured = tmp_path / "configured-codex"
        configured.write_text("#!/bin/sh\n", encoding="utf-8")
        env_exe = tmp_path / "env-codex"
        env_exe.write_text("#!/bin/sh\n", encoding="utf-8")
        which_codex = tmp_path / "which-codex"
        which_codex.write_text("#!/bin/sh\n", encoding="utf-8")
        (tmp_path / "npm-appdata").mkdir()
        (tmp_path / "npm-localappdata").mkdir()
        appdata_codex = tmp_path / "npm-appdata" / "codex.cmd"
        appdata_codex.write_text("@echo off\n", encoding="utf-8")
        localappdata_codex = tmp_path / "npm-localappdata" / "codex.cmd"
        localappdata_codex.write_text("@echo off\n", encoding="utf-8")
        home = tmp_path / "home"
        (home / ".local" / "bin").mkdir(parents=True)
        (home / ".npm-global" / "bin").mkdir(parents=True)
        home_local = home / ".local" / "bin" / "codex"
        home_local.write_text("#!/bin/sh\n", encoding="utf-8")
        home_npm = home / ".npm-global" / "bin" / "codex"
        home_npm.write_text("#!/bin/sh\n", encoding="utf-8")

        monkeypatch.setenv("CODEX_BIN", str(env_exe))
        monkeypatch.setenv("APPDATA", str(tmp_path / "npm-appdata"))
        monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "npm-localappdata"))
        monkeypatch.setattr(
            "src.connectors.codex_helpers.shutil.which",
            lambda name: str(which_codex),
        )
        monkeypatch.setattr(Path, "home", classmethod(lambda cls: home))

        candidates = candidate_codex_executables(str(configured))

        allowed = {
            os.path.realpath(str(configured)),
            os.path.realpath(str(env_exe)),
            os.path.realpath(str(which_codex)),
            os.path.realpath(str(appdata_codex)),
            os.path.realpath(str(localappdata_codex)),
            os.path.realpath(str(home_local)),
            os.path.realpath(str(home_npm)),
        }
        assert candidates, "expected at least one candidate"
        for c in candidates:
            assert (
                os.path.realpath(c) in allowed
            ), f"candidate not derived from env/which/home inputs: {c!r}"

    def test_windows_adds_appdata_and_localappdata_npm_candidates(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        appdata = tmp_path / "AppData"
        localappdata = tmp_path / "LocalAppData"
        (appdata / "npm").mkdir(parents=True)
        (localappdata / "npm").mkdir(parents=True)
        appdata_codex = appdata / "npm" / "codex.cmd"
        appdata_codex.write_text("@echo off\n", encoding="utf-8")
        localappdata_codex = localappdata / "npm" / "codex.cmd"
        localappdata_codex.write_text("@echo off\n", encoding="utf-8")

        monkeypatch.setenv("APPDATA", str(appdata))
        monkeypatch.setenv("LOCALAPPDATA", str(localappdata))
        monkeypatch.delenv("CODEX_BIN", raising=False)
        monkeypatch.setattr(
            "src.connectors.codex_helpers.shutil.which", lambda name: None
        )
        monkeypatch.setattr("src.connectors.codex_helpers.os.name", "nt")

        candidates = candidate_codex_executables(None)

        # Compare via os.path.realpath (bound to the real OS's path module at
        # import time) so the assertion does not re-dispatch Path() under the
        # mocked os.name and raise NotImplementedError on a mismatched OS.
        resolved_candidates = {os.path.realpath(c) for c in candidates}
        assert os.path.realpath(str(appdata_codex)) in resolved_candidates
        assert os.path.realpath(str(localappdata_codex)) in resolved_candidates

    def test_windows_adds_codex_cmd_and_exe_via_which(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("CODEX_BIN", raising=False)
        monkeypatch.delenv("APPDATA", raising=False)
        monkeypatch.delenv("LOCALAPPDATA", raising=False)
        which_results = {
            "codex": str(tmp_path / "codex"),
            "codex.cmd": str(tmp_path / "codex.cmd"),
            "codex.exe": str(tmp_path / "codex.exe"),
        }

        def fake_which(name: str) -> str | None:
            return which_results.get(name)

        monkeypatch.setattr("src.connectors.codex_helpers.shutil.which", fake_which)
        monkeypatch.setattr("src.connectors.codex_helpers.os.name", "nt")

        candidates = candidate_codex_executables(None)

        assert which_results["codex"] in candidates
        assert which_results["codex.cmd"] in candidates
        assert which_results["codex.exe"] in candidates

    def test_posix_adds_home_local_and_npm_global_candidates(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        home = tmp_path / "home"
        (home / ".local" / "bin").mkdir(parents=True)
        (home / ".npm-global" / "bin").mkdir(parents=True)
        local_codex = home / ".local" / "bin" / "codex"
        local_codex.write_text("#!/bin/sh\n", encoding="utf-8")
        npm_codex = home / ".npm-global" / "bin" / "codex"
        npm_codex.write_text("#!/bin/sh\n", encoding="utf-8")

        monkeypatch.delenv("CODEX_BIN", raising=False)
        monkeypatch.setattr(
            "src.connectors.codex_helpers.shutil.which", lambda name: None
        )
        monkeypatch.setattr("src.connectors.codex_helpers.os.name", "posix")
        monkeypatch.setattr(Path, "home", classmethod(lambda cls: home))

        candidates = candidate_codex_executables(None)

        # Compare via os.path.realpath so the assertion does not re-dispatch
        # Path() under the mocked os.name (PosixPath on Windows would raise).
        resolved_candidates = {os.path.realpath(c) for c in candidates}
        assert os.path.realpath(str(local_codex)) in resolved_candidates
        assert os.path.realpath(str(npm_codex)) in resolved_candidates


# ---------------------------------------------------------------------------
# Model prefix / auto / effort helpers
# ---------------------------------------------------------------------------


class TestStripOpenaiModelPrefix:
    def test_strips_openai_prefix(self) -> None:
        assert strip_openai_model_prefix("openai/gpt-5.4") == "gpt-5.4"

    def test_passes_through_unprefixed(self) -> None:
        assert strip_openai_model_prefix("gpt-5.4") == "gpt-5.4"

    def test_empty_returns_empty(self) -> None:
        assert strip_openai_model_prefix("") == ""


class TestIsAutoModel:
    def test_auto_is_auto(self) -> None:
        assert is_auto_model("auto") is True

    def test_empty_is_auto(self) -> None:
        assert is_auto_model("") is True

    def test_case_insensitive_auto(self) -> None:
        assert is_auto_model("AUTO") is True

    def test_real_model_is_not_auto(self) -> None:
        assert is_auto_model("gpt-5.4") is False


class TestMapReasoningEffort:
    def test_low_medium_high_pass_through(self) -> None:
        assert map_reasoning_effort_to_codex_effort("low") == "low"
        assert map_reasoning_effort_to_codex_effort("medium") == "medium"
        assert map_reasoning_effort_to_codex_effort("high") == "high"

    def test_none_returns_none(self) -> None:
        assert map_reasoning_effort_to_codex_effort(None) is None

    def test_unknown_values_pass_through_to_codex(self) -> None:
        # The connector does not maintain an allowlist; any non-empty value is
        # forwarded so codex can validate (e.g. "xhigh" used by some models).
        assert map_reasoning_effort_to_codex_effort("xhigh") == "xhigh"
        assert map_reasoning_effort_to_codex_effort("ultra") == "ultra"

    def test_empty_returns_none(self) -> None:
        assert map_reasoning_effort_to_codex_effort("") is None

    def test_case_insensitive(self) -> None:
        assert map_reasoning_effort_to_codex_effort("HIGH") == "high"
        assert map_reasoning_effort_to_codex_effort("XHigh") == "xhigh"


class TestAppServerResolveVerbosity:
    def test_resolve_from_request_field(
        self, connector: OpenAICodexAppServerConnector
    ) -> None:
        request = _make_request(
            processed_messages=[ChatMessage(role="user", content="hi")],
            verbosity="low",
        )
        assert connector._resolve_verbosity(request) == "low"

    def test_resolve_from_extra_body(
        self, connector: OpenAICodexAppServerConnector
    ) -> None:
        request = _make_request(
            processed_messages=[ChatMessage(role="user", content="hi")],
        )
        object.__setattr__(
            request.request,
            "extra_body",
            {"verbosity": "high"},
        )
        assert connector._resolve_verbosity(request) == "high"

    def test_resolve_none_when_unset(
        self, connector: OpenAICodexAppServerConnector
    ) -> None:
        request = _make_request(
            processed_messages=[ChatMessage(role="user", content="hi")],
        )
        assert connector._resolve_verbosity(request) is None

    def test_resolve_invalid_returns_none(
        self, connector: OpenAICodexAppServerConnector
    ) -> None:
        request = _make_request(
            processed_messages=[ChatMessage(role="user", content="hi")],
            verbosity="extreme",
        )
        assert connector._resolve_verbosity(request) is None

    def test_resolve_invalid_body_falls_back_to_extra_body(
        self, connector: OpenAICodexAppServerConnector
    ) -> None:
        request = _make_request(
            processed_messages=[ChatMessage(role="user", content="hi")],
            verbosity="extreme",
        )
        object.__setattr__(
            request.request,
            "extra_body",
            {"verbosity": "high"},
        )
        assert connector._resolve_verbosity(request) == "high"


class TestAppServerVerbositySpawnOverrides:
    async def test_build_command_includes_model_verbosity(
        self,
        connector: OpenAICodexAppServerConnector,
        temp_workspace: Path,
    ) -> None:
        runtime = _make_runtime(temp_workspace)
        runtime.applied_model_verbosity = "low"
        connector._codex_executable = "codex"
        connector._codex_config_overrides = []
        cmd = await connector._build_subprocess_command(runtime)
        idx = cmd.index("-c")
        assert cmd[idx + 1] == "model_verbosity=low"

    async def test_prepare_turn_kills_when_verbosity_changes(
        self,
        connector: OpenAICodexAppServerConnector,
        temp_workspace: Path,
    ) -> None:
        runtime = _make_runtime(
            temp_workspace,
            model="auto",
            stdout_lines=[
                b'{"jsonrpc":"2.0","id":1,"result":{"turn":{"id":"turn_1"}}}\n',
            ],
            thread_id="thr_1",
        )
        runtime.initialized = True
        runtime.history_state = None
        runtime.applied_model_verbosity = "high"
        # Live process present
        assert runtime.process is not None
        assert runtime.process.poll() is None

        kill_mock = AsyncMock()
        connector._process_timeout = 5.0
        with (
            patch.object(connector, "_cancel_stale_kill_timer", AsyncMock()),
            patch.object(connector, "_kill_runtime", kill_mock),
            patch.object(connector, "_spawn_process", AsyncMock()),
            patch.object(connector, "_perform_handshake", AsyncMock()),
        ):
            await connector._prepare_turn_request_locked(
                runtime,
                _make_request(
                    processed_messages=[ChatMessage(role="user", content="hi")],
                    verbosity="low",
                ),
            )

        kill_mock.assert_awaited_once()
        assert runtime.applied_model_verbosity == "low"


class TestReasoningEffortForwardedToTurnStart:
    """reasoning_effort (e.g. from ``?reasoning_effort=...`` URI params) must be
    forwarded to ``turn/start.effort``, including non-standard values like xhigh.
    """

    @staticmethod
    def _turn_start_params(runtime: CodexAppServerRuntime) -> dict[str, Any]:
        turn_starts = [
            w for w in _decode_writes(runtime) if w.get("method") == "turn/start"
        ]
        assert turn_starts, f"no turn/start write; writes={_decode_writes(runtime)!r}"
        return dict(turn_starts[-1]["params"])

    async def _run(
        self,
        connector: OpenAICodexAppServerConnector,
        temp_workspace: Path,
        reasoning_effort: str | None,
        model: str = "auto",
    ) -> dict[str, Any]:
        runtime = _make_runtime(
            temp_workspace,
            model=model,
            stdout_lines=[
                b'{"jsonrpc":"2.0","id":1,"result":{"turn":{"id":"turn_1"}}}\n',
            ],
            thread_id="thr_1",
        )
        runtime.initialized = True
        runtime.history_state = None
        connector._process_timeout = 5.0
        with (
            patch.object(connector, "_cancel_stale_kill_timer", AsyncMock()),
            patch.object(connector, "_spawn_process", AsyncMock()),
            patch.object(connector, "_perform_handshake", AsyncMock()),
        ):
            await connector._prepare_turn_request_locked(
                runtime,
                _make_request(
                    processed_messages=[ChatMessage(role="user", content="hi")],
                    model=f"openai/{model}",
                    reasoning_effort=reasoning_effort,
                ),
            )
        return self._turn_start_params(runtime)

    async def test_xhigh_forwarded_to_turn_start_effort(
        self,
        connector: OpenAICodexAppServerConnector,
        temp_workspace: Path,
    ) -> None:
        params = await self._run(connector, temp_workspace, reasoning_effort="xhigh")
        assert params.get("effort") == "xhigh"

    async def test_high_forwarded_to_turn_start_effort(
        self,
        connector: OpenAICodexAppServerConnector,
        temp_workspace: Path,
    ) -> None:
        params = await self._run(connector, temp_workspace, reasoning_effort="high")
        assert params.get("effort") == "high"

    async def test_no_reasoning_effort_omits_effort(
        self,
        connector: OpenAICodexAppServerConnector,
        temp_workspace: Path,
    ) -> None:
        params = await self._run(connector, temp_workspace, reasoning_effort=None)
        assert "effort" not in params

    async def test_ultra_kept_for_ultra_capable_model(
        self,
        connector: OpenAICodexAppServerConnector,
        temp_workspace: Path,
    ) -> None:
        params = await self._run(
            connector, temp_workspace, reasoning_effort="ultra", model="gpt-5.6-sol"
        )
        assert params.get("effort") == "ultra"

    async def test_ultra_clamped_to_xhigh_for_xhigh_only_model(
        self,
        connector: OpenAICodexAppServerConnector,
        temp_workspace: Path,
    ) -> None:
        params = await self._run(
            connector, temp_workspace, reasoning_effort="ultra", model="gpt-5.5"
        )
        assert params.get("effort") == "xhigh"

    async def test_invalid_effort_falls_back_to_default_for_non_auto(
        self,
        connector: OpenAICodexAppServerConnector,
        temp_workspace: Path,
    ) -> None:
        params = await self._run(
            connector, temp_workspace, reasoning_effort="bogus", model="gpt-5.5"
        )
        assert params.get("effort") == "medium"


# ---------------------------------------------------------------------------
# Handshake order
# ---------------------------------------------------------------------------


class TestHandshakeOrder:
    async def test_handshake_auto_model_omits_model_param(
        self, connector: OpenAICodexAppServerConnector, temp_workspace: Path
    ) -> None:
        runtime = _make_runtime(
            temp_workspace,
            model="auto",
            stdout_lines=[
                b'{"jsonrpc":"2.0","id":1,"result":{}}\n',
                b'{"jsonrpc":"2.0","id":2,"result":{"id":"thr_1"}}\n',
            ],
        )
        await connector._perform_handshake(runtime)

        writes = _decode_writes(runtime)
        assert writes[0]["method"] == "initialize"
        assert "id" in writes[0]
        assert writes[0]["params"]["clientInfo"]["name"] == "llm-interactive-proxy"
        assert writes[1]["method"] == "initialized"
        assert "id" not in writes[1]
        assert writes[2]["method"] == "thread/start"
        assert "id" in writes[2]
        assert "cwd" in writes[2]["params"]
        assert "runtimeWorkspaceRoots" in writes[2]["params"]
        assert "model" not in writes[2]["params"]
        assert runtime.thread_id == "thr_1"
        assert runtime.initialized is True

    async def test_handshake_explicit_model_includes_model_param(
        self, connector: OpenAICodexAppServerConnector, temp_workspace: Path
    ) -> None:
        runtime = _make_runtime(
            temp_workspace,
            model="gpt-5.4",
            stdout_lines=[
                b'{"jsonrpc":"2.0","id":1,"result":{}}\n',
                b'{"jsonrpc":"2.0","id":2,"result":{"thread":{"id":"thr_2"}}}\n',
            ],
        )
        await connector._perform_handshake(runtime)

        writes = _decode_writes(runtime)
        assert writes[2]["method"] == "thread/start"
        assert writes[2]["params"]["model"] == "gpt-5.4"
        # Defensive read: threadId may be nested under result.thread.id.
        assert runtime.thread_id == "thr_2"

    async def test_handshake_error_response_raises(
        self, connector: OpenAICodexAppServerConnector, temp_workspace: Path
    ) -> None:
        runtime = _make_runtime(
            temp_workspace,
            model="auto",
            stdout_lines=[
                b'{"jsonrpc":"2.0","id":1,"error":{"code":-32000,"message":"nope"}}\n',
            ],
        )
        with pytest.raises(BackendError):
            await connector._perform_handshake(runtime)


# ---------------------------------------------------------------------------
# Workspace validation
# ---------------------------------------------------------------------------


class TestWorkspaceValidation:
    def test_raises_without_workspace_hint(
        self, connector: OpenAICodexAppServerConnector
    ) -> None:
        with pytest.raises(BackendError) as exc_info:
            connector._resolve_project_dir_for_request(_make_request())
        assert exc_info.value.details.get("code") == ACP_MISSING_PROJECT_WORKSPACE_CODE

    def test_accepts_usable_project_dir_from_options(
        self,
        connector: OpenAICodexAppServerConnector,
        temp_workspace: Path,
    ) -> None:
        req = _make_request(options={"project_dir": str(temp_workspace)})
        resolved = connector._resolve_project_dir_for_request(req)
        assert resolved == temp_workspace.resolve()

    def test_rejects_unusable_hint(
        self,
        connector: OpenAICodexAppServerConnector,
        tmp_path: Path,
    ) -> None:
        missing = tmp_path / "missing"
        req = _make_request(extra_body={"project_dir": str(missing)})
        with pytest.raises(BackendError) as exc_info:
            connector._resolve_project_dir_for_request(req)
        assert exc_info.value.details.get("code") == ACP_MISSING_PROJECT_WORKSPACE_CODE
        assert exc_info.value.details.get("hint") == str(missing)


# ---------------------------------------------------------------------------
# Event mapper
# ---------------------------------------------------------------------------


class TestCodexEventMapper:
    def test_agent_message_delta_streams_content(self) -> None:
        mapper = CodexEventMapper()
        msg = ACPNotification(
            method="item/agentMessage/delta", params={"id": "m1", "delta": "Hello"}
        )
        assert mapper.handle(msg) == [CodexStreamPiece(content="Hello")]

    def test_reasoning_delta_opens_and_closes_thinking_block(self) -> None:
        mapper = CodexEventMapper()
        open_piece = mapper.handle(
            ACPNotification(
                method="item/reasoning/summaryTextDelta",
                params={"id": "r1", "summaryIndex": 0, "delta": "Thinking step"},
            )
        )
        append_piece = mapper.handle(
            ACPNotification(
                method="item/reasoning/summaryTextDelta",
                params={"id": "r1", "summaryIndex": 0, "delta": " more"},
            )
        )
        done_pieces = mapper.handle(
            ACPNotification(
                method="turn/completed",
                params={"turn": {"status": "completed"}},
            )
        )
        assert open_piece == [CodexStreamPiece(content="Thinking:\nThinking step")]
        assert append_piece == [CodexStreamPiece(content=" more")]
        # Close piece precedes the terminal done piece.
        assert done_pieces[0] == CodexStreamPiece(content="\n\n")
        assert done_pieces[-1] == CodexStreamPiece(done=True, finish_reason="stop")
        reasoning = "".join(
            p.content for p in (open_piece + append_piece + done_pieces) if p.content
        )
        assert reasoning == "Thinking:\nThinking step more\n\n"

    def test_command_started_and_completed_summaries_no_raw_output(self) -> None:
        mapper = CodexEventMapper()
        started = mapper.handle(
            ACPNotification(
                method="item/started",
                params={
                    "type": "commandExecution",
                    "id": "c1",
                    "command": "npm test",
                    "cwd": "/home/me/proj",
                    "status": "inProgress",
                    "aggregatedOutput": "SECRET OUTPUT",
                },
            )
        )
        completed = mapper.handle(
            ACPNotification(
                method="item/completed",
                params={
                    "type": "commandExecution",
                    "id": "c1",
                    "command": "npm test",
                    "cwd": "/home/me/proj",
                    "status": "completed",
                    "exitCode": 0,
                    "durationMs": 1200,
                    "aggregatedOutput": "more secret output",
                },
            )
        )
        # ACP-style: nothing on start; a fenced Tool block on completion (no raw output).
        assert started == []
        joined = "".join(p.content or "" for p in completed)
        assert "Tool: npm" in joined
        assert "```text" in joined
        assert "Input size: 8 bytes" in joined
        assert "Output size: 18 bytes" in joined  # len("more secret output")
        assert "SECRET" not in joined
        assert "secret output" not in joined

    def test_command_summary_prefers_command_actions_over_wrapped_command(self) -> None:
        # Real Codex wraps shell commands in a quoted pwsh path whose
        # first-token basename mis-resolves to "Program"; the user-facing
        # command lives in commandActions[0].command.
        mapper = CodexEventMapper()
        pieces = mapper.handle(
            ACPNotification(
                method="item/completed",
                params={
                    "type": "commandExecution",
                    "id": "c1",
                    "command": "\"C:\\Program Files\\PowerShell\\7\\pwsh.exe\" -Command 'echo hello'",
                    "commandActions": [{"type": "unknown", "command": "echo hello"}],
                    "exitCode": 0,
                    "durationMs": 186,
                    "aggregatedOutput": "hello\r\n",
                },
            )
        )
        assert len(pieces) == 1
        content = pieces[0].content or ""
        assert "Tool: echo" in content
        assert "Program" not in content
        assert "Input size: 10 bytes" in content  # len("echo hello")
        assert "Output size: 7 bytes" in content  # len("hello\r\n")
        # Raw output is not streamed, only its size.
        assert "hello\r\n" not in content

    def test_file_change_completed_emits_fenced_block_no_diff(self) -> None:
        mapper = CodexEventMapper()
        started = mapper.handle(
            ACPNotification(
                method="item/started",
                params={
                    "type": "fileChange",
                    "id": "f1",
                    "changes": [
                        {"path": "a.py", "kind": "edit", "diff": "SECRET DIFF"},
                    ],
                    "status": "inProgress",
                },
            )
        )
        # ACP-style: nothing on start; the fenced Tool block lands on completion.
        assert started == []
        completed = mapper.handle(
            ACPNotification(
                method="item/completed",
                params={
                    "type": "fileChange",
                    "id": "f1",
                    "changes": [
                        {"path": "a.py", "kind": "edit", "diff": "SECRET DIFF"},
                    ],
                    "status": "completed",
                },
            )
        )
        assert len(completed) == 1
        content = completed[0].content or ""
        assert "Tool: fileChange" in content
        assert "```text" in content
        # Paths and diff bodies are not streamed (ACP generic Tool block).
        assert "a.py" not in content
        assert "SECRET DIFF" not in content

    def test_turn_completed_finish_reason_variants(self) -> None:
        for status, expected in (
            ("completed", "stop"),
            ("interrupted", "interrupted"),
            ("failed", "error"),
        ):
            mapper = CodexEventMapper()
            pieces = mapper.handle(
                ACPNotification(
                    method="turn/completed", params={"turn": {"status": status}}
                )
            )
            done = [p for p in pieces if p.done]
            assert len(done) == 1
            assert done[0].finish_reason == expected

    def test_unknown_status_maps_to_error(self) -> None:
        """Bugbot FIX: an unknown/empty turn status must fail closed to
        ``error`` (not ``stop``) so ``_iter_codex_stream_pieces`` does not
        commit ``pending_history_state`` on an unrecognized status. Covers
        empty-string status, an unrecognized non-empty status, a missing
        ``status`` key, and a missing ``turn`` key entirely.
        """
        params_variants: tuple[dict[str, Any], ...] = (
            {"turn": {"status": ""}},
            {"turn": {"status": "canceled"}},
            {"turn": {}},
            {},
        )
        for params in params_variants:
            mapper = CodexEventMapper()
            pieces = mapper.handle(
                ACPNotification(method="turn/completed", params=params)
            )
            done = [p for p in pieces if p.done]
            assert len(done) == 1
            assert done[0].finish_reason == "error"

    def test_turn_plan_updated_summary_with_step_statuses(self) -> None:
        mapper = CodexEventMapper()
        pieces = mapper.handle(
            ACPNotification(
                method="turn/plan/updated",
                params={
                    "turnId": "t1",
                    "plan": [
                        {"step": "do x", "status": "inProgress"},
                        {"step": "do y", "status": "pending"},
                    ],
                },
            )
        )
        assert len(pieces) == 1
        content = pieces[0].content or ""
        assert content.startswith("[plan]")
        assert "do x (inProgress)" in content
        assert "do y (pending)" in content

    def test_command_execution_output_delta_suppressed(self) -> None:
        mapper = CodexEventMapper()
        pieces = mapper.handle(
            ACPNotification(
                method="item/commandExecution/outputDelta",
                params={"id": "c1", "delta": "raw stdout line"},
            )
        )
        assert pieces == []

    def test_unknown_method_returns_empty(self) -> None:
        mapper = CodexEventMapper()
        assert mapper.handle(ACPNotification(method="something/new", params={})) == []

    def test_text_only_mode_supplies_summaries(self) -> None:
        mapper = CodexEventMapper(progress_mode="text_only")
        pieces = mapper.handle(
            ACPNotification(
                method="item/started",
                params={
                    "type": "commandExecution",
                    "id": "c1",
                    "command": "ls",
                    "cwd": "/p",
                    "status": "inProgress",
                },
            )
        )
        assert pieces == []


# ---------------------------------------------------------------------------
# Approval handler
# ---------------------------------------------------------------------------


class TestApprovalHandler:
    @pytest.mark.parametrize(
        "method",
        [
            "execCommandApproval",
            "applyPatchApproval",
            "item/commandExecution/requestApproval",
            "item/fileChange/requestApproval",
        ],
    )
    def test_auto_accept_approvals(self, method: str) -> None:
        result, accepted = decide_codex_server_request(method, {"command": "rm -rf /x"})
        assert accepted is True
        assert result == {"decision": "accept"}

    def test_permissions_request_approval_echoes_permissions(self) -> None:
        params = {"permissions": {"fileSystem": {"write": ["/a", "/b"]}}}
        result, accepted = decide_codex_server_request(
            "item/permissions/requestApproval", params
        )
        assert accepted is True
        assert result == {"permissions": {"fileSystem": {"write": ["/a", "/b"]}}}

    def test_permissions_request_approval_missing_permissions_echoes_empty(
        self,
    ) -> None:
        result, accepted = decide_codex_server_request(
            "item/permissions/requestApproval", {}
        )
        assert accepted is True
        assert result == {"permissions": {}}

    @pytest.mark.parametrize(
        "method",
        ["item/tool/requestUserInput", "mcpServer/elicitation/request"],
    )
    def test_fail_closed_methods_decline(self, method: str) -> None:
        result, accepted = decide_codex_server_request(method, {})
        assert accepted is False
        assert result == {"decision": "decline"}

    def test_unknown_method_declines(self) -> None:
        result, accepted = decide_codex_server_request("some/unknown", {})
        assert accepted is False
        assert result == {"decision": "decline"}

    def test_sanitize_approval_summary_short_and_secret_free(self) -> None:
        summary = sanitize_approval_summary(
            {
                "command": "rm -rf /super/secret/path --token=ABCDEF",
                "cwd": "/home/me/projects/proj",
                "exitCode": 0,
            }
        )
        assert "secret" not in summary
        assert "ABCDEF" not in summary
        assert "rm" in summary
        assert "proj" in summary
        assert "exit=0" in summary
        assert len(summary) <= 120

    def test_sanitize_approval_summary_truncates(self) -> None:
        long_cwd = "/" + "a" * 200
        summary = sanitize_approval_summary({"command": "run", "cwd": long_cwd})
        assert len(summary) <= 120
        assert summary.endswith("...")

    def test_sanitize_approval_summary_paths_count(self) -> None:
        summary = sanitize_approval_summary(
            {"changes": [{"path": "a"}, {"path": "b"}, {"path": "c"}]}
        )
        assert "paths=3" in summary


# ---------------------------------------------------------------------------
# Cancellation primitives
# ---------------------------------------------------------------------------


class TestCancellationSendsTurnInterrupt:
    async def test_send_turn_interrupt_writes_correct_payload(
        self,
        connector: OpenAICodexAppServerConnector,
        temp_workspace: Path,
    ) -> None:
        runtime = _make_runtime(
            temp_workspace,
            model="auto",
            stdout_lines=[],
            thread_id="thr_1",
            turn_id="turn_1",
        )
        await runtime.request_lock.acquire()

        req_id = await connector._send_turn_interrupt(runtime)

        assert req_id >= 1
        writes = _decode_writes(runtime)
        interrupt = writes[-1]
        assert interrupt["method"] == "turn/interrupt"
        assert interrupt["params"] == {"threadId": "thr_1", "turnId": "turn_1"}
        assert "id" in interrupt

    async def test_send_turn_interrupt_without_active_turn_raises(
        self,
        connector: OpenAICodexAppServerConnector,
        temp_workspace: Path,
    ) -> None:
        runtime = _make_runtime(temp_workspace, model="auto", stdout_lines=[])
        with pytest.raises(BackendError):
            await connector._send_turn_interrupt(runtime)

    async def test_release_runtime_request_lock_releases(
        self,
        connector: OpenAICodexAppServerConnector,
        temp_workspace: Path,
    ) -> None:
        runtime = _make_runtime(temp_workspace, model="auto", stdout_lines=[])
        await runtime.request_lock.acquire()
        assert runtime.request_lock.locked()
        await connector._release_runtime_request_lock(runtime)
        assert not runtime.request_lock.locked()

    def test_build_turn_interrupt_payload_shape(self) -> None:
        assert build_turn_interrupt_payload("thr_9", "turn_9") == {
            "threadId": "thr_9",
            "turnId": "turn_9",
        }


# ---------------------------------------------------------------------------
# Server request handling (transport + decision)
# ---------------------------------------------------------------------------


class TestHandleServerRequest:
    async def test_accepted_approval_writes_result(
        self,
        connector: OpenAICodexAppServerConnector,
        temp_workspace: Path,
    ) -> None:
        runtime = _make_runtime(temp_workspace, model="auto", stdout_lines=[])
        msg = ACPNotification(
            method="item/commandExecution/requestApproval",
            id=77,
            params={"command": "ls", "cwd": "/p"},
        )
        await connector._handle_server_request(runtime, msg)
        writes = _decode_writes(runtime)
        result = writes[-1]
        assert result["id"] == 77
        assert result["result"] == {"decision": "accept"}

    async def test_declined_approval_writes_decline(
        self,
        connector: OpenAICodexAppServerConnector,
        temp_workspace: Path,
    ) -> None:
        runtime = _make_runtime(temp_workspace, model="auto", stdout_lines=[])
        msg = ACPNotification(method="item/tool/requestUserInput", id=88, params={})
        await connector._handle_server_request(runtime, msg)
        writes = _decode_writes(runtime)
        result = writes[-1]
        assert result["id"] == 88
        assert result["result"] == {"decision": "decline"}

    async def test_permissions_approval_echoes(
        self,
        connector: OpenAICodexAppServerConnector,
        temp_workspace: Path,
    ) -> None:
        runtime = _make_runtime(temp_workspace, model="auto", stdout_lines=[])
        msg = ACPNotification(
            method="item/permissions/requestApproval",
            id=99,
            params={"permissions": {"fileSystem": {"write": ["/x"]}}},
        )
        await connector._handle_server_request(runtime, msg)
        writes = _decode_writes(runtime)
        result = writes[-1]
        assert result["id"] == 99
        assert result["result"]["permissions"] == {"fileSystem": {"write": ["/x"]}}


# ---------------------------------------------------------------------------
# Non-streaming accumulation helper
# ---------------------------------------------------------------------------


class TestNonStreamingAccumulation:
    def test_accumulate_pieces_joins_content_and_reasoning(self) -> None:
        pieces = [
            CodexStreamPiece(content="Hello "),
            CodexStreamPiece(content="world"),
            CodexStreamPiece(reasoning_content="Thinking..."),
            CodexStreamPiece(done=True, finish_reason="stop"),
        ]
        content, reasoning = accumulate_pieces(pieces)
        assert content == "Hello world"
        assert reasoning == "Thinking..."

    def test_accumulate_pieces_no_reasoning_returns_none(self) -> None:
        pieces = [CodexStreamPiece(content="only")]
        content, reasoning = accumulate_pieces(pieces)
        assert content == "only"
        assert reasoning is None

    def test_accumulate_pieces_empty(self) -> None:
        content, reasoning = accumulate_pieces([])
        assert content == ""
        assert reasoning is None


# ---------------------------------------------------------------------------
# Connector basics
# ---------------------------------------------------------------------------


class TestConnectorBasics:
    def test_backend_type_and_vendor_prefix(self) -> None:
        assert OpenAICodexAppServerConnector.backend_type == "openai-codex-app-server"
        assert OpenAICodexAppServerConnector.VENDOR_PREFIX == "openai"
        assert OpenAICodexAppServerConnector.requires_explicit_workspace is True

    def test_has_static_credentials_false(
        self, connector: OpenAICodexAppServerConnector
    ) -> None:
        assert connector.has_static_credentials is False

    def test_get_available_models_openai_prefixed(
        self, connector: OpenAICodexAppServerConnector
    ) -> None:
        models = connector.get_available_models()
        # ``auto`` sentinel first, then the discovered catalog's routable slugs.
        assert models == [
            "openai/auto",
            "openai/gpt-5.6-sol",
            "openai/gpt-5.6-luna",
            "openai/gpt-5.5",
        ]
        assert all(m.startswith("openai/") for m in models)

    async def test_build_codex_command_uses_overrides_and_extra(
        self,
        connector: OpenAICodexAppServerConnector,
        temp_workspace: Path,
    ) -> None:
        connector._codex_executable = "/usr/local/bin/codex"
        connector._codex_config_overrides = ["k=v"]
        connector._app_server_extra_args = ["--verbose"]
        runtime = _make_runtime(temp_workspace, model="auto")
        cmd = await connector._build_subprocess_command(runtime)
        assert cmd[0] == "/usr/local/bin/codex"
        assert "--dangerously-bypass-approvals-and-sandbox" in cmd
        assert "app-server" in cmd
        assert "-c" in cmd and "k=v" in cmd
        assert "--stdio" in cmd
        assert "--verbose" in cmd

    def test_resolve_client_session_id_defaults(
        self, connector: OpenAICodexAppServerConnector
    ) -> None:
        assert connector._resolve_client_session_id(_make_request()) == "default"

    def test_resolve_client_session_id_from_context(
        self, connector: OpenAICodexAppServerConnector
    ) -> None:
        req = _make_request(session_id="  sess-42  ")
        assert connector._resolve_client_session_id(req) == "sess-42"

    def test_runtime_locks_initialized(
        self, connector: OpenAICodexAppServerConnector, temp_workspace: Path
    ) -> None:
        runtime = connector._create_runtime(temp_workspace, "auto")
        assert runtime.process_lock is not None
        assert runtime.request_lock is not None
        assert runtime.cancellation_lock is not None
        assert runtime.cancellation_event is not None


# ---------------------------------------------------------------------------
# initialize probe
# ---------------------------------------------------------------------------


class TestInitialize:
    async def test_initialize_missing_executable_raises_configuration_error(
        self,
        connector: OpenAICodexAppServerConnector,
        temp_workspace: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.delenv("CODEX_BIN", raising=False)
        monkeypatch.delenv("APPDATA", raising=False)
        monkeypatch.delenv("LOCALAPPDATA", raising=False)
        monkeypatch.setattr("src.connectors.codex_helpers.shutil.which", lambda _: None)
        # Point Path.home() at the temp workspace so the POSIX candidates
        # (~/.local/bin/codex, ~/.npm-global/bin/codex) cannot resolve to a real
        # user home that happens to contain a codex binary on a dev machine.
        monkeypatch.setattr(Path, "home", classmethod(lambda cls: temp_workspace))

        from src.core.common.exceptions import ConfigurationError

        with pytest.raises(ConfigurationError):
            await connector.initialize(
                project_dir=str(temp_workspace),
                codex_executable=str(temp_workspace / "nope"),
            )
        assert connector.is_backend_functional() is False
        assert connector._initialization_failed is True
        assert connector._validation_errors == [
            "openai-codex-app-server initialization failed"
        ]

    async def test_initialize_success_sets_functional(
        self,
        connector: OpenAICodexAppServerConnector,
        temp_workspace: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        fake_exe = temp_workspace / "codex"
        fake_exe.write_text("#!/bin/sh\n", encoding="utf-8")
        monkeypatch.setattr(
            connector, "_check_codex_available", AsyncMock(return_value=True)
        )
        monkeypatch.setattr(
            connector, "_probe_app_server", AsyncMock(return_value=True)
        )
        await connector.initialize(
            project_dir=str(temp_workspace),
            codex_executable=str(fake_exe),
            model="openai/gpt-5.4",
            progress_mode="text_plus_summaries",
            codex_config_overrides=["k=v"],
            codex_app_server_extra_args=["--verbose"],
        )
        assert connector.is_backend_functional() is True
        assert connector._default_project_dir == temp_workspace.resolve()
        assert connector._model == "gpt-5.4"
        assert connector._codex_config_overrides == ["k=v"]
        assert connector._app_server_extra_args == ["--verbose"]


# ---------------------------------------------------------------------------
# App-server launch probe (_probe_app_server)
# ---------------------------------------------------------------------------


class _TimeoutFakeStdout(FakeStdout):
    """FakeStdout whose readline raises asyncio.TimeoutError.

    Simulates a Codex app-server subprocess that stays alive but never emits a
    JSON-RPC line within the probe's read timeout.
    """

    def readline(self, size: int = -1) -> bytes:
        _ = size
        raise asyncio.TimeoutError()


def _install_probe_popen(monkeypatch: pytest.MonkeyPatch, proc: FakeProcess) -> None:
    """Monkeypatch ``subprocess.Popen`` to return ``proc`` and neutralize the
    Windows ``taskkill`` call inside ``_terminate_process`` so probe unit tests
    never spawn a real subprocess or shell out to taskkill."""

    def _fake_popen(*_args: Any, **_kwargs: Any) -> FakeProcess:
        return proc

    monkeypatch.setattr(
        "src.connectors.openai_codex_app_server.subprocess.Popen", _fake_popen
    )
    monkeypatch.setattr(
        "src.connectors.acp_core.base_connector.subprocess.run",
        lambda *_a, **_k: None,
    )


class TestProbeAppServer:
    async def test_probe_succeeds_for_json_rpc_response(
        self,
        connector: OpenAICodexAppServerConnector,
        temp_workspace: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        connector._codex_executable = "codex"
        fake_proc = FakeProcess(
            stdout_lines=[
                b'{"jsonrpc":"2.0","id":1,"result":'
                b'{"capabilities":{"experimentalApi":true}}}\n'
            ]
        )
        fake_proc._poll = None
        _install_probe_popen(monkeypatch, fake_proc)

        result = await connector._probe_app_server("codex")

        assert result is True
        # The finally must have terminated the probe process (no orphan).
        assert fake_proc.terminated is True

    async def test_probe_fails_when_process_exits_immediately(
        self,
        connector: OpenAICodexAppServerConnector,
        temp_workspace: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        connector._codex_executable = "codex"
        # Wrapper collision / CLI parse error: stdout is empty and the process
        # already exited (poll() non-None).
        fake_proc = FakeProcess(stdout_lines=[])
        fake_proc._poll = 1
        _install_probe_popen(monkeypatch, fake_proc)

        result = await connector._probe_app_server("codex")

        assert result is False

    async def test_probe_fails_on_non_json_output(
        self,
        connector: OpenAICodexAppServerConnector,
        temp_workspace: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        connector._codex_executable = "codex"
        # The wrapper prints a CLI parse error (non-JSON) on stdout and stays
        # alive long enough for readline to return it.
        fake_proc = FakeProcess(
            stdout_lines=[b"error: cannot be used multiple times\n"]
        )
        fake_proc._poll = None
        _install_probe_popen(monkeypatch, fake_proc)

        result = await connector._probe_app_server("codex")

        assert result is False

    async def test_probe_fails_on_timeout(
        self,
        connector: OpenAICodexAppServerConnector,
        temp_workspace: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        connector._codex_executable = "codex"
        fake_proc = FakeProcess(stdout_lines=[])
        # Replace stdout with one whose readline raises asyncio.TimeoutError,
        # simulating an app-server that never responds within the read timeout.
        fake_proc.stdout = _TimeoutFakeStdout(lines=[])
        fake_proc._poll = None
        _install_probe_popen(monkeypatch, fake_proc)

        result = await connector._probe_app_server("codex")

        assert result is False
        # The finally must still terminate the probe process (no orphan).
        assert fake_proc.terminated is True

    async def test_initialize_raises_when_probe_fails(
        self,
        connector: OpenAICodexAppServerConnector,
        temp_workspace: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        fake_exe = temp_workspace / "codex"
        fake_exe.write_text("#!/bin/sh\n", encoding="utf-8")
        monkeypatch.setattr(
            connector, "_check_codex_available", AsyncMock(return_value=True)
        )
        monkeypatch.setattr(
            connector, "_probe_app_server", AsyncMock(return_value=False)
        )

        with pytest.raises(ConfigurationError, match="app-server probe failed"):
            await connector.initialize(
                project_dir=str(temp_workspace),
                codex_executable=str(fake_exe),
            )
        assert connector.is_backend_functional() is False
        assert connector._initialization_failed is True

    async def test_initialize_succeeds_when_version_and_probe_pass(
        self,
        connector: OpenAICodexAppServerConnector,
        temp_workspace: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        fake_exe = temp_workspace / "codex"
        fake_exe.write_text("#!/bin/sh\n", encoding="utf-8")
        monkeypatch.setattr(
            connector, "_check_codex_available", AsyncMock(return_value=True)
        )
        monkeypatch.setattr(
            connector, "_probe_app_server", AsyncMock(return_value=True)
        )

        await connector.initialize(
            project_dir=str(temp_workspace),
            codex_executable=str(fake_exe),
            model="openai/gpt-5.4",
        )
        assert connector.is_backend_functional() is True


# ---------------------------------------------------------------------------
# initialize probe-and-pick across multiple candidates
# ---------------------------------------------------------------------------


class TestInitializeProbeAndPick:
    """initialize() probes each candidate and picks the first working one."""

    @staticmethod
    def _two_candidates(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> tuple[str, str]:
        """Build two distinct candidate executables and return (first, second).

        The first is the configured executable; the second is surfaced via
        ``shutil.which("codex")``. All other sources (CODEX_BIN, APPDATA,
        LOCALAPPDATA, Path.home) are neutralized so the candidate list is
        deterministic and exactly two entries. Both returned paths are
        resolved absolute paths so assertions can compare them directly
        against the connector's chosen executable.
        """

        first = tmp_path / "codex-wrapper"
        first.write_text("#!/bin/sh\n", encoding="utf-8")
        second = tmp_path / "codex-raw"
        second.write_text("#!/bin/sh\n", encoding="utf-8")
        first_resolved = str(first.resolve())
        second_resolved = str(second.resolve())
        monkeypatch.delenv("CODEX_BIN", raising=False)
        monkeypatch.delenv("APPDATA", raising=False)
        monkeypatch.delenv("LOCALAPPDATA", raising=False)
        # which() returns the resolved second path so the stored candidate
        # matches the resolved value the connector keeps.
        monkeypatch.setattr(
            "src.connectors.codex_helpers.shutil.which",
            lambda name: second_resolved if name == "codex" else None,
        )
        monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
        return (first_resolved, second_resolved)

    async def test_initialize_picks_second_candidate_when_first_probe_fails(
        self,
        connector: OpenAICodexAppServerConnector,
        temp_workspace: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        first, second = self._two_candidates(temp_workspace, monkeypatch)
        first_resolved = str(Path(first).resolve())
        second_resolved = str(Path(second).resolve())

        # --version passes for both; the app-server probe fails only for the
        # first (wrapper collision) and passes for the second.
        monkeypatch.setattr(
            connector,
            "_check_codex_available",
            AsyncMock(return_value=True),
        )

        async def _probe(executable: str) -> bool:
            return executable != first_resolved

        monkeypatch.setattr(
            connector, "_probe_app_server", AsyncMock(side_effect=_probe)
        )

        await connector.initialize(
            project_dir=str(temp_workspace),
            codex_executable=first,
        )
        assert connector.is_backend_functional() is True
        assert connector._codex_executable == second_resolved

    async def test_initialize_skips_candidate_that_fails_version_check(
        self,
        connector: OpenAICodexAppServerConnector,
        temp_workspace: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        first, second = self._two_candidates(temp_workspace, monkeypatch)
        first_resolved = str(Path(first).resolve())
        second_resolved = str(Path(second).resolve())

        # The first candidate fails --version (so the probe is never run for
        # it); the second passes both checks.
        async def _check(executable: str | None = None) -> bool:
            return executable != first_resolved

        monkeypatch.setattr(
            connector, "_check_codex_available", AsyncMock(side_effect=_check)
        )
        monkeypatch.setattr(
            connector, "_probe_app_server", AsyncMock(return_value=True)
        )

        await connector.initialize(
            project_dir=str(temp_workspace),
            codex_executable=first,
        )
        assert connector.is_backend_functional() is True
        assert connector._codex_executable == second_resolved

    async def test_initialize_raises_when_all_candidates_fail(
        self,
        connector: OpenAICodexAppServerConnector,
        temp_workspace: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        first, second = self._two_candidates(temp_workspace, monkeypatch)
        first_resolved = str(Path(first).resolve())
        second_resolved = str(Path(second).resolve())

        monkeypatch.setattr(
            connector,
            "_check_codex_available",
            AsyncMock(return_value=True),
        )
        monkeypatch.setattr(
            connector, "_probe_app_server", AsyncMock(return_value=False)
        )

        with pytest.raises(
            ConfigurationError, match="app-server probe failed"
        ) as exc_info:
            await connector.initialize(
                project_dir=str(temp_workspace),
                codex_executable=first,
            )
        assert connector.is_backend_functional() is False
        assert connector._initialization_failed is True
        # The error details must list every candidate that was tried.
        tried = exc_info.value.details.get("tried_candidates")
        assert tried == [first_resolved, second_resolved]

    async def test_initialize_raises_not_callable_when_no_candidate_runs_version(
        self,
        connector: OpenAICodexAppServerConnector,
        temp_workspace: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        # Every candidate fails the --version check (CLI missing/broken), so
        # the app-server probe must NEVER run and the error must be "not
        # callable", not the misleading "app-server probe failed".
        first, second = self._two_candidates(temp_workspace, monkeypatch)
        first_resolved = str(Path(first).resolve())
        second_resolved = str(Path(second).resolve())
        monkeypatch.setattr(
            connector,
            "_check_codex_available",
            AsyncMock(return_value=False),
        )
        probe_mock = AsyncMock(return_value=True)
        monkeypatch.setattr(connector, "_probe_app_server", probe_mock)

        with pytest.raises(ConfigurationError, match="not callable") as exc_info:
            await connector.initialize(
                project_dir=str(temp_workspace),
                codex_executable=first,
            )
        assert connector.is_backend_functional() is False
        assert connector._initialization_failed is True
        tried = exc_info.value.details.get("tried_candidates")
        assert tried == [first_resolved, second_resolved]
        # The app-server probe was never run for any candidate.
        probe_mock.assert_not_called()
        # Distinct from the wrapper-collision error.
        assert "app-server probe failed" not in str(exc_info.value)

    async def test_initialize_picks_first_candidate_when_it_passes(
        self,
        connector: OpenAICodexAppServerConnector,
        temp_workspace: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        # Common case: the first candidate (configured) passes both checks and
        # is selected; no later candidate is probed.
        first, _second = self._two_candidates(temp_workspace, monkeypatch)
        first_resolved = str(Path(first).resolve())

        check_calls: list[str | None] = []
        probe_calls: list[str] = []

        async def _check(executable: str | None = None) -> bool:
            check_calls.append(executable)
            return True

        async def _probe(executable: str) -> bool:
            probe_calls.append(executable)
            return True

        monkeypatch.setattr(
            connector, "_check_codex_available", AsyncMock(side_effect=_check)
        )
        monkeypatch.setattr(
            connector, "_probe_app_server", AsyncMock(side_effect=_probe)
        )

        await connector.initialize(
            project_dir=str(temp_workspace),
            codex_executable=first,
        )
        assert connector.is_backend_functional() is True
        assert connector._codex_executable == first_resolved
        # Only the first candidate is probed.
        assert probe_calls == [first_resolved]
        assert check_calls == [first_resolved]


# ---------------------------------------------------------------------------
# Async subprocess lifecycle: _iter_codex_stream_pieces
# ---------------------------------------------------------------------------


class TestIterCodexStreamPieces:
    async def test_content_deltas_then_turn_completed(
        self,
        connector: OpenAICodexAppServerConnector,
        temp_workspace: Path,
    ) -> None:
        connector._progress_mode = "text_only"
        runtime = _make_runtime(
            temp_workspace,
            model="auto",
            stdout_lines=[
                b'{"jsonrpc":"2.0","id":1,"result":{"turn":{"id":"turn_1"}}}\n',
                b'{"jsonrpc":"2.0","method":"item/agentMessage/delta",'
                b'"params":{"delta":"Hello"}}\n',
                b'{"jsonrpc":"2.0","method":"item/agentMessage/delta",'
                b'"params":{"delta":" world"}}\n',
                b'{"jsonrpc":"2.0","method":"turn/completed",'
                b'"params":{"turn":{"status":"completed"}}}\n',
            ],
            thread_id="thr_1",
        )
        connector._process_timeout = 5.0

        pieces: list[CodexStreamPiece] = []
        async for piece in connector._iter_codex_stream_pieces(runtime, 1, "auto"):
            pieces.append(piece)

        content_pieces = [p for p in pieces if p.content]
        done_pieces = [p for p in pieces if p.done]
        assert len(content_pieces) == 2
        assert content_pieces[0].content == "Hello"
        assert content_pieces[1].content == " world"
        assert len(done_pieces) == 1
        assert done_pieces[0].finish_reason == "stop"
        assert runtime.turn_id == "turn_1"

    async def test_reasoning_deltas_open_and_close_thinking_block(
        self,
        connector: OpenAICodexAppServerConnector,
        temp_workspace: Path,
    ) -> None:
        connector._progress_mode = "text_only"
        runtime = _make_runtime(
            temp_workspace,
            model="auto",
            stdout_lines=[
                b'{"jsonrpc":"2.0","id":7,"result":{"turn":{"id":"turn_r"}}}\n',
                b'{"jsonrpc":"2.0","method":"item/reasoning/summaryTextDelta",'
                b'"params":{"delta":"Thinking step"}}\n',
                b'{"jsonrpc":"2.0","method":"item/reasoning/summaryTextDelta",'
                b'"params":{"delta":" more"}}\n',
                b'{"jsonrpc":"2.0","method":"turn/completed",'
                b'"params":{"turn":{"status":"completed"}}}\n',
            ],
            thread_id="thr_1",
        )
        connector._process_timeout = 5.0

        pieces: list[CodexStreamPiece] = []
        async for piece in connector._iter_codex_stream_pieces(runtime, 7, "auto"):
            pieces.append(piece)

        content = "".join(p.content or "" for p in pieces if p.content)
        assert content == "Thinking:\nThinking step more\n\n"
        done_pieces = [p for p in pieces if p.done]
        assert len(done_pieces) == 1
        assert done_pieces[0].finish_reason == "stop"
        assert runtime.turn_id == "turn_r"

    async def test_server_request_mid_stream_handled_and_continues(
        self,
        connector: OpenAICodexAppServerConnector,
        temp_workspace: Path,
    ) -> None:
        connector._progress_mode = "text_only"
        runtime = _make_runtime(
            temp_workspace,
            model="auto",
            stdout_lines=[
                b'{"jsonrpc":"2.0","id":3,"result":{"turn":{"id":"turn_s"}}}\n',
                b'{"jsonrpc":"2.0","method":"item/agentMessage/delta",'
                b'"params":{"delta":"Hello"}}\n',
                b'{"jsonrpc":"2.0","id":77,"method":'
                b'"item/commandExecution/requestApproval",'
                b'"params":{"command":"ls","cwd":"/p"}}\n',
                b'{"jsonrpc":"2.0","method":"turn/completed",'
                b'"params":{"turn":{"status":"completed"}}}\n',
            ],
            thread_id="thr_1",
        )
        connector._process_timeout = 5.0

        pieces: list[CodexStreamPiece] = []
        async for piece in connector._iter_codex_stream_pieces(runtime, 3, "auto"):
            pieces.append(piece)

        # The approval result was written to stdin.
        writes = _decode_writes(runtime)
        approval_result = [w for w in writes if w.get("id") == 77]
        assert len(approval_result) == 1
        assert approval_result[0]["result"] == {"decision": "accept"}
        # Streaming continued past the server request.
        content_pieces = [p for p in pieces if p.content]
        assert any(p.content == "Hello" for p in content_pieces)
        done_pieces = [p for p in pieces if p.done]
        assert len(done_pieces) == 1
        assert done_pieces[0].finish_reason == "stop"

    async def test_turn_start_response_captures_turn_id_from_result_id(
        self,
        connector: OpenAICodexAppServerConnector,
        temp_workspace: Path,
    ) -> None:
        connector._progress_mode = "text_only"
        runtime = _make_runtime(
            temp_workspace,
            model="auto",
            stdout_lines=[
                b'{"jsonrpc":"2.0","id":11,"result":{"id":"turn_flat"}}\n',
                b'{"jsonrpc":"2.0","method":"turn/completed",'
                b'"params":{"turn":{"status":"completed"}}}\n',
            ],
            thread_id="thr_1",
        )
        connector._process_timeout = 5.0

        pieces: list[CodexStreamPiece] = []
        async for piece in connector._iter_codex_stream_pieces(runtime, 11, "auto"):
            pieces.append(piece)

        assert runtime.turn_id == "turn_flat"
        assert any(p.done for p in pieces)


# ---------------------------------------------------------------------------
# Async subprocess lifecycle: _stream_response (SSE chunk building)
# ---------------------------------------------------------------------------


class TestStreamResponse:
    async def test_sse_chunks_have_delta_content_finish_reason_and_done(
        self,
        connector: OpenAICodexAppServerConnector,
        temp_workspace: Path,
    ) -> None:
        connector._progress_mode = "text_only"
        runtime = _make_runtime(
            temp_workspace,
            model="auto",
            stdout_lines=[
                b'{"jsonrpc":"2.0","id":1,"result":{"turn":{"id":"t1"}}}\n',
                b'{"jsonrpc":"2.0","method":"item/agentMessage/delta",'
                b'"params":{"delta":"Hi"}}\n',
                b'{"jsonrpc":"2.0","method":"item/agentMessage/delta",'
                b'"params":{"delta":" there"}}\n',
                b'{"jsonrpc":"2.0","method":"turn/completed",'
                b'"params":{"turn":{"status":"completed"}}}\n',
            ],
            thread_id="thr_1",
        )
        connector._process_timeout = 5.0

        chunks: list[str] = []
        async for processed in connector._stream_response(runtime, "auto", 1):
            assert isinstance(processed.content, str)
            chunks.append(processed.content)

        # Content delta chunks.
        delta_chunks = [
            c for c in chunks if c.startswith("data: {") and "[DONE]" not in c
        ]
        assert len(delta_chunks) >= 2
        joined_deltas = "".join(delta_chunks)
        assert '"delta"' in joined_deltas
        assert "Hi" in joined_deltas
        assert " there" in joined_deltas

        # Final chunk carries finish_reason.
        finish_chunks = [
            c for c in delta_chunks if '"finish_reason"' in c and '"stop"' in c
        ]
        assert len(finish_chunks) == 1

        # Terminal [DONE] marker.
        assert chunks[-1] == "data: [DONE]\n\n"


# ---------------------------------------------------------------------------
# Cancel-teardown race fix (Part B): _stream_response_with_lock finally must
# skip releasing request_lock while cancellation is in progress.
# ---------------------------------------------------------------------------


class TestStreamResponseWithLockRelease:
    """Verifies the streaming ``_stream_response_with_lock`` finally gates the
    request_lock release + stale-kill scheduling on ``cancellation_event`` NOT
    being set, so a follow-up request cannot acquire the lock against a
    half-torn-down subprocess (the cancel-teardown race).
    """

    async def test_skips_release_when_cancellation_in_progress(
        self,
        connector: OpenAICodexAppServerConnector,
        temp_workspace: Path,
    ) -> None:
        runtime = _make_runtime(temp_workspace, model="auto", thread_id="thr_1")
        # Simulate cancellation in progress: the event is set (a real
        # _cancel_active_request sets it at its start, before teardown).
        assert runtime.cancellation_event is not None
        runtime.cancellation_event.set()
        # The streaming branch acquired the lock before yielding.
        await runtime.request_lock.acquire()
        assert runtime.request_lock.locked()

        async def _fake_iter(
            _runtime: CodexAppServerRuntime,
            _turn_id: int,
            _model: str,
        ) -> AsyncGenerator[CodexStreamPiece, None]:
            # Yield nothing; simulates _iter_codex_stream_pieces exiting
            # immediately when cancellation_event is set (cancel_task wins
            # asyncio.wait and the iterator returns early).
            return
            yield  # pragma: no cover - makes this an async generator

        with (
            patch.object(
                connector, "_iter_codex_stream_pieces", side_effect=_fake_iter
            ),
            patch.object(
                connector, "_schedule_stale_kill_after_turn", AsyncMock()
            ) as schedule_mock,
        ):
            async for _ in connector._stream_response_with_lock(runtime, "auto", 1):
                pass

        # The finally did NOT release the lock because cancellation is in
        # progress -- _cancel_active_request owns the release (Part A). This
        # is the race fix: the lock stays held until teardown completes.
        assert runtime.request_lock is not None
        assert runtime.request_lock.locked()
        # And stale-kill was NOT scheduled (the finally skipped it).
        schedule_mock.assert_not_awaited()
        # The event is still set -- the finally did NOT clear it (the cancel
        # path owns clearing it in its finally, after teardown).
        assert runtime.cancellation_event.is_set()

    async def test_releases_on_natural_stream_end(
        self,
        connector: OpenAICodexAppServerConnector,
        temp_workspace: Path,
    ) -> None:
        runtime = _make_runtime(temp_workspace, model="auto", thread_id="thr_1")
        assert runtime.cancellation_event is not None
        assert not runtime.cancellation_event.is_set()
        await runtime.request_lock.acquire()
        assert runtime.request_lock.locked()

        async def _fake_iter(
            _runtime: CodexAppServerRuntime,
            _turn_id: int,
            _model: str,
        ) -> AsyncGenerator[CodexStreamPiece, None]:
            yield CodexStreamPiece(done=True, finish_reason="stop")

        with (
            patch.object(
                connector, "_iter_codex_stream_pieces", side_effect=_fake_iter
            ),
            patch.object(
                connector, "_schedule_stale_kill_after_turn", AsyncMock()
            ) as schedule_mock,
        ):
            async for _ in connector._stream_response_with_lock(runtime, "auto", 1):
                pass

        # Natural stream end (no cancellation): the finally released the lock
        # and scheduled stale-kill so the next turn can acquire the lock.
        assert runtime.request_lock is not None
        assert not runtime.request_lock.locked()
        schedule_mock.assert_awaited_once()
        assert not runtime.cancellation_event.is_set()


# ---------------------------------------------------------------------------
# Async subprocess lifecycle: chat_completions (non-streaming)
# ---------------------------------------------------------------------------


class TestChatCompletionsNonStreaming:
    async def test_returns_response_envelope_with_accumulated_content(
        self,
        connector: OpenAICodexAppServerConnector,
        temp_workspace: Path,
    ) -> None:
        connector.is_functional = True
        connector._default_project_dir = temp_workspace
        runtime = _make_runtime(temp_workspace, model="auto", thread_id="thr_1")

        async def _fake_iter(
            _runtime: CodexAppServerRuntime,
            _turn_id: int,
            _model: str,
        ) -> AsyncGenerator[CodexStreamPiece, None]:
            yield CodexStreamPiece(content="Hello ")
            yield CodexStreamPiece(content="world")
            yield CodexStreamPiece(done=True, finish_reason="stop")

        with (
            patch.object(
                connector, "_acquire_runtime", AsyncMock(return_value=runtime)
            ),
            patch.object(
                connector,
                "_prepare_turn_request_locked",
                AsyncMock(return_value=(1, "auto")),
            ),
            patch.object(
                connector, "_iter_codex_stream_pieces", side_effect=_fake_iter
            ),
        ):
            response = await connector.chat_completions(_make_request())

        assert isinstance(response, ResponseEnvelope)
        assert response.status_code == 200
        assert isinstance(response.content, dict)
        message = response.content["choices"][0]["message"]
        assert message["content"] == "Hello world"
        assert message["role"] == "assistant"
        assert response.content["model"] == "auto"
        assert response.content["object"] == "chat.completion"

    async def test_raises_service_unavailable_when_not_functional(
        self,
        connector: OpenAICodexAppServerConnector,
    ) -> None:
        connector.is_functional = False
        connector._initialization_failed = True
        with pytest.raises(ServiceUnavailableError):
            await connector.chat_completions(_make_request())


# ---------------------------------------------------------------------------
# Async subprocess lifecycle: chat_completions (streaming)
# ---------------------------------------------------------------------------


class TestChatCompletionsStreaming:
    async def test_returns_streaming_envelope_with_sse_chunks(
        self,
        connector: OpenAICodexAppServerConnector,
        temp_workspace: Path,
    ) -> None:
        connector.is_functional = True
        connector._default_project_dir = temp_workspace
        runtime = _make_runtime(temp_workspace, model="auto", thread_id="thr_1")
        connector._process_timeout = 5.0
        connector._progress_mode = "text_only"
        runtime.process = FakeProcess(
            stdout_lines=[
                b'{"jsonrpc":"2.0","id":1,"result":{"turn":{"id":"t1"}}}\n',
                b'{"jsonrpc":"2.0","method":"item/agentMessage/delta",'
                b'"params":{"delta":"streamed"}}\n',
                b'{"jsonrpc":"2.0","method":"turn/completed",'
                b'"params":{"turn":{"status":"completed"}}}\n',
            ]
        )

        with (
            patch.object(
                connector, "_acquire_runtime", AsyncMock(return_value=runtime)
            ),
            patch.object(
                connector,
                "_prepare_turn_request_locked",
                AsyncMock(return_value=(1, "auto")),
            ),
            patch.object(connector, "_schedule_stale_kill_after_turn", AsyncMock()),
        ):
            response = await connector.chat_completions(_make_request(stream=True))

        assert isinstance(response, StreamingResponseEnvelope)
        assert response.media_type == "text/event-stream"
        assert response.cancel_callback is not None

        chunks: list[str] = []
        assert response.content is not None
        async for processed in response.content:
            assert isinstance(processed.content, str)
            chunks.append(processed.content)

        joined = "".join(chunks)
        assert "streamed" in joined
        assert '"finish_reason"' in joined
        assert joined.endswith("data: [DONE]\n\n")


# ---------------------------------------------------------------------------
# Async subprocess lifecycle: _cancel_active_request
# ---------------------------------------------------------------------------


class TestCancelActiveRequest:
    async def test_graceful_cancel_releases_lock_and_cleans_up(
        self,
        connector: OpenAICodexAppServerConnector,
        temp_workspace: Path,
    ) -> None:
        runtime = _make_runtime(
            temp_workspace,
            model="auto",
            stdout_lines=[
                b'{"jsonrpc":"2.0","method":"turn/completed",'
                b'"params":{"turn":{"status":"interrupted"}}}\n',
            ],
            thread_id="thr_1",
            turn_id="turn_1",
        )
        connector._process_timeout = 5.0
        proc = runtime.process
        assert isinstance(proc, FakeProcess)
        await runtime.request_lock.acquire()
        assert runtime.request_lock.locked()

        await connector._cancel_active_request(runtime, 1)

        assert not runtime.request_lock.locked()
        assert runtime.process is None

        writes = [json.loads(w.decode("utf-8").strip()) for w in proc.stdin.writes]
        interrupts = [w for w in writes if w.get("method") == "turn/interrupt"]
        assert len(interrupts) == 1
        assert interrupts[0]["params"] == {
            "threadId": "thr_1",
            "turnId": "turn_1",
        }

    async def test_force_kill_when_not_graceful(
        self,
        connector: OpenAICodexAppServerConnector,
        temp_workspace: Path,
    ) -> None:
        runtime = _make_runtime(
            temp_workspace,
            model="auto",
            stdout_lines=[],
            thread_id="thr_1",
            turn_id="turn_1",
        )
        await runtime.request_lock.acquire()
        assert runtime.request_lock.locked()

        with (
            patch.object(
                connector,
                "_attempt_graceful_cancel",
                AsyncMock(return_value=False),
            ),
            patch.object(connector, "_kill_runtime", AsyncMock()) as kill_mock,
        ):
            await connector._cancel_active_request(runtime, 1)

        kill_mock.assert_awaited_once()
        assert not runtime.request_lock.locked()

    async def test_releases_lock_even_when_teardown_raises(
        self,
        connector: OpenAICodexAppServerConnector,
        temp_workspace: Path,
    ) -> None:
        """Part A: the finally releases ``request_lock`` even when teardown
        raises mid-way, so a teardown exception cannot deadlock the runtime.
        Also verifies ``cancellation_event`` is cleared by the same finally.
        """
        runtime = _make_runtime(
            temp_workspace,
            model="auto",
            stdout_lines=[],
            thread_id="thr_1",
            turn_id="turn_1",
        )
        await runtime.request_lock.acquire()
        assert runtime.request_lock.locked()

        with (
            patch.object(
                connector,
                "_attempt_graceful_cancel",
                AsyncMock(side_effect=RuntimeError("teardown boom")),
            ),
            patch.object(connector, "_kill_runtime", AsyncMock()) as kill_mock,
            pytest.raises(RuntimeError, match="teardown boom"),
        ):
            await connector._cancel_active_request(runtime, 1)

        # The force-kill fallback must NOT run when graceful cancel raises
        # (the exception propagates past the graceful/force branch).
        kill_mock.assert_not_awaited()
        # Part A: the finally released the lock despite the raised exception.
        assert runtime.request_lock is not None
        assert not runtime.request_lock.locked()
        # And the cancellation_event was cleared by the finally.
        assert runtime.cancellation_event is not None
        assert not runtime.cancellation_event.is_set()


# ---------------------------------------------------------------------------
# Async subprocess lifecycle: spawn / kill / kill_all
# ---------------------------------------------------------------------------


class TestSpawnAndKill:
    async def test_spawn_process_sets_runtime_fields(
        self,
        connector: OpenAICodexAppServerConnector,
        temp_workspace: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        runtime = _make_runtime(temp_workspace, model="auto")
        fake_proc = FakeProcess(stdout_lines=[])
        fake_proc._poll = None

        def _fake_popen(*_args: Any, **_kwargs: Any) -> FakeProcess:
            return fake_proc

        monkeypatch.setattr(
            "src.connectors.acp_core.base_connector.subprocess.Popen", _fake_popen
        )
        sentinel_identity = MagicMock()
        monkeypatch.setattr(
            "src.connectors.acp_core.base_connector.capture_acp_subprocess_identity",
            lambda _p, _c: sentinel_identity,
        )

        await connector._spawn_process(runtime)

        assert runtime.process is fake_proc
        assert runtime.last_activity > 0
        assert runtime.initialized is False
        assert runtime.thread_id is None
        assert runtime.turn_id is None
        assert runtime.acp_subprocess_identity is sentinel_identity

    async def test_spawn_process_early_exit_raises_connection_error(
        self,
        connector: OpenAICodexAppServerConnector,
        temp_workspace: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        runtime = _make_runtime(temp_workspace, model="auto")
        fake_proc = FakeProcess(stdout_lines=[])
        fake_proc._poll = 1  # exited

        def _fake_popen(*_args: Any, **_kwargs: Any) -> FakeProcess:
            return fake_proc

        monkeypatch.setattr(
            "src.connectors.acp_core.base_connector.subprocess.Popen", _fake_popen
        )
        monkeypatch.setattr(
            "src.connectors.acp_core.base_connector.capture_acp_subprocess_identity",
            lambda _p, _c: None,
        )

        with pytest.raises(APIConnectionError):
            await connector._spawn_process(runtime)
        assert runtime.process is None

    async def test_kill_runtime_closes_streams_and_clears_process(
        self,
        connector: OpenAICodexAppServerConnector,
        temp_workspace: Path,
    ) -> None:
        runtime = _make_runtime(temp_workspace, model="auto", stdout_lines=[])
        proc = runtime.process
        assert isinstance(proc, FakeProcess)
        with patch.object(connector, "_terminate_process", AsyncMock()):
            await connector._kill_runtime(runtime)
        assert runtime.process is None
        assert proc.stdin._closed is True
        assert proc.stdout._closed is True
        assert proc.stderr._closed is True

    async def test_kill_all_runtimes_clears_pool(
        self,
        connector: OpenAICodexAppServerConnector,
        temp_workspace: Path,
    ) -> None:
        ra = _make_runtime(temp_workspace, model="auto", stdout_lines=[])
        rb = _make_runtime(temp_workspace, model="gpt-5.4", stdout_lines=[])
        key_a = connector._build_runtime_key(temp_workspace, "auto", "default")
        key_b = connector._build_runtime_key(temp_workspace, "gpt-5.4", "default")
        connector._runtimes[key_a] = ra
        connector._runtimes[key_b] = rb
        with patch.object(connector, "_terminate_process", AsyncMock()):
            await connector._kill_all_runtimes()
        assert len(connector._runtimes) == 0
        assert ra.process is None
        assert rb.process is None


# ---------------------------------------------------------------------------
# Async subprocess lifecycle: _reap_idle_runtime
# ---------------------------------------------------------------------------


class TestReapIdleRuntime:
    async def test_idle_runtime_replaced_with_fresh(
        self,
        connector: OpenAICodexAppServerConnector,
        temp_workspace: Path,
    ) -> None:
        connector._idle_timeout = 5.0
        runtime = _make_runtime(temp_workspace, model="auto", stdout_lines=[])
        runtime.last_activity = 1.0
        key = connector._build_runtime_key(temp_workspace, "auto", "default")
        connector._runtimes[key] = runtime

        with (
            patch(
                "src.connectors.acp_core.base_connector.time.monotonic",
                return_value=100.0,
            ),
            patch.object(connector, "_terminate_process", AsyncMock()),
        ):
            result = await connector._reap_idle_runtime(key, runtime)

        assert result is not runtime
        assert result.process is None
        assert result.last_activity == 0.0
        assert connector._runtimes[key] is result

    async def test_recent_activity_returns_same_runtime(
        self,
        connector: OpenAICodexAppServerConnector,
        temp_workspace: Path,
    ) -> None:
        connector._idle_timeout = 5.0
        runtime = _make_runtime(temp_workspace, model="auto", stdout_lines=[])
        runtime.last_activity = 99.0
        key = connector._build_runtime_key(temp_workspace, "auto", "default")
        connector._runtimes[key] = runtime

        with patch(
            "src.connectors.acp_core.base_connector.time.monotonic",
            return_value=100.0,
        ):
            result = await connector._reap_idle_runtime(key, runtime)

        assert result is runtime

    async def test_process_none_returns_canonical_when_pool_swapped(
        self,
        connector: OpenAICodexAppServerConnector,
        temp_workspace: Path,
    ) -> None:
        """Bugbot FIX: when the caller's runtime has process=None, re-read the
        pool so a concurrent idle-reap that swapped in a fresh runtime is
        observed. Without this, the caller returns a detached runtime and
        spawns a duplicate child for the same pool key (duplicate agents +
        divergent history for one workspace/session/model tuple).
        """
        connector._idle_timeout = 5.0
        key = connector._build_runtime_key(temp_workspace, "auto", "default")
        # The pool already holds a fresh replacement (live process) swapped in
        # by a concurrent idle-reap.
        fresh_runtime = _make_runtime(temp_workspace, model="auto", stdout_lines=[])
        connector._runtimes[key] = fresh_runtime
        # The caller's stale ref has its process already killed by the
        # concurrent idle-reap.
        stale_runtime = _make_runtime(temp_workspace, model="auto")
        assert stale_runtime.process is None

        result = await connector._reap_idle_runtime(key, stale_runtime)

        assert result is fresh_runtime
        assert result is not stale_runtime

    async def test_process_none_returns_same_when_pool_unchanged(
        self,
        connector: OpenAICodexAppServerConnector,
        temp_workspace: Path,
    ) -> None:
        """When the pool still holds the caller's runtime (no concurrent swap)
        and its process is None, return it unchanged -- there is no
        replacement to make.
        """
        connector._idle_timeout = 5.0
        key = connector._build_runtime_key(temp_workspace, "auto", "default")
        runtime = _make_runtime(temp_workspace, model="auto")
        assert runtime.process is None
        connector._runtimes[key] = runtime

        result = await connector._reap_idle_runtime(key, runtime)

        assert result is runtime


# ---------------------------------------------------------------------------
# Async subprocess lifecycle: shutdown
# ---------------------------------------------------------------------------


class TestShutdown:
    async def test_shutdown_kills_all_runtimes_and_empties_pool(
        self,
        connector: OpenAICodexAppServerConnector,
        temp_workspace: Path,
    ) -> None:
        ra = _make_runtime(temp_workspace, model="auto", stdout_lines=[])
        rb = _make_runtime(temp_workspace, model="gpt-5.4", stdout_lines=[])
        key_a = connector._build_runtime_key(temp_workspace, "auto", "default")
        key_b = connector._build_runtime_key(temp_workspace, "gpt-5.4", "default")
        connector._runtimes[key_a] = ra
        connector._runtimes[key_b] = rb
        with patch.object(connector, "_terminate_process", AsyncMock()):
            await connector.shutdown()
        assert len(connector._runtimes) == 0
        assert ra.process is None
        assert rb.process is None


# ---------------------------------------------------------------------------
# HistoryState-aware turn input (FIX 1) + client-facing model echo (FIX 2)
# ---------------------------------------------------------------------------


class TestTurnInputHistory:
    """Verify the ported ACP history-state logic drives ``turn/start`` input."""

    async def test_first_turn_sends_full_transcript(
        self,
        connector: OpenAICodexAppServerConnector,
        temp_workspace: Path,
    ) -> None:
        messages = [
            ChatMessage(role="system", content="You are helpful."),
            ChatMessage(role="user", content="first question"),
            ChatMessage(role="assistant", content="first answer"),
            ChatMessage(role="user", content="second question"),
        ]
        runtime = _make_runtime(
            temp_workspace,
            model="auto",
            stdout_lines=[
                b'{"jsonrpc":"2.0","id":1,"result":{"turn":{"id":"turn_1"}}}\n',
            ],
            thread_id="thr_1",
        )
        runtime.initialized = True
        runtime.history_state = None

        with (
            patch.object(connector, "_cancel_stale_kill_timer", AsyncMock()),
            patch.object(connector, "_spawn_process", AsyncMock()),
            patch.object(connector, "_perform_handshake", AsyncMock()),
        ):
            turn_request_id, requested_model = (
                await connector._prepare_turn_request_locked(
                    runtime,
                    _make_request(processed_messages=messages, model="openai/auto"),
                )
            )

        assert turn_request_id >= 1
        assert _last_turn_start_input_text(
            runtime
        ) == ACPTranscriptSerializer.serialize(messages)
        # FIX 2 (deferred commit): history_state is NOT mutated in prepare;
        # the staged state lives in pending_history_state until turn/start is
        # accepted by the stream iterator.
        assert runtime.history_state is None
        assert runtime.pending_history_state is not None
        assert runtime.pending_history_state.message_count == 4
        assert (
            runtime.pending_history_state.prefix_hash
            == _hash_chat_messages_prefix_stable(messages, 4)
        )
        # FIX 2: effective_model is echoed verbatim when set.
        assert requested_model == "openai/auto"

    async def test_append_only_sends_tail(
        self,
        connector: OpenAICodexAppServerConnector,
        temp_workspace: Path,
    ) -> None:
        messages = [
            ChatMessage(role="system", content="You are helpful."),
            ChatMessage(role="user", content="first question"),
            ChatMessage(role="assistant", content="first answer"),
            ChatMessage(role="user", content="second question"),
        ]
        prefix_hash = _hash_chat_messages_prefix_stable(messages, 3)
        runtime = _make_runtime(
            temp_workspace,
            model="auto",
            stdout_lines=[
                b'{"jsonrpc":"2.0","id":1,"result":{"turn":{"id":"turn_2"}}}\n',
            ],
            thread_id="thr_1",
        )
        runtime.initialized = True
        runtime.history_state = HistoryState(message_count=3, prefix_hash=prefix_hash)

        with (
            patch.object(connector, "_cancel_stale_kill_timer", AsyncMock()),
            patch.object(connector, "_spawn_process", AsyncMock()),
            patch.object(connector, "_perform_handshake", AsyncMock()),
        ):
            await connector._prepare_turn_request_locked(
                runtime,
                _make_request(processed_messages=messages, model="openai/auto"),
            )

        assert _last_turn_start_input_text(runtime) == (
            ACPTranscriptSerializer.serialize_tail(messages, 3)
        )
        # FIX 2 (deferred commit): history_state keeps its prior value
        # (message_count=3); the new state is staged in pending_history_state.
        assert runtime.history_state.message_count == 3
        assert runtime.history_state.prefix_hash == prefix_hash
        assert runtime.pending_history_state is not None
        assert runtime.pending_history_state.message_count == 4
        assert (
            runtime.pending_history_state.prefix_hash
            == _hash_chat_messages_prefix_stable(messages, 4)
        )

    async def test_idempotent_retry_sends_last_user_message(
        self,
        connector: OpenAICodexAppServerConnector,
        temp_workspace: Path,
    ) -> None:
        messages = [
            ChatMessage(role="system", content="You are helpful."),
            ChatMessage(role="user", content="only question"),
        ]
        prefix_hash = _hash_chat_messages_prefix_stable(messages, 2)
        runtime = _make_runtime(
            temp_workspace,
            model="auto",
            stdout_lines=[
                b'{"jsonrpc":"2.0","id":1,"result":{"turn":{"id":"turn_3"}}}\n',
            ],
            thread_id="thr_1",
        )
        runtime.initialized = True
        runtime.history_state = HistoryState(message_count=2, prefix_hash=prefix_hash)

        with (
            patch.object(connector, "_cancel_stale_kill_timer", AsyncMock()),
            patch.object(connector, "_spawn_process", AsyncMock()),
            patch.object(connector, "_perform_handshake", AsyncMock()),
        ):
            await connector._prepare_turn_request_locked(
                runtime,
                _make_request(processed_messages=messages, model="openai/auto"),
            )

        assert _last_turn_start_input_text(runtime) == "only question"
        # Idempotent retry keeps the history_state unchanged.
        assert runtime.history_state.message_count == 2
        assert runtime.history_state.prefix_hash == prefix_hash

    async def test_divergence_resets_runtime_and_resends_full_transcript(
        self,
        connector: OpenAICodexAppServerConnector,
        temp_workspace: Path,
    ) -> None:
        messages = [ChatMessage(role="user", content="diverged question")]
        runtime = _make_runtime(
            temp_workspace,
            model="auto",
            stdout_lines=[
                b'{"jsonrpc":"2.0","id":1,"result":{"turn":{"id":"turn_4"}}}\n',
            ],
            thread_id="thr_1",
        )
        runtime.initialized = True
        # Mismatched state: claims 5 messages with a bogus prefix hash.
        runtime.history_state = HistoryState(message_count=5, prefix_hash="bogus")

        kill_mock = AsyncMock()
        spawn_mock = AsyncMock()
        handshake_mock = AsyncMock()

        with (
            patch.object(connector, "_cancel_stale_kill_timer", AsyncMock()),
            patch.object(connector, "_spawn_process", spawn_mock),
            patch.object(connector, "_perform_handshake", handshake_mock),
            patch.object(connector, "_kill_runtime", kill_mock),
        ):
            await connector._prepare_turn_request_locked(
                runtime,
                _make_request(processed_messages=messages, model="openai/auto"),
            )

        # Divergence path: kill -> spawn -> handshake all awaited.
        kill_mock.assert_awaited_once()
        handshake_mock.assert_awaited_once()
        # _spawn_process is awaited at the top and again after the kill reset.
        assert spawn_mock.await_count >= 2
        assert _last_turn_start_input_text(runtime) == (
            ACPTranscriptSerializer.serialize(messages)
        )
        # FIX 2 (deferred commit): _kill_runtime is mocked here, so
        # history_state is NOT cleared by the divergence kill; prepare does
        # NOT mutate history_state (deferred commit). The new state is staged
        # in pending_history_state (committed by the stream iterator on
        # turn/start ok).
        assert runtime.history_state.message_count == 5
        assert runtime.history_state.prefix_hash == "bogus"
        assert runtime.pending_history_state is not None
        assert runtime.pending_history_state.message_count == 1
        assert (
            runtime.pending_history_state.prefix_hash
            == _hash_chat_messages_prefix_stable(messages, 1)
        )

    async def test_response_model_echoes_effective_model(
        self,
        connector: OpenAICodexAppServerConnector,
        temp_workspace: Path,
    ) -> None:
        async def _run(
            runtime_model: str, effective_model: str, expected_echo: str
        ) -> None:
            runtime = _make_runtime(
                temp_workspace,
                model=runtime_model,
                stdout_lines=[
                    b'{"jsonrpc":"2.0","id":1,"result":{"turn":{"id":"turn_m"}}}\n',
                ],
                thread_id="thr_1",
            )
            runtime.initialized = True
            with (
                patch.object(connector, "_cancel_stale_kill_timer", AsyncMock()),
                patch.object(connector, "_spawn_process", AsyncMock()),
                patch.object(connector, "_perform_handshake", AsyncMock()),
            ):
                _, requested_model = await connector._prepare_turn_request_locked(
                    runtime,
                    _make_request(
                        processed_messages=[ChatMessage(role="user", content="hi")],
                        model=effective_model,
                    ),
                )
            assert requested_model == expected_echo

        # effective_model set -> echoed verbatim (vendor-prefixed form kept).
        await _run("gpt-5.4", "openai/gpt-5.4", "openai/gpt-5.4")
        # effective_model="auto" is truthy -> echoed verbatim.
        await _run("gpt-5.4", "auto", "auto")
        # Empty effective_model -> vendor-prefixed stripped runtime model.
        await _run("auto", "", "openai/auto")

    async def test_empty_messages_raises_no_messages_found(
        self,
        connector: OpenAICodexAppServerConnector,
        temp_workspace: Path,
    ) -> None:
        runtime = _make_runtime(
            temp_workspace,
            model="auto",
            stdout_lines=[],
            thread_id="thr_1",
        )
        runtime.initialized = True
        with (
            patch.object(connector, "_cancel_stale_kill_timer", AsyncMock()),
            patch.object(connector, "_spawn_process", AsyncMock()),
            patch.object(connector, "_perform_handshake", AsyncMock()),
            pytest.raises(BackendError, match="No messages found in request"),
        ):
            await connector._prepare_turn_request_locked(
                runtime,
                _make_request(processed_messages=[], model="openai/auto"),
            )


# ---------------------------------------------------------------------------
# FIX 3: _prepare_turn_request_locked must NOT await the turn/start response
# ---------------------------------------------------------------------------


class TestPrepareTurnRequestNoAwait:
    """Verify prepare sends ``turn/start`` and returns WITHOUT consuming the
    response or capturing ``runtime.turn_id`` (the stream iterator does both)."""

    async def test_does_not_await_turn_start_response(
        self,
        connector: OpenAICodexAppServerConnector,
        temp_workspace: Path,
    ) -> None:
        # Queue a turn/start response in stdout -- prepare must NOT consume it.
        runtime = _make_runtime(
            temp_workspace,
            model="auto",
            stdout_lines=[
                b'{"jsonrpc":"2.0","id":1,"result":{"turn":{"id":"turn_1"}}}\n',
            ],
            thread_id="thr_1",
        )
        runtime.initialized = True
        runtime.history_state = None
        proc = runtime.process
        assert isinstance(proc, FakeProcess)
        connector._process_timeout = 5.0

        with (
            patch.object(connector, "_cancel_stale_kill_timer", AsyncMock()),
            patch.object(connector, "_spawn_process", AsyncMock()),
            patch.object(connector, "_perform_handshake", AsyncMock()),
        ):
            turn_request_id, requested_model = (
                await connector._prepare_turn_request_locked(
                    runtime,
                    _make_request(
                        processed_messages=[ChatMessage(role="user", content="hi")],
                        model="openai/auto",
                    ),
                )
            )

        assert turn_request_id >= 1
        assert requested_model == "openai/auto"
        # turn/start was written.
        writes = _decode_writes(runtime)
        turn_starts = [w for w in writes if w.get("method") == "turn/start"]
        assert len(turn_starts) == 1
        # FIX 2 (deferred commit): history_state is NOT mutated in prepare;
        # the staged state lives in pending_history_state until the stream
        # iterator sees the turn/start response.
        assert runtime.history_state is None
        assert runtime.pending_history_state is not None
        # turn_id is NOT captured here -- the stream iterator does that.
        assert runtime.turn_id is None
        # The turn/start response was NOT consumed: still queued in stdout.
        assert len(proc.stdout._lines) == 1

    async def test_history_state_set_after_send(
        self,
        connector: OpenAICodexAppServerConnector,
        temp_workspace: Path,
    ) -> None:
        messages = [ChatMessage(role="user", content="hello")]
        runtime = _make_runtime(
            temp_workspace,
            model="auto",
            stdout_lines=[],
            thread_id="thr_1",
        )
        runtime.initialized = True
        runtime.history_state = None

        with (
            patch.object(connector, "_cancel_stale_kill_timer", AsyncMock()),
            patch.object(connector, "_spawn_process", AsyncMock()),
            patch.object(connector, "_perform_handshake", AsyncMock()),
        ):
            await connector._prepare_turn_request_locked(
                runtime,
                _make_request(processed_messages=messages, model="openai/auto"),
            )

        # FIX 2 (deferred commit): history_state stays None; the new state is
        # staged in pending_history_state (committed by the stream iterator on
        # turn/start ok).
        assert runtime.history_state is None
        assert runtime.pending_history_state is not None
        assert runtime.pending_history_state.message_count == 1
        assert (
            runtime.pending_history_state.prefix_hash
            == _hash_chat_messages_prefix_stable(messages, 1)
        )


class TestEventMapperProgressMode:
    def test_text_only_suppresses_completed_summaries(self) -> None:
        mapper = CodexEventMapper(progress_mode="text_only")
        # commandExecution completed -> suppressed (gated behind _summaries_enabled)
        cmd_pieces = mapper.handle(
            ACPNotification(
                method="item/completed",
                params={
                    "type": "commandExecution",
                    "id": "c1",
                    "command": "npm test",
                    "exitCode": 0,
                    "durationMs": 100,
                },
            )
        )
        assert cmd_pieces == []
        # fileChange completed -> suppressed
        file_pieces = mapper.handle(
            ACPNotification(
                method="item/completed",
                params={
                    "type": "fileChange",
                    "id": "f1",
                    "changes": [{"path": "a.py", "kind": "edit"}],
                },
            )
        )
        assert file_pieces == []
        # agentMessage delta still emits content in text_only mode.
        delta_pieces = mapper.handle(
            ACPNotification(
                method="item/agentMessage/delta",
                params={"delta": "hello"},
            )
        )
        assert delta_pieces == [CodexStreamPiece(content="hello")]

    def test_text_plus_summaries_emits_completed_summaries(self) -> None:
        mapper = CodexEventMapper()  # default = "text_plus_summaries"
        pieces = mapper.handle(
            ACPNotification(
                method="item/completed",
                params={
                    "type": "commandExecution",
                    "id": "c1",
                    "command": "npm test",
                    "exitCode": 0,
                    "durationMs": 100,
                },
            )
        )
        assert len(pieces) == 1
        content = pieces[0].content or ""
        assert "Tool: npm" in content
        assert "```text" in content


# ---------------------------------------------------------------------------
# FIX 1 + FIX 2: _attempt_graceful_cancel must not orphan the subprocess
# ---------------------------------------------------------------------------


class TestAttemptGracefulCancel:
    async def test_returns_true_when_process_already_exited(
        self,
        connector: OpenAICodexAppServerConnector,
        temp_workspace: Path,
    ) -> None:
        runtime = _make_runtime(
            temp_workspace,
            model="auto",
            stdout_lines=[],
            thread_id="thr_1",
            turn_id="turn_1",
        )
        proc = runtime.process
        assert isinstance(proc, FakeProcess)
        proc._poll = 0  # already exited

        result = await connector._attempt_graceful_cancel(
            runtime, request_id=1, total_timeout_s=2.0
        )

        assert result is True
        # Short-circuited: no turn/interrupt was sent.
        writes = _decode_writes(runtime)
        assert not any(w.get("method") == "turn/interrupt" for w in writes)

    async def test_turn_completed_then_stdin_close_exits_returns_true(
        self,
        connector: OpenAICodexAppServerConnector,
        temp_workspace: Path,
    ) -> None:
        runtime = _make_runtime(
            temp_workspace,
            model="auto",
            stdout_lines=[
                b'{"jsonrpc":"2.0","method":"turn/completed",'
                b'"params":{"turn":{"status":"interrupted"}}}\n',
            ],
            thread_id="thr_1",
            turn_id="turn_1",
        )
        proc = runtime.process
        assert isinstance(proc, FakeProcess)
        # Model the Codex app-server exiting when stdin closes.
        proc.stdin = ExitOnCloseStdin(proc)
        assert proc.poll() is None  # alive during drain
        connector._process_timeout = 5.0

        result = await connector._attempt_graceful_cancel(
            runtime, request_id=1, total_timeout_s=3.0
        )

        assert result is True
        # turn/interrupt was sent.
        writes = _decode_writes(runtime)
        interrupts = [w for w in writes if w.get("method") == "turn/interrupt"]
        assert len(interrupts) == 1
        assert interrupts[0]["params"] == {"threadId": "thr_1", "turnId": "turn_1"}
        # stdin was closed (the stdin-close path was taken).
        assert proc.stdin._closed is True
        # No orphan: the process actually exited (poll is non-None).
        assert proc.poll() is not None

    async def test_turn_completed_but_process_still_alive_returns_false(
        self,
        connector: OpenAICodexAppServerConnector,
        temp_workspace: Path,
    ) -> None:
        runtime = _make_runtime(
            temp_workspace,
            model="auto",
            stdout_lines=[
                b'{"jsonrpc":"2.0","method":"turn/completed",'
                b'"params":{"turn":{"status":"interrupted"}}}\n',
            ],
            thread_id="thr_1",
            turn_id="turn_1",
        )
        proc = runtime.process
        assert isinstance(proc, FakeProcess)
        assert proc.poll() is None  # alive, stays alive
        connector._process_timeout = 5.0

        with patch.object(
            connector, "_wait_for_process_exit", AsyncMock(return_value=False)
        ):
            result = await connector._attempt_graceful_cancel(
                runtime, request_id=1, total_timeout_s=3.0
            )

        assert result is False
        # turn/interrupt was still sent before the drain.
        writes = _decode_writes(runtime)
        interrupts = [w for w in writes if w.get("method") == "turn/interrupt"]
        assert len(interrupts) == 1
        # stdin was closed attempting to shut the server down.
        assert proc.stdin._closed is True
        # Process still alive -> _cancel_active_request will force-kill.
        assert proc.poll() is None

    async def test_server_request_during_drain_is_handled(
        self,
        connector: OpenAICodexAppServerConnector,
        temp_workspace: Path,
    ) -> None:
        runtime = _make_runtime(
            temp_workspace,
            model="auto",
            stdout_lines=[
                b'{"jsonrpc":"2.0","id":77,"method":'
                b'"item/commandExecution/requestApproval",'
                b'"params":{"command":"ls","cwd":"/p"}}\n',
                b'{"jsonrpc":"2.0","method":"turn/completed",'
                b'"params":{"turn":{"status":"interrupted"}}}\n',
            ],
            thread_id="thr_1",
            turn_id="turn_1",
        )
        proc = runtime.process
        assert isinstance(proc, FakeProcess)
        proc.stdin = ExitOnCloseStdin(proc)
        assert proc.poll() is None
        connector._process_timeout = 5.0

        result = await connector._attempt_graceful_cancel(
            runtime, request_id=1, total_timeout_s=3.0
        )

        assert result is True
        writes = _decode_writes(runtime)
        # The approval result was written via _handle_server_request.
        approval_results = [w for w in writes if w.get("id") == 77]
        assert len(approval_results) == 1
        assert approval_results[0]["result"] == {"decision": "accept"}
        # turn/interrupt was also sent before the drain.
        interrupts = [w for w in writes if w.get("method") == "turn/interrupt"]
        assert len(interrupts) == 1
        # stdin was closed and the process exited (no orphan).
        assert proc.stdin._closed is True
        assert proc.poll() is not None


# ---------------------------------------------------------------------------
# FIX 1: non-streaming chat_completions honors turn finish_reason
# ---------------------------------------------------------------------------


class TestNonStreamingFinishReason:
    """Non-streaming chat_completions must map finish_reason and raise on error."""

    async def test_completed_turn_finish_reason_stop(
        self,
        connector: OpenAICodexAppServerConnector,
        temp_workspace: Path,
    ) -> None:
        connector.is_functional = True
        connector._default_project_dir = temp_workspace
        runtime = _make_runtime(temp_workspace, model="auto", thread_id="thr_1")

        async def _fake_iter(
            _runtime: CodexAppServerRuntime,
            _turn_id: int,
            _model: str,
        ) -> AsyncGenerator[CodexStreamPiece, None]:
            yield CodexStreamPiece(content="Hello ")
            yield CodexStreamPiece(content="world")
            yield CodexStreamPiece(done=True, finish_reason="stop")

        with (
            patch.object(
                connector, "_acquire_runtime", AsyncMock(return_value=runtime)
            ),
            patch.object(
                connector,
                "_prepare_turn_request_locked",
                AsyncMock(return_value=(1, "auto")),
            ),
            patch.object(
                connector, "_iter_codex_stream_pieces", side_effect=_fake_iter
            ),
        ):
            response = await connector.chat_completions(_make_request())

        assert isinstance(response, ResponseEnvelope)
        assert response.status_code == 200
        content = response.content
        assert isinstance(content, dict)
        choices = content["choices"]
        assert isinstance(choices, list) and choices
        choice = choices[0]
        assert isinstance(choice, dict)
        assert choice["finish_reason"] == "stop"
        message = choice["message"]
        assert isinstance(message, dict)
        assert message["content"] == "Hello world"

    async def test_interrupted_turn_finish_reason_stop(
        self,
        connector: OpenAICodexAppServerConnector,
        temp_workspace: Path,
    ) -> None:
        connector.is_functional = True
        connector._default_project_dir = temp_workspace
        runtime = _make_runtime(temp_workspace, model="auto", thread_id="thr_1")

        async def _fake_iter(
            _runtime: CodexAppServerRuntime,
            _turn_id: int,
            _model: str,
        ) -> AsyncGenerator[CodexStreamPiece, None]:
            yield CodexStreamPiece(content="partial")
            yield CodexStreamPiece(done=True, finish_reason="interrupted")

        with (
            patch.object(
                connector, "_acquire_runtime", AsyncMock(return_value=runtime)
            ),
            patch.object(
                connector,
                "_prepare_turn_request_locked",
                AsyncMock(return_value=(1, "auto")),
            ),
            patch.object(
                connector, "_iter_codex_stream_pieces", side_effect=_fake_iter
            ),
        ):
            response = await connector.chat_completions(_make_request())

        assert isinstance(response, ResponseEnvelope)
        assert response.status_code == 200
        content = response.content
        assert isinstance(content, dict)
        choices = content["choices"]
        assert isinstance(choices, list) and choices
        choice = choices[0]
        assert isinstance(choice, dict)
        # interrupted -> mapped to "stop" (no OpenAI equivalent).
        assert choice["finish_reason"] == "stop"
        message = choice["message"]
        assert isinstance(message, dict)
        assert message["content"] == "partial"

    async def test_failed_turn_raises_backend_error(
        self,
        connector: OpenAICodexAppServerConnector,
        temp_workspace: Path,
    ) -> None:
        connector.is_functional = True
        connector._default_project_dir = temp_workspace
        runtime = _make_runtime(temp_workspace, model="auto", thread_id="thr_1")

        async def _fake_iter(
            _runtime: CodexAppServerRuntime,
            _turn_id: int,
            _model: str,
        ) -> AsyncGenerator[CodexStreamPiece, None]:
            yield CodexStreamPiece(content="partial before failure")
            yield CodexStreamPiece(done=True, finish_reason="error")

        with (
            patch.object(
                connector, "_acquire_runtime", AsyncMock(return_value=runtime)
            ),
            patch.object(
                connector,
                "_prepare_turn_request_locked",
                AsyncMock(return_value=(1, "auto")),
            ),
            patch.object(
                connector, "_iter_codex_stream_pieces", side_effect=_fake_iter
            ),
            pytest.raises(BackendError, match="Codex turn failed"),
        ):
            await connector.chat_completions(_make_request())


# ---------------------------------------------------------------------------
# FIX 2: non-streaming chat_completions lock release is idempotent
# ---------------------------------------------------------------------------


class TestNonStreamingLockRelease:
    """Non-streaming ``chat_completions`` must release ``request_lock``
    idempotently so a cancel callback that releases the lock first does not
    collide with the finally and raise ``RuntimeError: Lock is not acquired``.
    """

    async def test_non_streaming_releases_lock_on_success(
        self,
        connector: OpenAICodexAppServerConnector,
        temp_workspace: Path,
    ) -> None:
        connector.is_functional = True
        connector._default_project_dir = temp_workspace
        runtime = _make_runtime(temp_workspace, model="auto", thread_id="thr_1")

        async def _fake_iter(
            _runtime: CodexAppServerRuntime,
            _turn_id: int,
            _model: str,
        ) -> AsyncGenerator[CodexStreamPiece, None]:
            yield CodexStreamPiece(content="Hello ")
            yield CodexStreamPiece(content="world")
            yield CodexStreamPiece(done=True, finish_reason="stop")

        with (
            patch.object(
                connector, "_acquire_runtime", AsyncMock(return_value=runtime)
            ),
            patch.object(
                connector,
                "_prepare_turn_request_locked",
                AsyncMock(return_value=(1, "auto")),
            ),
            patch.object(
                connector, "_iter_codex_stream_pieces", side_effect=_fake_iter
            ),
        ):
            response = await connector.chat_completions(_make_request())

        assert isinstance(response, ResponseEnvelope)
        assert response.status_code == 200
        # Lock released by the outer finally.
        assert runtime.request_lock is not None
        assert not runtime.request_lock.locked()

    async def test_non_streaming_no_double_release_on_cancel(
        self,
        connector: OpenAICodexAppServerConnector,
        temp_workspace: Path,
    ) -> None:
        """Cancel-during-non-streaming must not double-release the lock.

        Simulates the race: while the non-streaming stream iterator is "in
        flight", the cancel callback (``_cancel_active_request``) releases
        ``request_lock`` first. The outer finally in ``chat_completions`` then
        calls the idempotent ``_release_runtime_request_lock`` -- a no-op when
        the lock is not held -- instead of ``lock.release()`` which would raise
        ``RuntimeError: Lock is not acquired``.
        """
        connector.is_functional = True
        connector._default_project_dir = temp_workspace
        runtime = _make_runtime(temp_workspace, model="auto", thread_id="thr_1")
        iter_started = asyncio.Event()
        iter_proceed = asyncio.Event()

        async def _fake_iter(
            _runtime: CodexAppServerRuntime,
            _turn_id: int,
            _model: str,
        ) -> AsyncGenerator[CodexStreamPiece, None]:
            # Signal that we are inside the iterator (lock is held by the
            # non-streaming branch at this point).
            iter_started.set()
            # Simulate the cancel callback firing during the turn: a real
            # ``_cancel_active_request`` sets ``cancellation_event`` and ends
            # by calling ``_release_runtime_request_lock(runtime)``.
            if runtime.cancellation_event is not None:
                runtime.cancellation_event.set()
            await connector._release_runtime_request_lock(runtime)
            # Wait for the test harness to let us proceed; this guarantees the
            # cancel release happened while the non-streaming branch still held
            # the outer try/finally scope.
            await iter_proceed.wait()
            # Yield a stop piece so chat_completions builds a normal response.
            yield CodexStreamPiece(done=True, finish_reason="stop")

        with (
            patch.object(
                connector, "_acquire_runtime", AsyncMock(return_value=runtime)
            ),
            patch.object(
                connector,
                "_prepare_turn_request_locked",
                AsyncMock(return_value=(1, "auto")),
            ),
            patch.object(
                connector, "_iter_codex_stream_pieces", side_effect=_fake_iter
            ),
            patch.object(connector, "_schedule_stale_kill_after_turn", AsyncMock()),
        ):
            chat_task = asyncio.create_task(connector.chat_completions(_make_request()))
            await asyncio.wait_for(iter_started.wait(), timeout=5.0)
            # The iterator has released the lock already. Let it proceed and
            # yield the stop piece; chat_completions then runs its finally.
            iter_proceed.set()
            response = await asyncio.wait_for(chat_task, timeout=10.0)

        assert isinstance(response, ResponseEnvelope)
        assert response.status_code == 200
        # No RuntimeError was raised (the test would have failed above) and the
        # lock ends up unlocked (released by the iterator, no-op'd by finally).
        assert runtime.request_lock is not None
        assert not runtime.request_lock.locked()

    async def test_release_runtime_request_lock_is_idempotent(
        self,
        connector: OpenAICodexAppServerConnector,
        temp_workspace: Path,
    ) -> None:
        """Directly verify ``_release_runtime_request_lock`` is a no-op when
        the lock is not held, so a second call after release cannot raise."""
        runtime = _make_runtime(temp_workspace, model="auto", stdout_lines=[])
        assert runtime.request_lock is not None
        await runtime.request_lock.acquire()
        assert runtime.request_lock.locked()
        await connector._release_runtime_request_lock(runtime)
        assert not runtime.request_lock.locked()
        # Second call must be a no-op (no RuntimeError).
        await connector._release_runtime_request_lock(runtime)
        assert not runtime.request_lock.locked()

    async def test_non_streaming_skips_release_when_cancellation_in_progress(
        self,
        connector: OpenAICodexAppServerConnector,
        temp_workspace: Path,
    ) -> None:
        """Part B (non-streaming): the outer finally in ``chat_completions``
        must SKIP releasing ``request_lock`` while ``cancellation_event`` is
        set, so a follow-up request cannot acquire the lock against a
        half-torn-down subprocess. ``_cancel_active_request`` owns the release
        in its finally (Part A) once teardown completes.
        """
        connector.is_functional = True
        connector._default_project_dir = temp_workspace
        runtime = _make_runtime(temp_workspace, model="auto", thread_id="thr_1")
        # Simulate cancellation in progress: the event is set.
        assert runtime.cancellation_event is not None
        runtime.cancellation_event.set()

        async def _fake_iter(
            _runtime: CodexAppServerRuntime,
            _turn_id: int,
            _model: str,
        ) -> AsyncGenerator[CodexStreamPiece, None]:
            # Yield nothing; simulates _iter_codex_stream_pieces exiting
            # immediately on cancellation_event being set.
            return
            yield  # pragma: no cover - makes this an async generator

        with (
            patch.object(
                connector, "_acquire_runtime", AsyncMock(return_value=runtime)
            ),
            patch.object(
                connector,
                "_prepare_turn_request_locked",
                AsyncMock(return_value=(1, "auto")),
            ),
            patch.object(
                connector, "_iter_codex_stream_pieces", side_effect=_fake_iter
            ),
            patch.object(connector, "_schedule_stale_kill_after_turn", AsyncMock()),
        ):
            response = await connector.chat_completions(_make_request())

        assert isinstance(response, ResponseEnvelope)
        assert response.status_code == 200
        # Outer finally SKIPPED the release because cancellation is in
        # progress -- the lock stays held until _cancel_active_request
        # releases it (Part A). This is the race fix.
        assert runtime.request_lock is not None
        assert runtime.request_lock.locked()
        # The event is still set (the non-streaming finally does not clear it;
        # _cancel_active_request owns clearing it in its finally).
        assert runtime.cancellation_event.is_set()


# ---------------------------------------------------------------------------
# FIX 1 (streaming): SSE done chunk maps interrupted/error to stop
# ---------------------------------------------------------------------------


class TestStreamingFinishReasonMapping:
    """Streaming SSE must never emit non-OpenAI finish_reason values."""

    @staticmethod
    def _parse_finish_reason(sse: str) -> str | None:
        assert sse.startswith("data: {")
        payload = sse[len("data: ") :].strip()
        data = json.loads(payload)
        choices = data.get("choices")
        assert isinstance(choices, list) and choices
        return cast("str | None", choices[0].get("finish_reason"))

    def test_create_sse_chunk_maps_interrupted_to_stop(
        self, connector: OpenAICodexAppServerConnector
    ) -> None:
        piece = CodexStreamPiece(done=True, finish_reason="interrupted")
        sse = connector._create_sse_chunk_from_piece(piece, "auto", "chunk-1")
        assert sse is not None
        assert self._parse_finish_reason(sse) == "stop"

    def test_create_sse_chunk_maps_error_to_stop(
        self, connector: OpenAICodexAppServerConnector
    ) -> None:
        piece = CodexStreamPiece(done=True, finish_reason="error")
        sse = connector._create_sse_chunk_from_piece(piece, "auto", "chunk-1")
        assert sse is not None
        assert self._parse_finish_reason(sse) == "stop"

    def test_create_sse_chunk_stop_passes_through(
        self, connector: OpenAICodexAppServerConnector
    ) -> None:
        piece = CodexStreamPiece(done=True, finish_reason="stop")
        sse = connector._create_sse_chunk_from_piece(piece, "auto", "chunk-1")
        assert sse is not None
        assert self._parse_finish_reason(sse) == "stop"

    async def test_stream_response_emits_stop_for_interrupted_turn(
        self,
        connector: OpenAICodexAppServerConnector,
        temp_workspace: Path,
    ) -> None:
        connector._progress_mode = "text_only"
        runtime = _make_runtime(
            temp_workspace,
            model="auto",
            stdout_lines=[
                b'{"jsonrpc":"2.0","id":1,"result":{"turn":{"id":"t1"}}}\n',
                b'{"jsonrpc":"2.0","method":"turn/completed",'
                b'"params":{"turn":{"status":"interrupted"}}}\n',
            ],
            thread_id="thr_1",
        )
        connector._process_timeout = 5.0

        chunks: list[str] = []
        async for processed in connector._stream_response(runtime, "auto", 1):
            assert isinstance(processed.content, str)
            chunks.append(processed.content)

        data_chunks = [
            c for c in chunks if c.startswith("data: {") and "[DONE]" not in c
        ]
        finish_chunks = [c for c in data_chunks if '"finish_reason"' in c]
        assert len(finish_chunks) == 1
        assert self._parse_finish_reason(finish_chunks[0]) == "stop"
        assert chunks[-1] == "data: [DONE]\n\n"

    async def test_stream_response_emits_stop_for_failed_turn(
        self,
        connector: OpenAICodexAppServerConnector,
        temp_workspace: Path,
    ) -> None:
        connector._progress_mode = "text_only"
        runtime = _make_runtime(
            temp_workspace,
            model="auto",
            stdout_lines=[
                b'{"jsonrpc":"2.0","id":1,"result":{"turn":{"id":"t1"}}}\n',
                b'{"jsonrpc":"2.0","method":"turn/completed",'
                b'"params":{"turn":{"status":"failed"}}}\n',
            ],
            thread_id="thr_1",
        )
        connector._process_timeout = 5.0

        chunks: list[str] = []
        async for processed in connector._stream_response(runtime, "auto", 1):
            assert isinstance(processed.content, str)
            chunks.append(processed.content)

        data_chunks = [
            c for c in chunks if c.startswith("data: {") and "[DONE]" not in c
        ]
        finish_chunks = [c for c in data_chunks if '"finish_reason"' in c]
        assert len(finish_chunks) == 1
        assert self._parse_finish_reason(finish_chunks[0]) == "stop"
        assert chunks[-1] == "data: [DONE]\n\n"


# ---------------------------------------------------------------------------
# FIX 2: history_state commit deferred until turn/start is accepted
# ---------------------------------------------------------------------------


class TestHistoryStateCommit:
    """history_state must advance ONLY when Codex accepts the turn."""

    async def test_history_state_not_set_in_prepare(
        self,
        connector: OpenAICodexAppServerConnector,
        temp_workspace: Path,
    ) -> None:
        messages = [ChatMessage(role="user", content="hello")]
        runtime = _make_runtime(
            temp_workspace,
            model="auto",
            stdout_lines=[
                b'{"jsonrpc":"2.0","id":1,"result":{"turn":{"id":"turn_1"}}}\n',
            ],
            thread_id="thr_1",
        )
        runtime.initialized = True
        runtime.history_state = None

        with (
            patch.object(connector, "_cancel_stale_kill_timer", AsyncMock()),
            patch.object(connector, "_spawn_process", AsyncMock()),
            patch.object(connector, "_perform_handshake", AsyncMock()),
        ):
            await connector._prepare_turn_request_locked(
                runtime,
                _make_request(processed_messages=messages, model="openai/auto"),
            )

        # history_state unchanged (still None); pending holds the new state.
        assert runtime.history_state is None
        assert runtime.pending_history_state is not None
        assert runtime.pending_history_state.message_count == 1
        assert (
            runtime.pending_history_state.prefix_hash
            == _hash_chat_messages_prefix_stable(messages, 1)
        )

    async def test_history_state_committed_on_turn_completed(
        self,
        connector: OpenAICodexAppServerConnector,
        temp_workspace: Path,
    ) -> None:
        connector._progress_mode = "text_only"
        runtime = _make_runtime(
            temp_workspace,
            model="auto",
            stdout_lines=[
                b'{"jsonrpc":"2.0","id":7,"result":{"turn":{"id":"turn_ok"}}}\n',
                b'{"jsonrpc":"2.0","method":"turn/completed",'
                b'"params":{"turn":{"status":"completed"}}}\n',
            ],
            thread_id="thr_1",
        )
        connector._process_timeout = 5.0
        pending = HistoryState(message_count=2, prefix_hash="abc")
        runtime.history_state = None
        runtime.pending_history_state = pending

        pieces: list[CodexStreamPiece] = []
        async for piece in connector._iter_codex_stream_pieces(runtime, 7, "auto"):
            pieces.append(piece)

        # turn/start acceptance does NOT commit; the commit happens only when
        # the terminal turn/completed(completed) notification arrives.
        assert runtime.turn_id == "turn_ok"
        assert runtime.history_state is pending
        assert runtime.pending_history_state is None
        assert any(p.done for p in pieces)

    async def test_history_state_not_committed_on_turn_start_error(
        self,
        connector: OpenAICodexAppServerConnector,
        temp_workspace: Path,
    ) -> None:
        runtime = _make_runtime(
            temp_workspace,
            model="auto",
            stdout_lines=[
                b'{"jsonrpc":"2.0","id":9,"error":'
                b'{"code":-32000,"message":"turn rejected"}}\n',
            ],
            thread_id="thr_1",
        )
        connector._process_timeout = 5.0
        prior_state = HistoryState(message_count=1, prefix_hash="prior")
        pending = HistoryState(message_count=2, prefix_hash="abc")
        runtime.history_state = prior_state
        runtime.pending_history_state = pending

        with pytest.raises(BackendError, match="Codex process error"):
            async for _ in connector._iter_codex_stream_pieces(runtime, 9, "auto"):
                pass

        # turn/start rejected -> history_state unchanged, pending discarded.
        assert runtime.history_state is prior_state
        assert runtime.pending_history_state is None

    async def test_history_state_not_committed_on_interrupted_turn(
        self,
        connector: OpenAICodexAppServerConnector,
        temp_workspace: Path,
    ) -> None:
        """An interrupted turn must NOT commit pending_history_state.

        Queues turn/start ok + turn/completed(status interrupted). The
        interrupted finish_reason discards the pending state so a client retry
        hits the correct branch (history_state keeps its prior value).
        """
        connector._progress_mode = "text_only"
        runtime = _make_runtime(
            temp_workspace,
            model="auto",
            stdout_lines=[
                b'{"jsonrpc":"2.0","id":7,"result":{"turn":{"id":"turn_int"}}}\n',
                b'{"jsonrpc":"2.0","method":"turn/completed",'
                b'"params":{"turn":{"status":"interrupted"}}}\n',
            ],
            thread_id="thr_1",
        )
        connector._process_timeout = 5.0
        prior_state = HistoryState(message_count=1, prefix_hash="prior")
        pending = HistoryState(message_count=2, prefix_hash="abc")
        runtime.history_state = prior_state
        runtime.pending_history_state = pending

        pieces: list[CodexStreamPiece] = []
        async for piece in connector._iter_codex_stream_pieces(runtime, 7, "auto"):
            pieces.append(piece)

        # turn_id captured, but interrupted -> pending discarded, history_state
        # keeps its prior value.
        assert runtime.turn_id == "turn_int"
        assert runtime.history_state is prior_state
        assert runtime.pending_history_state is None
        assert any(p.done for p in pieces)
        done_piece = next(p for p in pieces if p.done)
        assert done_piece.finish_reason == "interrupted"

    async def test_history_state_not_committed_on_failed_turn(
        self,
        connector: OpenAICodexAppServerConnector,
        temp_workspace: Path,
    ) -> None:
        """A failed turn (turn/completed status failed) must NOT commit pending.

        Mirrors the interrupted-turn test but for the ``failed`` status path
        (finish_reason ``error``). pending is discarded so a client retry
        resends the correct transcript.
        """
        connector._progress_mode = "text_only"
        runtime = _make_runtime(
            temp_workspace,
            model="auto",
            stdout_lines=[
                b'{"jsonrpc":"2.0","id":7,"result":{"turn":{"id":"turn_fail"}}}\n',
                b'{"jsonrpc":"2.0","method":"turn/completed",'
                b'"params":{"turn":{"status":"failed"}}}\n',
            ],
            thread_id="thr_1",
        )
        connector._process_timeout = 5.0
        prior_state = HistoryState(message_count=1, prefix_hash="prior")
        pending = HistoryState(message_count=2, prefix_hash="abc")
        runtime.history_state = prior_state
        runtime.pending_history_state = pending

        pieces: list[CodexStreamPiece] = []
        async for piece in connector._iter_codex_stream_pieces(runtime, 7, "auto"):
            pieces.append(piece)

        assert runtime.turn_id == "turn_fail"
        assert runtime.history_state is prior_state
        assert runtime.pending_history_state is None
        done_piece = next(p for p in pieces if p.done)
        assert done_piece.finish_reason == "error"

    async def test_unknown_status_does_not_commit_history(
        self,
        connector: OpenAICodexAppServerConnector,
        temp_workspace: Path,
    ) -> None:
        """Bugbot FIX: an unrecognized/empty turn status must NOT commit
        pending_history_state. The mapper maps an unknown status to ``error``
        (fail closed), so the ``_iter_codex_stream_pieces`` commit check
        (``finish_reason == "stop"``) is False -> pending discarded,
        history_state keeps its prior value -> a client retry hits the
        correct branch.
        """
        connector._progress_mode = "text_only"
        runtime = _make_runtime(
            temp_workspace,
            model="auto",
            stdout_lines=[
                b'{"jsonrpc":"2.0","id":7,"result":{"turn":{"id":"turn_unk"}}}\n',
                b'{"jsonrpc":"2.0","method":"turn/completed",'
                b'"params":{"turn":{"status":""}}}\n',
            ],
            thread_id="thr_1",
        )
        connector._process_timeout = 5.0
        prior_state = HistoryState(message_count=1, prefix_hash="prior")
        pending = HistoryState(message_count=2, prefix_hash="abc")
        runtime.history_state = prior_state
        runtime.pending_history_state = pending

        pieces: list[CodexStreamPiece] = []
        async for piece in connector._iter_codex_stream_pieces(runtime, 7, "auto"):
            pieces.append(piece)

        assert runtime.turn_id == "turn_unk"
        assert runtime.history_state is prior_state
        assert runtime.pending_history_state is None
        done_piece = next(p for p in pieces if p.done)
        assert done_piece.finish_reason == "error"

    async def test_failed_turn_then_retry_sends_full_transcript(
        self,
        connector: OpenAICodexAppServerConnector,
        temp_workspace: Path,
    ) -> None:
        """Core Bugbot scenario: a failed first turn must not corrupt the
        retry path. history_state stays None so the retry resends the FULL
        transcript instead of just the last user line.
        """
        messages = [
            ChatMessage(role="system", content="You are helpful."),
            ChatMessage(role="user", content="first question"),
            ChatMessage(role="assistant", content="first answer"),
            ChatMessage(role="user", content="second question"),
        ]
        runtime = _make_runtime(
            temp_workspace,
            model="auto",
            stdout_lines=[],
            thread_id="thr_1",
        )
        runtime.initialized = True
        runtime.history_state = None

        # First prepare: first-turn path, state None -> full transcript staged
        # as pending. turn/start is NOT consumed here (prepare returns after
        # the send), so history_state stays None.
        with (
            patch.object(connector, "_cancel_stale_kill_timer", AsyncMock()),
            patch.object(connector, "_spawn_process", AsyncMock()),
            patch.object(connector, "_perform_handshake", AsyncMock()),
        ):
            await connector._prepare_turn_request_locked(
                runtime,
                _make_request(processed_messages=messages, model="openai/auto"),
            )

        # Simulate the stream iterator seeing a turn/start ERROR response:
        # pending is discarded, history_state stays None.
        assert runtime.history_state is None
        assert runtime.pending_history_state is not None
        runtime.pending_history_state = None  # discarded by the error path

        # Second prepare (retry) with the SAME messages: history_state is still
        # None -> first-turn path again -> full transcript resent (NOT the
        # idempotent last-user-line path).
        with (
            patch.object(connector, "_cancel_stale_kill_timer", AsyncMock()),
            patch.object(connector, "_spawn_process", AsyncMock()),
            patch.object(connector, "_perform_handshake", AsyncMock()),
        ):
            await connector._prepare_turn_request_locked(
                runtime,
                _make_request(processed_messages=messages, model="openai/auto"),
            )

        assert _last_turn_start_input_text(runtime) == (
            ACPTranscriptSerializer.serialize(messages)
        )
        assert runtime.history_state is None
        assert runtime.pending_history_state is not None
        assert runtime.pending_history_state.message_count == len(messages)


# ---------------------------------------------------------------------------
# FIX 3: handshake failure kills the runtime so the next request respawns
# ---------------------------------------------------------------------------


class TestHandshakeFailureKillsRuntime:
    """A failed handshake must terminate the child + clear process state."""

    async def test_initial_handshake_failure_kills_runtime(
        self,
        connector: OpenAICodexAppServerConnector,
        temp_workspace: Path,
    ) -> None:
        runtime = _make_runtime(
            temp_workspace,
            model="auto",
            stdout_lines=[],
            thread_id=None,
        )
        runtime.initialized = False
        # Pretend spawn produced a live process.
        spawn_mock = AsyncMock()
        kill_mock = AsyncMock()
        handshake_mock = AsyncMock(side_effect=BackendError(message="handshake boom"))

        with (
            patch.object(connector, "_cancel_stale_kill_timer", AsyncMock()),
            patch.object(connector, "_spawn_process", spawn_mock),
            patch.object(connector, "_perform_handshake", handshake_mock),
            patch.object(connector, "_kill_runtime", kill_mock),
            pytest.raises(BackendError, match="handshake boom"),
        ):
            await connector._prepare_turn_request_locked(
                runtime,
                _make_request(
                    processed_messages=[ChatMessage(role="user", content="hi")],
                    model="openai/auto",
                ),
            )

        # spawn ran, then handshake raised, then kill ran before re-raise.
        spawn_mock.assert_awaited_once()
        handshake_mock.assert_awaited_once()
        kill_mock.assert_awaited_once()

    async def test_divergence_handshake_failure_kills_runtime(
        self,
        connector: OpenAICodexAppServerConnector,
        temp_workspace: Path,
    ) -> None:
        messages = [ChatMessage(role="user", content="diverged question")]
        runtime = _make_runtime(
            temp_workspace,
            model="auto",
            stdout_lines=[],
            thread_id="thr_1",
        )
        runtime.initialized = True
        # Diverged state -> divergence path (kill + spawn + handshake).
        runtime.history_state = HistoryState(message_count=5, prefix_hash="bogus")

        spawn_mock = AsyncMock()
        kill_mock = AsyncMock()
        handshake_mock = AsyncMock(side_effect=BackendError(message="hs fail"))

        with (
            patch.object(connector, "_cancel_stale_kill_timer", AsyncMock()),
            patch.object(connector, "_spawn_process", spawn_mock),
            patch.object(connector, "_perform_handshake", handshake_mock),
            patch.object(connector, "_kill_runtime", kill_mock),
            pytest.raises(BackendError, match="hs fail"),
        ):
            await connector._prepare_turn_request_locked(
                runtime,
                _make_request(processed_messages=messages, model="openai/auto"),
            )

        # Divergence kill (1) + handshake-failure kill (1) = 2 kills total.
        assert kill_mock.await_count == 2
        # spawn: once at top, once after divergence kill = 2.
        assert spawn_mock.await_count == 2
        # handshake attempted once (the divergence-path one).
        handshake_mock.assert_awaited_once()
