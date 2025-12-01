"""
Unit tests for InitHandler.

These tests verify the functionality of session initialization,
file context storage, and error handling.
"""

from unittest.mock import MagicMock

import pytest
from src.codebuff.connection_manager import ConnectionManager
from src.codebuff.exceptions import CodebuffSessionError
from src.codebuff.handlers.init_handler import InitHandler
from src.codebuff.schemas import InitAction


class TestInitHandler:
    """Test suite for InitHandler."""

    @pytest.mark.asyncio
    async def test_handle_init_stores_file_context(self):
        """Test that handle_init stores file context in session."""
        # Arrange
        connection_manager = ConnectionManager()
        init_handler = InitHandler(connection_manager)
        websocket = MagicMock()
        session_id = "test-session-123"

        connection_manager.connect(websocket, session_id)

        file_context = {
            "file1.py": {"content": "print('hello')"},
            "file2.py": {"content": "def foo(): pass"},
        }

        init_action = InitAction(
            type="init",
            fingerprintId="test-fingerprint",
            authToken=None,
            fileContext=file_context,
            repoUrl=None,
        )

        # Act
        response = await init_handler.handle_init(websocket, init_action)

        # Assert
        session = connection_manager.get_session(websocket)
        assert session is not None
        assert session.file_context == file_context
        assert response.type == "init-response"
        assert response.usage == 0.0
        assert response.remainingBalance == float("inf")

    @pytest.mark.asyncio
    async def test_handle_init_stores_fingerprint_id(self):
        """Test that handle_init stores fingerprint ID in session."""
        # Arrange
        connection_manager = ConnectionManager()
        init_handler = InitHandler(connection_manager)
        websocket = MagicMock()
        session_id = "test-session-123"

        connection_manager.connect(websocket, session_id)

        init_action = InitAction(
            type="init",
            fingerprintId="test-fingerprint-456",
            authToken=None,
            fileContext={},
            repoUrl=None,
        )

        # Act
        await init_handler.handle_init(websocket, init_action)

        # Assert
        session = connection_manager.get_session(websocket)
        assert session is not None
        assert session.fingerprint_id == "test-fingerprint-456"

    @pytest.mark.asyncio
    async def test_handle_init_stores_auth_token(self):
        """Test that handle_init stores auth token in session."""
        # Arrange
        connection_manager = ConnectionManager()
        init_handler = InitHandler(connection_manager)
        websocket = MagicMock()
        session_id = "test-session-123"

        connection_manager.connect(websocket, session_id)

        init_action = InitAction(
            type="init",
            fingerprintId="test-fingerprint",
            authToken="test-auth-token-789",
            fileContext={},
            repoUrl=None,
        )

        # Act
        await init_handler.handle_init(websocket, init_action)

        # Assert
        session = connection_manager.get_session(websocket)
        assert session is not None
        assert session.auth_token == "test-auth-token-789"

    @pytest.mark.asyncio
    async def test_handle_init_returns_dummy_usage_values(self):
        """Test that handle_init returns dummy usage values for MVP."""
        # Arrange
        connection_manager = ConnectionManager()
        init_handler = InitHandler(connection_manager)
        websocket = MagicMock()
        session_id = "test-session-123"

        connection_manager.connect(websocket, session_id)

        init_action = InitAction(
            type="init",
            fingerprintId="test-fingerprint",
            authToken=None,
            fileContext={},
            repoUrl=None,
        )

        # Act
        response = await init_handler.handle_init(websocket, init_action)

        # Assert
        assert response.type == "init-response"
        assert response.usage == 0.0
        assert response.remainingBalance == float("inf")
        assert response.message == "Session initialized successfully"

    @pytest.mark.asyncio
    async def test_handle_init_with_empty_file_context(self):
        """Test that handle_init works with empty file context."""
        # Arrange
        connection_manager = ConnectionManager()
        init_handler = InitHandler(connection_manager)
        websocket = MagicMock()
        session_id = "test-session-123"

        connection_manager.connect(websocket, session_id)

        init_action = InitAction(
            type="init",
            fingerprintId="test-fingerprint",
            authToken=None,
            fileContext={},
            repoUrl=None,
        )

        # Act
        response = await init_handler.handle_init(websocket, init_action)

        # Assert
        session = connection_manager.get_session(websocket)
        assert session is not None
        assert session.file_context == {}
        assert response.type == "init-response"

    @pytest.mark.asyncio
    async def test_handle_init_unknown_session_raises_error(self):
        """Test that handle_init raises error for unknown session."""
        # Arrange
        connection_manager = ConnectionManager()
        init_handler = InitHandler(connection_manager)
        websocket = MagicMock()

        # Don't connect the websocket

        init_action = InitAction(
            type="init",
            fingerprintId="test-fingerprint",
            authToken=None,
            fileContext={},
            repoUrl=None,
        )

        # Act & Assert
        with pytest.raises(CodebuffSessionError) as exc_info:
            await init_handler.handle_init(websocket, init_action)

        assert "Session not found" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_handle_init_with_large_file_context(self):
        """Test that handle_init handles large file contexts."""
        # Arrange
        connection_manager = ConnectionManager()
        init_handler = InitHandler(connection_manager)
        websocket = MagicMock()
        session_id = "test-session-123"

        connection_manager.connect(websocket, session_id)

        # Create a large file context
        file_context = {
            f"file{i}.py": {"content": f"# File {i}\n" * 100} for i in range(50)
        }

        init_action = InitAction(
            type="init",
            fingerprintId="test-fingerprint",
            authToken=None,
            fileContext=file_context,
            repoUrl=None,
        )

        # Act
        response = await init_handler.handle_init(websocket, init_action)

        # Assert
        session = connection_manager.get_session(websocket)
        assert session is not None
        assert session.file_context == file_context
        assert len(session.file_context) == 50
        assert response.type == "init-response"

    @pytest.mark.asyncio
    async def test_handle_init_response_structure(self):
        """Test that handle_init returns correctly structured response."""
        # Arrange
        connection_manager = ConnectionManager()
        init_handler = InitHandler(connection_manager)
        websocket = MagicMock()
        session_id = "test-session-123"

        connection_manager.connect(websocket, session_id)

        init_action = InitAction(
            type="init",
            fingerprintId="test-fingerprint",
            authToken="test-token",
            fileContext={"file.py": {"content": "test"}},
            repoUrl="https://github.com/test/repo",
        )

        # Act
        response = await init_handler.handle_init(websocket, init_action)

        # Assert - verify response structure
        assert response.type == "init-response"
        assert response.message is not None
        assert isinstance(response.usage, float)
        assert isinstance(response.remainingBalance, float)
        assert response.usage == 0.0
        assert response.remainingBalance == float("inf")

    @pytest.mark.asyncio
    async def test_handle_init_multiple_times_updates_context(self):
        """Test that calling handle_init multiple times updates file context."""
        # Arrange
        connection_manager = ConnectionManager()
        init_handler = InitHandler(connection_manager)
        websocket = MagicMock()
        session_id = "test-session-123"

        connection_manager.connect(websocket, session_id)

        # First init
        init_action1 = InitAction(
            type="init",
            fingerprintId="test-fingerprint",
            authToken=None,
            fileContext={"file1.py": {"content": "first"}},
            repoUrl=None,
        )
        await init_handler.handle_init(websocket, init_action1)

        # Second init with different context
        init_action2 = InitAction(
            type="init",
            fingerprintId="test-fingerprint",
            authToken=None,
            fileContext={"file2.py": {"content": "second"}},
            repoUrl=None,
        )
        await init_handler.handle_init(websocket, init_action2)

        # Assert - should have the second context
        session = connection_manager.get_session(websocket)
        assert session is not None
        assert session.file_context == {"file2.py": {"content": "second"}}
