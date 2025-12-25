"""
Unit tests for Codebuff PromptHandler.

Tests prompt processing, streaming response handling, error handling,
and cancellation.
"""

import asyncio
import contextlib
from unittest.mock import AsyncMock, Mock, patch

import pytest
from src.codebuff.exceptions import CodebuffError
from src.codebuff.format_converter import FormatConverter
from src.codebuff.handlers.prompt_handler import PromptHandler
from src.codebuff.schemas import PromptAction, SessionState

from tests.mocks.backend_factory import MockBackendFactory
from tests.mocks.connection_manager import MockConnectionManager


@pytest.fixture
def prompt_handler():
    """Create a PromptHandler instance for testing."""
    backend_factory = MockBackendFactory()
    format_converter = FormatConverter()
    connection_manager = MockConnectionManager()
    return PromptHandler(backend_factory, format_converter, connection_manager)


@pytest.fixture
def mock_websocket():
    """Create a mock WebSocket for testing."""
    websocket = Mock()
    websocket.send_json = AsyncMock()
    return websocket


@pytest.fixture
def sample_prompt_action():
    """Create a sample PromptAction for testing."""
    return PromptAction(
        type="prompt",
        promptId="test-prompt-123",
        prompt="Hello, how are you?",
        fingerprintId="test-fingerprint",
        sessionState={"messages": []},
        model="gpt-4",
    )


class TestPromptHandlerInitialization:
    """Tests for PromptHandler initialization."""

    def test_initialization(self, prompt_handler):
        """Test that PromptHandler initializes correctly."""
        assert prompt_handler is not None
        assert prompt_handler._backend_factory is not None
        assert prompt_handler._format_converter is not None
        assert prompt_handler._connection_manager is not None
        assert isinstance(prompt_handler._active_requests, dict)
        assert len(prompt_handler._active_requests) == 0


class TestMessageExtraction:
    """Tests for message extraction from prompt actions."""

    def test_extract_from_prompt_field(self, prompt_handler):
        """Test extracting messages from prompt field."""
        action = PromptAction(
            type="prompt",
            promptId="test-1",
            prompt="Test message",
            fingerprintId="fp-1",
            sessionState={},
        )

        messages = prompt_handler._extract_messages(action)

        assert len(messages) == 1
        assert messages[0].role == "user"
        assert messages[0].content == "Test message"

    def test_extract_from_content_field(self, prompt_handler):
        """Test extracting messages from content field."""
        action = PromptAction(
            type="prompt",
            promptId="test-2",
            content=[
                {"role": "user", "content": "Hello"},
                {"role": "assistant", "content": "Hi there"},
            ],
            fingerprintId="fp-2",
            sessionState={},
        )

        messages = prompt_handler._extract_messages(action)

        assert len(messages) == 2
        assert messages[0].role == "user"
        assert messages[1].role == "assistant"

    def test_extract_from_session_state(self, prompt_handler):
        """Test extracting messages from session state."""
        action = PromptAction(
            type="prompt",
            promptId="test-3",
            fingerprintId="fp-3",
            sessionState={
                "messages": [
                    {"role": "user", "content": "Previous message"},
                ]
            },
        )

        messages = prompt_handler._extract_messages(action)

        assert len(messages) == 1
        assert messages[0].role == "user"
        assert messages[0].content == "Previous message"

    def test_extract_empty_raises_error(self, prompt_handler):
        """Test that extracting from empty action raises error."""
        action = PromptAction(
            type="prompt",
            promptId="test-4",
            fingerprintId="fp-4",
            sessionState={},
        )

        with pytest.raises(CodebuffError) as exc_info:
            prompt_handler._extract_messages(action)

        assert "No messages found" in str(exc_info.value)


class TestBackendRouting:
    """Tests for backend routing based on model names."""

    def test_route_gpt_models_to_openai(self, prompt_handler):
        """Test that GPT models route to OpenAI backend."""
        models = ["gpt-4", "gpt-3.5-turbo", "gpt-4-turbo"]

        for model in models:
            backend_type = prompt_handler._determine_backend_type(model)
            assert backend_type == "openai"

    def test_route_claude_models_to_anthropic(self, prompt_handler):
        """Test that Claude models route to Anthropic backend."""
        models = ["claude-3-opus", "claude-3-sonnet", "claude-2"]

        for model in models:
            backend_type = prompt_handler._determine_backend_type(model)
            assert backend_type == "anthropic"

    def test_route_gemini_models_to_gemini(self, prompt_handler):
        """Test that Gemini models route to Gemini backend."""
        models = ["gemini-pro", "gemini-1.5-pro"]

        for model in models:
            backend_type = prompt_handler._determine_backend_type(model)
            assert backend_type == "gemini"

    def test_unknown_model_defaults_to_openai(self, prompt_handler):
        """Test that unknown models default to OpenAI backend."""
        backend_type = prompt_handler._determine_backend_type("unknown-model-xyz")
        assert backend_type == "openai"


