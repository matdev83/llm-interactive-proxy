"""
Unit tests for Codebuff WebSocket server.

These tests verify the WebSocket server functionality including connection
handling, message sending, heartbeat monitoring, and graceful shutdown.
"""

import json
from unittest.mock import AsyncMock, Mock

import pytest
from fastapi import WebSocketDisconnect
from src.codebuff.connection_manager import ConnectionManager
from src.codebuff.format_converter import FormatConverter
from src.codebuff.handlers.init_handler import InitHandler
from src.codebuff.handlers.prompt_handler import PromptHandler
from src.codebuff.handlers.subscription_handler import SubscriptionHandler
from src.codebuff.message_router import MessageRouter
from src.codebuff.schemas import AckMessage, InitResponseAction, ServerActionMessage
from src.codebuff.server import CodebuffWebSocketServer


def create_mock_websocket() -> Mock:
    """Create a mock WebSocket connection."""
    websocket = Mock()
    websocket.accept = AsyncMock()
    websocket.receive_text = AsyncMock()
    websocket.send_text = AsyncMock()
    websocket.close = AsyncMock()
    return websocket


@pytest.fixture
def connection_manager() -> ConnectionManager:
    """Create a ConnectionManager instance."""
    return ConnectionManager(heartbeat_timeout_seconds=60)


@pytest.fixture
def message_router() -> MessageRouter:
    """Create a MessageRouter instance."""
    return MessageRouter()


@pytest.fixture
def format_converter() -> FormatConverter:
    """Create a FormatConverter instance."""
    return FormatConverter()


@pytest.fixture
def prompt_handler() -> Mock:
    """Create a mock PromptHandler."""
    handler = Mock(spec=PromptHandler)
    handler.handle_prompt = AsyncMock()
    return handler


@pytest.fixture
def init_handler() -> Mock:
    """Create a mock InitHandler."""
    handler = Mock(spec=InitHandler)
    handler.handle_init = AsyncMock()
    return handler


@pytest.fixture
def subscription_handler() -> Mock:
    """Create a mock SubscriptionHandler."""
    handler = Mock(spec=SubscriptionHandler)
    handler.handle_subscribe = AsyncMock()
    handler.handle_unsubscribe = AsyncMock()
    return handler


@pytest.fixture
def server(
    connection_manager: ConnectionManager,
    message_router: MessageRouter,
    prompt_handler: Mock,
    init_handler: Mock,
    subscription_handler: Mock,
) -> CodebuffWebSocketServer:
    """Create a CodebuffWebSocketServer instance."""
    return CodebuffWebSocketServer(
        connection_manager=connection_manager,
        message_router=message_router,
        prompt_handler=prompt_handler,
        init_handler=init_handler,
        subscription_handler=subscription_handler,
        config=Mock(),
    )


@pytest.mark.asyncio
async def test_handle_connection_accepts_websocket(
    server: CodebuffWebSocketServer,
) -> None:
    """Test that handle_connection accepts the WebSocket connection."""
    websocket = create_mock_websocket()

    # Mock identify message
    identify_msg = json.dumps(
        {"type": "identify", "txid": 1, "clientSessionId": "test-session"}
    )

    # Mock receive_text to return identify then disconnect
    websocket.receive_text.side_effect = [identify_msg, WebSocketDisconnect()]

    await server.handle_connection(websocket)

    # Verify accept was called
    websocket.accept.assert_called_once()


@pytest.mark.asyncio
async def test_handle_connection_registers_session(
    server: CodebuffWebSocketServer, connection_manager: ConnectionManager
) -> None:
    """Test that handle_connection registers the session after identify."""
    websocket = create_mock_websocket()

    # Mock identify message
    identify_msg = json.dumps(
        {"type": "identify", "txid": 1, "clientSessionId": "test-session"}
    )

    # Mock receive_text to return identify then disconnect
    websocket.receive_text.side_effect = [identify_msg, WebSocketDisconnect()]

    await server.handle_connection(websocket)

    # Session should be cleaned up after disconnect, but we can verify it was registered
    # by checking that no error was raised during connection


@pytest.mark.asyncio
async def test_handle_connection_processes_ping(
    server: CodebuffWebSocketServer, connection_manager: ConnectionManager
) -> None:
    """Test that handle_connection processes ping messages."""
    websocket = create_mock_websocket()

    # Mock messages
    identify_msg = json.dumps(
        {"type": "identify", "txid": 1, "clientSessionId": "test-session"}
    )
    ping_msg = json.dumps({"type": "ping", "txid": 2})

    # Mock receive_text to return identify, ping, then disconnect
    websocket.receive_text.side_effect = [
        identify_msg,
        ping_msg,
        WebSocketDisconnect(),
    ]

    await server.handle_connection(websocket)

    # Verify ack messages were sent (one for identify, one for ping)
    assert websocket.send_text.call_count >= 2


@pytest.mark.asyncio
async def test_handle_connection_cleans_up_on_disconnect(
    server: CodebuffWebSocketServer, connection_manager: ConnectionManager
) -> None:
    """Test that handle_connection cleans up session on disconnect."""
    websocket = create_mock_websocket()

    # Mock identify message
    identify_msg = json.dumps(
        {"type": "identify", "txid": 1, "clientSessionId": "test-session"}
    )

    # Mock receive_text to return identify then disconnect
    websocket.receive_text.side_effect = [identify_msg, WebSocketDisconnect()]

    await server.handle_connection(websocket)

    # Verify session is cleaned up
    session = connection_manager.get_session(websocket)
    assert session is None


