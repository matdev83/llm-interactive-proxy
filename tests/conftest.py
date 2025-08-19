"""
Global pytest configuration.

This file contains fixtures that are available to all test modules.
"""

import asyncio
import logging
from collections.abc import AsyncIterator, Generator
from pathlib import Path
from typing import Any, cast

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from src.connectors.base import LLMBackend
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
from src.core.interfaces.backend_service_interface import IBackendService
from src.core.interfaces.di_interface import IServiceProvider
from src.core.interfaces.session_service_interface import ISessionService

# Import shared fixtures

# Silence logging during tests
logging.getLogger().setLevel(logging.WARNING)

# Global state for service provider isolation
_original_service_provider: IServiceProvider | None = None
_original_service_collection: ServiceCollection | None = None


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
async def test_service_provider(test_app: FastAPI) -> Any:  # type: ignore
    """Get the service provider from the test app.

    This fixture ensures that the service provider is properly initialized
    for tests, even if the app's startup event hasn't been triggered.
    """
    # Ensure service provider is available
    if (
        not hasattr(test_app.state, "service_provider")
        or not test_app.state.service_provider
    ):
        from src.core.app.application_factory import ApplicationBuilder
        from src.core.di.services import set_service_provider

        # Get or create a basic config for tests
        config = getattr(test_app.state, "app_config", None)
        if config is None:
            from src.core.config.app_config import AppConfig

            config = AppConfig()

        # Initialize services
        builder = ApplicationBuilder()
        provider = await builder._initialize_services(test_app, config)

        # Set global provider and app.state
        set_service_provider(provider)
        test_app.state.service_provider = provider

    return test_app.state.service_provider


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

    app, _ = build_app(test_config)

    # Ensure httpx_client is available for tests that might need it directly
    # Note: build_app already creates httpx_client and registers all services
    # including CommandRegistry, so we don't need to override the service provider

    return app


# Legacy client fixture removed as part of migration to new architecture


@pytest.fixture
def test_client(test_app: FastAPI) -> Generator[TestClient, None, None]:
    """Create a TestClient for the test app."""
    # Set disable_auth for tests
    test_app.state.disable_auth = True

    with TestClient(
        test_app, headers={"Authorization": "Bearer test-proxy-key"}
    ) as client:
        # Ensure the test client has a valid API key for services that need it
        if hasattr(test_app.state, "app_config"):
            # First set API keys
            if not test_app.state.app_config.auth.api_keys:
                test_app.state.app_config.auth.api_keys = ["test-proxy-key"]

            # Then disable auth for tests
            test_app.state.app_config.auth.disable_auth = True

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


import nest_asyncio

nest_asyncio.apply()


# Helper utilities for migrating tests away from direct `app.state` usage
def get_backend_instance(app: FastAPI, name: str) -> LLMBackend:
    """Resolve a concrete backend instance by name using the DI container only.

    This function enforces the new SOLID/DIP architecture: no legacy fallbacks
    (such as `app.state.<backend>_backend` or auto-created mock backends) are
    permitted. Tests must ensure required backends are registered in the
    application's service provider (for example via the `ensure_backend`
    fixture).

    Args:
        app: FastAPI application instance
        name: backend short name (e.g., 'openrouter')

    Returns:
        Backend instance registered in the DI container

    Raises:
        RuntimeError: if the service provider is not available or the backend
            cannot be resolved/initialized via the DI-backed BackendService.
    """
    svc = getattr(app.state, "service_provider", None)
    if not svc:
        raise RuntimeError(
            "Service provider not available on app.state; ensure the application registers services via DI and the test initializes the service provider."
        )

    # Resolve the backend service from DI
    backend_service = svc.get_required_service(IBackendService)
    if backend_service is None:
        raise RuntimeError(
            "IBackendService not available from service provider. Ensure the application registers the backend service via DI."
        )

    # If backend already created and cached, return it
    backend = getattr(backend_service, "_backends", {}).get(name)
    if backend is not None:
        return cast(LLMBackend, backend)

    # Otherwise initialize the backend using the DI-managed factory (async)
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)

    try:
        backend_instance = loop.run_until_complete(
            initialize_backend_for_test(app, name)
        )
        if backend_instance is not None:
            return backend_instance
    except Exception as e:
        raise RuntimeError(
            f"Failed to initialize backend '{name}' via DI: {e!s}"
        ) from e

    # If we reach here, the backend couldn't be resolved via DI
    raise RuntimeError(
        f"Backend '{name}' not registered in IBackendService. Ensure tests register the backend via DI (e.g., using the 'ensure_backend' fixture)."
    )


