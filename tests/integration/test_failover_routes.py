"""
Integration tests for failover routes in the new SOLID architecture.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient
from src.core.app.application_factory import build_app
from src.core.di.container import ServiceCollection
from src.core.domain.configuration.backend_config import BackendConfiguration
from src.core.interfaces.configuration import IConfig
from src.core.services.failover_service import FailoverService


@pytest.fixture
def app(monkeypatch):
    """Create a test application."""
    # Patch the configure_middleware function to disable authentication
    
    # Patch the config to disable authentication
    with patch('src.core.app.middleware_config.configure_middleware'):
        # Build the app
        app = build_app()
        
        # Create and set up a service provider manually for testing
        services = ServiceCollection()
        service_provider = services.build_service_provider()
        app.state.service_provider = service_provider
        
        # Initialize the integration bridge
        from src.core.integration.bridge import IntegrationBridge
        bridge = IntegrationBridge(app)
        app.state.integration_bridge = bridge
        
        # Set up failover routes for testing
        app.state.failover_routes = {
            "test-model": {
                "policy": "k",
                "elements": ["openai:gpt-4", "anthropic:claude-3-opus"]
            },
            "test-model-m": {
                "policy": "m",
                "elements": ["openai:gpt-4", "anthropic:claude-3-opus"]
            },
            "test-model-km": {
                "policy": "km",
                "elements": ["openai:gpt-4", "anthropic:claude-3-opus"]
            },
            "test-model-mk": {
                "policy": "mk",
                "elements": ["openai:gpt-4", "anthropic:claude-3-opus"]
            }
        }
        
        # Ensure disable_auth is set
        app.state.config = app.state.config or {}
        app.state.config["disable_auth"] = True
        
        return app


def test_failover_route_commands(app, monkeypatch):
    """Test failover route commands in the new architecture."""
    # Mock the APIKeyMiddleware's dispatch method to always return the next response
    
    # Patch the get_integration_bridge function to return the bridge from app.state
    def mock_get_integration_bridge(app_param=None):
        return app.state.integration_bridge
    
    async def mock_dispatch(self, request, call_next):
        return await call_next(request)
    
    with patch('src.core.integration.bridge.get_integration_bridge', new=mock_get_integration_bridge), \
         patch('src.core.security.middleware.APIKeyMiddleware.dispatch', new=mock_dispatch):
        # Create a test client
        client = TestClient(app)
        
        # Create a new failover route
        response = client.post(
            "/v2/chat/completions",
            json={
                "model": "gpt-3.5-turbo",
                "messages": [{"role": "user", "content": "!/create-failover-route(name=test-route,policy=k)"}],
                "session_id": "test-failover-session"
            }
        )
        
        assert response.status_code == 200
        assert "Failover route 'test-route' created with policy 'k'" in response.json()["choices"][0]["message"]["content"]
        
        # Append an element to the route
        response = client.post(
            "/v2/chat/completions",
            json={
                "model": "gpt-3.5-turbo",
                "messages": [{"role": "user", "content": "!/route-append(name=test-route,element=openai:gpt-4)"}],
                "session_id": "test-failover-session"
            }
        )
        
        assert response.status_code == 200
        assert "Element 'openai:gpt-4' appended to failover route 'test-route'" in response.json()["choices"][0]["message"]["content"]
        
        # List the route elements
        response = client.post(
            "/v2/chat/completions",
            json={
                "model": "gpt-3.5-turbo",
                "messages": [{"role": "user", "content": "!/route-list(name=test-route)"}],
                "session_id": "test-failover-session"
            }
        )
        
        assert response.status_code == 200
        assert "openai:gpt-4" in response.json()["choices"][0]["message"]["content"]
        
        # Prepend an element to the route
        response = client.post(
            "/v2/chat/completions",
            json={
                "model": "gpt-3.5-turbo",
                "messages": [{"role": "user", "content": "!/route-prepend(name=test-route,element=anthropic:claude-3-opus)"}],
                "session_id": "test-failover-session"
            }
        )
        
        assert response.status_code == 200
        assert "Element 'anthropic:claude-3-opus' prepended to failover route 'test-route'" in response.json()["choices"][0]["message"]["content"]
        
        # List all routes
        response = client.post(
            "/v2/chat/completions",
            json={
                "model": "gpt-3.5-turbo",
                "messages": [{"role": "user", "content": "!/list-failover-routes"}],
                "session_id": "test-failover-session"
            }
        )
        
        assert response.status_code == 200
        assert "test-route" in response.json()["choices"][0]["message"]["content"]
        
        # Clear the route
        response = client.post(
            "/v2/chat/completions",
            json={
                "model": "gpt-3.5-turbo",
                "messages": [{"role": "user", "content": "!/route-clear(name=test-route)"}],
                "session_id": "test-failover-session"
            }
        )
        
        assert response.status_code == 200
        assert "All elements cleared from failover route 'test-route'" in response.json()["choices"][0]["message"]["content"]
        
        # Delete the route
        response = client.post(
            "/v2/chat/completions",
            json={
                "model": "gpt-3.5-turbo",
                "messages": [{"role": "user", "content": "!/delete-failover-route(name=test-route)"}],
                "session_id": "test-failover-session"
            }
        )
        
        assert response.status_code == 200
        assert "Failover route 'test-route' deleted" in response.json()["choices"][0]["message"]["content"]


@pytest.mark.asyncio
async def test_failover_service():
    """Test the failover service."""
    # Create a mock config
    mock_config = MagicMock(spec=IConfig)
    mock_config.get.side_effect = lambda key, default=None: {
        "openai_api_keys": {"key1": "test-key-1", "key2": "test-key-2"},
        "anthropic_api_keys": {"key1": "test-key-1"},
    }.get(key, default)
    
    # Create the failover service
    failover_service = FailoverService(mock_config)
    
    # Create a test backend configuration
    backend_config = BackendConfiguration(
        backend_type="openai",
        model="gpt-4",
        failover_routes={
            "gpt-4": {
                "policy": "k",
                "elements": ["openai:gpt-4"]
            },
            "test-m": {
                "policy": "m",
                "elements": ["openai:gpt-4", "anthropic:claude-3-opus"]
            },
            "test-km": {
                "policy": "km",
                "elements": ["openai:gpt-4", "anthropic:claude-3-opus"]
            },
            "test-mk": {
                "policy": "mk",
                "elements": ["openai:gpt-4", "anthropic:claude-3-opus"]
            }
        }
    )
    
    # Test policy "k" (single backend, all keys)
    attempts = failover_service.get_failover_attempts(backend_config, "gpt-4", "openai")
    assert len(attempts) == 2  # Two keys for openai
    assert all(attempt.backend == "openai" for attempt in attempts)
    assert all(attempt.model == "gpt-4" for attempt in attempts)
    
    # Test policy "m" (multiple backends, first key for each)
    attempts = failover_service.get_failover_attempts(backend_config, "test-m", "openai")
    assert len(attempts) == 2  # One key from each backend
    assert attempts[0].backend == "openai"
    assert attempts[0].model == "gpt-4"
    assert attempts[1].backend == "anthropic"
    assert attempts[1].model == "claude-3-opus"
    
    # Test policy "km" (all keys for all models)
    attempts = failover_service.get_failover_attempts(backend_config, "test-km", "openai")
    assert len(attempts) == 3  # Two keys for openai + one key for anthropic
    
    # Test policy "mk" (round-robin keys across models)
    attempts = failover_service.get_failover_attempts(backend_config, "test-mk", "openai")
    assert len(attempts) == 3  # Two rounds of keys (2 for openai, 1 for anthropic)


@pytest.mark.asyncio
async def test_backend_service_failover():
    """Test the backend service failover functionality."""
    # Create a mock config
    mock_config = MagicMock(spec=IConfig)
    mock_config.get.side_effect = lambda key, default=None: {
        "openai_api_keys": {"key1": "test-key-1"},
        "anthropic_api_keys": {"key1": "test-key-1"},
    }.get(key, default)
    
    # Create a mock backend factory
    mock_factory = MagicMock()
    mock_backend = AsyncMock()
    mock_factory.create_backend.return_value = mock_backend
    mock_factory.initialize_backend = AsyncMock()
    
    # Create a mock rate limiter
    mock_rate_limiter = AsyncMock()
    mock_rate_limiter.check_limit = AsyncMock(return_value=MagicMock(is_limited=False))
    mock_rate_limiter.record_usage = AsyncMock()
    
    # Create the failover service with mock config
    failover_service = FailoverService(mock_config)
    
    # Create the backend service
    from src.core.services.backend_service import BackendService
    backend_service = BackendService(
        factory=mock_factory,
        rate_limiter=mock_rate_limiter,
        config=mock_config,
        failover_routes={
            "test-model": {
                "policy": "k",
                "elements": ["openai:gpt-4", "anthropic:claude-3-opus"]
            }
        }
    )
    
    # Replace the failover service with our mocked one
    backend_service._failover_service = failover_service
    
    # Create a test request
    from src.core.domain.chat import ChatMessage, ChatRequest
    request = ChatRequest(
        model="test-model",
        messages=[ChatMessage(role="user", content="Hello")],
        extra_body={"backend_type": "openai"}
    )
    
    # Mock the backend to fail on the first call but succeed on the second
    mock_backend.chat_completions = AsyncMock(side_effect=[
        Exception("Test error"),  # First call fails
        ({"id": "test", "choices": [{"message": {"content": "Success"}}]}, {})  # Second call succeeds
    ])
    
    # Override the _get_or_create_backend method to always return our mock backend
    backend_service._get_or_create_backend = AsyncMock(return_value=mock_backend)
    
    # Call the backend service
    response = await backend_service.call_completion(request)
    
    # Verify that the response is from the successful call
    assert response.id == "test"
    assert response.choices[0]["message"]["content"] == "Success"
    
    # Verify that the backend was called twice
    assert mock_backend.chat_completions.call_count == 2


if __name__ == "__main__":
    pytest.main(["-xvs", __file__])
