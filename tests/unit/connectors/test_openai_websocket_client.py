"""Unit tests for OpenAI WebSocket client."""

import json
from unittest.mock import AsyncMock, patch

import pytest
from src.connectors.openai_websocket_client import OpenAIWebSocketClient
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


@pytest.mark.asyncio
async def test_connect_authentication_error(ws_client):
    """Test connection failure with authentication error."""
    with patch("websockets.connect", new_callable=AsyncMock) as mock_connect:
        from websockets.exceptions import InvalidStatusCode

        mock_connect.side_effect = InvalidStatusCode(401, {})

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
        with pytest.raises(InvalidRequestError):
            async for _ in ws_client.send_response_create(payload):
                pass


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
async def test_event_to_processed_response_skip_session(ws_client):
    """Test skipping session events."""
    event_data = {"type": "session.created"}

    result = ws_client._event_to_processed_response(event_data)

    assert result is None
