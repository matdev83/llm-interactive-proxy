from __future__ import annotations

import asyncio
from collections.abc import AsyncGenerator
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from src.connectors.acp_core.base_connector import BaseAcpConnector
from src.connectors.acp_core.types import ACPNotification, ACPProcessRuntime
from src.connectors.acp_core.types import AcpStreamPiece as AcpStreamPiece
from src.connectors.contracts import (
    ConnectorChatCompletionsRequest,
    ConnectorRequestContext,
)
from src.core.domain.chat import CanonicalChatRequest, ChatMessage
from src.core.domain.responses import ResponseEnvelope


class DummyAcpConnector(BaseAcpConnector):
    backend_type = "dummy-acp"
    VENDOR_PREFIX = "dummy"

    async def _build_acp_command(self, runtime: ACPProcessRuntime) -> list[str]:
        return ["dummy", "acp"]

    async def _perform_handshake(self, runtime: ACPProcessRuntime) -> None:
        runtime.session_id = "dummy-session"
        runtime.initialized = True

    async def _handle_server_request(
        self, runtime: ACPProcessRuntime, msg: ACPNotification
    ) -> None:
        pass

    def get_available_models(self) -> list[str]:
        return ["dummy/model"]

    async def initialize(self, **kwargs: Any) -> None:
        self._default_project_dir = Path("/tmp/dummy")
        self.is_functional = True


def _make_request(
    stream: bool = False,
    with_history: bool = False,
    *,
    messages: list[ChatMessage] | None = None,
    session_id: str | None = None,
) -> ConnectorChatCompletionsRequest:
    resolved_messages = messages or (
        [
            ChatMessage(role="system", content="You are a helpful assistant."),
            ChatMessage(role="user", content="What is 2+2?"),
            ChatMessage(role="assistant", content="4"),
            ChatMessage(role="user", content="hello"),
        ]
        if with_history
        else [ChatMessage(role="user", content="hello")]
    )

    request = CanonicalChatRequest(
        model="dummy/model",
        stream=stream,
        messages=resolved_messages,
    )
    context: ConnectorRequestContext | None = None
    if session_id is not None:
        context = ConnectorRequestContext(
            request_id=None, session_id=session_id, client_host=None
        )
    return ConnectorChatCompletionsRequest(
        request=request,
        processed_messages=resolved_messages,
        effective_model="dummy/model",
        identity=None,
        cancellation_token=None,
        cancellation_coordinator=None,
        context=context,
        options={},
    )


@pytest.fixture
def connector() -> DummyAcpConnector:
    return DummyAcpConnector(MagicMock(), MagicMock())


def test_resolve_stream_keepalive_interval_default(
    connector: DummyAcpConnector,
) -> None:
    assert connector._resolve_stream_keepalive_interval() == 12.0


def test_session_update_thought_maps_to_reasoning_piece(
    connector: DummyAcpConnector,
) -> None:
    msg = ACPNotification(
        method="session/update",
        params={
            "sessionId": "s1",
            "update": {
                "sessionUpdate": "agent_thought_chunk",
                "content": {"type": "text", "text": "planning step"},
            },
        },
    )
    piece = connector._session_update_to_stream_piece(msg)
    assert piece == AcpStreamPiece(reasoning_content="planning step")


def test_session_update_tool_call_maps_to_progress_piece(
    connector: DummyAcpConnector,
) -> None:
    msg = ACPNotification(
        method="session/update",
        params={
            "sessionId": "s1",
            "update": {
                "sessionUpdate": "tool_call",
                "toolCall": {"name": "read_file"},
            },
        },
    )
    piece = connector._session_update_to_stream_piece(msg)
    assert piece == AcpStreamPiece(reasoning_content="[tool] read_file\n")


def test_resolve_stream_keepalive_interval_from_config(
    connector: DummyAcpConnector,
) -> None:
    fh = MagicMock()
    fh.keepalive_interval = 7.5
    connector.config = MagicMock()
    connector.config.failure_handling = fh
    assert connector._resolve_stream_keepalive_interval() == 7.5


def test_build_runtime_key_includes_client_session_id(
    connector: DummyAcpConnector,
) -> None:
    key = connector._build_runtime_key(Path("/tmp/ws"), "my-model", "client-42")
    assert key == (str(Path("/tmp/ws")), "my-model", "client-42")


def test_resolve_client_session_id_defaults(connector: DummyAcpConnector) -> None:
    req = _make_request()
    assert connector._resolve_client_session_id(req) == "default"


def test_resolve_client_session_id_from_context(connector: DummyAcpConnector) -> None:
    req = _make_request(session_id="  abc  ")
    assert connector._resolve_client_session_id(req) == "abc"


