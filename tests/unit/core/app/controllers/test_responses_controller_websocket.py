"""Unit tests for ResponsesController WebSocket handling."""

import contextlib
import json
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import WebSocketDisconnect
from src.core.app.controllers.responses_controller import ResponsesController
from src.core.domain.responses import ResponseEnvelope, StreamingResponseEnvelope
from src.core.interfaces.response_processor_interface import ProcessedResponse


@pytest.fixture
def mock_processor():
    processor = AsyncMock()
    return processor


@pytest.fixture
def mock_translation_service():
    service = MagicMock()
    service.to_domain_request = MagicMock()
    service.from_domain_response = MagicMock()
    return service


@pytest.fixture
def controller(
    mock_processor, mock_translation_service, responses_controller_backend_deps
):
    return ResponsesController(
        request_processor=mock_processor,
        translation_service=mock_translation_service,
        **responses_controller_backend_deps,
    )


@pytest.fixture
def mock_websocket():
    ws = AsyncMock()
    ws.accept = AsyncMock()
    ws.send_json = AsyncMock()
    ws.close = AsyncMock()
    ws.headers = {}
    return ws


@pytest.mark.asyncio
async def test_websocket_connection_accept(controller, mock_websocket):
    """Test WebSocket connection is accepted."""
    # Simulate immediate disconnect
    mock_websocket.receive_text = AsyncMock(side_effect=WebSocketDisconnect())

    with contextlib.suppress(Exception):
        await controller.handle_websocket_connection(mock_websocket)

    mock_websocket.accept.assert_called_once()


@pytest.mark.asyncio
async def test_websocket_connection_timeout(controller, mock_websocket):
    """Test WebSocket connection timeout handling."""
    # Mock time module in the responses_controller module
    with patch(
        "src.core.app.controllers.responses_controller.time"
    ) as mock_time_module:
        # First call for request_id generation, second for start time, third for elapsed check
        mock_time_module.time.side_effect = [0, 0, 3601]

        mock_websocket.receive_text = AsyncMock()

        await controller.handle_websocket_connection(mock_websocket)

        # Should send timeout error
        assert mock_websocket.send_json.called
        error_event = mock_websocket.send_json.call_args[0][0]
        assert error_event["type"] == "error"
        assert error_event["error"]["code"] == "websocket_connection_limit_reached"


@pytest.mark.asyncio
async def test_websocket_response_create_basic(
    controller, mock_websocket, mock_processor, mock_translation_service
):
    """Test handling basic response.create event."""
    # Mock request message
    request_event = {
        "type": "response.create",
        "model": "gpt-4o",
        "input": "Hello",
    }

    mock_websocket.receive_text = AsyncMock(
        side_effect=[
            json.dumps(request_event),
            WebSocketDisconnect(),  # Then disconnect
        ]
    )

    # Mock domain request and response
    mock_domain_request = MagicMock()
    mock_translation_service.to_domain_request.return_value = mock_domain_request

    mock_response = ResponseEnvelope(
        content={"id": "resp_123", "output": []}, status_code=200
    )
    mock_processor.process_request.return_value = mock_response

    with contextlib.suppress(Exception):
        await controller.handle_websocket_connection(mock_websocket)

    # Should have sent done event
    assert mock_websocket.send_json.called
    sent_events = [call[0][0] for call in mock_websocket.send_json.call_args_list]
    done_events = [e for e in sent_events if e.get("type") == "response.done"]
    assert len(done_events) > 0


@pytest.mark.asyncio
async def test_websocket_non_streaming_store_before_response_done_send(
    controller, mock_websocket, mock_processor, mock_translation_service
) -> None:
    """Session store must record the response before response.done is sent on the wire."""
    order: list[str] = []

    orig_store = controller._store_completed_responses_payload

    async def track_store(
        payload: dict[str, Any],
        *,
        instructions: str | None = None,
        history_items: list[Any] | None = None,
    ) -> None:
        order.append("store_start")
        await orig_store(
            payload,
            instructions=instructions,
            history_items=history_items,
        )
        order.append("store_end")

    controller._store_completed_responses_payload = track_store  # type: ignore[method-assign]

    async def capture_send(data: dict[str, Any]) -> None:
        order.append(f"send:{data.get('type')}")

    mock_websocket.send_json = AsyncMock(side_effect=capture_send)

    request_event = {
        "type": "response.create",
        "model": "gpt-4o",
        "input": "Hello",
    }
    mock_websocket.receive_text = AsyncMock(
        side_effect=[json.dumps(request_event), WebSocketDisconnect()]
    )

    mock_domain_request = MagicMock()
    mock_translation_service.to_domain_request.return_value = mock_domain_request

    mock_response = ResponseEnvelope(
        content={"id": "resp_ws_order", "output": [], "object": "response"},
        status_code=200,
    )
    mock_processor.process_request.return_value = mock_response

    with contextlib.suppress(Exception):
        await controller.handle_websocket_connection(mock_websocket)

    assert "store_end" in order
    idx_store_end = order.index("store_end")
    done_send_indices = [i for i, x in enumerate(order) if x == "send:response.done"]
    assert done_send_indices
    assert idx_store_end < min(done_send_indices)


