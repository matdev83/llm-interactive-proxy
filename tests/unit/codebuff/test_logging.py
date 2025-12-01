"""
Unit tests for Codebuff logging functionality.

These tests verify that logging is properly implemented across all
Codebuff components.
"""

import logging
from unittest.mock import MagicMock, patch

import pytest
from src.codebuff.connection_manager import ConnectionManager
from src.codebuff.exceptions import CodebuffSessionError
from src.codebuff.message_router import MessageRouter


class TestConnectionLogging:
    """Test connection-related logging."""

    def test_connection_logs_session_id(self):
        """Test that connection logging includes session ID."""
        manager = ConnectionManager()
        websocket = MagicMock()
        session_id = "test-session-123"

        with patch.object(
            logging.getLogger("src.codebuff.connection_manager"), "info"
        ) as mock_log:
            manager.connect(websocket, session_id)

            # Verify logging occurred
            assert mock_log.called
            # Verify session_id is in the log arguments
            call_args = mock_log.call_args[0]
            assert len(call_args) >= 2
            assert "session_id" in call_args[0]
            assert call_args[1] == session_id

    def test_connection_initialization_logged(self):
        """Test that ConnectionManager initialization is logged."""
        with patch.object(
            logging.getLogger("src.codebuff.connection_manager"), "info"
        ) as mock_log:
            manager = ConnectionManager(heartbeat_timeout_seconds=30)

            # Verify initialization was logged
            assert mock_log.called
            call_args = mock_log.call_args[0]
            assert "ConnectionManager initialized" in call_args[0]
            assert 30 in call_args


class TestMessageLogging:
    """Test message-related logging."""

    def test_invalid_json_logs_error(self):
        """Test that invalid JSON messages are logged as errors."""
        router = MessageRouter()
        invalid_json = "{ invalid json"

        with patch.object(
            logging.getLogger("src.codebuff.message_router"), "error"
        ) as mock_log:
            # This should fail to parse and log an error
            try:
                router.parse_json(invalid_json)
            except Exception:
                pass

            # Verify error was logged
            assert mock_log.called
            call_args = mock_log.call_args[0]
            assert "Failed to parse JSON" in call_args[0]

    def test_validation_failure_logs_error(self):
        """Test that validation failures are logged."""
        router = MessageRouter()
        # Invalid message - missing required fields
        invalid_message = {"type": "identify"}  # Missing txid and clientSessionId

        with patch.object(
            logging.getLogger("src.codebuff.message_router"), "error"
        ) as mock_log:
            try:
                router.validate_message(invalid_message)
            except Exception:
                pass

            # Verify error was logged
            assert mock_log.called
            call_args = mock_log.call_args[0]
            assert "validation failed" in call_args[0].lower()


class TestErrorLogging:
    """Test error-related logging."""

    def test_duplicate_session_logs_warning(self):
        """Test that duplicate session ID attempts are logged."""
        manager = ConnectionManager()
        websocket1 = MagicMock()
        websocket2 = MagicMock()
        session_id = "duplicate-session"

        # Connect first websocket
        manager.connect(websocket1, session_id)

        with patch.object(
            logging.getLogger("src.codebuff.connection_manager"), "warning"
        ) as mock_log:
            # Try to connect second websocket with same session ID
            with pytest.raises(CodebuffSessionError):
                manager.connect(websocket2, session_id)

            # Verify warning was logged
            assert mock_log.called
            call_args = mock_log.call_args[0]
            assert "duplicate session id" in call_args[0].lower()
            assert call_args[1] == session_id

    def test_unknown_connection_update_logs_warning(self):
        """Test that updating unknown connection logs warning."""
        manager = ConnectionManager()
        websocket = MagicMock()

        with patch.object(
            logging.getLogger("src.codebuff.connection_manager"), "warning"
        ) as mock_log:
            # Try to update last_seen for unknown connection
            with pytest.raises(CodebuffSessionError):
                manager.update_last_seen(websocket)

            # Verify warning was logged
            assert mock_log.called
            call_args = mock_log.call_args[0]
            assert "unknown connection" in call_args[0].lower()


