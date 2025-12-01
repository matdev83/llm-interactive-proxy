"""
Integration tests for Codebuff WebSocket server startup and configuration.

These tests verify that the Codebuff WebSocket server integrates correctly
with the existing FastAPI infrastructure.
"""

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from src.anthropic_server import create_anthropic_app_async
from src.core.config.app_config import AppConfig


@pytest.mark.asyncio
async def test_codebuff_endpoint_registration_when_enabled() -> None:
    """Test that WebSocket endpoint is registered when Codebuff is enabled.

    Validates: Requirements 10.5
    """
    # Create config with Codebuff enabled
    config = AppConfig.from_env()
    # Override codebuff settings
    config_dict = config.model_dump()
    config_dict["codebuff"] = {
        "enabled": True,
        "websocket_path": "/ws",
        "heartbeat_timeout_seconds": 60,
        "session_cleanup_hours": 1,
        "max_connections": 1000,
        "max_message_size_bytes": 1048576,
    }
    config = AppConfig(**config_dict)

    # Create app
    app = await create_anthropic_app_async(config)

    # Verify app was created
    assert isinstance(app, FastAPI)

    # Verify Codebuff server is attached to app state
    assert hasattr(app.state, "codebuff_server")
    assert app.state.codebuff_server is not None

    # Verify WebSocket endpoint exists
    routes = [route.path for route in app.routes]
    assert "/ws" in routes


@pytest.mark.asyncio
async def test_codebuff_endpoint_not_registered_when_disabled() -> None:
    """Test that WebSocket endpoint is not registered when Codebuff is disabled.

    Validates: Requirements 10.5
    """
    # Create config with Codebuff disabled
    config = AppConfig.from_env()
    # Override codebuff settings
    config_dict = config.model_dump()
    config_dict["codebuff"] = {
        "enabled": False,
        "websocket_path": "/ws",
        "heartbeat_timeout_seconds": 60,
        "session_cleanup_hours": 1,
        "max_connections": 1000,
        "max_message_size_bytes": 1048576,
    }
    config = AppConfig(**config_dict)

    # Create app
    app = await create_anthropic_app_async(config)

    # Verify app was created
    assert isinstance(app, FastAPI)

    # Verify Codebuff server is not attached to app state
    assert not hasattr(app.state, "codebuff_server")

    # Verify WebSocket endpoint does not exist
    routes = [route.path for route in app.routes]
    assert "/ws" not in routes


@pytest.mark.asyncio
async def test_configuration_loading() -> None:
    """Test that Codebuff configuration is loaded correctly.

    Validates: Requirements 10.5
    """
    # Create config with custom Codebuff settings
    config = AppConfig.from_env()
    config_dict = config.model_dump()
    config_dict["codebuff"] = {
        "enabled": True,
        "websocket_path": "/custom-ws",
        "heartbeat_timeout_seconds": 120,
        "session_cleanup_hours": 2,
        "max_connections": 500,
        "max_message_size_bytes": 2097152,
    }
    config = AppConfig(**config_dict)

    # Verify configuration values
    assert config.codebuff.enabled is True
    assert config.codebuff.websocket_path == "/custom-ws"
    assert config.codebuff.heartbeat_timeout_seconds == 120
    assert config.codebuff.session_cleanup_hours == 2
    assert config.codebuff.max_connections == 500
    assert config.codebuff.max_message_size_bytes == 2097152


@pytest.mark.asyncio
async def test_websocket_connection_with_enabled_server() -> None:
    """Test that WebSocket connections can be established when server is enabled.

    Validates: Requirements 10.5
    """
    # Create config with Codebuff enabled
    config = AppConfig.from_env()
    config_dict = config.model_dump()
    config_dict["codebuff"] = {
        "enabled": True,
        "websocket_path": "/ws",
        "heartbeat_timeout_seconds": 60,
        "session_cleanup_hours": 1,
        "max_connections": 1000,
        "max_message_size_bytes": 1048576,
    }
    config = AppConfig(**config_dict)

    # Create app
    app = await create_anthropic_app_async(config)

    # Create test client
    client = TestClient(app)

    # Attempt to connect to WebSocket endpoint
    # Note: We're just verifying the endpoint exists and accepts connections
    # Full protocol testing is done in other test files
    with client.websocket_connect("/ws") as websocket:
        # Connection successful - endpoint is registered and functional
        assert websocket is not None


@pytest.mark.asyncio
async def test_default_configuration_values() -> None:
    """Test that default Codebuff configuration values are correct.

    Validates: Requirements 10.5
    """
    # Create config without overriding Codebuff settings
    config = AppConfig.from_env()

    # Verify default values
    assert config.codebuff.enabled is False
    assert config.codebuff.websocket_path == "/ws"
    assert config.codebuff.heartbeat_timeout_seconds == 60
    assert config.codebuff.session_cleanup_hours == 1
    assert config.codebuff.max_connections == 1000
    assert config.codebuff.max_message_size_bytes == 1048576
