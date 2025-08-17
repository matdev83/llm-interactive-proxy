"""
Integration tests for the PWD command in the new SOLID architecture.
"""

from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient
from src.core.app.application_factory import build_app


@pytest.fixture
def app():
    """Create a test application."""
    # Build the app
    app = build_app()

    # Manually set up services for testing since lifespan isn't called in tests
    import httpx
    from src.core.app.application_factory import ServiceConfigurator
    from src.core.config.app_config import AppConfig
    from src.core.di.services import set_service_provider

    # Ensure config exists
    app.state.app_config = app.state.app_config or AppConfig()
    app.state.app_config.auth.disable_auth = True

    # Create httpx client for services
    app.state.httpx_client = httpx.AsyncClient()

    # Create service provider
    configurator = ServiceConfigurator()
    service_provider = configurator.configure_services(app.state.app_config)

    # Store the service provider
    set_service_provider(service_provider)
    app.state.service_provider = service_provider

    # Initialize the integration bridge
    from src.core.integration.bridge import IntegrationBridge

    bridge = IntegrationBridge(app)
    bridge.new_initialized = True  # Mark new architecture as initialized
    app.state.integration_bridge = bridge

    # Auth is already disabled above

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
            state=SessionState(project_dir="/test/project/dir"),
        )

    with (
        patch(
            "src.core.integration.bridge.get_integration_bridge",
            new=mock_get_integration_bridge,
        ),
        patch(
            "src.core.security.middleware.APIKeyMiddleware.dispatch", new=mock_dispatch
        ),
        patch(
            "src.core.services.session_service.SessionService.get_session",
            new=mock_get_session,
        ),
    ):
        # Create a test client
        client = TestClient(app)

        # Send a PWD command
        response = client.post(
            "/v2/chat/completions",
            json={
                "model": "gpt-3.5-turbo",
                "messages": [{"role": "user", "content": "!/pwd"}],
                "session_id": "test-pwd-session",
            },
        )

        # Verify the response
        assert response.status_code == 200
        assert (
            response.json()["choices"][0]["message"]["content"] == "/test/project/dir"
        )


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
            session_id="test-pwd-session", state=SessionState(project_dir=None)
        )

    with (
        patch(
            "src.core.integration.bridge.get_integration_bridge",
            new=mock_get_integration_bridge,
        ),
        patch(
            "src.core.security.middleware.APIKeyMiddleware.dispatch", new=mock_dispatch
        ),
        patch(
            "src.core.services.session_service.SessionService.get_session",
            new=mock_get_session,
        ),
    ):
        # Create a test client
        client = TestClient(app)

        # Send a PWD command
        response = client.post(
            "/v2/chat/completions",
            json={
                "model": "gpt-3.5-turbo",
                "messages": [{"role": "user", "content": "!/pwd"}],
                "session_id": "test-pwd-session",
            },
        )

        # Verify the response
        assert response.status_code == 200
        assert (
            "Project directory not set"
            in response.json()["choices"][0]["message"]["content"]
        )
