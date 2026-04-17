"""Unit tests for OpenAI WebSocket client."""

import inspect
import json
from enum import Enum
from unittest.mock import AsyncMock, patch

import pytest
from src.connectors.openai_websocket_client import OpenAIWebSocketClient

# Same group as test_openai_websocket_boundary_capture: shared `websockets.connect` patches.
pytestmark = pytest.mark.xdist_group("openai_websocket_boundary_capture")
from src.core.common.exceptions import (
    AuthenticationError,
    InvalidRequestError,
    ServiceUnavailableError,
)


@pytest.fixture
def api_key():
    return "test-api-key"


@pytest.fixture
def ws_client(api_key):
    return OpenAIWebSocketClient(api_key=api_key, api_base="wss://api.openai.com/v1")


@pytest.mark.asyncio
async def test_connect_sends_v2_beta_header(api_key):
    client = OpenAIWebSocketClient(
        api_key=api_key,
        api_base="wss://api.openai.com/v1",
        responses_websocket_mode="v2",
    )
    calls: list[dict[str, object]] = []

    async def modern_connect(
        uri: str,
        *,
        additional_headers: dict[str, str],
        ping_interval: int,
        ping_timeout: int,
        close_timeout: int,
    ):
        calls.append(
            {
                "uri": uri,
                "additional_headers": additional_headers,
                "ping_interval": ping_interval,
                "ping_timeout": ping_timeout,
                "close_timeout": close_timeout,
            }
        )
        mock_ws = AsyncMock()
        mock_ws.closed = False
        return mock_ws

    with patch("websockets.connect", new=modern_connect):
        await client.connect()

    assert len(calls) == 1
    headers = calls[0]["additional_headers"]
    assert isinstance(headers, dict)
    assert headers.get("OpenAI-Beta") == "responses-websocket-mode=v2"


@pytest.mark.asyncio
async def test_connect_falls_back_to_extra_headers_for_legacy_websockets(api_key):
    client = OpenAIWebSocketClient(
        api_key=api_key,
        api_base="wss://api.openai.com/v1",
        responses_websocket_mode="v2",
    )
    calls: list[dict[str, object]] = []

    async def legacy_connect(
        uri: str,
        *,
        extra_headers: dict[str, str],
        ping_interval: int,
        ping_timeout: int,
        close_timeout: int,
    ):
        calls.append(
            {
                "uri": uri,
                "extra_headers": extra_headers,
                "ping_interval": ping_interval,
                "ping_timeout": ping_timeout,
                "close_timeout": close_timeout,
            }
        )
        mock_ws = AsyncMock()
        mock_ws.closed = False
        return mock_ws

    assert "extra_headers" in inspect.signature(legacy_connect).parameters
    assert "additional_headers" not in inspect.signature(legacy_connect).parameters

    with patch("websockets.connect", new=legacy_connect):
        await client.connect()

    assert len(calls) == 1
    headers = calls[0]["extra_headers"]
    assert isinstance(headers, dict)
    assert headers.get("OpenAI-Beta") == "responses-websocket-mode=v2"


@pytest.mark.asyncio
async def test_connect_success(ws_client):
    """Test successful WebSocket connection."""
    with patch("websockets.connect", new_callable=AsyncMock) as mock_connect:
        mock_ws = AsyncMock()
        mock_ws.closed = False
        mock_connect.return_value = mock_ws

        await ws_client.connect()

        assert ws_client._connection is not None
        assert ws_client._connection_start_time is not None
        mock_connect.assert_called_once()


class _StateOnlyConnectionState(Enum):
    OPEN = "OPEN"
    CLOSED = "CLOSED"


@pytest.mark.asyncio
async def test_connect_reuses_state_only_open_connection(ws_client):
    """Newer websockets runtimes expose state instead of .closed."""
    existing_connection = AsyncMock()
    existing_connection.state = _StateOnlyConnectionState.OPEN
    ws_client._connection = existing_connection

    with patch("websockets.connect", new_callable=AsyncMock) as mock_connect:
        await ws_client.connect()

    mock_connect.assert_not_called()


@pytest.mark.asyncio
async def test_disconnect_closes_state_only_open_connection(ws_client):
    """Disconnect must work when the runtime only exposes .state."""
    existing_connection = AsyncMock()
    existing_connection.state = _StateOnlyConnectionState.OPEN
    ws_client._connection = existing_connection

    await ws_client.disconnect()

    existing_connection.close.assert_called_once()
    assert ws_client._connection is None


def test_connection_is_closed_detects_state_only_runtime(ws_client):
    open_connection = AsyncMock()
    open_connection.state = _StateOnlyConnectionState.OPEN

    closed_connection = AsyncMock()
    closed_connection.state = _StateOnlyConnectionState.CLOSED

    assert ws_client._connection_is_closed(open_connection) is False
    assert ws_client._connection_is_closed(closed_connection) is True


