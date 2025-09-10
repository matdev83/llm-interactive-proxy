"""
Tests for Application Factory

Test suite for the simplified application factory module.
"""

import os
import sys
from unittest.mock import MagicMock, patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

# Add project root to path to ensure imports work
sys.path.insert(
    0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../../../../"))
)

from src.core.app import application_factory
from src.core.app.application_builder import ApplicationBuilder

build_app = application_factory.build_app
from src.core.config.app_config import AppConfig


class TestApplicationBuilderServices:  # Renamed class to reflect testing ApplicationBuilder's service init
    """Tests for ApplicationBuilder's service initialization."""

    @patch(
        "src.core.di.services.get_service_collection"
    )  # Patch get_service_collection where it's imported from
    async def test_initialize_services_registers_all_required_services(
        self, mock_get_service_collection
    ):
        """Test that all required services are registered during build."""
        mock_services = MagicMock()  # Create a mock ServiceCollection
        mock_get_service_collection.return_value = (
            mock_services  # Return it from get_service_collection
        )
        mock_services.build_service_provider.return_value = (
            MagicMock()
        )  # Mock the return of build_service_provider

        config = AppConfig()

        builder = ApplicationBuilder()
        app = await builder.build(config)

        # Verify core services are registered via the app.state.service_provider
        assert hasattr(app.state, "service_provider")
        assert app.state.service_provider is not None
        # You can add more specific assertions here if needed, e.g., checking for specific services
        # from src.core.interfaces.session_service_interface import ISessionService
        # session_service = app.state.service_provider.get_required_service(ISessionService)
        # assert session_service is not None

    @patch("src.core.di.services.get_service_collection")
    async def test_initialize_services_handles_backend_registration(
        self, mock_get_service_collection
    ):
        """Test that backend services are properly registered during build."""
        mock_services = MagicMock()  # Create a mock ServiceCollection
        mock_get_service_collection.return_value = (
            mock_services  # Return it from get_service_collection
        )
        mock_provider = MagicMock()
        mock_provider.get_service.return_value = MagicMock()  # Mock service retrieval
        mock_services.build_service_provider.return_value = mock_provider

        config = AppConfig()

        # Create a builder with all the necessary stages
        from src.core.app.stages import (
            BackendStage,
            CoreServicesStage,
            InfrastructureStage,
        )

        builder = ApplicationBuilder()
        builder.add_stage(CoreServicesStage())
        builder.add_stage(InfrastructureStage())
        builder.add_stage(BackendStage())

        app = await builder.build(config)

        # Verify that IBackendService was registered and can be retrieved
        from src.core.interfaces.backend_service_interface import IBackendService

        # The service provider should be accessible via app.state
        app.state.service_provider = mock_provider
        backend_service = app.state.service_provider.get_service(IBackendService)
        assert backend_service is not None


class TestBuildApp:
    """Tests for build_app function."""

    @patch("src.core.app.application_builder.build_app_async")
    @patch("src.core.config.app_config.AppConfig.from_env")
    def test_build_app_loads_config(self, mock_from_env, mock_build_app_async):
        """Test that build_app loads configuration."""
        mock_config_instance = MagicMock()
        mock_from_env.return_value = mock_config_instance
        mock_fastapi_app = MagicMock(spec=FastAPI)

        # Create a coroutine mock that returns the FastAPI app
        async def mock_async_build(config):
            return mock_fastapi_app

        mock_build_app_async.return_value = mock_async_build(mock_config_instance)

        app = build_app()

        # Verify AppConfig.from_env was called
        mock_from_env.assert_called_once()

        # Verify build_app_async was called with the config
        mock_build_app_async.assert_called_once_with(mock_config_instance)

        # Verify the app is returned
        assert app is mock_fastapi_app

    @patch("src.core.app.application_builder.build_app_async")
    @patch("src.core.config.app_config.AppConfig.from_env")
    def test_build_app_creates_fastapi_app(self, mock_from_env, mock_build_app_async):
        """Test that build_app creates a FastAPI application."""
        mock_config_instance = MagicMock()
        mock_from_env.return_value = mock_config_instance

        # Mock FastAPI app with title
        mock_fastapi_app = MagicMock(spec=FastAPI, title="LLM Interactive Proxy")

        # Create a coroutine mock that returns the FastAPI app
        async def mock_async_build(config):
            return mock_fastapi_app

        mock_build_app_async.return_value = mock_async_build(mock_config_instance)

        app = build_app()

        assert app is mock_fastapi_app
        assert app.title == "LLM Interactive Proxy"

    @patch("src.core.app.application_builder.build_app_async")
    @patch("src.core.config.app_config.AppConfig.from_env")
    def test_build_app_sets_up_app_state(self, mock_from_env, mock_build_app_async):
        """Test that build_app sets up app state correctly."""
        mock_config_instance = MagicMock()
        mock_from_env.return_value = mock_config_instance

        # Create a mock FastAPI app
        mock_fastapi_app = MagicMock(spec=FastAPI)

        # Create a proper state mock object
        mock_state = MagicMock()
        mock_state.app_config = mock_config_instance
        mock_state.service_provider = MagicMock()
        mock_state.service_provider.get_service = MagicMock()

        # Attach the state to the app
        mock_fastapi_app.state = mock_state

        # Create a coroutine mock that returns the FastAPI app
        async def mock_async_build(config):
            return mock_fastapi_app

        mock_build_app_async.return_value = mock_async_build(mock_config_instance)

        app = build_app()

        # Verify the app state is set up correctly
        assert hasattr(app.state, "app_config")
        assert hasattr(app.state, "service_provider")
        assert hasattr(app.state.service_provider, "get_service")
        assert app.state.app_config == mock_config_instance


class TestIntegration:
    """Integration tests for the application factory."""

    def test_app_handles_models_endpoint(self, monkeypatch):
        """Test that the /models endpoint is available."""
        monkeypatch.setenv("DISABLE_AUTH", "true")
        monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")

        # Create a config with auth disabled
        config = AppConfig()
        config.auth.disable_auth = True

        app = build_app(config=config)

        with TestClient(app) as client:
            response = client.get("/models")
            assert response.status_code == 200
            assert "data" in response.json()

    def test_app_dependency_injection_works(self, monkeypatch):
        """Test that dependency injection is properly configured."""
        monkeypatch.setenv("DISABLE_AUTH", "true")
        config = AppConfig()
        config.auth.disable_auth = True

        app = build_app(config=config)

        with TestClient(app):
            # Verify service provider is available after startup
            assert hasattr(app.state, "service_provider")
            assert app.state.service_provider is not None

            # Verify we can get services from the provider
            from src.core.interfaces.session_service_interface import ISessionService

            session_service = app.state.service_provider.get_required_service(
                ISessionService
            )
            assert session_service is not None