class TestCancellation:
    """Tests for request cancellation."""

    @pytest.mark.asyncio
    async def test_cancel_active_request(self, prompt_handler):
        """Test cancelling an active request."""

        # Create a mock task
        async def mock_task():
            with contextlib.suppress(asyncio.CancelledError):
                await asyncio.sleep(
                    1
                )  # Optimized from 10s - sufficient for cancellation test

        task = asyncio.create_task(mock_task())
        prompt_id = "test-cancel-1"
        prompt_handler._active_requests[prompt_id] = task

        # Cancel the request
        await prompt_handler.cancel_request(prompt_id)

        # Verify request was removed
        assert prompt_id not in prompt_handler._active_requests

        # Wait for task to finish
        with contextlib.suppress(asyncio.CancelledError, asyncio.TimeoutError):
            await asyncio.wait_for(task, timeout=0.1)

        # Verify task was cancelled
        assert task.cancelled() or task.done()

    @pytest.mark.asyncio
    async def test_cancel_nonexistent_request(self, prompt_handler):
        """Test cancelling a non-existent request doesn't raise error."""
        # Should not raise an error
        await prompt_handler.cancel_request("nonexistent-id")


class TestErrorHandling:
    """Tests for error handling in prompt processing."""

    @pytest.mark.asyncio
    async def test_handle_prompt_with_no_session(
        self, prompt_handler, mock_websocket, sample_prompt_action
    ):
        """Test handling prompt when session doesn't exist."""
        # Don't register a session
        await prompt_handler.handle_prompt(mock_websocket, sample_prompt_action)

        # Verify error response was sent
        mock_websocket.send_json.assert_called_once()
        call_args = mock_websocket.send_json.call_args[0][0]
        assert call_args["type"] == "action"
        assert call_args["data"]["type"] == "prompt-error"
        assert "Session not found" in call_args["data"]["message"]

    @pytest.mark.asyncio
    async def test_handle_prompt_with_extraction_error(
        self, prompt_handler, mock_websocket
    ):
        """Test handling prompt when message extraction fails."""
        # Create action with no messages
        action = PromptAction(
            type="prompt",
            promptId="test-error",
            fingerprintId="fp-error",
            sessionState={},
        )

        # Register a session
        from datetime import datetime

        session = SessionState(
            session_id="test-session",
            created_at=datetime.utcnow(),
            last_seen=datetime.utcnow(),
        )
        prompt_handler._connection_manager._sessions[mock_websocket] = session

        # Handle the prompt
        await prompt_handler.handle_prompt(mock_websocket, action)

        # Verify error response was sent
        mock_websocket.send_json.assert_called_once()
        call_args = mock_websocket.send_json.call_args[0][0]
        assert call_args["type"] == "action"
        assert call_args["data"]["type"] == "prompt-error"


class TestPromptProcessing:
    """Tests for complete prompt processing flow."""

    @pytest.mark.asyncio
    async def test_handle_prompt_stores_fingerprint(
        self, prompt_handler, mock_websocket, sample_prompt_action
    ):
        """Test that handling prompt stores fingerprint ID."""
        # Register a session
        from datetime import datetime

        session = SessionState(
            session_id="test-session",
            created_at=datetime.utcnow(),
            last_seen=datetime.utcnow(),
        )
        prompt_handler._connection_manager._sessions[mock_websocket] = session

        # Mock the backend to avoid actual API calls
        with patch.object(prompt_handler, "_stream_response", new_callable=AsyncMock):
            await prompt_handler.handle_prompt(mock_websocket, sample_prompt_action)

            # Verify fingerprint was stored
            assert session.fingerprint_id == sample_prompt_action.fingerprintId

    @pytest.mark.asyncio
    async def test_handle_prompt_stores_auth_token(
        self, prompt_handler, mock_websocket
    ):
        """Test that handling prompt stores auth token."""
        # Create action with auth token
        action = PromptAction(
            type="prompt",
            promptId="test-auth",
            prompt="Test",
            fingerprintId="fp-auth",
            authToken="test-token-123",
            sessionState={},
        )

        # Register a session
        from datetime import datetime

        session = SessionState(
            session_id="test-session",
            created_at=datetime.utcnow(),
            last_seen=datetime.utcnow(),
        )
        prompt_handler._connection_manager._sessions[mock_websocket] = session

        # Mock the backend to avoid actual API calls
        with patch.object(prompt_handler, "_stream_response", new_callable=AsyncMock):
            await prompt_handler.handle_prompt(mock_websocket, action)

            # Verify auth token was stored
            assert session.auth_token == action.authToken