def get_session_service_from_app(app: FastAPI) -> ISessionService:
    """Resolve ISessionService from DI. Do not fall back to legacy session_manager."""
    svc = app.state.service_provider.get_required_service(ISessionService)
    if svc is None:
        raise RuntimeError(
            "ISessionService not available from service provider. Ensure the application registers the session service via DI."
        )
    return cast(ISessionService, svc)


async def initialize_backend_for_test(app: FastAPI, backend_name: str) -> LLMBackend:
    """Initialize a backend for testing purposes.

    Args:
        app: FastAPI application instance
        backend_name: Name of the backend to initialize

    Returns:
        Initialized backend instance
    """
    # Get the backend service
    backend_service = app.state.service_provider.get_required_service(IBackendService)

    # Initialize the backend (this will create and cache it)
    backend_instance = await backend_service._get_or_create_backend(backend_name)

    return cast(LLMBackend, backend_instance)


@pytest.fixture
async def ensure_backend(test_app: FastAPI, request: pytest.FixtureRequest) -> None:
    """Ensure a specific backend is registered in the DI container.

    Usage:
        @pytest.mark.backends(["openai", "openrouter"])
        def test_something(ensure_backend):
            # The backends will be auto-registered
            pass
    """
    # Check if we should use mock backends
    use_mock_backends = getattr(request.config, "option", None)
    if use_mock_backends is None or getattr(use_mock_backends, "mock_backends", True):
        # Import and use the test backend factory
        from tests.test_backend_factory import (
            patch_backend_initialization,
        )

        patch_backend_initialization(test_app)

    # Check if the test has the backends marker
    marker = request.node.get_closest_marker("backends")
    if marker:
        backend_names = marker.args[0] if marker.args else []
        for backend_name in backend_names:
            try:
                await initialize_backend_for_test(test_app, backend_name)
            except Exception as e:
                pytest.fail(f"Failed to initialize backend {backend_name}: {e}")

    # Also check for a single backend marker
    marker = request.node.get_closest_marker("backend")
    if marker:
        backend_name = marker.args[0] if marker.args else None
        if backend_name:
            try:
                await initialize_backend_for_test(test_app, backend_name)
            except Exception as e:
                pytest.fail(f"Failed to initialize backend {backend_name}: {e}")


@pytest.fixture
def use_real_backends(request):
    """Fixture to indicate that a test should use real backends instead of mocks.

    Usage:
        def test_something(use_real_backends):
            # This test will use real backends
            pass
    """
    # Set a flag to indicate that the test should use real backends
    if not hasattr(request.config, "option"):
        request.config.option = type("Options", (), {})
    request.config.option.mock_backends = False
    yield
    # Reset the flag after the test
    request.config.option.mock_backends = True


@pytest.fixture
def mock_backend_factory(test_app: FastAPI):
    """Fixture to provide access to the mock backend factory.

    Usage:
        def test_something(mock_backend_factory):
            # Configure a mock backend
            backend = mock_backend_factory.create_backend("openai")
            backend.configure_response({"choices": [{"message": {"content": "Custom response"}}]})
    """
    from tests.test_backend_factory import (
        TestBackendFactory,
        patch_backend_initialization,
    )

    patch_backend_initialization(test_app)
    return TestBackendFactory


@pytest.fixture(autouse=True)
def isolate_global_state() -> Generator[None, None, None]:
    """Automatically isolate global state between tests.

    This fixture runs for every test and ensures that global service provider
    and integration bridge state doesn't contaminate other tests.
    """
    # Save the current global service provider state
    import src.core.di.services as services_module

    original_provider = services_module._service_provider
    original_services = services_module._service_collection

    # Save the current global integration bridge state (if it exists)
    try:
        import src.core.integration.bridge as bridge_module

        original_bridge = getattr(bridge_module, "_integration_bridge", None)
    except (ImportError, AttributeError):
        bridge_module = None  # type: ignore
        original_bridge = None

    # Save the original backend initialization function
    original_init_backend = initialize_backend_for_test

    try:
        # Run the test
        yield
    finally:
        # Restore the original global state
        services_module._service_provider = original_provider
        services_module._service_collection = original_services

        # Restore bridge if it was available
        if bridge_module is not None and hasattr(bridge_module, "_integration_bridge"):
            bridge_module._integration_bridge = original_bridge

        # Restore the original backend initialization function
        globals()["initialize_backend_for_test"] = original_init_backend


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
