from __future__ import annotations

from collections.abc import AsyncGenerator
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from src.connectors.acp_core.base_connector import BaseAcpConnector
from src.connectors.acp_core.types import ACPNotification, ACPProcessRuntime
from src.connectors.acp_core.types import AcpStreamPiece as AcpStreamPiece
from src.connectors.contracts import ConnectorChatCompletionsRequest
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
    stream: bool = False, with_history: bool = False
) -> ConnectorChatCompletionsRequest:
    messages = (
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
        messages=messages,
    )
    return ConnectorChatCompletionsRequest(
        request=request,
        processed_messages=messages,
        effective_model="dummy/model",
        identity=None,
        cancellation_token=None,
        cancellation_coordinator=None,
        context=None,
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


@pytest.mark.asyncio
async def test_base_acp_connector_history_injected_logic(
    connector: DummyAcpConnector,
) -> None:
    connector._default_project_dir = Path("/tmp/dummy")
    runtime = connector._create_runtime(Path("/tmp/dummy"), "model")
    runtime.process = MagicMock()
    runtime.process.stdin = MagicMock()
    runtime.process.stdout = MagicMock()

    assert runtime.history_injected is False

    with (
        patch.object(connector, "_spawn_process", AsyncMock()),
        patch.object(
            connector, "_send_jsonrpc_message", AsyncMock(return_value=1)
        ) as send_mock,
    ):

        await connector._prepare_prompt_request_locked(
            runtime, _make_request(with_history=True)
        )

        assert runtime.history_injected is True

        # Check that the prompt sent contains the transcript preamble
        sent_params = send_mock.call_args[0][2]
        prompt_text = sent_params["prompt"][0]["text"]
        assert "System Note:" in prompt_text

        # Second request should not inject history
        await connector._prepare_prompt_request_locked(runtime, _make_request())

        sent_params_2 = send_mock.call_args[0][2]
        prompt_text_2 = sent_params_2["prompt"][0]["text"]
        assert "System Note:" not in prompt_text_2
        assert prompt_text_2 == "hello"


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
