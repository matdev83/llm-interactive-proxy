import asyncio
import contextlib
import inspect
import warnings
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from src.core.app.test_builder import build_test_app
from src.core.interfaces.backend_service_interface import IBackendService
from src.core.interfaces.session_service_interface import ISessionService


# Provide env fixtures used by config tests
@pytest.fixture
def mock_env_vars(monkeypatch: pytest.MonkeyPatch) -> dict[str, str]:
    env = {
        "APP_HOST": "localhost",
        "APP_PORT": "9000",
        "PROXY_TIMEOUT": "30",
        "DISABLE_AUTH": "true",
        # Provide API keys for backends picked up by from_env()
        "OPENAI_API_KEY": "test_openai_key",
        "OPENROUTER_API_KEY": "test_openrouter_key",
        "ANTHROPIC_API_KEY": "test_anthropic_key",
        "GEMINI_API_KEY": "test_gemini_key",
        # Default backend
        "LLM_BACKEND": "openai",
        # Make from_env() consider test environment in defaults
        "PYTEST_CURRENT_TEST": "1",
    }
    for k, v in env.items():
        monkeypatch.setenv(k, v)
    return env


@pytest.fixture
def temp_config_path(tmp_path: Path) -> Path:
    """Create a minimal valid YAML config file and return its path."""
    import yaml

    cfg = {
        "host": "localhost",
        "port": 9000,
        "logging": {"level": "INFO"},
        "session": {"cleanup_enabled": False, "default_interactive_mode": True},
        # Minimal backends object (empty is allowed by schema)
        "backends": {},
    }
    p = tmp_path / "app.config.yaml"
    with p.open("w", encoding="utf-8") as f:
        yaml.safe_dump(cfg, f, sort_keys=False)
    return p


@pytest.fixture
def test_client() -> TestClient:
    """A basic TestClient using the default test app with auth disabled."""
    app = build_test_app()
    client = TestClient(app, headers={"Authorization": "Bearer test-proxy-key"})
    try:
        yield client
    finally:
        with contextlib.suppress(Exception):
            client.close()


def _cleanup_root_artifacts() -> None:
    import os

    root = os.path.dirname(os.path.abspath(__file__))
    root = os.path.dirname(root)
    for fname in ("compressed_pytest_output.txt",):
        path = os.path.join(root, fname)
        with contextlib.suppress(Exception):
            if os.path.exists(path):
                os.remove(path)


def pytest_sessionstart(session) -> None:  # type: ignore[no-untyped-def]
    """Session start hook: clean artifacts and install warning filters."""
    _cleanup_root_artifacts()
    _install_global_warning_filters()


def pytest_sessionfinish(session, exitstatus) -> None:  # type: ignore[no-untyped-def]
    """Cleanup potential artifacts after the test session finishes."""
    _cleanup_root_artifacts()


# Apply a global, message-targeted filter for Windows ProactorEventLoop noise
pytestmark = pytest.mark.filterwarnings(
    "ignore:unclosed event loop <ProactorEventLoop.*:ResourceWarning"
)


def pytest_configure(config) -> None:  # type: ignore[no-untyped-def]
    """Install warning filters in each worker process (xdist)."""
    _install_global_warning_filters()


# Test helper utilities expected by some tests
def get_backend_instance(app: any, backend_type: str):  # type: ignore[no-untyped-def]
    """Inject and return a backend instance used by BackendService.

    If the backend is not yet created, insert a simple placeholder object under
    BackendService._backends so tests can patch its methods before requests run.
    """
    # Resolve BackendService from DI
    service_provider = getattr(app.state, "service_provider", None)
    if service_provider is None:
        raise RuntimeError("service_provider not found on app.state")
    backend_service: IBackendService = service_provider.get_required_service(  # type: ignore[type-abstract]
        IBackendService
    )

    # Access internal cache
    cache = getattr(backend_service, "_backends", None)
    if not isinstance(cache, dict):
        raise RuntimeError("BackendService does not expose a _backends cache")

    if backend_type not in cache:

        class _Dummy:
            async def chat_completions(self, *args, **kwargs):  # type: ignore[no-untyped-def]
                raise NotImplementedError

        cache[backend_type] = _Dummy()

    return cache[backend_type]


def get_session_service_from_app(app: any) -> ISessionService:  # type: ignore[no-untyped-def]
    """Resolve the ISessionService from DI."""
    service_provider = getattr(app.state, "service_provider", None)
    if service_provider is None:
        raise RuntimeError("service_provider not found on app.state")
    return service_provider.get_required_service(ISessionService)


@pytest.fixture
def assert_all_responses_were_requested() -> bool:
    """Relax pytest-httpx default to avoid teardown assertion on unused mocks.

    Tests that need strict behavior can override via mark:
    @pytest.mark.httpx_mock(assert_all_responses_were_requested=True)
    """
    return False


@pytest.fixture
def assert_all_requests_were_expected() -> bool:
    """Relax pytest-httpx default to avoid teardown assertion on unexpected requests.

    Tests that need strict behavior can override via mark.
    """
    return False


@pytest.hookimpl(tryfirst=True)
def pytest_pyfunc_call(pyfuncitem: pytest.Function) -> bool | None:
    """Execute async tests using a lightweight event loop runner."""

    test_function = pyfuncitem.obj

    if not inspect.iscoroutinefunction(test_function):
        return None

    loop = asyncio.new_event_loop()
    try:
        asyncio.set_event_loop(loop)

        signature = inspect.signature(test_function)
        call_args: dict[str, Any] = {}
        for name in signature.parameters:
            if name in pyfuncitem.funcargs:
                call_args[name] = pyfuncitem.funcargs[name]

        loop.run_until_complete(test_function(**call_args))
    finally:
        asyncio.set_event_loop(None)
        loop.close()

    return True


def _install_global_warning_filters() -> None:
    warnings.filterwarnings("ignore", category=PendingDeprecationWarning)
    warnings.filterwarnings("ignore", category=DeprecationWarning)
    warnings.filterwarnings("ignore", category=ResourceWarning)
    warnings.filterwarnings("ignore", category=RuntimeWarning)
    warnings.filterwarnings("ignore", category=ImportWarning)
    warnings.filterwarnings("ignore", category=UserWarning)
