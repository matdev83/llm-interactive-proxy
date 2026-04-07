from __future__ import annotations

import json
import sys
from unittest.mock import AsyncMock, patch

import pytest
from src.connectors.contracts import ConnectorRequestContext

# Serialize with other wire-capture / websocket tests to avoid patch races under xdist.
pytestmark = pytest.mark.xdist_group("openai_websocket_boundary_capture")


@pytest.mark.asyncio
async def test_openai_websocket_client_captures_outbound_and_inbound_frames() -> None:
    # Ensure the module is not cached from previous tests
    module_name = "src.connectors.openai_websocket_client"
    if module_name in sys.modules:
        del sys.modules[module_name]

    context = ConnectorRequestContext(
        request_id="req-openai-ws-boundary",
        session_id="sess-openai-ws-boundary",
        client_host="127.0.0.1",
        extensions={},
    )

    async def inbound_messages():
        yield json.dumps(
            {
                "type": "response.delta",
                "delta": {"content": "hello"},
            }
        )
        yield json.dumps(
            {
                "type": "response.done",
                "response": {"id": "resp_123", "output": []},
            }
        ).encode("utf-8")

    mock_ws = AsyncMock()
    mock_ws.closed = False
    mock_ws.__aiter__ = lambda self=mock_ws: inbound_messages()

    outbound_capture = AsyncMock()
    inbound_capture = AsyncMock()

    with (
        patch("websockets.connect", new_callable=AsyncMock, return_value=mock_ws),
        patch(
            "src.core.common.wire_boundary_capture.capture_websocket_backend_outbound",
            outbound_capture,
        ),
        patch(
            "src.core.common.wire_boundary_capture.capture_websocket_backend_inbound",
            inbound_capture,
        ),
    ):
        # Import after patches are applied to ensure fresh import
        from src.connectors.openai_websocket_client import OpenAIWebSocketClient

        client = OpenAIWebSocketClient(
            api_key="test-key",
            api_base="wss://api.openai.com/v1",
        )
        await client.connect()
        responses = [
            response
            async for response in client.send_response_create(
                {
                    "model": "gpt-4o",
                    "input": "hello",
                    "stream": True,
                    "background": True,
                },
                context=context,
                backend="openai",
                model="gpt-4o",
                key_name="OPENAI_API_KEY",
            )
        ]

    sent_frame = mock_ws.send.await_args.args[0]
    sent_event = json.loads(sent_frame)

    assert sent_event["type"] == "response.create"
    assert sent_event["model"] == "gpt-4o"
    assert sent_event["input"] == "hello"
    assert "stream" not in sent_event
    assert "background" not in sent_event

    assert outbound_capture.await_args is not None
    outbound_kwargs = outbound_capture.await_args.kwargs
    assert outbound_kwargs["payload"] == sent_frame.encode("utf-8")
    assert outbound_kwargs["backend"] == "openai"
    assert outbound_kwargs["model"] == "gpt-4o"
    assert outbound_kwargs["key_name"] == "OPENAI_API_KEY"
    assert outbound_kwargs["context"] == context
    assert outbound_kwargs["message_type"] == "text"

    assert inbound_capture.await_count == 2
    first_inbound = inbound_capture.await_args_list[0].kwargs
    second_inbound = inbound_capture.await_args_list[1].kwargs
    assert (
        first_inbound["payload"]
        == b'{"type": "response.delta", "delta": {"content": "hello"}}'
    )
    assert first_inbound["message_type"] == "text"
    assert (
        second_inbound["payload"]
        == b'{"type": "response.done", "response": {"id": "resp_123", "output": []}}'
    )
    assert second_inbound["message_type"] == "binary"

    assert [response.metadata["event_type"] for response in responses] == [
        "response.delta",
        "response.done",
    ]
