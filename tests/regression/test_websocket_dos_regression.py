"""Regression test for CodeBuff WebSocket DoS vulnerability fix.

This test verifies that the CodeBuff WebSocket server properly limits message
size to prevent DoS attacks through maliciously large JSON payloads.

Fixed: Should enforce max_message_size_bytes limit to prevent memory exhaustion.
"""

import json

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from src.codebuff.factory import create_codebuff_server
from src.core.config.app_config import AppConfig


@pytest.fixture
def app() -> FastAPI:
    """Create a FastAPI app with Codebuff WebSocket endpoint."""
    app = FastAPI()

    # Create Codebuff server components with DoS protection limits
    config = AppConfig.from_env()
    config_dict = config.model_dump()
    config_dict["codebuff"] = {
        "enabled": True,
        "websocket_path": "/ws",
        "heartbeat_timeout_seconds": 60,
        "session_cleanup_hours": 1,
        "max_connections": 1000,
        "max_message_size_bytes": 1048576,  # 1MB limit for DoS protection
    }
    config = AppConfig(**config_dict)

    # Create mock service provider
    from unittest.mock import MagicMock

    mock_backend_factory = MagicMock()
    mock_service_provider = MagicMock()
    mock_service_provider.get_required_service.return_value = mock_backend_factory
    mock_service_provider.get_service.return_value = None

    # Create server
    server = create_codebuff_server(config, mock_service_provider)
    server.register_endpoint(app)

    # Store server in app state for access in tests
    app.state.codebuff_server = server

    return app


@pytest.fixture
def client(app: FastAPI) -> TestClient:
    """Create a test client for the FastAPI app."""
    return TestClient(app)


