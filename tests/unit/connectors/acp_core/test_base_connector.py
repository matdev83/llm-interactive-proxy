from __future__ import annotations

import asyncio
from collections.abc import AsyncGenerator
from dataclasses import replace
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from src.connectors.acp_core.base_connector import BaseAcpConnector
from src.connectors.acp_core.types import ACPNotification, ACPProcessRuntime
from src.connectors.acp_core.types import AcpStreamPiece as AcpStreamPiece
from src.connectors.acp_core.workspace_policy import ACP_MISSING_PROJECT_WORKSPACE_CODE
from src.connectors.contracts import (
    ConnectorChatCompletionsRequest,
    ConnectorRequestContext,
)
from src.core.common.exceptions import BackendError
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


class StrictWorkspaceDummy(DummyAcpConnector):
    requires_explicit_workspace = True


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
    runtime = connector._create_runtime(Path("/tmp/ws"), "m")
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
    piece = connector._session_update_to_stream_piece(msg, runtime)
    assert piece == AcpStreamPiece(content="Thinking:\nplanning step")


def test_session_update_thought_prefers_text_delta_over_full_text(
    connector: DummyAcpConnector,
) -> None:
    runtime = connector._create_runtime(Path("/tmp/ws"), "m")
    msg = ACPNotification(
        method="session/update",
        params={
            "sessionId": "s1",
            "update": {
                "sessionUpdate": "agent_thought_chunk",
                "content": {
                    "type": "text",
                    "text": "cumulative snapshot",
                    "textDelta": "delta only",
                },
            },
        },
    )
    piece = connector._session_update_to_stream_piece(msg, runtime)
    assert piece == AcpStreamPiece(content="Thinking:\ndelta only")


def test_session_update_message_after_thought_closes_block(
    connector: DummyAcpConnector,
) -> None:
    runtime = connector._create_runtime(Path("/tmp/ws"), "m")
    first = ACPNotification(
        method="session/update",
        params={
            "sessionId": "s1",
            "update": {
                "sessionUpdate": "agent_thought_chunk",
                "content": {"type": "text", "text": "follow-up analysis"},
            },
        },
    )
    second = ACPNotification(
        method="session/update",
        params={
            "sessionId": "s1",
            "update": {
                "sessionUpdate": "agent_message_chunk",
                "content": {"type": "text", "text": "visible answer"},
            },
        },
    )
    piece1 = connector._session_update_to_stream_piece(first, runtime)
    piece2 = connector._session_update_to_stream_piece(second, runtime)
    assert piece1 == AcpStreamPiece(content="Thinking:\nfollow-up analysis")
    assert piece2 == AcpStreamPiece(content="\n\nvisible answer")


def test_session_update_consecutive_thought_chunks_append_without_reopening(
    connector: DummyAcpConnector,
) -> None:
    runtime = connector._create_runtime(Path("/tmp/ws"), "m")
    first = ACPNotification(
        method="session/update",
        params={
            "sessionId": "s1",
            "update": {
                "sessionUpdate": "agent_thought_chunk",
                "content": {"type": "text", "text": "I now have a clear understanding"},
            },
        },
    )
    second = ACPNotification(
        method="session/update",
        params={
            "sessionId": "s1",
            "update": {
                "sessionUpdate": "agent_thought_chunk",
                "content": {"type": "text", "text": " and can proceed"},
            },
        },
    )
    piece1 = connector._session_update_to_stream_piece(first, runtime)
    piece2 = connector._session_update_to_stream_piece(second, runtime)
    assert piece1 == AcpStreamPiece(
        content="Thinking:\nI now have a clear understanding"
    )
    assert piece2 == AcpStreamPiece(content=" and can proceed")


def test_session_update_flat_acp_tool_call_spec_shape(
    connector: DummyAcpConnector,
) -> None:
    runtime = connector._create_runtime(Path("/tmp/ws"), "m")
    msg = ACPNotification(
        method="session/update",
        params={
            "sessionId": "s1",
            "update": {
                "sessionUpdate": "tool_call",
                "toolCallId": "call_001",
                "title": "Reading configuration file",
                "kind": "read",
                "status": "pending",
                "rawInput": {"path": "/etc/app.json"},
            },
        },
    )
    piece = connector._session_update_to_stream_piece(msg, runtime)
    assert piece is None
    flush = connector._flush_incomplete_acp_tool_streams(runtime)
    assert len(flush) == 1
    assert flush[0].content is not None
    assert flush[0].content.startswith("---\n```text\nTool: Reading configuration file")
    assert "Input size:" in flush[0].content
    assert "Output size: 0 bytes" in flush[0].content
    assert "Status:" not in flush[0].content


