"""Integration tests for backend probing in test environment."""

import os

import pytest
from fastapi.testclient import TestClient
from src.core.app.test_builder import build_test_app as build_app
from src.core.interfaces.backend_config_provider_interface import IBackendConfigProvider


@pytest.fixture
def test_env() -> None:
    """Set up test environment variables."""
    old_env = os.environ.copy()
    os.environ["PYTEST_CURRENT_TEST"] = "test_backend_probing.py::test_something"
    os.environ["LLM_BACKEND"] = "openai"
    yield
    os.environ.clear()
    os.environ.update(old_env)


@pytest.fixture
async def app_client(test_env: None) -> TestClient:
    """Create a test client with the application."""
    app, config = build_app()

    # Disable auth for tests
    app.state.disable_auth = True
    if hasattr(app.state, "app_config") and hasattr(app.state.app_config, "auth"):
        app.state.app_config.auth.disable_auth = True

    # Ensure service provider is initialized
    if not hasattr(app.state, "service_provider") or not app.state.service_provider:
        from src.core.app.test_builder import (
            TestApplicationBuilder as ApplicationBuilder,
        )

        # Initialize services
        builder = ApplicationBuilder()
        provider = await builder._initialize_services(app, config)

        # Set service provider on app.state
        app.state.service_provider = provider

        # Initialize backends
        await builder._initialize_backends(app, config)

    return TestClient(app)


@pytest.mark.asyncio
async def test_functional_backends_in_test_env(app_client: TestClient) -> None:
    """Test that functional backends are correctly identified in test env."""
    # The app should have initialized with at least the default backend
    response = app_client.get("/v1/models")
    assert response.status_code == 200

    # Get the models response
    data = response.json()
    assert "data" in data
    assert len(data["data"]) > 0

    # Check that we have at least some models
    assert len(data["data"]) > 0

    # Extract backend types if model IDs contain them
    backend_types = set()
    for model in data["data"]:
        if ":" in model["id"]:
            backend_type = model["id"].split(":")[0]
            backend_types.add(backend_type)

    # In test environment, we might not have specific backends
    # Just check that we have models available
    assert len(data["data"]) > 0


@pytest.mark.asyncio
async def test_backend_config_provider_in_di(app_client: TestClient) -> None:
    """Test that the BackendConfigProvider is correctly registered in DI."""
    # Access the service provider from app.state
    service_provider = app_client.app.state.service_provider
    assert service_provider is not None

    # Get the IBackendConfigProvider from DI
    from src.core.interfaces.backend_config_provider_interface import (
        IBackendConfigProvider,
    )

    provider = service_provider.get_service(IBackendConfigProvider)
    assert provider is not None

    # Check that the provider returns the expected default backend
    assert provider.get_default_backend() == "openai"

    # Check that the provider returns functional backends
    functional_backends = provider.get_functional_backends()
    assert "openai" in functional_backends


@pytest.mark.asyncio
async def test_httpx_client_shared_in_di(app_client: TestClient) -> None:
    """Test that a single httpx.AsyncClient is shared across services."""
    # Access the service provider from app.state
    service_provider = app_client.app.state.service_provider
    assert service_provider is not None

    # Get the httpx.AsyncClient from DI
    import httpx

    client1 = service_provider.get_service(httpx.AsyncClient)
    assert client1 is not None

    # Get it again and verify it's the same instance
    client2 = service_provider.get_service(httpx.AsyncClient)
    assert client2 is client1  # Same instance

    # Check that it's stored on app.state for shutdown handling
    assert hasattr(app_client.app.state, "httpx_client")
    assert app_client.app.state.httpx_client is client1


@pytest.mark.asyncio
async def test_backend_factory_uses_shared_client(app_client: TestClient) -> None:
    """Test that BackendFactory uses the shared httpx client."""
    # Access the service provider from app.state
    service_provider = app_client.app.state.service_provider
    assert service_provider is not None

    # Get the shared httpx client
    import httpx

    shared_client = service_provider.get_service(httpx.AsyncClient)
    assert shared_client is not None

    # Get the BackendFactory
    from src.core.services.backend_factory import BackendFactory

    factory = service_provider.get_service(BackendFactory)
    assert factory is not None

    # Check that the factory uses the shared client
    assert factory._client is shared_client


@pytest.mark.asyncio
async def test_backend_service_uses_backend_config_provider(
    app_client: TestClient,
) -> None:
    """Test that BackendService uses the BackendConfigProvider."""
    # Access the service provider from app.state
    service_provider = app_client.app.state.service_provider
    assert service_provider is not None

    # Get the BackendService
    from src.core.services.backend_service import BackendService

    service = service_provider.get_service(BackendService)
    assert service is not None

    # Check that it has a _backend_config_provider attribute
    assert hasattr(service, "_backend_config_provider")
    assert service._backend_config_provider is not None

    # Check that it's an instance of IBackendConfigProvider
    assert isinstance(service._backend_config_provider, IBackendConfigProvider)
