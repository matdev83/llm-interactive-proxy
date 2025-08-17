"""
Tests for Application Factory

Test suite for the simplified application factory module.
"""

from unittest.mock import MagicMock, patch

from fastapi import FastAPI
from fastapi.testclient import TestClient
from src.core.app.application_factory import ServiceConfigurator, build_app
from src.core.config.app_config import AppConfig


class TestCreateServiceProvider:
    """Tests for ServiceConfigurator."""

    def test_create_service_provider_registers_all_required_services(self):
        """Test that all required services are registered."""
        config = AppConfig()

        with patch(
            "src.core.app.application_factory.get_service_collection"
        ) as mock_collection:
            mock_services = MagicMock()
            mock_collection.return_value = mock_services

            service_configurator = ServiceConfigurator()
            _ = service_configurator.configure_services(
                config
            )  # Assign to unused variable to avoid F841

            # Verify core services are registered
            assert mock_services.add_instance.called
            assert mock_services.add_singleton.called
            assert mock_services.build_service_provider.called

    def test_create_service_provider_handles_backend_registration(self):
        """Test that backend services are properly registered."""
        config = AppConfig()

        with patch(
            "src.core.app.application_factory.get_service_collection"
        ) as mock_collection:
            mock_services = MagicMock()
            mock_collection.return_value = mock_services

            service_configurator = ServiceConfigurator()
            _ = service_configurator.configure_services(
                config
            )  # Assign to unused variable to avoid F841

            # Verify backend factory registration through factory functions
            assert mock_services.add_singleton_factory.called


class TestBuildApp:
    """Tests for build_app function."""

    def test_build_app_loads_config(self):
        """Test that build_app loads configuration."""
        with (
            patch("src.core.app.application_factory.load_config") as mock_load,
            patch(
                "src.core.app.application_factory.ServiceConfigurator"
            ) as mock_service_configurator_class,
        ):
            mock_service_configurator = MagicMock()
            mock_service_configurator_class.return_value = mock_service_configurator
            mock_service_configurator.configure_services.return_value = MagicMock()

            mock_config = AppConfig()
            mock_load.return_value = mock_config

            app = build_app()

            mock_load.assert_called_once()
            assert isinstance(app, FastAPI)

    def test_build_app_creates_fastapi_app(self):
        """Test that build_app creates a FastAPI application."""
        with (
            patch("src.core.app.application_factory.load_config") as mock_load,
            patch(
                "src.core.app.application_factory.ServiceConfigurator"
            ) as mock_service_configurator_class,
        ):
            mock_service_configurator = MagicMock()
            mock_service_configurator_class.return_value = mock_service_configurator
            mock_service_configurator.configure_services.return_value = MagicMock()

            mock_config = AppConfig()
            mock_load.return_value = mock_config

            app = build_app()

            assert isinstance(app, FastAPI)
            assert app.title == "LLM Interactive Proxy"

    def test_build_app_sets_up_app_state(self):
        """Test that build_app sets up app state correctly."""
        with (
            patch("src.core.app.application_factory.load_config") as mock_load,
            patch(
                "src.core.app.application_factory.ServiceConfigurator"
            ) as mock_service_configurator_class,
        ):
            mock_service_configurator = MagicMock()
            mock_service_configurator_class.return_value = mock_service_configurator
            mock_service_configurator.configure_services.return_value = MagicMock()

            mock_config = AppConfig()
            mock_load.return_value = mock_config

            app = build_app()

            assert hasattr(app.state, "app_config")
            assert hasattr(app.state, "service_provider")
            assert hasattr(app.state, "backend_configs")
            assert hasattr(app.state, "backends")
            assert hasattr(app.state, "failover_routes")


class TestIntegration:
    """Integration tests for the application factory."""

    def test_app_handles_models_endpoint(self, monkeypatch):
        """Test that the /models endpoint is available."""
        monkeypatch.setenv("DISABLE_AUTH", "true")
        monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")

        app = build_app()

        with TestClient(app) as client:
            response = client.get("/models")
            assert response.status_code == 200
            assert "data" in response.json()

    def test_app_dependency_injection_works(self, monkeypatch):
        """Test that dependency injection is properly configured."""
        monkeypatch.setenv("DISABLE_AUTH", "true")

        app = build_app()

        # Verify service provider is available
        assert hasattr(app.state, "service_provider")
        assert app.state.service_provider is not None

        # Verify we can get services from the provider
        from src.core.interfaces.session_service import ISessionService

        session_service = app.state.service_provider.get_service(ISessionService)
        assert session_service is not None
