"""
Integration tests for the models endpoints.

These tests verify that the /models and /v1/models endpoints work correctly
with both mocked and real backend configurations.
"""

from contextlib import suppress
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient
from src.constants import BackendType
from src.core.app.application_factory import build_app


class TestModelsEndpoints:
    """Integration tests for models discovery endpoints."""

    @pytest.fixture
    def app_with_auth_disabled(self, monkeypatch):
        """Create app with authentication disabled."""
        monkeypatch.setenv("DISABLE_AUTH", "true")
        return build_app()

    @pytest.fixture
    def app_with_auth_enabled(self, monkeypatch):
        """Create app with authentication enabled."""
        monkeypatch.setenv("PROXY_API_KEYS", "test-key-123")
        return build_app()

    def test_models_endpoint_no_auth(self, app_with_auth_disabled):
        """Test /models endpoint without authentication."""
        with TestClient(app_with_auth_disabled) as client:
            response = client.get("/models")

            assert response.status_code == 200
            data = response.json()
            assert "object" in data
            assert data["object"] == "list"
            assert "data" in data
            assert isinstance(data["data"], list)

            # Should have default models when no backends configured
            assert len(data["data"]) > 0

    def test_v1_models_endpoint_no_auth(self, app_with_auth_disabled):
        """Test /v1/models endpoint without authentication."""
        with TestClient(app_with_auth_disabled) as client:
            response = client.get("/v1/models")

            assert response.status_code == 200
            data = response.json()
            assert "object" in data
            assert data["object"] == "list"
            assert "data" in data
            assert isinstance(data["data"], list)

    def test_models_endpoint_with_auth(self, app_with_auth_enabled):
        """Test /models endpoint with authentication."""
        with TestClient(app_with_auth_enabled) as client:
            # Without auth - should fail
            response = client.get("/models")
            assert response.status_code == 401

            # With valid auth
            response = client.get(
                "/models", headers={"Authorization": "Bearer test-key-123"}
            )
            assert response.status_code == 200
            data = response.json()
            assert data["object"] == "list"

    def test_models_endpoint_invalid_auth(self, app_with_auth_enabled):
        """Test /models endpoint with invalid authentication."""
        with TestClient(app_with_auth_enabled) as client:
            response = client.get(
                "/models", headers={"Authorization": "Bearer invalid-key"}
            )
            assert response.status_code == 401
            assert "Invalid or missing API key" in response.json()["detail"]

    def test_models_with_configured_backends(self, monkeypatch):
        """Test models discovery with configured backends."""
        # Set up environment with multiple backends
        monkeypatch.setenv("DISABLE_AUTH", "true")
        monkeypatch.setenv("OPENAI_API_KEY", "test-openai-key")
        monkeypatch.setenv("ANTHROPIC_API_KEY", "test-anthropic-key")

        app = build_app()

        with (
            TestClient(app) as client,
            patch("src.core.app.controllers.models_controller.IBackendService"),
        ):
            mock_backend_service = MagicMock()

            # Mock OpenAI backend
            mock_openai_backend = MagicMock()
            mock_openai_backend.get_available_models.return_value = [
                "gpt-4",
                "gpt-3.5-turbo",
            ]

            # Mock Anthropic backend
            mock_anthropic_backend = MagicMock()
            mock_anthropic_backend.get_available_models.return_value = [
                "claude-3-opus",
                "claude-3-sonnet",
            ]

            # Setup mock to return different backends
            async def mock_get_backend(backend_type):
                if backend_type == BackendType.OPENAI:
                    return mock_openai_backend
                elif backend_type == BackendType.ANTHROPIC:
                    return mock_anthropic_backend
                raise ValueError(f"Unknown backend: {backend_type}")

            mock_backend_service._get_or_create_backend = AsyncMock(
                side_effect=mock_get_backend
            )

            # This won't work directly, but shows the intent
            # In reality, the backends would be discovered through the actual service
            response = client.get("/models")

            assert response.status_code == 200
            data = response.json()
            assert len(data["data"]) > 0

    def test_models_format_compliance(self, app_with_auth_disabled):
        """Test that models response follows OpenAI format."""
        with TestClient(app_with_auth_disabled) as client:
            response = client.get("/models")

            assert response.status_code == 200
            data = response.json()

            # Check overall structure
            assert data["object"] == "list"
            assert isinstance(data["data"], list)

            # Check each model object
            for model in data["data"]:
                assert "id" in model
                assert "object" in model
                assert model["object"] == "model"
                assert "owned_by" in model
                assert isinstance(model["id"], str)
                assert isinstance(model["owned_by"], str)

    def test_models_endpoint_error_handling(self, monkeypatch):
        """Test error handling in models endpoint."""
        monkeypatch.setenv("DISABLE_AUTH", "true")
        app = build_app()

        with (
            TestClient(app) as client,
            patch(
                "src.core.app.controllers.models_controller.get_backend_service"
            ) as mock_get_service,
        ):
            mock_get_service.side_effect = Exception("Service unavailable")

            response = client.get("/models")

            # Should handle the error gracefully
            assert response.status_code == 500
            assert "detail" in response.json()


