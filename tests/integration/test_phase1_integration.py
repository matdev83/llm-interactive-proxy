"""
Integration tests for Phase 1 of the SOLID integration.

These tests verify that the integration bridge properly connects
the old and new architectures.
"""

import pytest
from fastapi.testclient import TestClient
from src.main import build_app


def test_integration_bridge_initialization():
    """Test that the integration bridge initializes both architectures."""
    # Build app using legacy main.py
    app = build_app()
    
    # Verify that both architectures can coexist
    assert hasattr(app.state, 'config')
    
    # The app should build without errors
    assert app is not None


def test_hybrid_endpoints_available():
    """Test that hybrid endpoints are available."""
    app = build_app()
    client = TestClient(app)
    
    # Check that the new hybrid endpoints exist
    # These should be available even if they return errors due to missing config
    response = client.post("/v2/chat/completions", json={
        "model": "test",
        "messages": [{"role": "user", "content": "test"}]
    })
    
    # We expect some kind of response (even if it's an error due to missing auth/config)
    # The important thing is that the endpoint exists and doesn't return 404
    assert response.status_code != 404


def test_legacy_endpoints_still_work():
    """Test that legacy endpoints are still available."""
    app = build_app()
    client = TestClient(app)
    
    # Check that legacy endpoints still exist
    response = client.post("/v1/chat/completions", json={
        "model": "test", 
        "messages": [{"role": "user", "content": "test"}]
    })
    
    # We expect some kind of response (even if it's an error due to missing auth/config)
    # The important thing is that the endpoint exists and doesn't return 404
    assert response.status_code != 404


def test_feature_flags_environment():
    """Test that feature flags can be set via environment variables."""
    import os
    
    # Set a feature flag
    os.environ["USE_NEW_REQUEST_PROCESSOR"] = "true"
    
    try:
        app = build_app()
        
        # The app should still build successfully with feature flags
        assert app is not None
        
    finally:
        # Clean up
        if "USE_NEW_REQUEST_PROCESSOR" in os.environ:
            del os.environ["USE_NEW_REQUEST_PROCESSOR"]


@pytest.mark.asyncio
async def test_integration_bridge_async_initialization():
    """Test that the integration bridge can be initialized asynchronously."""
    from fastapi import FastAPI
    from src.core.integration import IntegrationBridge
    
    app = FastAPI()
    app.state.config = {"command_prefix": "!/"}
    
    bridge = IntegrationBridge(app)
    
    # Should be able to initialize both architectures
    await bridge.initialize_legacy_architecture()
    await bridge.initialize_new_architecture()
    
    # Verify initialization flags
    assert bridge.legacy_initialized
    assert bridge.new_initialized
    
    # Should be able to cleanup
    await bridge.cleanup()


def test_adapter_creation():
    """Test that adapters can be created successfully."""
    from src.core.adapters import (
        create_legacy_config_adapter,
        create_legacy_session_adapter,
    )
    from src.proxy_logic import ProxyState
    from src.session import Session
    
    # Test config adapter
    config = {"test": "value"}
    config_adapter = create_legacy_config_adapter(config)
    assert config_adapter.get("test") == "value"
    
    # Test command adapter - skip for now as it requires complex setup
    # TODO: Add proper CommandParser test when we have a simpler constructor
    # command_parser = CommandParser(config, "!/")
    # command_adapter = create_legacy_command_adapter(command_parser)
    # assert command_adapter is not None
    
    # Test session adapter
    proxy_state = ProxyState()
    session = Session(session_id="test", proxy_state=proxy_state)
    session_adapter = create_legacy_session_adapter(session)
    assert session_adapter.session_id == "test"