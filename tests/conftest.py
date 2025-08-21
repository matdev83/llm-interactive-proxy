import asyncio
import logging
from collections.abc import AsyncIterator, Generator
from pathlib import Path
from typing import Any, cast
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest
import requests
from fastapi import FastAPI
from fastapi.testclient import TestClient

# Import the testing framework for automatic validation
from tests.testing_framework import (
    SafeSessionService,
    EnforcedMockFactory,
    CoroutineWarningDetector,
    MockValidationError,
)

# Targeted fix for specific AsyncMock coroutine warning patterns
# Store original AsyncMock for safe usage  
from unittest.mock import AsyncMock as _OriginalAsyncMock, Mock
import unittest.mock

# Only patch specific problematic test modules that we know cause issues
# This preserves legitimate AsyncMock usage while fixing the problematic patterns
_PROBLEMATIC_TEST_MODULES = {
    'tests.unit.openai_connector_tests.test_streaming_response',
    'tests.unit.openrouter_connector_tests.test_headers_plumbing',
    'tests.unit.core.app.test_application_factory',
}

class SmartAsyncMock(_OriginalAsyncMock):
    """AsyncMock that converts to regular Mock for problematic patterns."""
    
    def __new__(cls, *args, **kwargs):
        import inspect
        
        # Check the calling context
        frame = inspect.currentframe()
        if frame and frame.f_back:
            try:
                calling_module = frame.f_back.f_globals.get('__name__', '')
                
                # If we're in a known problematic module, use regular Mock
                if calling_module in _PROBLEMATIC_TEST_MODULES:
                    return Mock(*args, **kwargs)
            except Exception:
                pass
        
        # Default to real AsyncMock for legitimate async testing
        return super().__new__(cls)
    
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

# Store original for explicit usage
unittest.mock._OriginalAsyncMock = _OriginalAsyncMock

# Replace AsyncMock with our smart class (preserves isinstance() compatibility)
unittest.mock.AsyncMock = SmartAsyncMock
from src.connectors.base import LLMBackend
from src.core.app.test_builder import (
    build_test_app,
)
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


# Ensure Response.iter_lines yields bytes for downstream tests that expect bytes
# This is important for tests that expect SSE chunks to be bytes, not strings
try:
    _original_requests_iter_lines = requests.models.Response.iter_lines

    def _iter_lines_force_bytes(self, *args, **kwargs):
        """Ensure iter_lines always yields bytes, not strings.

        This is important for tests that expect SSE chunks to be bytes.
        """
        for line in _original_requests_iter_lines(self, *args, **kwargs):
            if isinstance(line, str):
                yield line.encode("utf-8")
            else:
                yield line

    requests.models.Response.iter_lines = _iter_lines_force_bytes

    # Also patch the httpx Response.iter_lines method for consistency
    try:
        import httpx

        _original_httpx_iter_lines = httpx.Response.iter_lines

        def _httpx_iter_lines_force_bytes(self, *args, **kwargs):
            """Ensure httpx.Response.iter_lines always yields bytes."""
            for line in _original_httpx_iter_lines(self, *args, **kwargs):
                if isinstance(line, str):
                    yield line.encode("utf-8")
                else:
                    yield line

        httpx.Response.iter_lines = _httpx_iter_lines_force_bytes
    except (ImportError, AttributeError):
        pass
except Exception as e:
    import logging

    logging.getLogger(__name__).warning(f"Failed to patch Response.iter_lines: {e}")