@pytest.mark.asyncio
async def test_websocket_response_create_streaming(
    controller, mock_websocket, mock_processor, mock_translation_service
):
    """Test handling streaming response.create event."""
    request_event = {
        "type": "response.create",
        "model": "gpt-4o",
        "input": "Hello",
        "stream": True,
    }

    mock_websocket.receive_text = AsyncMock(
        side_effect=[
            json.dumps(request_event),
            WebSocketDisconnect(),
        ]
    )

    # Mock streaming response
    async def mock_stream():
        yield ProcessedResponse(
            content={"type": "response.delta", "delta": {"content": "Hi"}},
            metadata={"event_type": "response.delta"},
        )
        yield ProcessedResponse(
            content={"id": "resp_123", "output": []},
            metadata={"event_type": "response.done", "done": True},
        )

    mock_translation_service.to_domain_request.return_value = MagicMock()

    mock_response = StreamingResponseEnvelope(
        content=mock_stream(), media_type="text/event-stream"
    )
    mock_processor.process_request.return_value = mock_response

    with contextlib.suppress(Exception):
        await controller.handle_websocket_connection(mock_websocket)

    # Should have sent multiple events including done
    assert mock_websocket.send_json.call_count >= 2


@pytest.mark.asyncio
async def test_websocket_response_create_streaming_terminal_is_done_emits_response_done(
    controller, mock_websocket, mock_processor, mock_translation_service
):
    """Production pipeline marks terminals with metadata is_done, not done."""
    request_event = {
        "type": "response.create",
        "model": "gpt-4o",
        "input": "Hello",
        "stream": True,
    }

    mock_websocket.receive_text = AsyncMock(
        side_effect=[
            json.dumps(request_event),
            WebSocketDisconnect(),
        ]
    )

    async def mock_stream():
        yield ProcessedResponse(
            content={"type": "response.delta", "delta": {"content": "Hi"}},
            metadata={"event_type": "response.delta"},
        )
        yield ProcessedResponse(
            content={"id": "resp_is_done_1", "output": []},
            metadata={"event_type": "response.completed", "is_done": True},
        )

    mock_translation_service.to_domain_request.return_value = MagicMock()

    mock_response = StreamingResponseEnvelope(
        content=mock_stream(), media_type="text/event-stream"
    )
    mock_processor.process_request.return_value = mock_response

    with contextlib.suppress(Exception):
        await controller.handle_websocket_connection(mock_websocket)

    sent = [call[0][0] for call in mock_websocket.send_json.call_args_list]
    done_events = [e for e in sent if e.get("type") == "response.done"]
    assert len(done_events) == 1
    assert done_events[0].get("response", {}).get("id") == "resp_is_done_1"


@pytest.mark.asyncio
async def test_websocket_streaming_fallback_done_logs_debug(
    controller,
    mock_websocket,
    mock_processor,
    mock_translation_service,
):
    """Stream ends without terminal metadata but last chunk looks like a response object."""
    request_event = {
        "type": "response.create",
        "model": "gpt-4o",
        "input": "Hello",
        "stream": True,
    }

    mock_websocket.receive_text = AsyncMock(
        side_effect=[
            json.dumps(request_event),
            WebSocketDisconnect(),
        ]
    )

    async def mock_stream():
        yield ProcessedResponse(
            content={"type": "response.delta", "delta": {"content": "Hi"}},
            metadata={"event_type": "response.delta"},
        )
        yield ProcessedResponse(
            content={
                "id": "resp_fallback_1",
                "object": "response",
                "output": [],
                "status": "completed",
            },
            metadata={"event_type": "response.completed"},
        )

    mock_translation_service.to_domain_request.return_value = MagicMock()

    mock_response = StreamingResponseEnvelope(
        content=mock_stream(), media_type="text/event-stream"
    )
    mock_processor.process_request.return_value = mock_response

    with contextlib.suppress(Exception):
        await controller.handle_websocket_connection(mock_websocket)

    sent = [call[0][0] for call in mock_websocket.send_json.call_args_list]
    done_events = [e for e in sent if e.get("type") == "response.done"]
    assert len(done_events) == 1
    assert done_events[0].get("response", {}).get("id") == "resp_fallback_1"


