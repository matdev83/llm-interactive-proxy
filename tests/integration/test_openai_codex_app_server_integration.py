"""End-to-end integration tests for the OpenAI Codex App Server connector.

These tests spawn the REAL Codex CLI (codex app-server over stdio) and exercise
the full connector lifecycle (handshake -> thread/start -> turn/start ->
streaming notifications -> turn/completed) with NO mocks or emulators. They are
strictly opt-in: set ``RUN_OPENAI_CODEX_APP_SERVER_INTEGRATION=1`` to run them.

A working Codex executable is resolved at collection time. If the default
``codex`` on PATH is a wrapper that already injects
``--dangerously-bypass-approvals-and-sandbox --search`` (which would collide
with the flags the connector sends), the resolver falls back to alternate
candidates (``CODEX_BIN`` env var, ``codex.cmd`` in the npm global bin, etc.)
and probes each one by performing a real ``initialize`` handshake. This mirrors
what the connector itself does and guarantees the e2e flow runs against a
genuine Codex app-server subprocess.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import os
import shutil
import subprocess
import time
from collections.abc import AsyncGenerator
from pathlib import Path
from typing import Any

import httpx
import pytest
import pytest_asyncio
from src.connectors.contracts import (
    ConnectorChatCompletionsRequest,
    ConnectorRequestContext,
)
from src.connectors.openai_codex_app_server import (
    OpenAICodexAppServerConnector,
    build_codex_app_server_command,
    resolve_codex_executable,
)
from src.core.config.app_config import AppConfig
from src.core.domain.chat import CanonicalChatRequest, ChatMessage
from src.core.domain.responses import ResponseEnvelope, StreamingResponseEnvelope
from src.core.services.translation_service import TranslationService

logger = logging.getLogger(__name__)

_OPT_IN_ENV_VAR = "RUN_OPENAI_CODEX_APP_SERVER_INTEGRATION"
_PROBE_TIMEOUT_SECONDS = 15.0
_APP_SERVER_PROBE_TIMEOUT_SECONDS = 30.0
_INITIALIZE_PROBE_LINE = (
    json.dumps(
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {
                "clientInfo": {"name": "proxy-e2e-probe", "version": "0"},
                # Must match the connector: runtimeWorkspaceRoots in thread/start
                # is gated behind the experimentalApi client capability on real
                # Codex app-servers.
                "capabilities": {"experimentalApi": True},
            },
        },
        separators=(",", ":"),
    )
    + "\n"
).encode("utf-8")


pytestmark = pytest.mark.skipif(
    os.environ.get(_OPT_IN_ENV_VAR, "").strip() not in ("1", "true", "True"),
    reason="Set RUN_OPENAI_CODEX_APP_SERVER_INTEGRATION=1 to run real Codex "
    "app-server e2e tests",
)


def _candidate_codex_exes() -> list[str]:
    """Build an ordered, de-duplicated list of codex executable candidates.

    Order: ``CODEX_BIN`` env var, then the connector's own resolver, then
    ``shutil.which`` for the common Windows shim names, then the npm global
    ``codex.cmd``. The first candidate that passes the version + app-server
    initialize probe wins.
    """

    raw: list[str] = []
    env_bin = os.environ.get("CODEX_BIN", "").strip()
    if env_bin:
        raw.append(env_bin)
    resolved = resolve_codex_executable(None)
    if resolved:
        raw.append(resolved)
    for name in ("codex", "codex.cmd", "codex.exe"):
        which = shutil.which(name)
        if which:
            raw.append(which)
    appdata = os.environ.get("APPDATA")
    if appdata:
        npm_cmd = os.path.join(appdata, "npm", "codex.cmd")
        if os.path.isfile(npm_cmd):
            raw.append(npm_cmd)

    seen: set[str] = set()
    unique: list[str] = []
    for candidate in raw:
        try:
            key = str(Path(candidate).resolve()).lower()
        except (OSError, RuntimeError):
            key = candidate.lower()
        if key in seen:
            continue
        seen.add(key)
        unique.append(candidate)
    return unique


def _codex_version_ok(exe: str) -> bool:
    try:
        result = subprocess.run(
            [exe, "--version"],
            capture_output=True,
            timeout=15,
            check=False,
            shell=False,
        )
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
        return False
    return result.returncode == 0


def _codex_app_server_initialize_ok(exe: str) -> bool:
    """Spawn the real app-server, send initialize, read one JSON-RPC line.

    Real Codex app-server responses omit the ``jsonrpc`` field (they return
    ``{"id":1,"result":{...}}``), so the probe only requires a valid JSON object
    carrying ``id`` plus a ``result`` or ``error`` payload. This is a deliberate,
    evidence-based deviation from a naive ``jsonrpc``-field check.
    """

    cmd = build_codex_app_server_command(exe)
    proc: subprocess.Popen[bytes] | None = None
    try:
        proc = subprocess.Popen(
            cmd,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            cwd=str(Path.cwd()),
            shell=False,
            env=os.environ.copy(),
            creationflags=(
                subprocess.CREATE_NEW_PROCESS_GROUP if os.name == "nt" else 0
            ),
        )
        time.sleep(0.3)
        if proc.poll() is not None:
            return False
        assert proc.stdin is not None
        proc.stdin.write(_INITIALIZE_PROBE_LINE)
        proc.stdin.flush()
        assert proc.stdout is not None
        deadline = time.monotonic() + _APP_SERVER_PROBE_TIMEOUT_SECONDS
        line: bytes | None = None
        while time.monotonic() < deadline:
            if proc.poll() is not None:
                return False
            candidate = proc.stdout.readline(10 * 1024 * 1024 + 1)
            if candidate:
                line = candidate
                break
            time.sleep(0.05)
        if not line:
            return False
        data = json.loads(line.decode("utf-8"))
        if not isinstance(data, dict):
            return False
        if "id" not in data:
            return False
        return "result" in data or "error" in data
    except Exception:
        return False
    finally:
        if proc is not None:
            _terminate_subprocess(proc)


def _terminate_subprocess(proc: subprocess.Popen[bytes]) -> None:
    try:
        if proc.poll() is None:
            if proc.stdin is not None:
                with contextlib.suppress(Exception):
                    proc.stdin.close()
            if os.name == "nt":
                subprocess.run(
                    ["taskkill", "/PID", str(proc.pid), "/T", "/F"],
                    capture_output=True,
                    check=False,
                    shell=False,
                )
            else:
                proc.terminate()
            with contextlib.suppress(subprocess.TimeoutExpired):
                proc.wait(timeout=5)
    finally:
        for stream in (proc.stdin, proc.stdout, proc.stderr):
            if stream is not None:
                with contextlib.suppress(OSError, ValueError):
                    stream.close()


def _resolve_codex_exe() -> str | None:
    """Return the first codex candidate that passes version + app-server probes."""

    for candidate in _candidate_codex_exes():
        if not _codex_version_ok(candidate):
            continue
        if _codex_app_server_initialize_ok(candidate):
            logger.debug("Resolved working codex executable: %s", candidate)
            return candidate
    return None


def _codex_available() -> bool:
    """True when a real Codex CLI responds to ``--version`` and app-server init."""

    return _resolve_codex_exe() is not None


def _make_streaming_request(
    project_dir: Path, user_text: str, model: str = "auto"
) -> ConnectorChatCompletionsRequest:
    return _make_request(project_dir, user_text, stream=True, model=model)


def _make_request(
    project_dir: Path,
    user_text: str,
    *,
    stream: bool,
    model: str = "auto",
) -> ConnectorChatCompletionsRequest:
    request = CanonicalChatRequest(
        model=model,
        stream=stream,
        messages=[ChatMessage(role="user", content=user_text)],
        extra_body={"project_dir": str(project_dir)},
    )
    return ConnectorChatCompletionsRequest(
        request=request,
        processed_messages=[ChatMessage(role="user", content=user_text)],
        effective_model=model,
        identity=None,
        cancellation_token=None,
        cancellation_coordinator=None,
        context=ConnectorRequestContext(
            request_id="e2e", session_id="e2e-session", client_host=None
        ),
        options={},
    )


@pytest_asyncio.fixture
async def connector(
    tmp_path: Path,
) -> AsyncGenerator[OpenAICodexAppServerConnector, None]:
    exe = _resolve_codex_exe()
    if exe is None:
        pytest.skip(
            "No working Codex app-server executable available (set CODEX_BIN or "
            "install codex on PATH)."
        )

    (tmp_path / "README.md").write_text("# codex e2e workspace\n", encoding="utf-8")

    client = httpx.AsyncClient()
    connector = OpenAICodexAppServerConnector(client, AppConfig(), TranslationService())
    await connector.initialize(
        model="auto",
        project_dir=str(tmp_path),
        codex_executable=exe,
        process_timeout=180,
        idle_timeout=120,
    )
    assert (
        connector.is_backend_functional()
    ), "connector did not initialize as functional"

    try:
        yield connector
    finally:
        await connector.shutdown()
        await client.aclose()


async def _collect_stream(content: Any) -> list[str]:
    chunks: list[str] = []
    async for item in content:
        chunk = item.content
        chunks.append(chunk if isinstance(chunk, str) else "")
    return chunks


def _extract_text_from_sse_chunks(chunks: list[str]) -> str:
    """Reassemble assistant-visible text from ``data: {…}`` SSE chunks.

    Codex streams the answer token-by-token (e.g. ``PRO`` | ``XY`` | ``_CODE`` …),
    so the phrase under test is split across many SSE chunks. A contiguous
    substring check on the raw joined stream would therefore miss it; instead we
    parse each JSON chunk and concatenate ``choices[0].delta.content``.
    """

    parts: list[str] = []
    for chunk in chunks:
        if not chunk.startswith("data: {") or "[DONE]" in chunk:
            continue
        payload = chunk[len("data: ") :].strip()
        try:
            data = json.loads(payload)
        except json.JSONDecodeError:
            continue
        choices = data.get("choices")
        if not isinstance(choices, list) or not choices:
            continue
        first = choices[0]
        if not isinstance(first, dict):
            continue
        delta = first.get("delta")
        if isinstance(delta, dict):
            content = delta.get("content")
            if isinstance(content, str):
                parts.append(content)
    return "".join(parts)


async def test_temp_workspace_smoke_streams_phrase_before_done(
    connector: OpenAICodexAppServerConnector,
    tmp_path: Path,
) -> None:
    request = _make_streaming_request(
        tmp_path,
        "Reply with exactly the phrase PROXY_CODEX_E2E_OK and nothing else.",
    )

    response = await asyncio.wait_for(
        connector.chat_completions(request), timeout=120.0
    )
    assert isinstance(response, StreamingResponseEnvelope)
    assert response.content is not None

    chunks = await asyncio.wait_for(_collect_stream(response.content), timeout=120.0)
    joined = "".join(chunks)
    streamed_text = _extract_text_from_sse_chunks(chunks)

    assert (
        "proxy_codex_e2e_ok" in streamed_text.lower()
    ), f"expected PROXY_CODEX_E2E_OK in reassembled stream text; got: {streamed_text!r}"
    assert joined.endswith(
        "data: [DONE]\n\n"
    ), f"stream did not end with [DONE]; last chunks: {chunks[-3:]!r}"
    data_payload_chunks = [
        c for c in chunks if c.startswith("data: {") and "[DONE]" not in c
    ]
    assert (
        len(data_payload_chunks) >= 1
    ), "expected at least one streamed data: { chunk before [DONE]"
    assert (
        connector.is_backend_functional()
    ), "connector not functional after smoke turn"


async def test_cancellation_recovers_for_next_request(
    connector: OpenAICodexAppServerConnector,
    tmp_path: Path,
) -> None:
    async def _run() -> None:
        long_request = _make_streaming_request(
            tmp_path,
            "Count slowly from 1 to 100, one number per line, pausing briefly "
            "between each number.",
        )
        envelope = await connector.chat_completions(long_request)
        assert isinstance(envelope, StreamingResponseEnvelope)
        assert envelope.content is not None
        stream_content = envelope.content

        collected: list[str] = []

        async def _consume() -> None:
            async for item in stream_content:
                chunk = item.content
                if isinstance(chunk, str):
                    collected.append(chunk)

        consume_task = asyncio.create_task(_consume())

        # Wait for at least one streamed chunk, or ~6s, whichever comes first.
        deadline = time.monotonic() + 6.0
        while time.monotonic() < deadline and not collected:
            await asyncio.sleep(0.1)

        # Trigger the real proxy cancellation path.
        assert envelope.cancel_callback is not None
        await envelope.cancel_callback()

        try:
            await asyncio.wait_for(consume_task, timeout=30.0)
        except asyncio.TimeoutError:
            consume_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await consume_task

        # The cancelled stream must still have terminated (either with [DONE]
        # from the finally, or by ending cleanly). It must not hang.
        assert consume_task.done()

        # Second request on the SAME connector must succeed -> runtime recovered.
        recovered_request = _make_streaming_request(
            tmp_path,
            "Reply with exactly the phrase PROXY_CODEX_E2E_RECOVERED and nothing else.",
        )
        second = await asyncio.wait_for(
            connector.chat_completions(recovered_request), timeout=120.0
        )
        assert isinstance(second, StreamingResponseEnvelope)
        assert second.content is not None
        second_chunks = await asyncio.wait_for(
            _collect_stream(second.content), timeout=120.0
        )
        joined = "".join(second_chunks)
        recovered_text = _extract_text_from_sse_chunks(second_chunks)
        assert (
            "proxy_codex_e2e_recovered" in recovered_text.lower()
        ), f"expected PROXY_CODEX_E2E_RECOVERED after cancellation; got: {recovered_text!r}"
        assert joined.endswith(
            "data: [DONE]\n\n"
        ), f"recovered stream did not end with [DONE]; last: {second_chunks[-3:]!r}"
        assert (
            connector.is_backend_functional()
        ), "connector not functional after cancellation + recovery"

    await asyncio.wait_for(_run(), timeout=150.0)


async def test_non_streaming_returns_accumulated_content(
    connector: OpenAICodexAppServerConnector,
    tmp_path: Path,
) -> None:
    request = _make_request(
        tmp_path,
        "Reply with exactly the phrase PROXY_CODEX_E2E_NONSTREAM and nothing else.",
        stream=False,
    )

    response = await asyncio.wait_for(
        connector.chat_completions(request), timeout=120.0
    )
    assert isinstance(response, ResponseEnvelope)
    assert response.status_code == 200
    assert isinstance(response.content, dict)
    message = response.content["choices"][0]["message"]
    content = message["content"]
    assert isinstance(content, str), f"expected str content, got {type(content)!r}"
    assert (
        "proxy_codex_e2e_nonstream" in content.lower()
    ), f"expected PROXY_CODEX_E2E_NONSTREAM in non-streaming content; got: {content!r}"
