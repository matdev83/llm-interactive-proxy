import asyncio
import contextlib
import importlib.util
import inspect
import sys
import types
import warnings
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from src.core.app.test_builder import build_test_app
from src.core.interfaces.backend_service_interface import IBackendService
from src.core.interfaces.session_service_interface import ISessionService

"""Test fixtures and utilities."""


def _module_is_available(name: str) -> bool:
    """Return True if the optional module can be imported."""

    return importlib.util.find_spec(name) is not None


HAS_PYTEST_ASYNCIO = _module_is_available("pytest_asyncio")
HAS_PYTEST_HTTPX = _module_is_available("pytest_httpx")
HAS_PYTEST_XDIST = _module_is_available("xdist")


if not HAS_PYTEST_ASYNCIO:
    module = types.ModuleType("pytest_asyncio")

    def _asyncio_fixture(*fixture_args, **fixture_kwargs):
        def decorator(func):
            async def _skipped_fixture(*_args: Any, **_kwargs: Any):
                pytest.skip("pytest_asyncio not installed")

            return pytest.fixture(*fixture_args, **fixture_kwargs)(_skipped_fixture)

        return decorator

    module.fixture = _asyncio_fixture  # type: ignore[assignment]
    sys.modules.setdefault("pytest_asyncio", module)


if not HAS_PYTEST_HTTPX:
    module = types.ModuleType("pytest_httpx")
    module.HTTPXMock = Any  # type: ignore[assignment]
    sys.modules.setdefault("pytest_httpx", module)


if not HAS_PYTEST_HTTPX:

    @pytest.fixture
    def httpx_mock():  # type: ignore[no-redef]
        pytest.skip("pytest_httpx not installed")


def _strip_option(args: list[str], option: str) -> None:
    """Remove all occurrences of an option from the args list."""

    while option in args:
        index = args.index(option)
        del args[index]
        if option in {"-n", "--max-worker-restart", "--dist", "--asyncio-mode"} and index < len(args) and not args[index].startswith("-"):
            del args[index]


def _ensure_option(args: list[str], option: str, value: str | None = None) -> None:
    """Append an option with an optional value when absent."""

    if any(
        item == option
        or (value is not None and item == value)
        or item.startswith(f"{option}=")
        for item in args
    ):
        return

    if value is None:
        args.append(option)
    elif option.startswith("--"):
        args.append(f"{option}={value}")
    else:
        args.extend([option, value])


def _configure_optional_plugin_args(args: list[str]) -> None:
    """Apply default CLI options for optional plugins when available."""

    if HAS_PYTEST_ASYNCIO:
        _ensure_option(args, "--asyncio-mode", "auto")
    else:
        _strip_option(args, "--asyncio-mode")
        _strip_option(args, "--asyncio-mode=auto")

    if HAS_PYTEST_XDIST:
        if "-n" not in args and not any(a.startswith("--numprocesses") for a in args):
            _ensure_option(args, "-n", "7")
        if not any(a.startswith("--dist") for a in args):
            _ensure_option(args, "--dist", "loadfile")
        if not any(a.startswith("--max-worker-restart") for a in args):
            _ensure_option(args, "--max-worker-restart", "3")
    else:
        _strip_option(args, "-n")
        _strip_option(args, "--dist")
        _strip_option(args, "--dist=loadfile")
        _strip_option(args, "--max-worker-restart")
        _strip_option(args, "--max-worker-restart=3")


def pytest_load_initial_conftests(args, early_config, parser):
    _configure_optional_plugin_args(args)
    # If user already set -n/--numprocesses, respect it
    if "-n" in args or any(a.startswith("--numprocesses") for a in args):
        return

    # Simple heuristic: exactly one explicit nodeid like path::testname
    nodeids = [a for a in args if "::" in a]
    if len(nodeids) == 1:
        # Prepend -n 1 so xdist sees it during option parsing
        args[:0] = ["-n", "1"]


def pytest_collection_modifyitems(config, items):  # type: ignore[no-untyped-def]
    if not HAS_PYTEST_HTTPX:
        skip_httpx = pytest.mark.skip(reason="pytest_httpx not installed")
        for item in items:
            if "httpx_mock" in getattr(item, "fixturenames", ()):  # pragma: no branch
                item.add_marker(skip_httpx)

    if not HAS_PYTEST_ASYNCIO:
        skip_asyncio = pytest.mark.skip(reason="pytest_asyncio not installed")
        for item in items:
            if item.get_closest_marker("asyncio"):
                item.add_marker(skip_asyncio)


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
    config.addinivalue_line(
        "markers", "httpx_mock: mark tests that require pytest_httpx"
    )
    config.addinivalue_line(
        "markers", "asyncio: mark tests that require pytest_asyncio"
    )


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
