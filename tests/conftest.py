"""
Global pytest configuration.

This file contains fixtures that are available to all test modules.
"""

import asyncio
import logging
from collections.abc import AsyncIterator, Generator
from pathlib import Path

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from src.core.app.application_factory import build_app
from src.core.config_adapter import AppConfig
from src.core.di.container import ServiceCollection
from src.core.di.services import get_service_collection, set_service_provider
from src.core.interfaces.di import IServiceProvider

# Silence logging during tests
logging.getLogger().setLevel(logging.WARNING)


@pytest.fixture(scope="session")
def event_loop() -> Generator[asyncio.AbstractEventLoop, None, None]:
    """Create an event loop for the test session."""
    policy = asyncio.get_event_loop_policy()
    loop = policy.new_event_loop()
    yield loop
    loop.close()


@pytest.fixture(scope="session")
def test_config() -> AppConfig:
    """Create a test configuration."""
    # Create a test configuration
    return AppConfig(
        host="localhost",
        port=9000,
        proxy_timeout=10,
        command_prefix="!/",
        backends=AppConfig.BackendSettings(
            default_backend="openai",
            openai=AppConfig.BackendConfig(api_key="test_openai_key"),
            openrouter=AppConfig.BackendConfig(api_key="test_openrouter_key"),
        ),
        auth=AppConfig.AuthConfig(
            disable_auth=True,  # Disable auth for testing
            api_keys=["test_api_key"],
        ),
        session=AppConfig.SessionConfig(
            cleanup_enabled=False,  # Disable cleanup for testing
            default_interactive_mode=True,
        ),
        logging=AppConfig.LoggingConfig(
            level=AppConfig.LogLevel.WARNING  # Silence logging during tests
        ),
    )


@pytest.fixture
def test_services() -> ServiceCollection:
    """Create a service collection for testing."""
    return ServiceCollection()


@pytest.fixture
async def mock_http_client() -> AsyncIterator[httpx.AsyncClient]:
    """Create a mock HTTP client for testing."""
    client = httpx.AsyncClient()
    yield client
    # Close the client after the test
    # We use a generator to ensure it's closed even if the test fails
    # Note: In pytest, you need to yield the resource before cleanup
    await client.aclose()


@pytest.fixture
def test_app(test_config: AppConfig, mock_http_client: httpx.AsyncClient) -> FastAPI:
    """Create a FastAPI app for testing."""
    app = build_app()

    # Override app state with test config
    app.state.config = test_config.to_legacy_config()

    # Use the mock HTTP client
    app.state.httpx_client = mock_http_client

    # Manually set up service provider for testing since TestClient doesn't trigger lifespan
    from src.core.app.application_factory import register_services
    services = get_service_collection()
    register_services(services, app)
    provider = services.build_service_provider()
    set_service_provider(provider)
    app.state.service_provider = provider

    # Initialize integration bridge for legacy compatibility
    from src.core.integration import get_integration_bridge
    import asyncio
    
    async def setup_bridge():
        bridge = get_integration_bridge(app)
        await bridge.initialize_legacy_architecture()
        await bridge.initialize_new_architecture()
    
    # Run the async setup
    asyncio.run(setup_bridge())

    return app


@pytest.fixture
def test_client(test_app: FastAPI) -> TestClient:
    """Create a FastAPI test client."""
    return TestClient(test_app)


@pytest.fixture
def test_service_provider(
    test_services: ServiceCollection,
) -> Generator[IServiceProvider, None, None]:
    """Create a service provider for testing."""
    # Register the previous service provider to restore later
    previous_provider = get_service_collection()

    # Set our test service collection
    test_provider = test_services.build_service_provider()
    set_service_provider(test_provider)

    # Return the provider
    yield test_provider

    # Restore the previous provider
    if previous_provider:
        set_service_provider(previous_provider.build_service_provider())


@pytest.fixture
def temp_config_path(tmp_path: Path) -> Path:
    """Create a temporary config file for testing."""
    config_content = """
    host: "localhost"
    port: 9000
    
    backends:
      default_backend: "openai"
      openai:
        api_key: "test_key"
    
    auth:
      disable_auth: true
    """

    config_path = tmp_path / "config.yaml"
    config_path.write_text(config_content)

    return config_path


@pytest.fixture
def mock_env_vars(monkeypatch: pytest.MonkeyPatch) -> dict[str, str]:
    """Set up mock environment variables for testing.

    Returns a dictionary of the mock environment variables.
    """
    env_vars = {
        "APP_HOST": "localhost",
        "APP_PORT": "9000",
        "OPENAI_API_KEY": "test_openai_key",
        "OPENROUTER_API_KEY": "test_openrouter_key",
        "DISABLE_AUTH": "true",
    }

    # Set the environment variables
    for key, value in env_vars.items():
        monkeypatch.setenv(key, value)

    return env_vars
