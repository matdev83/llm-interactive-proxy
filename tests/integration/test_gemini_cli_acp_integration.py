from __future__ import annotations

import subprocess
from collections.abc import AsyncGenerator
from pathlib import Path

import httpx
import pytest
import pytest_asyncio
from src.connectors.contracts import ConnectorChatCompletionsRequest
from src.connectors.gemini_base.command_resolution import (
    build_gemini_cli_command,
    resolve_gemini_cli_executable,
)
from src.connectors.gemini_cli_acp import GeminiCliAcpConnector
from src.core.config.app_config import AppConfig
from src.core.domain.chat import CanonicalChatRequest, ChatMessage
from src.core.domain.responses import ResponseEnvelope, StreamingResponseEnvelope
from src.core.services.translation_service import TranslationService

pytestmark = [
    pytest.mark.integration,
    pytest.mark.network,
    pytest.mark.no_global_mock,
]

_OPT_IN_ENV_VAR = "RUN_GEMINI_CLI_ACP_INTEGRATION"
_ENABLED_VALUES = {"1", "true", "yes", "on"}


def _resolve_gemini_cli_executable() -> str | None:
    return resolve_gemini_cli_executable()


def _ensure_gemini_cli_available() -> str:
    executable = _resolve_gemini_cli_executable()
    if executable is None:
        pytest.skip("gemini CLI is not available on PATH.")

    try:
        result = subprocess.run(
            build_gemini_cli_command([executable, "--version"]),
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
    except (subprocess.TimeoutExpired, OSError):
        pytest.skip("gemini CLI is not callable from pytest.")

    if result.returncode != 0:
        pytest.skip("gemini CLI did not respond successfully to --version.")

    return executable


def _ensure_gemini_cli_authenticated() -> None:
    home = Path.home()
    candidates = (
        home / ".gemini" / "oauth_creds.json",
        home / ".gemini" / "oauth-credentials.json",
    )
    if not any(candidate.exists() for candidate in candidates):
        pytest.skip("gemini CLI is not authenticated.")


def _make_request(
    *,
    user_prompt: str,
    stream: bool,
    model: str = "google/gemini-2.5-flash",
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
async def live_connector(tmp_path: Path) -> AsyncGenerator[GeminiCliAcpConnector, None]:
    gemini_executable = _ensure_gemini_cli_available()
    _ensure_gemini_cli_authenticated()

    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / "README.md").write_text(
        "# Gemini ACP integration test\n\nThis workspace is used by a live pytest.\n",
        encoding="utf-8",
    )
    (workspace / "sample.py").write_text(
        "def smoke_test() -> str:\n    return 'gemini-acp'\n",
        encoding="utf-8",
    )

    client = httpx.AsyncClient()
    connector = GeminiCliAcpConnector(client, AppConfig(), TranslationService())
    await connector.initialize(
        workspace_path=str(workspace),
        gemini_cli_executable=gemini_executable,
        model="gemini-2.5-flash",
        auto_accept=True,
        process_timeout=180,
    )

    try:
        yield connector
    finally:
        await connector.shutdown()
        await client.aclose()


async def test_gemini_cli_acp_chat_completion_smoke(
    live_connector: GeminiCliAcpConnector,
) -> None:
    response = await live_connector.chat_completions(
        _make_request(
            user_prompt=(
                "Reply with a short acknowledgement that includes the word workspace."
            ),
            stream=False,
        )
    )

    assert isinstance(response, ResponseEnvelope)
    assert response.status_code == 200
    assert isinstance(response.content, dict)
    assert response.content["object"] == "chat.completion"
    assert response.content["choices"][0]["message"]["role"] == "assistant"
    content = response.content["choices"][0]["message"]["content"]
    assert isinstance(content, str) and content.strip()
    assert "workspace" in content.lower()


async def test_gemini_cli_acp_streaming_smoke(
    live_connector: GeminiCliAcpConnector,
) -> None:
    response = await live_connector.chat_completions(
        _make_request(
            user_prompt="List two short lines describing this workspace. Keep it brief.",
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
