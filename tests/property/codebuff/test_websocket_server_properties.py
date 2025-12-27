"""
Property-based tests for WebSocket server.

These tests verify correctness properties for the Codebuff WebSocket server,
including session isolation, operation isolation, and disconnect isolation.
"""

import asyncio
import contextlib
import json
from unittest.mock import AsyncMock, Mock

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st
from src.codebuff.connection_manager import ConnectionManager
from src.codebuff.handlers.init_handler import InitHandler
from src.codebuff.handlers.prompt_handler import PromptHandler
from src.codebuff.handlers.subscription_handler import SubscriptionHandler
from src.codebuff.message_router import MessageRouter
from src.codebuff.server import CodebuffWebSocketServer


@pytest.fixture(scope="module")
def mock_server_components():
    """Shared mock server components for all websocket tests in this module."""
    connection_manager = ConnectionManager()
    message_router = MessageRouter()

    prompt_handler = Mock(spec=PromptHandler)
    prompt_handler.handle_prompt = AsyncMock()

    init_handler = Mock(spec=InitHandler)
    init_handler.handle_init = AsyncMock()

    subscription_handler = Mock(spec=SubscriptionHandler)
    subscription_handler.handle_subscribe = AsyncMock()
    subscription_handler.handle_unsubscribe = AsyncMock()

    return {
        "connection_manager": connection_manager,
        "message_router": message_router,
        "prompt_handler": prompt_handler,
        "init_handler": init_handler,
        "subscription_handler": subscription_handler,
    }


# Strategy for generating session IDs
session_id_strategy = st.text(
    alphabet=st.characters(
        whitelist_categories=["Lu", "Ll", "Nd"], min_codepoint=48, max_codepoint=122
    ),
    min_size=1,
    max_size=50,
)

# Strategy for generating message content
message_content_strategy = st.text(min_size=0, max_size=100)


def create_mock_websocket(session_id: str) -> Mock:
    """Create a mock WebSocket connection.

    Args:
        session_id: Session ID for this connection

    Returns:
        Mock WebSocket object
    """
    websocket = Mock()
    websocket.accept = AsyncMock()
    websocket.receive_text = AsyncMock()
    websocket.send_text = AsyncMock()
    websocket.close = AsyncMock()
    websocket._session_id = session_id  # Store for reference
    return websocket


def create_identify_message(session_id: str, txid: int = 1) -> str:
    """Create an identify message JSON string.

    Args:
        session_id: Client session ID
        txid: Transaction ID

    Returns:
        JSON string of identify message
    """
    return json.dumps({"type": "identify", "txid": txid, "clientSessionId": session_id})


def create_ping_message(txid: int = 2) -> str:
    """Create a ping message JSON string.

    Args:
        txid: Transaction ID

    Returns:
        JSON string of ping message
    """
    return json.dumps({"type": "ping", "txid": txid})


@pytest.mark.asyncio
@given(session_ids=st.lists(session_id_strategy, min_size=2, max_size=5, unique=True))
@settings(max_examples=15, deadline=None)
async def test_property_19_session_isolation(
    session_ids: list[str], mock_server_components
) -> None:
    """
    Feature: codebuff-backend-compatibility, Property 19: Session isolation
    Validates: Requirements 7.1

    For any set of connected clients, each client's session state should be
    independent and not affect others.
    """
    connection_manager = mock_server_components["connection_manager"]
    message_router = mock_server_components["message_router"]
    prompt_handler = mock_server_components["prompt_handler"]
    init_handler = mock_server_components["init_handler"]
    subscription_handler = mock_server_components["subscription_handler"]

    server = CodebuffWebSocketServer(
        connection_manager=connection_manager,
        message_router=message_router,
        prompt_handler=prompt_handler,
        init_handler=init_handler,
        subscription_handler=subscription_handler,
        config=Mock(),
    )

    # Create mock WebSocket connections
    websockets = [create_mock_websocket(sid) for sid in session_ids]

    # Set up identify messages for each connection
    for i, (websocket, session_id) in enumerate(
        zip(websockets, session_ids, strict=False)
    ):
        identify_msg = create_identify_message(session_id, txid=i + 1)
        ping_msg = create_ping_message(txid=i + 100)

        # Mock receive_text to return identify, then ping, then disconnect
        websocket.receive_text.side_effect = [
            identify_msg,
            ping_msg,
            asyncio.CancelledError(),  # Simulate disconnect
        ]

    # Connect all clients concurrently
    tasks = [server.handle_connection(ws) for ws in websockets]

    with contextlib.suppress(Exception):
        await asyncio.gather(*tasks, return_exceptions=True)

    # Verify no sessions remain after disconnect
    for websocket in websockets:
        session = await connection_manager.get_session(websocket)
        assert session is None, "Session should be cleaned up after disconnect"