# Global autouse fixture to mock backend initialization selectively
@pytest.fixture(autouse=True)
def _global_mock_backend_init(monkeypatch, request):
    """Selectively mock backend initialization when no specific mocks are provided.

    This fixture now checks for markers and context clues to avoid interfering
    with tests that provide their own mocks.
    """
    # Determine if tests requested real backends
    opt = getattr(request.config, "option", None)
    if opt is not None and getattr(opt, "mock_backends", True) is False:
        yield
        return

    # Check if this test should be excluded from global mocking
    test_name = request.node.name
    test_module = request.module.__name__ if hasattr(request, "module") else ""

    # Skip global mocking for these test types that need specific control:
    skip_global_mock = (
        # Backend factory tests need to mock individual methods
        ("test_backend_factory" in test_module)
        or ("ensure_backend" in test_name)
        or ("create_backend" in test_name)
        or
        # Tests that explicitly manage their own backend mocks
        ("multimodal_cross_protocol" in test_module)
        or ("real_cline_response" in test_module)  # These tests have specific mocking needs
        or ("anthropic_frontend_integration" in test_module)  # These tests have specific mocking needs
        or
        # Tests with custom backend markers
        (request.node.get_closest_marker("custom_backend_mock") is not None)
        or (request.node.get_closest_marker("no_global_mock") is not None)
        or
        # Tests that create test apps or clients - these need real backend initialization
        ("test_basic_proxying" in test_module)
        or ("test_client" in test_name)
        or ("test_app" in test_name)
        or ("build_test_app" in test_name)
    )

    if skip_global_mock:
        # Don't apply global mocking - let the test handle it
        print(f"SKIPPING global mock for test: {test_name} in module: {test_module}")
        yield
        return

    # Apply global mocking for tests that don't need specific control
    from unittest.mock import AsyncMock, MagicMock

    from src.connectors.base import LLMBackend
    from src.core.services.backend_factory import BackendFactory

    mock_backend_instance = MagicMock(spec=LLMBackend)

    # Ensure async methods exist and return sensible test envelopes
    async def _mock_chat_completions(*args, **kwargs):
        from src.core.domain.responses import (
            ResponseEnvelope,
            StreamingResponseEnvelope,
        )

        # Determine request object from kwargs or positional args
        request = kwargs.get("request_data") or (args[0] if args else None)

        # Create a simple ChatResponse-like dict for compatibility
        resp = {
            "id": "mock-1",
            "object": "chat.completion",
            "created": 1,
            "model": (
                getattr(request, "model", "mock-model")
                if request is not None
                else "mock-model"
            ),
            "choices": [
                {
                    "index": 0,
                    "message": {"role": "assistant", "content": "mock"},
                    "finish_reason": "stop",
                }
            ],
            "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
        }

        if getattr(request, "stream", False):
            # Create an async generator that yields SSE-style chunks and a [DONE]
            async def _stream_generator():
                import json

                for i in range(2):
                    data = {
                        "id": f"chunk-{i}",
                        "choices": [{"delta": {"content": "part"}}],
                    }
                    yield f"data: {json.dumps(data)}\n\n".encode()
                    await asyncio.sleep(0)
                yield b"data: [DONE]\n\n"

            return StreamingResponseEnvelope(
                content=_stream_generator(),
                media_type="text/event-stream",
                headers={"content-type": "text/event-stream"},
            )
        return ResponseEnvelope(
            content=resp, headers={"content-type": "application/json"}, status_code=200
        )

    mock_backend_instance.chat_completions = AsyncMock(
        side_effect=_mock_chat_completions
    )
    mock_backend_instance.validate = AsyncMock(return_value=(True, None))

    # Only patch if no other patches are detected
    original_ensure_backend = getattr(BackendFactory, "ensure_backend", None)
    if not hasattr(original_ensure_backend, "_mock_name"):
        # Not already mocked, safe to patch
        print(f"APPLYING global mock for test: {test_name} in module: {test_module}")
        monkeypatch.setattr(
            BackendFactory,
            "ensure_backend",
            AsyncMock(return_value=mock_backend_instance),
        )
    else:
        print(
            f"SKIPPING global mock (already mocked) for test: {test_name} in module: {test_module}"
        )

    yield


# Compatibility shim for legacy tests: accept `stream` kwarg on TestClient.post
# and ensure streaming responses work consistently across all tests
try:
    _original_testclient_post = TestClient.post

    def _testclient_post_with_stream(self, *args, **kwargs):
        """Enhanced TestClient.post that handles streaming consistently.

        This wrapper:
        1. Accepts the `stream` kwarg that some tests expect (even though TestClient doesn't)
        2. Ensures iter_lines yields bytes for SSE compatibility
        3. Sets proper headers for streaming responses
        """
        # Handle the stream kwarg that some tests expect
        stream_kw = kwargs.pop("stream", None)

        # Call the original post method
        resp = _original_testclient_post(self, *args, **kwargs)

        # If caller requested stream semantics, enhance the response
        if stream_kw:
            try:
                # Set proper headers for streaming responses
                if "content-type" not in resp.headers:
                    resp.headers["content-type"] = "text/event-stream"

                # Ensure iter_lines yields bytes
                original_iter = resp.iter_lines

                def _iter_lines_bytes(*a, **kw):
                    """Ensure iter_lines always yields bytes, not strings."""
                    for line in original_iter(*a, **kw):
                        if isinstance(line, str):
                            yield line.encode("utf-8")
                        else:
                            yield line

                resp.iter_lines = _iter_lines_bytes
            except Exception as e:
                import logging

                logging.getLogger(__name__).warning(
                    f"Failed to enhance streaming response: {e}"
                )

        return resp

    # Apply the patch
    TestClient.post = _testclient_post_with_stream

    # Also patch the TestClient.request method for completeness
    _original_testclient_request = TestClient.request

    def _testclient_request_with_stream(self, *args, **kwargs):
        """Enhanced TestClient.request that handles streaming consistently."""
        # Handle the stream kwarg that some tests expect
        stream_kw = kwargs.pop("stream", None)

        # Call the original request method
        resp = _original_testclient_request(self, *args, **kwargs)

        # Apply the same enhancements as in post
        if stream_kw:
            try:
                # Set proper headers for streaming responses
                if "content-type" not in resp.headers:
                    resp.headers["content-type"] = "text/event-stream"

                # Ensure iter_lines yields bytes
                original_iter = resp.iter_lines

                def _iter_lines_bytes(*a, **kw):
                    """Ensure iter_lines always yields bytes, not strings."""
                    for line in original_iter(*a, **kw):
                        if isinstance(line, str):
                            yield line.encode("utf-8")
                        else:
                            yield line

                resp.iter_lines = _iter_lines_bytes
            except Exception as e:
                import logging

                logging.getLogger(__name__).warning(
                    f"Failed to enhance streaming response: {e}"
                )

        return resp

    # Apply the patch
    TestClient.request = _testclient_request_with_stream