def test_session_update_tool_call_emits_summary_when_completed(
    connector: DummyAcpConnector,
) -> None:
    runtime = connector._create_runtime(Path("/tmp/ws"), "m")
    msg = ACPNotification(
        method="session/update",
        params={
            "sessionId": "s1",
            "update": {
                "sessionUpdate": "tool_call",
                "toolCall": {
                    "name": "read_file",
                    "arguments": '{"path": "/x"}',
                    "status": "completed",
                },
            },
        },
    )
    pieces = connector._session_update_to_stream_pieces(msg, runtime)
    joined = "".join(p.content or "" for p in pieces)
    assert "Status:" not in joined
    assert joined.startswith("---\n```text\nTool: read_file")
    assert "Tool: read_file" in joined
    assert "Input size:" in joined
    assert "/x" not in joined


def test_session_update_tool_call_update_emits_status_and_size_summary(
    connector: DummyAcpConnector,
) -> None:
    runtime = connector._create_runtime(Path("/tmp/ws"), "m")
    call = ACPNotification(
        method="session/update",
        params={
            "sessionId": "s1",
            "update": {
                "sessionUpdate": "tool_call",
                "toolCall": {
                    "toolCallId": "tc-1",
                    "name": "list_dir",
                    "arguments": '{"path": "."}',
                    "status": "in_progress",
                },
            },
        },
    )
    upd = ACPNotification(
        method="session/update",
        params={
            "sessionId": "s1",
            "update": {
                "sessionUpdate": "tool_call_update",
                "toolCallUpdate": {
                    "toolCallId": "tc-1",
                    "name": "list_dir",
                    "result": ["a.txt", "b.txt"],
                    "status": "completed",
                },
            },
        },
    )
    first = connector._session_update_to_stream_pieces(call, runtime)
    second = connector._session_update_to_stream_pieces(upd, runtime)
    assert first == []
    joined = "".join(p.content or "" for p in second)
    assert "Status:" not in joined
    assert joined.startswith("---\n```text\nTool: list_dir")
    assert "Tool: list_dir" in joined
    assert "Output size:" in joined
    assert "a.txt" not in joined


def test_session_update_tool_call_list_emits_each_tool_separately(
    connector: DummyAcpConnector,
) -> None:
    runtime = connector._create_runtime(Path("/tmp/ws"), "m")
    msg = ACPNotification(
        method="session/update",
        params={
            "sessionId": "s1",
            "update": {
                "sessionUpdate": "tool_call",
                "toolCall": [
                    {"name": "read_file", "toolCallId": "x1", "status": "completed"},
                    {"name": "list_dir", "toolCallId": "x2", "status": "completed"},
                ],
            },
        },
    )
    pieces = connector._session_update_to_stream_pieces(msg, runtime)
    joined = "".join(p.content or "" for p in pieces)
    assert "read_file" in joined
    assert "list_dir" in joined
    assert len(runtime.acp_tool_stream_accum) == 2


def test_session_update_tool_summary_defers_until_output_observed(
    connector: DummyAcpConnector,
) -> None:
    runtime = connector._create_runtime(Path("/tmp/ws"), "m")
    early = ACPNotification(
        method="session/update",
        params={
            "sessionId": "s1",
            "update": {
                "sessionUpdate": "tool_call",
                "toolCall": {
                    "toolCallId": "tc-1",
                    "name": "list_dir",
                    "status": "completed",
                },
            },
        },
    )
    pieces1 = connector._session_update_to_stream_pieces(early, runtime)
    joined1 = "".join(p.content or "" for p in pieces1)
    assert "Status:" not in joined1
    assert "Tool: list_dir" not in joined1
    late = ACPNotification(
        method="session/update",
        params={
            "sessionId": "s1",
            "update": {
                "sessionUpdate": "tool_call_update",
                "toolCallUpdate": {
                    "toolCallId": "tc-1",
                    "name": "list_dir",
                    "result": ["a.txt"],
                },
            },
        },
    )
    pieces2 = connector._session_update_to_stream_pieces(late, runtime)
    joined2 = "".join(p.content or "" for p in pieces2)
    assert joined2.startswith("---\n```text\nTool: list_dir")
    assert "Tool: list_dir" in joined2
    assert "Output size:" in joined2
    assert "a.txt" not in joined2