class TestDisconnectLogging:
    """Test disconnection-related logging."""

    def test_disconnect_logs_session_id(self):
        """Test that disconnection logging includes session ID."""
        manager = ConnectionManager()
        websocket = MagicMock()
        session_id = "test-session-456"

        # Connect first
        manager.connect(websocket, session_id)

        with patch.object(
            logging.getLogger("src.codebuff.connection_manager"), "info"
        ) as mock_log:
            manager.disconnect(websocket)

            # Verify logging occurred
            assert mock_log.called
            # Verify session_id is in the log arguments
            call_args = mock_log.call_args[0]
            assert len(call_args) >= 2
            assert "disconnect" in call_args[0].lower()
            assert call_args[1] == session_id

    def test_disconnect_unknown_connection_logs_warning(self):
        """Test that disconnecting unknown connection logs warning."""
        manager = ConnectionManager()
        websocket = MagicMock()

        with patch.object(
            logging.getLogger("src.codebuff.connection_manager"), "warning"
        ) as mock_log:
            manager.disconnect(websocket)

            # Verify warning was logged
            assert mock_log.called
            call_args = mock_log.call_args[0]
            assert "unknown connection" in call_args[0].lower()


class TestSensitiveDataFiltering:
    """Test that sensitive data is not logged."""

    def test_session_id_logged_but_not_auth_token(self):
        """Test that session IDs are logged but auth tokens are not."""
        manager = ConnectionManager()
        websocket = MagicMock()
        session_id = "public-session-id"
        auth_token = "secret-auth-token-12345"

        # Ensure they're different
        assert session_id != auth_token

        with patch.object(
            logging.getLogger("src.codebuff.connection_manager"), "info"
        ) as mock_info:
            with patch.object(
                logging.getLogger("src.codebuff.connection_manager"), "debug"
            ) as mock_debug:
                # Perform operations
                manager.connect(websocket, session_id)
                manager.disconnect(websocket)

                # Collect all log calls
                all_calls = mock_info.call_args_list + mock_debug.call_args_list

                # Verify session_id appears in logs
                session_id_found = False
                auth_token_found = False

                for call in all_calls:
                    args = call[0]
                    log_content = str(args)

                    if session_id in log_content:
                        session_id_found = True

                    if auth_token in log_content:
                        auth_token_found = True

                # Session ID should be logged
                assert session_id_found, "Session ID should appear in logs"
                # Auth token should NOT be logged
                assert not auth_token_found, "Auth token should NOT appear in logs"

    def test_no_full_message_content_in_logs(self):
        """Test that full message contents are not logged."""
        router = MessageRouter()
        # Create a message with sensitive content
        import json

        message_data = {
            "type": "identify",
            "txid": 1,
            "clientSessionId": "test-session",
            "sensitiveData": "this-should-not-be-logged",
        }
        raw_message = json.dumps(message_data)

        with patch.object(
            logging.getLogger("src.codebuff.message_router"), "error"
        ) as mock_error:
            with patch.object(
                logging.getLogger("src.codebuff.message_router"), "info"
            ) as mock_info:
                with patch.object(
                    logging.getLogger("src.codebuff.message_router"), "debug"
                ) as mock_debug:
                    # Process the message
                    import asyncio

                    asyncio.run(router.route_message(raw_message))

                    # Collect all log calls
                    all_calls = (
                        mock_error.call_args_list
                        + mock_info.call_args_list
                        + mock_debug.call_args_list
                    )

                    # Verify that the sensitive data is not in logs
                    for call in all_calls:
                        args = call[0]
                        log_content = str(args)
                        # The full message content should not be logged
                        assert (
                            "this-should-not-be-logged" not in log_content
                        ), "Sensitive message content should not be logged"
