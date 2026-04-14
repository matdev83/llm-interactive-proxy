from __future__ import annotations

import os
import subprocess
from collections.abc import AsyncGenerator
from pathlib import Path

import httpx
import pytest
import pytest_asyncio
from src.connectors.contracts import ConnectorChatCompletionsRequest
from src.connectors.cursor_cli_acp import (
    CursorCliAcpConnector,
    resolve_cursor_agent_executable,
)
from src.core.config.app_config import AppConfig
from src.core.domain.chat import CanonicalChatRequest, ChatMessage
from src.core.domain.responses import ResponseEnvelope, StreamingResponseEnvelope
from src.core.services.translation_service import TranslationService

pytestmark = [
    pytest.mark.integration,
    pytest.mark.network,
    pytest.mark.no_global_mock,
]

_OPT_IN_ENV_VAR = "RUN_CURSOR_CLI_ACP_INTEGRATION"
_ENABLED_VALUES = {"1", "true", "yes", "on"}


def _is_opted_in() -> bool:
    value = os.getenv(_OPT_IN_ENV_VAR, "")
    return value.strip().lower() in _ENABLED_VALUES


def _ensure_opted_in() -> None:
    if not _is_opted_in():
        pytest.skip(
            f"Set {_OPT_IN_ENV_VAR}=1 to run the live Cursor CLI ACP integration test."
        )


def _ensure_agent_available() -> str:
    exe = resolve_cursor_agent_executable(None)
    if exe is None:
        pytest.skip("Cursor CLI (agent) is not available on PATH.")

    try:
        result = subprocess.run(
            [exe, "--version"],
            capture_output=True,
            text=True,
            timeout=15,
            check=False,
        )
    except (subprocess.TimeoutExpired, OSError):
        pytest.skip("Cursor CLI is not callable from pytest.")

    if result.returncode != 0:
        pytest.skip("Cursor CLI did not respond successfully to --version.")

    return exe


def _make_request(
    *,
    user_prompt: str,
    stream: bool,
    model: str = "cursor/composer-2",
) -> ConnectorChatCompletionsRequest:
    request = CanonicalChatRequest(
        model=model,
        stream=stream,
        messages=[ChatMessage(role="user", content=user_prompt)],
    )
    return ConnectorChatCompletionsRequest(
        request=request,
        processed_messages=[ChatMessage(role="user", content=user_prompt)],
        effective_model=model,
        identity=None,
        cancellation_token=None,
        cancellation_coordinator=None,
        context=None,
        options={},
    )


@pytest_asyncio.fixture
async def live_connector(tmp_path: Path) -> AsyncGenerator[CursorCliAcpConnector, None]:
    _ensure_opted_in()
    agent_exe = _ensure_agent_available()

    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / "README.md").write_text(
        "# Cursor ACP integration test\n\nThis workspace is used by a live pytest.\n",
        encoding="utf-8",
    )

    client = httpx.AsyncClient()
    connector = CursorCliAcpConnector(client, AppConfig(), TranslationService())
    await connector.initialize(
        workspace_path=str(workspace),
        cursor_cli_executable=agent_exe,
        model="composer-2",
        auto_accept=True,
        trust_workspace=True,
        process_timeout=180,
    )

    try:
        yield connector
    finally:
        await connector.shutdown()
        await client.aclose()


async def test_cursor_cli_acp_chat_completion_smoke(
    live_connector: CursorCliAcpConnector,
) -> None:
    response = await live_connector.chat_completions(
        _make_request(
            user_prompt='Reply with exactly: "CURSOR_ACP_OK"',
            stream=False,
        )
    )

    assert isinstance(response, ResponseEnvelope)
    assert response.status_code == 200
    assert isinstance(response.content, dict)
    assert response.content["object"] == "chat.completion"
    assert response.content["choices"][0]["message"]["role"] == "assistant"
    content = response.content["choices"][0]["message"]["content"]
    assert isinstance(content, str) and "CURSOR_ACP_OK" in content


async def test_cursor_cli_acp_streaming_smoke(
    live_connector: CursorCliAcpConnector,
) -> None:
    response = await live_connector.chat_completions(
        _make_request(
            user_prompt="Say hello in one short sentence.",
            stream=True,
        )
    )

    assert isinstance(response, StreamingResponseEnvelope)
    assert response.content is not None

    chunks: list[str] = []
    async for item in response.content:
        assert isinstance(item.content, str)
        chunks.append(item.content)

    assert chunks
    assert chunks[-1] == "data: [DONE]\n\n"
    assert any("data: " in chunk for chunk in chunks[:-1])