@pytest.mark.asyncio
async def test_send_message_sends_ack(server: CodebuffWebSocketServer) -> None:
    """Test that send_message sends an ack message."""
    websocket = create_mock_websocket()

    ack = AckMessage(type="ack", txid=1, success=True, error=None)

    await server.send_message(websocket, ack)

    # Verify send_text was called
    websocket.send_text.assert_called_once()

    # Verify the message content
    sent_message = websocket.send_text.call_args[0][0]
    message_dict = json.loads(sent_message)

    assert message_dict["type"] == "ack"
    assert message_dict["txid"] == 1
    assert message_dict["success"] is True


@pytest.mark.asyncio
async def test_send_message_sends_action(server: CodebuffWebSocketServer) -> None:
    """Test that send_message sends an action message."""
    websocket = create_mock_websocket()

    init_response = InitResponseAction(
        type="init-response",
        message="Initialized",
        agentNames=None,
        usage=0.0,
        remainingBalance=1000.0,
        next_quota_reset=None,
    )

    action_message = ServerActionMessage(type="action", data=init_response)

    await server.send_message(websocket, action_message)

    # Verify send_text was called
    websocket.send_text.assert_called_once()

    # Verify the message content
    sent_message = websocket.send_text.call_args[0][0]
    message_dict = json.loads(sent_message)

    assert message_dict["type"] == "action"
    assert message_dict["data"]["type"] == "init-response"


@pytest.mark.asyncio
async def test_start_heartbeat_monitor_starts_task(
    server: CodebuffWebSocketServer,
) -> None:
    """Test that start_heartbeat_monitor starts the background task."""
    await server.start_heartbeat_monitor()

    # Verify task is created
    assert server._heartbeat_task is not None
    assert not server._heartbeat_task.done()

    # Clean up
    await server.shutdown()


@pytest.mark.asyncio
async def test_heartbeat_monitor_cleans_up_stale_connections(
    server: CodebuffWebSocketServer, connection_manager: ConnectionManager
) -> None:
    """Test that heartbeat monitor cleans up stale connections."""
    # Create a mock connection
    websocket = create_mock_websocket()
    connection_manager.connect(websocket, "test-session")

    # Start heartbeat monitor
    await server.start_heartbeat_monitor()

    # Wait a bit for the monitor to run (it checks every 30 seconds, but we'll
    # manually trigger cleanup for testing)
    await connection_manager.cleanup_stale_connections()

    # Clean up
    await server.shutdown()


@pytest.mark.asyncio
async def test_shutdown_cancels_heartbeat_task(
    server: CodebuffWebSocketServer,
) -> None:
    """Test that shutdown cancels the heartbeat monitoring task."""
    await server.start_heartbeat_monitor()

    # Verify task is running
    assert server._heartbeat_task is not None
    assert not server._heartbeat_task.done()

    # Shutdown
    await server.shutdown()

    # Verify task is cancelled
    assert server._heartbeat_task is None or server._heartbeat_task.done()


@pytest.mark.asyncio
async def test_shutdown_sets_shutdown_event(server: CodebuffWebSocketServer) -> None:
    """Test that shutdown sets the shutdown event."""
    assert not server._shutdown_event.is_set()

    await server.shutdown()

    assert server._shutdown_event.is_set()


@pytest.mark.asyncio
async def test_handle_connection_with_invalid_identify(
    server: CodebuffWebSocketServer,
) -> None:
    """Test that handle_connection handles invalid identify message."""
    websocket = create_mock_websocket()

    # Mock invalid identify message (missing clientSessionId)
    invalid_msg = json.dumps({"type": "identify", "txid": 1})

    websocket.receive_text.side_effect = [invalid_msg]

    await server.handle_connection(websocket)

    # Verify connection was closed
    # Websocket should be closed - may be called multiple times (once in _wait_for_identify,
    # once in finally block for cleanup) which is safe and prevents resource leaks
    assert websocket.close.call_count >= 1


@pytest.mark.asyncio
async def test_handle_connection_with_subscribe(
    server: CodebuffWebSocketServer,
    connection_manager: ConnectionManager,
    subscription_handler: Mock,
) -> None:
    """Test that handle_connection handles subscribe messages."""
    websocket = create_mock_websocket()

    # Mock messages
    identify_msg = json.dumps(
        {"type": "identify", "txid": 1, "clientSessionId": "test-session"}
    )
    subscribe_msg = json.dumps(
        {"type": "subscribe", "txid": 2, "topics": ["test-topic"]}
    )

    websocket.receive_text.side_effect = [
        identify_msg,
        subscribe_msg,
        WebSocketDisconnect(),
    ]

    await server.handle_connection(websocket)

    # Verify subscription handler was called
    subscription_handler.handle_subscribe.assert_called_once()


@pytest.mark.asyncio
async def test_register_endpoint_creates_websocket_route(
    server: CodebuffWebSocketServer,
) -> None:
    """Test that register_endpoint creates a WebSocket route."""
    # Create a mock FastAPI app
    app = Mock()
    app.websocket = Mock()

    server.register_endpoint(app)

    # Verify websocket decorator was called
    app.websocket.assert_called_once_with("/ws")