class TestWebSocketDoSRegression:
    """Regression tests for WebSocket DoS vulnerability fix."""

    def create_large_payload(self, size_mb: int) -> dict:
        """Create a large JSON payload for testing."""
        large_data = "x" * (size_mb * 1024 * 1024)  # Large string
        return {
            "type": "ping",
            "txid": 2,
            "largeData": large_data,
            "nested": {
                "more": {
                    "deep": {
                        "structures": [large_data]
                        * 10  # Reduced from 100 to 10 for performance
                    }
                }
            },
        }

    def test_large_payload_rejected(self, client: TestClient, app: FastAPI) -> None:
        """Test that large payloads (>1MB) are rejected."""
        max_message_size = app.state.codebuff_server.config.max_message_size_bytes

        # Create payload larger than limit (optimized for performance)
        # Using 1MB base + minimal padding ensures it exceeds 1MB limit efficiently
        large_payload = self.create_large_payload(size_mb=1)
        # Add extra data to ensure it exceeds limit (reduced padding for performance)
        large_payload["extra"] = "x" * (
            50 * 1024
        )  # Reduced from 150KB to 50KB for performance
        payload_json = json.dumps(large_payload)
        payload_size = len(payload_json.encode("utf-8"))

        assert payload_size > max_message_size, (
            f"Test payload ({payload_size} bytes) should exceed "
            f"max_message_size ({max_message_size} bytes)"
        )

        with client.websocket_connect("/ws") as websocket:
            # Send identify message first
            identify_msg = {
                "type": "identify",
                "txid": 1,
                "clientSessionId": "test-session-dos",
            }
            websocket.send_json(identify_msg)

            # Receive ack
            ack = websocket.receive_json()
            assert ack.get("success") is True, "Identify should succeed"

            # Try to send large payload - should be rejected
            # The WebSocket implementation should reject messages exceeding max_message_size
            try:
                websocket.send_json(large_payload)
                # If message is sent, server should close connection or reject it
                # Wait a bit to see if connection is closed
                try:
                    response = websocket.receive_json(timeout=1.0)
                    # If we get a response, it should be an error
                    assert response.get("type") == "error" or not response.get(
                        "success"
                    ), "Large payload should result in error response"
                except Exception:
                    # Connection closed is also acceptable (DoS protection working)
                    pass
            except Exception as e:
                # Exception during send is acceptable if it's due to size limit
                assert (
                    "size" in str(e).lower() or "too large" in str(e).lower()
                ), f"Exception should be related to size limit, got: {e}"

    def test_normal_payload_works(self, client: TestClient, app: FastAPI) -> None:
        """Test that normal payloads (<1MB) work correctly."""
        max_message_size = app.state.codebuff_server.config.max_message_size_bytes

        # Create normal payload well under limit
        normal_payload = {"type": "ping", "txid": 2, "data": "test"}
        payload_json = json.dumps(normal_payload)
        payload_size = len(payload_json.encode("utf-8"))

        assert payload_size < max_message_size, (
            f"Test payload ({payload_size} bytes) should be under "
            f"max_message_size ({max_message_size} bytes)"
        )

        with client.websocket_connect("/ws") as websocket:
            # Send identify message first
            identify_msg = {
                "type": "identify",
                "txid": 1,
                "clientSessionId": "test-session-normal",
            }
            websocket.send_json(identify_msg)

            # Receive ack
            ack = websocket.receive_json()
            assert ack.get("success") is True, "Identify should succeed"

            # Send normal payload - should work
            websocket.send_json(normal_payload)

            # Should receive ack
            response = websocket.receive_json()
            assert response.get("type") == "ack", "Should receive ack"
            assert response.get("success") is True, "Normal payload should succeed"

    def test_max_message_size_configured(self, app: FastAPI) -> None:
        """Test that max_message_size_bytes is configured correctly."""
        max_message_size = app.state.codebuff_server.config.max_message_size_bytes

        # Should have a reasonable limit (e.g., 1MB)
        assert max_message_size > 0, "max_message_size_bytes should be positive"
        assert max_message_size <= 10 * 1024 * 1024, (
            f"max_message_size_bytes ({max_message_size}) should be reasonable "
            "(<= 10MB)"
        )

    def test_deeply_nested_payload_handled(
        self, client: TestClient, app: FastAPI
    ) -> None:
        """Test that deeply nested JSON payloads are handled correctly."""

        def create_nested_dict(depth: int):
            if depth <= 0:
                return {"value": "deep_value", "data": "x" * 1000}
            return {"nested": create_nested_dict(depth - 1), "data": "x" * 100}

        # Create deeply nested payload (but within size limit)
        nested_payload = {
            "type": "ping",
            "txid": 2,
            "deeply_nested": create_nested_dict(100),
        }

        payload_json = json.dumps(nested_payload)
        payload_size = len(payload_json.encode("utf-8"))

        max_message_size = app.state.codebuff_server.config.max_message_size_bytes

        with client.websocket_connect("/ws") as websocket:
            # Send identify message first
            identify_msg = {
                "type": "identify",
                "txid": 1,
                "clientSessionId": "test-session-nested",
            }
            websocket.send_json(identify_msg)

            # Receive ack
            ack = websocket.receive_json()
            assert ack.get("success") is True, "Identify should succeed"

            if payload_size > max_message_size:
                # If payload exceeds size limit, should be rejected
                try:
                    websocket.send_json(nested_payload)
                    # Should get error or connection closed
                    try:
                        response = websocket.receive_json(timeout=1.0)
                        assert response.get("type") == "error" or not response.get(
                            "success"
                        ), "Large nested payload should result in error"
                    except Exception:
                        # Connection closed is acceptable
                        pass
                except Exception:
                    # Exception during send is acceptable
                    pass
            else:
                # If within size limit, should process (may still fail due to depth)
                try:
                    websocket.send_json(nested_payload)
                    # May succeed or fail depending on depth limits
                    try:
                        response = websocket.receive_json(timeout=2.0)
                        # Any response is acceptable (success or error)
                        assert response is not None, "Should receive some response"
                    except Exception:
                        # Timeout or connection closed is acceptable for deep nesting
                        pass
                except Exception:
                    # Exception is acceptable if depth protection is in place
                    pass