@pytest.mark.asyncio
async def test_websocket_invalid_json(controller, mock_websocket):
    """Test handling invalid JSON in WebSocket message."""
    mock_websocket.receive_text = AsyncMock(
        side_effect=[
            "not valid json",
            WebSocketDisconnect(),
        ]
    )

    with contextlib.suppress(Exception):
        await controller.handle_websocket_connection(mock_websocket)

    # Should send error event
    error_calls = [
        call
        for call in mock_websocket.send_json.call_args_list
        if call[0][0].get("type") == "error"
        and call[0][0].get("error", {}).get("code") == "invalid_json"
    ]
    assert len(error_calls) > 0


@pytest.mark.asyncio
async def test_websocket_invalid_json_schema_rejected_like_http(
    controller, mock_websocket
):
    """Invalid response_format.json_schema must be rejected on WS like HTTP (400 invalid_schema)."""
    request_event = {
        "type": "response.create",
        "model": "gpt-4o",
        "response_format": {
            "type": "json_schema",
            "json_schema": {
                "name": "broken_schema",
                "schema": "not-an-object",
            },
        },
    }

    await controller._handle_websocket_response_create(
        mock_websocket,
        request_event,
        request_id="req_invalid_schema",
    )

    error_event = mock_websocket.send_json.call_args_list[-1][0][0]
    assert error_event["type"] == "error"
    assert error_event["status"] == 400
    assert error_event["error"]["code"] == "invalid_schema"


@pytest.mark.asyncio
async def test_websocket_non_streaming_provider_native_message_normalized_to_canonical(
    controller,
    mock_websocket,
    mock_processor,
    mock_translation_service,
) -> None:
    """Cross-provider native payloads are normalized to canonical Responses objects on response.done."""
    request_event = {
        "type": "response.create",
        "model": "anthropic:claude-3-5-sonnet-20241022",
        "input": "Hello",
    }
    mock_translation_service.to_domain_request.return_value = MagicMock()
    mock_processor.process_request.return_value = ResponseEnvelope(
        content={
            "id": "msg_upstream",
            "type": "message",
            "role": "assistant",
            "content": [{"type": "text", "text": '{"x": 1}'}],
            "stop_reason": "end_turn",
            "usage": {"input_tokens": 1, "output_tokens": 2},
        },
        status_code=200,
    )

    await controller._handle_websocket_response_create(
        mock_websocket,
        request_event,
        request_id="req_canonical_ws",
    )

    last = mock_websocket.send_json.call_args_list[-1][0][0]
    assert last.get("type") == "response.done"
    body = last.get("response", {})
    assert body.get("object") == "response"
    assert body.get("id") == "msg_upstream"
    assert isinstance(body.get("choices"), list)
    assert body["choices"][0]["finish_reason"] == "stop"
    assert body["usage"]["prompt_tokens"] == 1
    assert body["usage"]["completion_tokens"] == 2


@pytest.mark.asyncio
async def test_websocket_unsupported_event_type(controller, mock_websocket):
    """Test handling unsupported event type."""
    unsupported_event = {
        "type": "unsupported.event",
        "data": "something",
    }

    mock_websocket.receive_text = AsyncMock(
        side_effect=[
            json.dumps(unsupported_event),
            WebSocketDisconnect(),
        ]
    )

    with contextlib.suppress(Exception):
        await controller.handle_websocket_connection(mock_websocket)

    # Should send error event
    error_calls = [
        call
        for call in mock_websocket.send_json.call_args_list
        if call[0][0].get("type") == "error"
        and call[0][0].get("error", {}).get("code") == "unsupported_event_type"
    ]
    assert len(error_calls) > 0


@pytest.mark.asyncio
async def test_websocket_previous_response_not_found(
    controller, mock_websocket, mock_translation_service
):
    """Test handling previous_response_id not in cache."""
    request_event = {
        "type": "response.create",
        "model": "gpt-4o",
        "input": "Hello",
        "previous_response_id": "resp_nonexistent",
    }

    mock_websocket.receive_text = AsyncMock(
        side_effect=[
            json.dumps(request_event),
            WebSocketDisconnect(),
        ]
    )

    mock_translation_service.to_domain_request.return_value = MagicMock()

    with contextlib.suppress(Exception):
        await controller.handle_websocket_connection(mock_websocket)

    # Should send previous_response_not_found error
    error_calls = [
        call
        for call in mock_websocket.send_json.call_args_list
        if call[0][0].get("type") == "error"
        and call[0][0].get("error", {}).get("code") == "previous_response_not_found"
    ]
    assert len(error_calls) > 0