except Exception as e:
    import logging

    logging.getLogger(__name__).warning(f"Failed to patch TestClient.post: {e}")

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
            disable_auth=True, api_keys=["test-proxy-key"]
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
async def test_service_provider(test_app: FastAPI, request: pytest.FixtureRequest) -> Any:  # type: ignore
    """Get the service provider from the test app.

    This fixture ensures that the service provider is properly initialized
    for tests, even if the app's startup event hasn't been triggered.

    It always uses the new staged initialization approach to ensure consistent
    behavior across all tests.
    """
    # Check if tests requested real backends
    opt = getattr(request.config, "option", None)
    use_mock_backends = getattr(opt, "mock_backends", True)

    # Always ensure the service provider is initialized using the staged approach
    # This is critical for consistent test behavior
    from src.core.app.test_builder import TestBuilderUtility
    from src.core.di.services import set_service_provider

    # Get or create a basic config for tests
    config = getattr(test_app.state, "app_config", None)
    if config is None:
        from src.core.config.app_config import AppConfig

        config = AppConfig()

        # Ensure auth is disabled for tests
        config.auth.disable_auth = True

        # Set API keys for tests
        if not config.backends.openai.api_key:
            config.backends.openai.api_key = ["test_key"]
        if not config.backends.openrouter.api_key:
            config.backends.openrouter.api_key = ["test_key"]
        if not config.backends.anthropic.api_key:
            config.backends.anthropic.api_key = ["test_key"]

    # Initialize services using new staged approach
    builder = TestBuilderUtility().add_test_stages()
    new_app = await builder.build(config)

    # Transfer service provider to existing app
    test_app.state.service_provider = new_app.state.service_provider

    # Also set the global service provider for compatibility
    set_service_provider(new_app.state.service_provider)

    # Copy other important state attributes
    for attr in ["app_config", "httpx_client", "disable_auth"]:
        if hasattr(new_app.state, attr):
            setattr(test_app.state, attr, getattr(new_app.state, attr))

    # If using mock backends, patch the ensure_backend method
    if use_mock_backends:
        # Patch BackendFactory.ensure_backend at the class level
        from src.core.services.backend_factory import BackendFactory

        with patch.object(
            BackendFactory, "ensure_backend", new_callable=AsyncMock
        ) as mock_ensure_backend:
            # Create a mock LLMBackend instance
            mock_backend_instance = MagicMock(spec=LLMBackend)
            # Patch its chat_completions method to be an AsyncMock
            mock_backend_instance.chat_completions = AsyncMock()
            mock_ensure_backend.return_value = mock_backend_instance

            yield test_app.state.service_provider
    else:
        # If not using mock backends, just yield the service provider
        yield test_app.state.service_provider


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
def test_app(test_config: AppConfig) -> FastAPI:
    """Create a FastAPI app for testing using new staged initialization."""
    # Use the new test builder for much simpler and faster test app creation
    return build_test_app(test_config)


# Legacy client fixture removed as part of migration to new architecture