@pytest.mark.asyncio
async def test_connect_authentication_error(ws_client):
    """Test connection failure with authentication error."""
    with patch("websockets.connect", new_callable=AsyncMock) as mock_connect:

        class AuthFailureError(Exception):
            def __init__(self) -> None:
                super().__init__("unauthorized")
                self.status_code = 401

        mock_connect.side_effect = AuthFailureError()

        with pytest.raises(AuthenticationError):
            await ws_client.connect()


@pytest.mark.asyncio
async def test_connect_service_unavailable(ws_client):
    """Test connection failure with service unavailable error."""
    with patch("websockets.connect", new_callable=AsyncMock) as mock_connect:
        mock_connect.side_effect = Exception("Connection failed")

        with pytest.raises(ServiceUnavailableError):
            await ws_client.connect()


@pytest.mark.asyncio
async def test_disconnect(ws_client):
    """Test WebSocket disconnection."""
    with patch("websockets.connect", new_callable=AsyncMock) as mock_connect:
        mock_ws = AsyncMock()
        mock_ws.closed = False
        mock_connect.return_value = mock_ws

        await ws_client.connect()
        await ws_client.disconnect()

        assert ws_client._connection is None
        assert ws_client._connection_start_time is None
        mock_ws.close.assert_called_once()


@pytest.mark.asyncio
async def test_send_response_create_basic(ws_client):
    """Test sending response.create event and receiving response."""
    with patch("websockets.connect", new_callable=AsyncMock) as mock_connect:
        mock_ws = AsyncMock()
        mock_ws.closed = False

        # Mock receiving events
        response_done = {
            "type": "response.done",
            "response": {
                "id": "resp_123",
                "output": [{"type": "message", "content": "Hello"}],
            },
        }

        async def mock_aiter(self):
            yield json.dumps(response_done)

        # Set __aiter__ to return the generator directly
        mock_ws.__aiter__ = lambda self: mock_aiter(self)
        mock_connect.return_value = mock_ws

        await ws_client.connect()

        payload = {"model": "gpt-4o", "input": "Test message"}
        responses = []
        async for response in ws_client.send_response_create(payload):
            responses.append(response)

        assert len(responses) > 0
        mock_ws.send.assert_called_once()


@pytest.mark.asyncio
async def test_send_response_create_with_previous_id(ws_client):
    """Test continuation with previous_response_id."""
    with patch("websockets.connect", new_callable=AsyncMock) as mock_connect:
        mock_ws = AsyncMock()
        mock_ws.closed = False

        # Mock receiving events
        response_done = {
            "type": "response.done",
            "response": {"id": "resp_456", "output": []},
        }

        async def mock_aiter(self):
            yield json.dumps(response_done)

        mock_ws.__aiter__ = lambda self: mock_aiter(self)
        mock_connect.return_value = mock_ws

        await ws_client.connect()

        # Cache a response AFTER connection (cache is cleared on connect)
        ws_client._response_cache["resp_123"] = {"id": "resp_123"}

        payload = {"model": "gpt-4o", "input": "Follow-up message"}
        responses = []
        async for response in ws_client.send_response_create(
            payload, previous_response_id="resp_123"
        ):
            responses.append(response)

        assert len(responses) > 0
        # Should have included previous_response_id in the sent event
        sent_event = json.loads(mock_ws.send.call_args[0][0])
        assert sent_event.get("previous_response_id") == "resp_123"


@pytest.mark.asyncio
async def test_send_response_create_preserves_previous_id_without_local_cache(
    ws_client,
):
    """Continuation must not depend on connection-local response cache."""
    with patch("websockets.connect", new_callable=AsyncMock) as mock_connect:
        mock_ws = AsyncMock()
        mock_ws.closed = False

        response_done = {
            "type": "response.done",
            "response": {"id": "resp_789", "output": []},
        }

        async def mock_aiter(self):
            yield json.dumps(response_done)

        mock_ws.__aiter__ = lambda self: mock_aiter(self)
        mock_connect.return_value = mock_ws

        await ws_client.connect()

        payload = {"model": "gpt-4o", "input": "Follow-up message"}
        async for _ in ws_client.send_response_create(
            payload, previous_response_id="resp_missing_locally"
        ):
            pass

        sent_event = json.loads(mock_ws.send.call_args[0][0])
        assert sent_event.get("previous_response_id") == "resp_missing_locally"


@pytest.mark.asyncio
async def test_error_handling_previous_response_not_found(ws_client):
    """Test error handling for previous_response_not_found."""
    with patch("websockets.connect", new_callable=AsyncMock) as mock_connect:
        mock_ws = AsyncMock()
        mock_ws.closed = False

        error_event = {
            "type": "error",
            "error": {
                "code": "previous_response_not_found",
                "message": "Response not found",
            },
        }

        async def mock_aiter(self):
            yield json.dumps(error_event)

        mock_ws.__aiter__ = lambda self: mock_aiter(self)
        mock_connect.return_value = mock_ws

        await ws_client.connect()

        payload = {"model": "gpt-4o", "input": "Test"}
        with pytest.raises(InvalidRequestError) as exc_info:
            async for _ in ws_client.send_response_create(payload):
                pass

        assert exc_info.value.details["code"] == "previous_response_not_found"


