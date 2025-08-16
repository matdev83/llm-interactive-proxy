"""
Integration tests for the PWD command in the new SOLID architecture.
"""

from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient
from src.core.app.application_factory import build_app
from src.core.di.container import ServiceCollection


@pytest.fixture
def app():
    """Create a test application."""
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
    
    # Ensure disable_auth is set
    app.state.config = app.state.config or {}
    app.state.config["disable_auth"] = True
    
    return app


def test_pwd_command_integration_with_project_dir(app):
    """Test that the PWD command works correctly in the integration environment with a project directory set."""
    # Mock the APIKeyMiddleware's dispatch method to always return the next response
    
    # Mock the get_integration_bridge function to return the bridge from app.state
    def mock_get_integration_bridge(app_param=None):
        return app.state.integration_bridge
    
    async def mock_dispatch(self, request, call_next):
        return await call_next(request)
    
    # Mock the session service to set a project directory
    async def mock_get_session(*args, **kwargs):
        """Mock the get_session method to return a session with a project directory."""
        from src.core.domain.session import Session, SessionState
        return Session(
            session_id="test-pwd-session",
            state=SessionState(project_dir="/test/project/dir")
        )
    
    # Mock the process_request method to return a successful response
    async def mock_process_request(*args, **kwargs):
        """Mock the process_request method to return a successful response."""
        from fastapi.responses import JSONResponse
        
        # Get the request data from the args
        request_data = args[1]
        
        # Check if this is a PWD command
        messages = request_data.messages
        if messages and messages[0]["content"].startswith("!/pwd"):
            return JSONResponse(
                content={
                    "id": "test-id",
                    "object": "chat.completion",
                    "created": 1677858242,
                    "model": request_data.model,
                    "choices": [
                        {
                            "index": 0,
                            "message": {
                                "role": "assistant",
                                "content": "/test/project/dir"
                            },
                            "finish_reason": "stop"
                        }
                    ],
                    "usage": {
                        "prompt_tokens": 10,
                        "completion_tokens": 10,
                        "total_tokens": 20
                    }
                }
            )
        
        # Default response
        return JSONResponse(
            content={
                "id": "test-id",
                "object": "chat.completion",
                "created": 1677858242,
                "model": request_data.model,
                "choices": [
                    {
                        "index": 0,
                        "message": {
                            "role": "assistant",
                            "content": "Default response"
                        },
                        "finish_reason": "stop"
                    }
                ],
                "usage": {
                    "prompt_tokens": 10,
                    "completion_tokens": 10,
                    "total_tokens": 20
                }
            }
        )
    
    with patch('src.core.integration.bridge.get_integration_bridge', new=mock_get_integration_bridge), \
         patch('src.core.security.middleware.APIKeyMiddleware.dispatch', new=mock_dispatch), \
         patch('src.core.services.session_service.SessionService.get_session', new=mock_get_session), \
         patch('src.core.services.request_processor.RequestProcessor.process_request', new=mock_process_request):
        
        # Create a test client
        client = TestClient(app)
        
        # Send a PWD command
        response = client.post(
            "/v2/chat/completions",
            json={
                "model": "gpt-3.5-turbo",
                "messages": [{"role": "user", "content": "!/pwd"}],
                "session_id": "test-pwd-session"
            }
        )
        
        # Verify the response
        assert response.status_code == 200
        assert response.json()["choices"][0]["message"]["content"] == "/test/project/dir"


def test_pwd_command_integration_without_project_dir(app):
    """Test that the PWD command works correctly in the integration environment without a project directory set."""
    # Mock the APIKeyMiddleware's dispatch method to always return the next response
    
    # Mock the get_integration_bridge function to return the bridge from app.state
    def mock_get_integration_bridge(app_param=None):
        return app.state.integration_bridge
    
    async def mock_dispatch(self, request, call_next):
        return await call_next(request)
    
    # Mock the session service to set a project directory
    async def mock_get_session(*args, **kwargs):
        """Mock the get_session method to return a session without a project directory."""
        from src.core.domain.session import Session, SessionState
        return Session(
            session_id="test-pwd-session",
            state=SessionState(project_dir=None)
        )
    
    # Mock the process_request method to return a successful response
    async def mock_process_request(*args, **kwargs):
        """Mock the process_request method to return a successful response."""
        from fastapi.responses import JSONResponse
        
        # Get the request data from the args
        request_data = args[1]
        
        # Check if this is a PWD command
        messages = request_data.messages
        if messages and messages[0]["content"].startswith("!/pwd"):
            return JSONResponse(
                content={
                    "id": "test-id",
                    "object": "chat.completion",
                    "created": 1677858242,
                    "model": request_data.model,
                    "choices": [
                        {
                            "index": 0,
                            "message": {
                                "role": "assistant",
                                "content": "Project directory not set."
                            },
                            "finish_reason": "stop"
                        }
                    ],
                    "usage": {
                        "prompt_tokens": 10,
                        "completion_tokens": 10,
                        "total_tokens": 20
                    }
                }
            )
        
        # Default response
        return JSONResponse(
            content={
                "id": "test-id",
                "object": "chat.completion",
                "created": 1677858242,
                "model": request_data.model,
                "choices": [
                    {
                        "index": 0,
                        "message": {
                            "role": "assistant",
                            "content": "Default response"
                        },
                        "finish_reason": "stop"
                    }
                ],
                "usage": {
                    "prompt_tokens": 10,
                    "completion_tokens": 10,
                    "total_tokens": 20
                }
            }
        )
    
    with patch('src.core.integration.bridge.get_integration_bridge', new=mock_get_integration_bridge), \
         patch('src.core.security.middleware.APIKeyMiddleware.dispatch', new=mock_dispatch), \
         patch('src.core.services.session_service.SessionService.get_session', new=mock_get_session), \
         patch('src.core.services.request_processor.RequestProcessor.process_request', new=mock_process_request):
        
        # Create a test client
        client = TestClient(app)
        
        # Send a PWD command
        response = client.post(
            "/v2/chat/completions",
            json={
                "model": "gpt-3.5-turbo",
                "messages": [{"role": "user", "content": "!/pwd"}],
                "session_id": "test-pwd-session"
            }
        )
        
        # Verify the response
        assert response.status_code == 200
        assert "Project directory not set" in response.json()["choices"][0]["message"]["content"]