@pytest.mark.asyncio
async def test_acquire_runtime_isolates_per_client_session(
    connector: DummyAcpConnector,
) -> None:
    connector._default_project_dir = Path("/tmp/dummy")
    ra = await connector._acquire_runtime(_make_request(session_id="s-a"))
    rb = await connector._acquire_runtime(_make_request(session_id="s-b"))
    assert ra is not rb
    assert ra.client_session_id == "s-a"
    assert rb.client_session_id == "s-b"
    assert len(connector._runtimes) == 2


@pytest.mark.asyncio
async def test_prepare_prompt_first_turn_serializes_full_transcript(
    connector: DummyAcpConnector,
) -> None:
    connector._default_project_dir = Path("/tmp/dummy")
    runtime = connector._create_runtime(Path("/tmp/dummy"), "model")
    runtime.process = MagicMock()
    runtime.process.stdin = MagicMock()
    runtime.process.stdout = MagicMock()

    assert runtime.history_state is None

    with (
        patch.object(connector, "_spawn_process", AsyncMock()),
        patch.object(
            connector, "_send_jsonrpc_message", AsyncMock(return_value=1)
        ) as send_mock,
    ):
        await connector._prepare_prompt_request_locked(
            runtime, _make_request(with_history=True)
        )

    assert runtime.history_state is not None
    assert runtime.history_state.message_count == 4
    sent_params = send_mock.call_args[0][2]
    assert "System Note:" in sent_params["prompt"][0]["text"]


@pytest.mark.asyncio
async def test_prepare_prompt_incremental_tail_after_non_acp_turns(
    connector: DummyAcpConnector,
) -> None:
    connector._default_project_dir = Path("/tmp/dummy")
    runtime = connector._create_runtime(Path("/tmp/dummy"), "model")
    runtime.process = MagicMock()
    runtime.process.stdin = MagicMock()
    runtime.process.stdout = MagicMock()

    base = [
        ChatMessage(role="user", content="first"),
        ChatMessage(role="assistant", content="ack"),
    ]
    extended = [
        *base,
        ChatMessage(role="user", content="from other model"),
        ChatMessage(role="assistant", content="external reply"),
        ChatMessage(role="user", content="back to acp"),
    ]

    with (
        patch.object(connector, "_spawn_process", AsyncMock()),
        patch.object(
            connector, "_send_jsonrpc_message", AsyncMock(return_value=1)
        ) as send_mock,
    ):
        await connector._prepare_prompt_request_locked(
            runtime, _make_request(messages=base)
        )
        assert runtime.history_state is not None
        assert runtime.history_state.message_count == 2

        await connector._prepare_prompt_request_locked(
            runtime, _make_request(messages=extended)
        )

    assert runtime.history_state.message_count == 5
    last_text = send_mock.call_args[0][2]["prompt"][0]["text"]
    assert "Additional conversation occurred" in last_text
    assert "from other model" in last_text
    assert "back to acp" in last_text


@pytest.mark.asyncio
async def test_prepare_prompt_diverged_prefix_resets_and_reserializes_full(
    connector: DummyAcpConnector,
) -> None:
    connector._default_project_dir = Path("/tmp/dummy")
    runtime = connector._create_runtime(Path("/tmp/dummy"), "model")
    runtime.process = MagicMock()
    runtime.process.stdin = MagicMock()
    runtime.process.stdout = MagicMock()

    messages_v1 = [
        ChatMessage(role="user", content="q1"),
        ChatMessage(role="assistant", content="a1"),
        ChatMessage(role="user", content="q2"),
    ]
    messages_v2 = [
        ChatMessage(role="user", content="q1-edited"),
        ChatMessage(role="assistant", content="a1"),
        ChatMessage(role="user", content="q2"),
    ]

    with (
        patch.object(connector, "_spawn_process", AsyncMock()),
        patch.object(
            connector, "_send_jsonrpc_message", AsyncMock(return_value=1)
        ) as send_mock,
        patch.object(connector, "_kill_runtime", AsyncMock()) as kill_mock,
    ):
        await connector._prepare_prompt_request_locked(
            runtime, _make_request(messages=messages_v1)
        )
        await connector._prepare_prompt_request_locked(
            runtime, _make_request(messages=messages_v2)
        )

    kill_mock.assert_awaited_once()
    last_text = send_mock.call_args[0][2]["prompt"][0]["text"]
    assert "q1-edited" in last_text
    assert "System Note: The user is continuing a previous session" in last_text