@pytest.mark.asyncio
async def test_error_handling_connection_limit(ws_client):
    """Test error handling for connection limit reached."""
    with patch("websockets.connect", new_callable=AsyncMock) as mock_connect:
        mock_ws = AsyncMock()
        mock_ws.closed = False

        error_event = {
            "type": "error",
            "error": {
                "code": "websocket_connection_limit_reached",
                "message": "Connection limit reached",
            },
        }

        async def mock_aiter(self):
            yield json.dumps(error_event)

        mock_ws.__aiter__ = lambda self: mock_aiter(self)
        mock_connect.return_value = mock_ws

        await ws_client.connect()

        payload = {"model": "gpt-4o", "input": "Test"}
        with pytest.raises(ServiceUnavailableError):
            async for _ in ws_client.send_response_create(payload):
                pass


@pytest.mark.asyncio
async def test_connection_timeout_detection(ws_client):
    """Test connection timeout detection."""
    with patch("websockets.connect", new_callable=AsyncMock) as mock_connect:
        mock_ws = AsyncMock()
        mock_ws.closed = False
        mock_connect.return_value = mock_ws

        await ws_client.connect()

        # Manually set connection start time to past
        ws_client._connection_start_time = 0  # Way in the past

        assert ws_client._is_connection_expired() is True


@pytest.mark.asyncio
async def test_context_manager(ws_client):
    """Test using WebSocket client as context manager."""
    with patch("websockets.connect", new_callable=AsyncMock) as mock_connect:
        mock_ws = AsyncMock()
        mock_ws.closed = False
        mock_connect.return_value = mock_ws

        async with ws_client as client:
            assert client._connection is not None

        # Should disconnect on exit
        mock_ws.close.assert_called_once()


@pytest.mark.asyncio
async def test_event_to_processed_response_delta(ws_client):
    """Test converting delta events to ProcessedResponse."""
    event_data = {
        "type": "response.content_part.delta",
        "delta": {"content": "Hello"},
    }

    result = ws_client._event_to_processed_response(event_data)

    assert result is not None
    assert result.content["type"] == "content.delta"
    assert result.content["delta"]["content"] == "Hello"


@pytest.mark.asyncio
async def test_event_to_processed_response_done(ws_client):
    """Test converting done events to ProcessedResponse."""
    event_data = {
        "type": "response.done",
        "response": {"id": "resp_123", "output": []},
    }

    result = ws_client._event_to_processed_response(event_data)

    assert result is not None
    assert result.metadata["done"] is True
    assert result.content["id"] == "resp_123"


@pytest.mark.asyncio
async def test_event_to_processed_response_completed(ws_client):
    """Websocket v2 may emit response.completed instead of response.done."""
    event_data = {
        "type": "response.completed",
        "response": {"id": "resp_v2", "output": []},
    }

    result = ws_client._event_to_processed_response(event_data)

    assert result is not None
    assert result.metadata["done"] is True
    assert result.metadata["event_type"] == "response.completed"
    assert result.content["id"] == "resp_v2"


@pytest.mark.asyncio
async def test_send_response_create_terminates_on_response_completed(ws_client):
    """Stream loop must finish when the server sends response.completed."""
    with patch("websockets.connect", new_callable=AsyncMock) as mock_connect:
        mock_ws = AsyncMock()
        mock_ws.closed = False

        completed = {
            "type": "response.completed",
            "response": {"id": "resp_ws2", "output": []},
        }

        async def mock_aiter(self):
            yield json.dumps(completed)

        mock_ws.__aiter__ = lambda self: mock_aiter(self)
        mock_connect.return_value = mock_ws

        await ws_client.connect()

        payload = {"model": "gpt-4o", "input": "Test message"}
        responses = []
        async for response in ws_client.send_response_create(payload):
            responses.append(response)

        assert responses
        assert responses[-1].metadata.get("done") is True
        assert responses[-1].metadata.get("event_type") == "response.completed"


@pytest.mark.asyncio
async def test_event_to_processed_response_preserves_output_item_done_payload(
    ws_client,
):
    """Tool completion events must preserve full Responses metadata."""
    event_data = {
        "type": "response.output_item.done",
        "output_index": 1,
        "item": {
            "id": "fc_123",
            "type": "function_call",
            "name": "shell",
            "arguments": "{}",
        },
    }

    result = ws_client._event_to_processed_response(event_data)

    assert result is not None
    assert result.metadata["event_type"] == "response.output_item.done"
    assert result.content == event_data


@pytest.mark.asyncio
async def test_event_to_processed_response_skip_session(ws_client):
    """Test skipping session events."""
    event_data = {"type": "session.created"}

    result = ws_client._event_to_processed_response(event_data)

    assert result is None