def test_session_update_deferred_tool_summary_flushes_at_stream_end(
    connector: DummyAcpConnector,
) -> None:
    runtime = connector._create_runtime(Path("/tmp/ws"), "m")
    early = ACPNotification(
        method="session/update",
        params={
            "sessionId": "s1",
            "update": {
                "sessionUpdate": "tool_call",
                "toolCall": {
                    "toolCallId": "tc-1",
                    "name": "list_dir",
                    "status": "completed",
                },
            },
        },
    )
    pieces = connector._session_update_to_stream_pieces(early, runtime)
    assert pieces == []
    flush = connector._flush_incomplete_acp_tool_streams(runtime)
    assert len(flush) == 1
    assert flush[0].content is not None
    assert flush[0].content.startswith("---\n```text\nTool: list_dir")
    assert "Input size: 0 bytes" in flush[0].content
    assert "Output size: 0 bytes" in flush[0].content


def test_session_update_multiple_tools_without_correlation_ids_emit_separately(
    connector: DummyAcpConnector,
) -> None:
    runtime = connector._create_runtime(Path("/tmp/ws"), "m")
    first = ACPNotification(
        method="session/update",
        params={
            "sessionId": "s1",
            "update": {
                "sessionUpdate": "tool_call",
                "toolCall": {"name": "read_file", "status": "completed"},
            },
        },
    )
    second = ACPNotification(
        method="session/update",
        params={
            "sessionId": "s1",
            "update": {
                "sessionUpdate": "tool_call",
                "toolCall": {"name": "list_dir", "status": "completed"},
            },
        },
    )
    p1 = connector._session_update_to_stream_pieces(first, runtime)
    p2 = connector._session_update_to_stream_pieces(second, runtime)
    assert len(p1) >= 1 and any("read_file" in (x.content or "") for x in p1)
    assert len(p2) >= 1 and any("list_dir" in (x.content or "") for x in p2)
    assert len(runtime.acp_tool_stream_accum) == 2


def test_session_update_tool_call_update_seen_empty_tail_returns_none(
    connector: DummyAcpConnector,
) -> None:
    runtime = connector._create_runtime(Path("/tmp/ws"), "m")
    call = ACPNotification(
        method="session/update",
        params={
            "sessionId": "s1",
            "update": {
                "sessionUpdate": "tool_call",
                "toolCall": {
                    "toolCallId": "tc-1",
                    "name": "list_dir",
                    "arguments": '{"path": "."}',
                    "status": "pending",
                },
            },
        },
    )
    redundant = ACPNotification(
        method="session/update",
        params={
            "sessionId": "s1",
            "update": {
                "sessionUpdate": "tool_call_update",
                "toolCallUpdate": {
                    "toolCallId": "tc-1",
                    "name": "list_dir",
                },
            },
        },
    )
    first = connector._session_update_to_stream_piece(call, runtime)
    second = connector._session_update_to_stream_piece(redundant, runtime)
    assert first is None
    assert second is None


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
async def test_non_streaming_chat_completions_include_visible_thinking_blocks(
    connector: DummyAcpConnector,
) -> None:
    connector.is_functional = True
    connector._default_project_dir = Path("/tmp/dummy")
    runtime = connector._create_runtime(Path("/tmp/dummy"), "dummy/model")

    async def _mock_iter(
        _: ACPProcessRuntime, __: int, ___: str
    ) -> AsyncGenerator[AcpStreamPiece, None]:
        yield AcpStreamPiece(content="<thinking>\nplan step\n")
        yield AcpStreamPiece(content="\n</thinking>\n\n")
        yield AcpStreamPiece(content="Answer")

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
    assert message["content"] == "<thinking>\nplan step\n\n</thinking>\n\nAnswer"
    assert "reasoning_content" not in message


@pytest.mark.asyncio
async def test_requires_explicit_workspace_raises_without_override() -> None:
    connector = StrictWorkspaceDummy(MagicMock(), MagicMock())
    await connector.initialize()
    with pytest.raises(BackendError) as exc_info:
        connector._resolve_project_dir_for_request(_make_request())
    assert exc_info.value.details.get("code") == ACP_MISSING_PROJECT_WORKSPACE_CODE


@pytest.mark.asyncio
async def test_requires_explicit_workspace_accepts_options_project_dir(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "ws"
    workspace.mkdir()
    connector = StrictWorkspaceDummy(MagicMock(), MagicMock())
    await connector.initialize()
    base = _make_request()
    req = replace(base, options={"project_dir": str(workspace)})
    resolved = connector._resolve_project_dir_for_request(req)
    assert resolved == workspace.resolve()
