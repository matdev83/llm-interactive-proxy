"""Unit tests for ResponsesController WebSocket handling."""

import contextlib
import json
import logging
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
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
def controller(mock_processor, mock_translation_service):
    return ResponsesController(
        request_processor=mock_processor,
        translation_service=mock_translation_service,
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
    mock_websocket.receive_text = AsyncMock(
        side_effect=Exception("WebSocketDisconnect")
    )

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
            Exception("WebSocketDisconnect"),  # Then disconnect
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
            Exception("WebSocketDisconnect"),
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
            Exception("WebSocketDisconnect"),
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
    caplog: pytest.LogCaptureFixture,
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
            Exception("WebSocketDisconnect"),
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

    caplog.set_level(
        logging.DEBUG, logger="src.core.app.controllers.responses_controller"
    )

    with contextlib.suppress(Exception):
        await controller.handle_websocket_connection(mock_websocket)

    sent = [call[0][0] for call in mock_websocket.send_json.call_args_list]
    done_events = [e for e in sent if e.get("type") == "response.done"]
    assert len(done_events) == 1
    assert done_events[0].get("response", {}).get("id") == "resp_fallback_1"
    assert any(
        "emitting response.done from last dict chunk" in r.message
        for r in caplog.records
    )


@pytest.mark.asyncio
async def test_websocket_invalid_json(controller, mock_websocket):
    """Test handling invalid JSON in WebSocket message."""
    mock_websocket.receive_text = AsyncMock(
        side_effect=[
            "not valid json",
            Exception("WebSocketDisconnect"),
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
async def test_websocket_unsupported_event_type(controller, mock_websocket):
    """Test handling unsupported event type."""
    unsupported_event = {
        "type": "unsupported.event",
        "data": "something",
    }

    mock_websocket.receive_text = AsyncMock(
        side_effect=[
            json.dumps(unsupported_event),
            Exception("WebSocketDisconnect"),
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
            Exception("WebSocketDisconnect"),
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
            Exception("WebSocketDisconnect"),
        ]
    )

    mock_translation_service.to_domain_request.return_value = MagicMock()

    # First response
    mock_response1 = ResponseEnvelope(
        content={"id": "resp_123", "output": []}, status_code=200
    )

    # Second response
    mock_response2 = ResponseEnvelope(
        content={"id": "resp_456", "output": []}, status_code=200
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
    mock_websocket.receive_text = AsyncMock(
        side_effect=Exception("WebSocketDisconnect")
    )

    with contextlib.suppress(Exception):
        await controller.handle_websocket_connection(mock_websocket)

    # Should close connection
    mock_websocket.close.assert_called()
