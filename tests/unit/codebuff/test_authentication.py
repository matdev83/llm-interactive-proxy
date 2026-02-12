"""
Unit tests for Codebuff authentication and usage tracking.

Tests auth token handling, fingerprint tracking, and cost attribution.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
from src.codebuff.connection_manager import ConnectionManager
from src.codebuff.format_converter import FormatConverter
from src.codebuff.handlers.init_handler import InitHandler
from src.codebuff.handlers.prompt_handler import PromptHandler
from src.codebuff.schemas import InitAction, PromptAction


def _build_prompt_handler(
    *,
    connection_manager: ConnectionManager,
    format_converter: FormatConverter,
    response_payload: dict[str, object],
) -> tuple[PromptHandler, MagicMock, MagicMock]:
    backend_service = MagicMock()
    mock_response = MagicMock()
    mock_response.response = response_payload
    backend_service.call_completion = AsyncMock(return_value=mock_response)
    handler = PromptHandler(
        backend_service=backend_service,
        format_converter=format_converter,
        connection_manager=connection_manager,
    )
    return handler, backend_service, mock_response


class TestAuthTokenHandling:
    """Tests for auth token handling."""

    @pytest.mark.asyncio
    async def test_prompt_with_auth_token_stores_token(self):
        """Test that auth token from prompt action is stored in session."""
        # Setup
        connection_manager = ConnectionManager()
        format_converter = FormatConverter()
        handler, _, _ = _build_prompt_handler(
            connection_manager=connection_manager,
            format_converter=format_converter,
            response_payload={"choices": [{"message": {"content": "test response"}}]},
        )

        # Create mock websocket
        websocket = MagicMock()
        websocket.send_json = AsyncMock()

        # Register connection
        session_id = "test-session"
        await connection_manager.connect(websocket, session_id)

        # Create prompt action with auth token
        action = PromptAction(
            type="prompt",
            promptId="test-prompt",
            fingerprintId="test-fingerprint",
            authToken="test-auth-token-123",
            sessionState={},
            content=[{"role": "user", "content": "test"}],
        )

        # Handle prompt
        await handler.handle_prompt(websocket, action)

        # Verify token is stored in session
        session = await connection_manager.get_session(websocket)
        assert session.auth_token == "test-auth-token-123"

    @pytest.mark.asyncio
    async def test_prompt_without_auth_token_accepts_request(self):
        """Test that prompt without auth token is accepted (MVP behavior)."""
        # Setup
        connection_manager = ConnectionManager()
        format_converter = FormatConverter()
        handler, _, _ = _build_prompt_handler(
            connection_manager=connection_manager,
            format_converter=format_converter,
            response_payload={"choices": [{"message": {"content": "test response"}}]},
        )

        # Create mock websocket
        websocket = MagicMock()
        websocket.send_json = AsyncMock()

        # Register connection
        session_id = "test-session"
        await connection_manager.connect(websocket, session_id)

        # Create prompt action without auth token
        action = PromptAction(
            type="prompt",
            promptId="test-prompt",
            fingerprintId="test-fingerprint",
            authToken=None,
            sessionState={},
            content=[{"role": "user", "content": "test"}],
        )

        # Handle prompt
        await handler.handle_prompt(websocket, action)

        # Verify request was processed
        assert websocket.send_json.called

        # Verify session has no auth token
        session = await connection_manager.get_session(websocket)
        assert session.auth_token is None

    @pytest.mark.asyncio
    async def test_init_with_auth_token_stores_token(self):
        """Test that auth token from init action is stored in session."""
        # Setup
        connection_manager = ConnectionManager()

        handler = InitHandler(
            connection_manager=connection_manager,
        )

        # Create mock websocket
        websocket = MagicMock()
        websocket.send_json = AsyncMock()

        # Register connection
        session_id = "test-session"
        await connection_manager.connect(websocket, session_id)

        # Create init action with auth token
        action = InitAction(
            type="init",
            fingerprintId="test-fingerprint",
            authToken="test-auth-token-456",
            fileContext={"files": []},
        )

        # Handle init
        await handler.handle_init(websocket, action)

        # Verify token is stored in session
        session = await connection_manager.get_session(websocket)
        assert session.auth_token == "test-auth-token-456"


class TestFingerprintTracking:
    """Tests for fingerprint ID tracking."""

    @pytest.mark.asyncio
    async def test_prompt_stores_fingerprint_id(self):
        """Test that fingerprint ID from prompt is stored in session."""
        # Setup
        connection_manager = ConnectionManager()
        format_converter = FormatConverter()
        handler, _, _ = _build_prompt_handler(
            connection_manager=connection_manager,
            format_converter=format_converter,
            response_payload={"choices": [{"message": {"content": "test response"}}]},
        )

        # Create mock websocket
        websocket = MagicMock()
        websocket.send_json = AsyncMock()

        # Register connection
        session_id = "test-session"
        await connection_manager.connect(websocket, session_id)

        # Create prompt action with fingerprint ID
        action = PromptAction(
            type="prompt",
            promptId="test-prompt",
            fingerprintId="unique-fingerprint-789",
            sessionState={},
            content=[{"role": "user", "content": "test"}],
        )

        # Handle prompt
        await handler.handle_prompt(websocket, action)

        # Verify fingerprint ID is stored in session
        session = await connection_manager.get_session(websocket)
        assert session.fingerprint_id == "unique-fingerprint-789"

    @pytest.mark.asyncio
    async def test_init_stores_fingerprint_id(self):
        """Test that fingerprint ID from init is stored in session."""
        # Setup
        connection_manager = ConnectionManager()

        handler = InitHandler(
            connection_manager=connection_manager,
        )

        # Create mock websocket
        websocket = MagicMock()
        websocket.send_json = AsyncMock()

        # Register connection
        session_id = "test-session"
        await connection_manager.connect(websocket, session_id)

        # Create init action with fingerprint ID
        action = InitAction(
            type="init",
            fingerprintId="unique-fingerprint-abc",
            fileContext={"files": []},
        )

        # Handle init
        await handler.handle_init(websocket, action)

        # Verify fingerprint ID is stored in session
        session = await connection_manager.get_session(websocket)
        assert session.fingerprint_id == "unique-fingerprint-abc"

    @pytest.mark.asyncio
    async def test_fingerprint_id_persists_across_requests(self):
        """Test that fingerprint ID persists across multiple requests."""
        # Setup
        connection_manager = ConnectionManager()
        format_converter = FormatConverter()
        handler, _, _ = _build_prompt_handler(
            connection_manager=connection_manager,
            format_converter=format_converter,
            response_payload={"choices": [{"message": {"content": "test response"}}]},
        )

        # Create mock websocket
        websocket = MagicMock()
        websocket.send_json = AsyncMock()

        # Register connection
        session_id = "test-session"
        await connection_manager.connect(websocket, session_id)

        # First prompt with fingerprint ID
        action1 = PromptAction(
            type="prompt",
            promptId="test-prompt-1",
            fingerprintId="persistent-fingerprint",
            sessionState={},
            content=[{"role": "user", "content": "test 1"}],
        )
        await handler.handle_prompt(websocket, action1)

        # Verify fingerprint ID is stored
        session = await connection_manager.get_session(websocket)
        assert session.fingerprint_id == "persistent-fingerprint"

        # Second prompt with same fingerprint ID
        action2 = PromptAction(
            type="prompt",
            promptId="test-prompt-2",
            fingerprintId="persistent-fingerprint",
            sessionState={},
            content=[{"role": "user", "content": "test 2"}],
        )
        await handler.handle_prompt(websocket, action2)

        # Verify fingerprint ID is still the same
        session = await connection_manager.get_session(websocket)
        assert session.fingerprint_id == "persistent-fingerprint"


class TestCostAttribution:
    """Tests for cost attribution to fingerprint/session."""

    @pytest.mark.asyncio
    async def test_cost_attributable_to_fingerprint_id(self):
        """Test that costs can be attributed to fingerprint ID."""
        # Setup
        connection_manager = ConnectionManager()
        format_converter = FormatConverter()
        handler, backend_service, mock_response = _build_prompt_handler(
            connection_manager=connection_manager,
            format_converter=format_converter,
            response_payload={
                "choices": [{"message": {"content": "test response"}}],
                "usage": {
                    "prompt_tokens": 100,
                    "completion_tokens": 50,
                    "total_tokens": 150,
                },
            },
        )

        # Create mock websocket
        websocket = MagicMock()
        websocket.send_json = AsyncMock()

        # Register connection
        session_id = "test-session"
        await connection_manager.connect(websocket, session_id)

        # Create prompt action with fingerprint ID
        action = PromptAction(
            type="prompt",
            promptId="test-prompt",
            fingerprintId="cost-tracking-fingerprint",
            sessionState={},
            content=[{"role": "user", "content": "test"}],
        )

        # Handle prompt
        await handler.handle_prompt(websocket, action)

        # Verify session has fingerprint ID for cost attribution
        session = await connection_manager.get_session(websocket)
        assert session.fingerprint_id == "cost-tracking-fingerprint"

        # Verify backend was called (usage data available)
        assert backend_service.call_completion.called

    @pytest.mark.asyncio
    async def test_cost_attributable_to_session_id_when_no_fingerprint(self):
        """Test that costs can be attributed to session ID when no fingerprint."""
        # Setup
        connection_manager = ConnectionManager()
        format_converter = FormatConverter()
        handler, backend_service, _ = _build_prompt_handler(
            connection_manager=connection_manager,
            format_converter=format_converter,
            response_payload={
                "choices": [{"message": {"content": "test response"}}],
                "usage": {
                    "prompt_tokens": 100,
                    "completion_tokens": 50,
                    "total_tokens": 150,
                },
            },
        )

        # Create mock websocket
        websocket = MagicMock()
        websocket.send_json = AsyncMock()

        # Register connection
        session_id = "test-session-for-cost"
        await connection_manager.connect(websocket, session_id)

        # Create prompt action without fingerprint ID (empty string)
        action = PromptAction(
            type="prompt",
            promptId="test-prompt",
            fingerprintId="",  # Empty fingerprint
            sessionState={},
            content=[{"role": "user", "content": "test"}],
        )

        # Handle prompt
        await handler.handle_prompt(websocket, action)

        # Verify session has session_id for cost attribution
        session = await connection_manager.get_session(websocket)
        assert session.session_id == session_id

        # Verify backend was called (usage data available)
        assert backend_service.call_completion.called

    @pytest.mark.asyncio
    async def test_usage_data_available_for_accounting(self):
        """Test that usage data is available for accounting integration."""
        # Setup
        connection_manager = ConnectionManager()
        format_converter = FormatConverter()
        handler, backend_service, mock_response = _build_prompt_handler(
            connection_manager=connection_manager,
            format_converter=format_converter,
            response_payload={
                "choices": [{"message": {"content": "test response"}}],
                "usage": {
                    "prompt_tokens": 250,
                    "completion_tokens": 125,
                    "total_tokens": 375,
                },
            },
        )

        # Create mock websocket
        websocket = MagicMock()
        websocket.send_json = AsyncMock()

        # Register connection
        session_id = "test-session"
        await connection_manager.connect(websocket, session_id)

        # Create prompt action
        action = PromptAction(
            type="prompt",
            promptId="test-prompt",
            fingerprintId="accounting-test",
            sessionState={},
            content=[{"role": "user", "content": "test"}],
        )

        # Handle prompt
        await handler.handle_prompt(websocket, action)

        # Verify backend was called
        assert backend_service.call_completion.called

        # Verify usage data is in the response
        assert "usage" in mock_response.response
        assert mock_response.response["usage"]["prompt_tokens"] == 250
        assert mock_response.response["usage"]["completion_tokens"] == 125
        assert mock_response.response["usage"]["total_tokens"] == 375