@pytest.mark.asyncio
async def test_websocket_response_caching(
    controller, mock_websocket, mock_processor, mock_translation_service
):
    """Test response caching for previous_response_id."""
    # First request
    request1 = {
        "type": "response.create",
        "model": "gpt-4o",
        "input": "First message",
    }

    # Second request with previous_response_id
    request2 = {
        "type": "response.create",
        "model": "gpt-4o",
        "input": "Second message",
        "previous_response_id": "resp_123",
    }

    mock_websocket.receive_text = AsyncMock(
        side_effect=[
            json.dumps(request1),
            json.dumps(request2),
            WebSocketDisconnect(),
        ]
    )

    mock_translation_service.to_domain_request.return_value = MagicMock()

    # First response (provider-native shape that normalizes without replacing ids)
    mock_response1 = ResponseEnvelope(
        content={
            "id": "resp_123",
            "type": "message",
            "content": [{"type": "text", "text": "first"}],
        },
        status_code=200,
    )

    mock_response2 = ResponseEnvelope(
        content={
            "id": "resp_456",
            "type": "message",
            "content": [{"type": "text", "text": "second"}],
        },
        status_code=200,
    )

    mock_processor.process_request.side_effect = [mock_response1, mock_response2]

    with contextlib.suppress(Exception):
        await controller.handle_websocket_connection(mock_websocket)

    # Second request should succeed (previous_response_id was cached)
    done_events = [
        call[0][0]
        for call in mock_websocket.send_json.call_args_list
        if call[0][0].get("type") == "response.done"
    ]
    assert len(done_events) >= 2


@pytest.mark.asyncio
async def test_websocket_connection_cleanup(controller, mock_websocket):
    """Test WebSocket connection cleanup on exit."""
    mock_websocket.receive_text = AsyncMock(side_effect=WebSocketDisconnect())

    with contextlib.suppress(Exception):
        await controller.handle_websocket_connection(mock_websocket)

    # Should close connection
    mock_websocket.close.assert_called()


@pytest.mark.asyncio
async def test_websocket_non_streaming_string_body_normalized_like_http(
    controller,
    mock_websocket,
    mock_processor,
    mock_translation_service,
) -> None:
    """Non-streaming WS applies the same Responses schema normalization as HTTP."""
    request_event = {
        "type": "response.create",
        "model": "gpt-4o",
        "input": "Hello",
    }
    mock_processor.process_request.return_value = ResponseEnvelope(
        content="upstream-returned-string-body",
        status_code=200,
    )

    await controller._handle_websocket_response_create(
        mock_websocket,
        request_event,
        request_id="req_nondict_body",
    )

    assert mock_websocket.send_json.called
    last = mock_websocket.send_json.call_args_list[-1][0][0]
    assert last.get("type") == "response.done"
    body = last.get("response", {})
    assert body.get("object") == "response"
    assert isinstance(body.get("choices"), list)
    assert (
        body.get("choices")[0]["message"]["content"] == "upstream-returned-string-body"
    )


@pytest.mark.asyncio
async def test_websocket_outbound_wire_capture_model_prefers_response_payload(
    mock_processor,
    mock_translation_service,
    responses_controller_backend_deps,
    mock_websocket,
) -> None:
    """Outbound capture metadata should use the resolved response model when available."""
    wire = MagicMock()
    wire.enabled = MagicMock(return_value=True)
    wire.capture_inbound_request = AsyncMock()
    wire.capture_outbound_response = AsyncMock()

    controller = ResponsesController(
        request_processor=mock_processor,
        translation_service=mock_translation_service,
        wire_capture=wire,
        **responses_controller_backend_deps,
    )

    request_event = {
        "type": "response.create",
        "model": "event-top-model",
        "input": "Hello",
    }
    mock_processor.process_request.return_value = ResponseEnvelope(
        content={"id": "resp_cap", "model": "body-model", "output": []},
        status_code=200,
    )

    await controller._handle_websocket_response_create(
        mock_websocket,
        request_event,
        request_id="req_capture_model",
    )

    wire.capture_outbound_response.assert_awaited()
    await_args = wire.capture_outbound_response.await_args
    assert await_args is not None
    kwargs = await_args.kwargs
    assert kwargs.get("model") == "event-top-model"
