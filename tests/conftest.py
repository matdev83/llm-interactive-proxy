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
from src.core.config.app_config import (
    AppConfig,
    AuthConfig,
    BackendConfig,
    BackendSettings,
    LoggingConfig,
    LogLevel,
    SessionConfig,
)
from src.core.di.container import ServiceCollection
from src.core.interfaces.di import IServiceProvider

# Silence logging during tests
logging.getLogger().setLevel(logging.WARNING)

# Global state for service provider isolation
_original_global_provider: IServiceProvider | None = None
_original_global_services: ServiceCollection | None = None


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
        backends=BackendSettings(
            default_backend="openai",
            openai=BackendConfig(api_key=["test_openai_key"]),
            openrouter=BackendConfig(api_key=["test_openrouter_key"]),
            anthropic=BackendConfig(api_key=["test_anthropic_key"]),
        ),
        auth=AuthConfig(
            disable_auth=False, api_keys=["test-proxy-key"]
        ),  # Enable auth with test key
        session=SessionConfig(
            cleanup_enabled=False,  # Disable cleanup for testing
            default_interactive_mode=True,
        ),
        logging=LoggingConfig(level=LogLevel.WARNING),  # Silence logging during tests
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
def test_app(test_config: AppConfig, tmp_path: Path) -> FastAPI:
    """Create a FastAPI app for testing."""
    # Create a temporary config file for the test app
    config_path = tmp_path / "test_config.yaml"
    with open(config_path, "w") as f:
        # Convert the config to legacy format to ensure compatibility
        legacy_config = test_config.to_legacy_config()

        # Ensure test API key is present
        if "api_keys" not in legacy_config or not legacy_config["api_keys"]:
            legacy_config["api_keys"] = ["test-proxy-key"]

        # Write YAML config
        import yaml

        yaml.dump(legacy_config, f)

    app = build_app(test_config)

    # Ensure httpx_client is available for tests that might need it directly
    # Note: build_app already creates httpx_client and registers all services
    # including CommandRegistry, so we don't need to override the service provider

    return app


# Legacy client fixture removed as part of migration to new architecture


@pytest.fixture
def test_client(test_app: FastAPI) -> Generator[TestClient, None, None]:
    """Create a TestClient for the test app."""
    with TestClient(
        test_app, headers={"Authorization": "Bearer test-proxy-key"}
    ) as client:
        yield client


# Legacy client fixture has been removed as part of the SOLID migration


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


# @pytest.fixture(autouse=True)
# def isolate_global_state() -> Generator[None, None, None]:
#     """Automatically isolate global state between tests.

#     This fixture runs for every test and ensures that global service provider
#     and integration bridge state doesn't contaminate other tests.
#     """
#     # Save the current global service provider state
#     import src.core.di.services as services_module

#     original_provider = services_module._global_provider
#     original_services = services_module._global_services

#     # Save the current global integration bridge state
#     import src.core.integration.bridge as bridge_module

#     original_bridge = bridge_module._integration_bridge

#     try:
#         # Run the test
#         yield
#     finally:
#         # Restore the original global state
#         services_module._global_provider = original_provider
#         services_module._global_services = original_services
#         bridge_module._integration_bridge = original_bridge


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
        # Numbered/alternate keys used by some tests
        "OPENROUTER_API_KEY_1": "test_openrouter_key_1",
        "GEMINI_API_KEY": "test_gemini_key",
        "GEMINI_API_KEY_1": "test_gemini_key_1",
        "DISABLE_AUTH": "true",
    }

    # Set the environment variables
    for key, value in env_vars.items():
        monkeypatch.setenv(key, value)

    return env_vars