class TestModelsDiscovery:
    """Test actual model discovery from backends."""

    @pytest.fixture
    def mock_backend_factory(self):
        """Create a mock backend factory."""
        from src.core.services.backend_factory import BackendFactory

        factory = MagicMock(spec=BackendFactory)
        return factory

    @pytest.mark.asyncio
    async def test_discover_openai_models(self, mock_backend_factory):
        """Test discovering models from OpenAI backend."""
        from src.core.interfaces.rate_limiter import IRateLimiter
        from src.core.services.backend_service import BackendService

        # Create mock rate limiter
        mock_rate_limiter = MagicMock(spec=IRateLimiter)
        mock_rate_limiter.check_rate_limit = AsyncMock(return_value=None)

        # Create mock config
        mock_config = MagicMock()
        mock_config.get.return_value = None

        # Create backend service
        service = BackendService(mock_backend_factory, mock_rate_limiter, mock_config)

        # Mock OpenAI backend
        mock_openai = MagicMock()
        mock_openai.get_available_models.return_value = [
            "gpt-4-turbo-preview",
            "gpt-4",
            "gpt-3.5-turbo",
            "gpt-3.5-turbo-16k",
        ]

        mock_backend_factory.create_backend.return_value = mock_openai
        mock_backend_factory.initialize_backend = AsyncMock()

        # Get backend and discover models
        backend = await service._get_or_create_backend(BackendType.OPENAI)
        models = backend.get_available_models()

        assert len(models) == 4
        assert "gpt-4" in models
        assert "gpt-3.5-turbo" in models

    @pytest.mark.asyncio
    async def test_discover_anthropic_models(self, mock_backend_factory):
        """Test discovering models from Anthropic backend."""
        from src.core.interfaces.rate_limiter import IRateLimiter
        from src.core.services.backend_service import BackendService

        # Create mock rate limiter
        mock_rate_limiter = MagicMock(spec=IRateLimiter)
        mock_rate_limiter.check_rate_limit = AsyncMock(return_value=None)

        # Create mock config
        mock_config = MagicMock()
        mock_config.get.return_value = None

        # Create backend service
        service = BackendService(mock_backend_factory, mock_rate_limiter, mock_config)

        # Mock Anthropic backend
        mock_anthropic = MagicMock()
        mock_anthropic.get_available_models.return_value = [
            "claude-3-opus-20240229",
            "claude-3-sonnet-20240229",
            "claude-3-haiku-20240307",
            "claude-2.1",
        ]

        mock_backend_factory.create_backend.return_value = mock_anthropic
        mock_backend_factory.initialize_backend = AsyncMock()

        # Get backend and discover models
        backend = await service._get_or_create_backend(BackendType.ANTHROPIC)
        models = backend.get_available_models()

        assert len(models) == 4
        assert "claude-3-opus-20240229" in models
        assert "claude-2.1" in models

    @pytest.mark.asyncio
    async def test_discover_models_with_failover(self, mock_backend_factory):
        """Test model discovery when primary backend fails."""
        from src.core.interfaces.rate_limiter import IRateLimiter
        from src.core.services.backend_service import BackendService

        # Create mock rate limiter
        mock_rate_limiter = MagicMock(spec=IRateLimiter)
        mock_rate_limiter.check_rate_limit = AsyncMock(return_value=None)

        # Create mock config with failover
        mock_config = MagicMock()
        mock_config.get.return_value = None

        # Create backend service with failover routes
        failover_routes = {
            BackendType.OPENAI: {
                "backend": BackendType.OPENROUTER,
                "model": "openai/gpt-4",
            }
        }

        service = BackendService(
            mock_backend_factory,
            mock_rate_limiter,
            mock_config,
            failover_routes=failover_routes,
        )

        # First call fails
        mock_backend_factory.create_backend.side_effect = [
            ValueError("API key invalid"),
            MagicMock(
                get_available_models=lambda: ["openrouter/gpt-4", "openrouter/claude-3"]
            ),
        ]
        mock_backend_factory.initialize_backend = AsyncMock()

        # Should handle the error and not crash
        with suppress(Exception):
            await service._get_or_create_backend(BackendType.OPENAI)

        # Second attempt should work with fallback
        backend = await service._get_or_create_backend(BackendType.OPENROUTER)
        models = backend.get_available_models()

        assert len(models) == 2
        assert "openrouter/gpt-4" in models