@pytest.mark.asyncio
async def test_prepare_prompt_same_length_retry_uses_last_user_only(
    connector: DummyAcpConnector,
) -> None:
    connector._default_project_dir = Path("/tmp/dummy")
    runtime = connector._create_runtime(Path("/tmp/dummy"), "model")
    runtime.process = MagicMock()
    runtime.process.stdin = MagicMock()
    runtime.process.stdout = MagicMock()
    msgs = [ChatMessage(role="user", content="ping")]

    with (
        patch.object(connector, "_spawn_process", AsyncMock()),
        patch.object(
            connector, "_send_jsonrpc_message", AsyncMock(return_value=1)
        ) as send_mock,
    ):
        await connector._prepare_prompt_request_locked(
            runtime, _make_request(messages=msgs)
        )
        hc = runtime.history_state.message_count if runtime.history_state else 0
        assert hc == 1
        await connector._prepare_prompt_request_locked(
            runtime, _make_request(messages=msgs)
        )

    last_text = send_mock.call_args[0][2]["prompt"][0]["text"]
    assert last_text == "ping"


def test_hash_messages_prefix_detects_edit(connector: DummyAcpConnector) -> None:
    a = [
        ChatMessage(role="user", content="x"),
        ChatMessage(role="assistant", content="y"),
    ]
    b = [
        ChatMessage(role="user", content="x-changed"),
        ChatMessage(role="assistant", content="y"),
    ]
    h1 = connector._hash_messages_prefix(a, 1)
    h2 = connector._hash_messages_prefix(b, 1)
    assert h1 != h2


def test_hash_messages_prefix_stable_ignores_metadata_only_changes(
    connector: DummyAcpConnector,
) -> None:
    a = [ChatMessage(role="user", content="hi", metadata={"a": 1})]
    b = [ChatMessage(role="user", content="hi", metadata={"b": 2})]
    assert connector._hash_messages_prefix(a, 1) == connector._hash_messages_prefix(
        b, 1
    )


@pytest.mark.asyncio
async def test_parallel_acquire_after_idle_reap_uses_same_pool_runtime(
    connector: DummyAcpConnector,
) -> None:
    connector._default_project_dir = Path("/tmp/dummy")
    connector._idle_timeout = 5.0
    rid = "sess-par"
    key = connector._build_runtime_key(Path("/tmp/dummy"), "model", rid)
    stale = connector._create_runtime(Path("/tmp/dummy"), "model", rid)
    stale.process = MagicMock()
    stale.process.poll.return_value = None
    stale.last_activity = 1.0
    async with connector._runtime_pool_lock:
        connector._runtimes[key] = stale

    with (
        patch(
            "src.connectors.acp_core.base_connector.time.monotonic",
            return_value=100.0,
        ),
        patch.object(connector, "_terminate_process", AsyncMock()),
    ):
        r1, r2 = await asyncio.gather(
            connector._acquire_runtime(_make_request(session_id=rid)),
            connector._acquire_runtime(_make_request(session_id=rid)),
        )

    assert r1 is r2
    assert r1 is not stale
    assert connector._runtimes[key] is r1


@pytest.mark.asyncio
async def test_kill_all_runtimes_next_acquire_creates_new_runtime_object(
    connector: DummyAcpConnector,
) -> None:
    connector._default_project_dir = Path("/tmp/dummy")
    r_before = await connector._acquire_runtime(_make_request(session_id="recycle"))
    await connector._kill_all_runtimes()
    assert len(connector._runtimes) == 0
    r_after = await connector._acquire_runtime(_make_request(session_id="recycle"))
    assert r_after is not r_before
    assert r_after.history_state is None


@pytest.mark.asyncio
async def test_non_streaming_chat_completions_preserve_reasoning_content(
    connector: DummyAcpConnector,
) -> None:
    connector.is_functional = True
    connector._default_project_dir = Path("/tmp/dummy")
    runtime = connector._create_runtime(Path("/tmp/dummy"), "dummy/model")

    async def _mock_iter(
        _: ACPProcessRuntime, __: int, ___: str
    ) -> AsyncGenerator[AcpStreamPiece, None]:
        yield AcpStreamPiece(reasoning_content="plan step\n")
        yield AcpStreamPiece(content="Answer")
        yield AcpStreamPiece(reasoning_content="tool finished\n")

    with (
        patch.object(connector, "_acquire_runtime", AsyncMock(return_value=runtime)),
        patch.object(
            connector,
            "_prepare_prompt_request_locked",
            AsyncMock(return_value=(5, "dummy/model")),
        ),
        patch.object(connector, "_iter_acp_stream_pieces", side_effect=_mock_iter),
    ):
        response = await connector.chat_completions(_make_request())

    assert isinstance(response, ResponseEnvelope)
    assert isinstance(response.content, dict)
    message = response.content["choices"][0]["message"]
    assert message["content"] == "Answer"
    assert message["reasoning_content"] == "plan step\ntool finished\n"