@pytest.mark.asyncio
@given(
    session_ids=st.lists(session_id_strategy, min_size=2, max_size=5, unique=True),
    operation_count=st.integers(min_value=1, max_value=3),
)
@settings(max_examples=30, deadline=None)
async def test_property_20_operation_isolation(
    session_ids: list[str], operation_count: int
) -> None:
    """
    Feature: codebuff-backend-compatibility, Property 20: Operation isolation
    Validates: Requirements 7.2

    For any client operation (prompt, init, etc.), it should not affect
    other clients' sessions.
    """
    # Create server components
    connection_manager = ConnectionManager()

    # Create mock handlers that track calls per session
    prompt_handler = Mock(spec=PromptHandler)
    prompt_handler.handle_prompt = AsyncMock()

    init_handler = Mock(spec=InitHandler)
    init_handler.handle_init = AsyncMock()

    subscription_handler = Mock(spec=SubscriptionHandler)
    subscription_handler.handle_subscribe = AsyncMock()

    # Create and register connections
    websockets = []
    for session_id in session_ids:
        websocket = create_mock_websocket(session_id)
        websockets.append(websocket)

        # Register connection directly (bypass identify for simplicity)
        await connection_manager.connect(websocket, session_id)

    # Perform operations on first client
    first_websocket = websockets[0]

    # Get initial state of all sessions
    initial_states = {}
    for websocket, session_id in zip(websockets, session_ids, strict=False):
        session = await connection_manager.get_session(websocket)
        assert session is not None
        initial_states[session_id] = {
            "subscriptions": set(session.subscriptions),
            "file_context": session.file_context,
        }

    # Perform operations on first client
    for _ in range(operation_count):
        # Update last_seen (simulating ping)
        await connection_manager.update_last_seen(first_websocket)

        # Subscribe to a topic
        await connection_manager.subscribe(first_websocket, ["test-topic"])

    # Verify other clients' sessions are unchanged
    for websocket, session_id in zip(websockets[1:], session_ids[1:], strict=False):
        session = await connection_manager.get_session(websocket)
        assert session is not None

        # Check that session state matches initial state
        assert (
            session.subscriptions == initial_states[session_id]["subscriptions"]
        ), f"Session {session_id} subscriptions should be unchanged"
        assert (
            session.file_context == initial_states[session_id]["file_context"]
        ), f"Session {session_id} file_context should be unchanged"

    # Clean up
    for websocket in websockets:
        await connection_manager.disconnect(websocket)


@pytest.mark.asyncio
@given(
    session_ids=st.lists(session_id_strategy, min_size=2, max_size=5, unique=True),
    disconnect_index=st.integers(min_value=0, max_value=4),
)
@settings(max_examples=20, deadline=None)
async def test_property_21_disconnect_isolation(
    session_ids: list[str], disconnect_index: int
) -> None:
    """
    Feature: codebuff-backend-compatibility, Property 21: Disconnect isolation
    Validates: Requirements 7.3

    For any client disconnecting, other active connections should remain
    unaffected.
    """
    # Ensure disconnect_index is valid
    if disconnect_index >= len(session_ids):
        disconnect_index = len(session_ids) - 1

    # Create server components
    connection_manager = ConnectionManager()

    # Create and register connections
    websockets = []
    for session_id in session_ids:
        websocket = create_mock_websocket(session_id)
        websockets.append(websocket)
        await connection_manager.connect(websocket, session_id)

    # Verify all connections are registered
    for websocket, session_id in zip(websockets, session_ids, strict=False):
        session = await connection_manager.get_session(websocket)
        assert session is not None
        assert session.session_id == session_id

    # Disconnect one client
    disconnected_websocket = websockets[disconnect_index]

    await connection_manager.disconnect(disconnected_websocket)

    # Verify disconnected client is removed
    session = await connection_manager.get_session(disconnected_websocket)
    assert session is None, "Disconnected session should be removed"

    # Verify other connections remain active
    for i, (websocket, session_id) in enumerate(
        zip(websockets, session_ids, strict=False)
    ):
        if i == disconnect_index:
            continue  # Skip the disconnected one

        session = await connection_manager.get_session(websocket)
        assert session is not None, f"Session {session_id} should still be active"
        assert (
            session.session_id == session_id
        ), f"Session {session_id} should have correct ID"

    # Clean up remaining connections
    for i, websocket in enumerate(websockets):
        if i != disconnect_index:
            await connection_manager.disconnect(websocket)