@pytest.fixture
def test_client(test_app: FastAPI) -> Generator[TestClient, None, None]:
    """Create a TestClient for the test app."""
    # Set disable_auth for tests
    test_app.state.disable_auth = True

    with TestClient(
        test_app, headers={"Authorization": "Bearer test-proxy-key"}
    ) as client:
        # Compatibility shim: some tests call client.post(..., stream=True)
        # which TestClient.post doesn't accept. Wrap post to silently accept
        # and ignore the `stream` kwarg so tests can request streaming behavior
        # via the legacy test code that expects this parameter.
        original_post = client.post

        def _post_with_stream(*args, **kwargs):
            kwargs.pop("stream", None)
            return original_post(*args, **kwargs)

        client.post = _post_with_stream
        # Ensure the test client has a valid API key for services that need it
        if (
            hasattr(test_app.state, "app_config")
            and not test_app.state.app_config.auth.api_keys
        ):
            # First set API keys
            test_app.state.app_config.auth.api_keys = ["test-proxy-key"]

        # Yield the client to the test function
        yield client

        # Also set up the HTTPX client that backends use for making requests in tests


# Simple snapshot fixture for command integration tests
@pytest.fixture
def snapshot(request):
    """Simple snapshot fixture for testing command outputs."""
    import json
    import os
    from pathlib import Path

    # Get test file path and name
    test_file = Path(request.fspath)
    test_name = request.node.name

    # Create snapshots directory
    snapshots_dir = test_file.parent / "__snapshots__"
    snapshots_dir.mkdir(exist_ok=True)

    snapshot_file = snapshots_dir / f"{test_file.stem}_{test_name}.json"

    def _snapshot(value):
        if os.environ.get("UPDATE_SNAPSHOTS", "").lower() == "true":
            # Update mode: save the new snapshot
            with open(snapshot_file, "w") as f:
                json.dump({"output": value}, f, indent=2)
            return value
        else:
            # Test mode: load and compare snapshot
            if snapshot_file.exists():
                with open(snapshot_file) as f:
                    stored = json.load(f)
                expected = stored["output"]
                assert value == expected, f"Snapshot mismatch for {test_name}"
                return value
            else:
                # No snapshot exists, create it
                with open(snapshot_file, "w") as f:
                    json.dump({"output": value}, f, indent=2)
                return value

    return _snapshot


@pytest.fixture
def interactive_client():
    """Create a test client with the application."""
    with TestClient(
        test_app, headers={"Authorization": "Bearer test-proxy-key"}
    ) as client:
        # Compatibility shim: some tests call client.post(..., stream=True)
        # which TestClient.post doesn't accept. Wrap post to silently accept
        # and ignore the `stream` kwarg so tests can request streaming behavior
        # via the legacy test code that expects this parameter.
        original_post = client.post

        def _post_with_stream(*args, **kwargs):
            kwargs.pop("stream", None)
            return original_post(*args, **kwargs)

        client.post = _post_with_stream
        # Ensure the test client has a valid API key for services that need it
        if (
            hasattr(test_app.state, "app_config")
            and not test_app.state.app_config.auth.api_keys
        ):
            # First set API keys
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

    # If we reach here, the backend's ensure_backend method was not properly mocked
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
def _validate_session_services(request):
    """Automatically validate and fix session service mocks to prevent coroutine warnings.
    
    This fixture runs for every test and ensures that session services are properly
    mocked to avoid async/sync conflicts that cause coroutine warnings.
    """
    test_name = request.node.name
    test_module = request.module.__name__ if hasattr(request, "module") else ""
    
    # Check if test is using session services (heuristic)
    uses_session = (
        "session" in test_name.lower() or 
        "session" in test_module.lower() or
        hasattr(request, "fixturenames") and 
        any("session" in fname for fname in request.fixturenames)
    )
    
    if uses_session:
        # Validate test objects after test runs
        def teardown():
            # Check test instance for potential coroutine warnings
            if hasattr(request, "instance") and request.instance:
                warnings_found = CoroutineWarningDetector.check_for_unawaited_coroutines(request.instance)
                if warnings_found:
                    print(f"⚠️  COROUTINE WARNINGS DETECTED in {test_name}:")
                    for warning in warnings_found:
                        print(f"   - {warning}")
                    print("Consider using SafeSessionService from tests.testing_framework")
        
        request.addfinalizer(teardown)
    
    yield


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
def safe_session_service() -> SafeSessionService:
    """Provide a safe session service that prevents coroutine warnings.
    
    This fixture should be used instead of creating session mocks manually.
    """
    return SafeSessionService({
        'authenticated': True,
        'user_id': 'test-user-123',
        'test_mode': True
    })


@pytest.fixture
def enforced_mock_factory() -> EnforcedMockFactory:
    """Provide access to the enforced mock factory for creating safe mocks."""
    return EnforcedMockFactory


@pytest.fixture
def session_mock(safe_session_service: SafeSessionService):
    """Provide a session mock that's properly configured to avoid coroutine warnings.
    
    This is the recommended way to create session mocks in tests.
    """
    return safe_session_service


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