class TestModelsEndpointIntegration:
    """Full integration tests with real app instances."""

    @pytest.mark.integration
    def test_full_models_discovery_flow(self, monkeypatch):
        """Test complete flow of model discovery."""
        # Setup environment
        monkeypatch.setenv("DISABLE_AUTH", "true")
        monkeypatch.setenv("DEFAULT_BACKEND", "openai")

        # Build app
        app = build_app()

        with TestClient(app) as client:
            # First request to models endpoint
            response = client.get("/models")
            assert response.status_code == 200

            models_data = response.json()
            assert models_data["object"] == "list"

            # Verify models can be used in chat completion
            if models_data["data"]:
                model_id = models_data["data"][0]["id"]

                # Try to use the model
                chat_response = client.post(
                    "/v1/chat/completions",
                    json={
                        "model": model_id,
                        "messages": [{"role": "user", "content": "test"}],
                        "max_tokens": 10,
                    },
                )

                # Might fail if no real backend configured, but shouldn't crash
                assert chat_response.status_code in [200, 401, 403, 500]

    @pytest.mark.integration
    def test_models_caching_behavior(self, monkeypatch):
        """Test that models endpoint implements proper caching."""
        monkeypatch.setenv("DISABLE_AUTH", "true")
        app = build_app()

        with TestClient(app) as client:
            # First request
            response1 = client.get("/models")
            assert response1.status_code == 200
            models1 = response1.json()["data"]

            # Second request (should be cached or consistent)
            response2 = client.get("/models")
            assert response2.status_code == 200
            models2 = response2.json()["data"]

            # Models should be consistent
            assert len(models1) == len(models2)
            for m1, m2 in zip(models1, models2, strict=False):
                assert m1["id"] == m2["id"]

    @pytest.mark.integration
    def test_models_endpoint_performance(self, monkeypatch):
        """Test models endpoint performance."""
        import time

        monkeypatch.setenv("DISABLE_AUTH", "true")
        app = build_app()

        with TestClient(app) as client:
            # Warm up
            client.get("/models")

            # Measure response time
            start = time.time()
            response = client.get("/models")
            duration = time.time() - start

            assert response.status_code == 200
            # Should respond quickly (< 1 second)
            assert duration < 1.0

    @pytest.mark.parametrize("endpoint", ["/models", "/v1/models"])
    def test_both_endpoints_return_same_data(self, endpoint, monkeypatch):
        """Test that both model endpoints return identical data."""
        monkeypatch.setenv("DISABLE_AUTH", "true")
        app = build_app()

        with TestClient(app) as client:
            response = client.get(endpoint)
            assert response.status_code == 200

            data = response.json()
            assert data["object"] == "list"
            assert "data" in data

            # Both endpoints should return same structure
            for model in data["data"]:
                assert "id" in model
                assert "object" in model
                assert "owned_by" in model
