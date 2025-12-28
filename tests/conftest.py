from __future__ import annotations

import asyncio
import contextlib
import importlib.util
import inspect
import os
import sys
import types
import warnings
import weakref
from collections.abc import Generator
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

import pytest

if TYPE_CHECKING:
    from fastapi.testclient import TestClient
    from src.core.interfaces.backend_service_interface import IBackendService
    from src.core.interfaces.session_service_interface import ISessionService

"""Test fixtures and utilities."""

_TESTMON_DATAFILE_ENV = "TESTMON_DATAFILE"
if _TESTMON_DATAFILE_ENV not in os.environ:
    # Keep pytest-testmon data under .pytest_cache to avoid read-only repo artifacts.
    repo_root = Path(__file__).resolve().parents[1]
    testmon_dir = repo_root / ".pytest_cache"
    testmon_dir.mkdir(parents=True, exist_ok=True)
    os.environ[_TESTMON_DATAFILE_ENV] = str(testmon_dir / ".testmondata")


def _module_is_available(name: str) -> bool:
    """Return True if the optional module can be imported."""

    return importlib.util.find_spec(name) is not None


HAS_PYTEST_ASYNCIO = _module_is_available("pytest_asyncio")
HAS_PYTEST_HTTPX = _module_is_available("pytest_httpx")
_SESSION_LOOP: asyncio.AbstractEventLoop | None = None
_TEST_CLIENTS: weakref.WeakSet[TestClient] = weakref.WeakSet()
_ORIGINAL_EVENT_LOOP_POLICY = asyncio.get_event_loop_policy()


def _ensure_windows_selector_event_loop_policy() -> None:
    """Use the Selector event loop on Windows to avoid Proactor shutdown hangs."""

    if sys.platform != "win32":
        return
    if os.environ.get("PYTEST_USE_PROACTOR_EVENT_LOOP", "").lower() in {
        "1",
        "true",
        "yes",
    }:
        return
    try:
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    except Exception:
        return


if HAS_PYTEST_ASYNCIO:
    import pytest_asyncio.plugin as pytest_asyncio_plugin

    def _safe_get_event_loop_no_warn(  # type: ignore[too-many-branches]
        policy: asyncio.AbstractEventLoopPolicy | None = None,
    ) -> asyncio.AbstractEventLoop:
        """Ensure pytest-asyncio always has a usable loop even if one was cleared."""

        try:
            if policy is not None:
                return policy.get_event_loop()
            return asyncio.get_event_loop()
        except RuntimeError:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            return loop

    pytest_asyncio_plugin._get_event_loop_no_warn = _safe_get_event_loop_no_warn

if not HAS_PYTEST_ASYNCIO:
    module = types.ModuleType("pytest_asyncio")

    def _asyncio_fixture(*fixture_args, **fixture_kwargs):
        def decorator(func):
            async def _skipped_fixture(*_args: Any, **_kwargs: Any):
                pytest.skip("pytest_asyncio not installed")

            return pytest.fixture(*fixture_args, **fixture_kwargs)(_skipped_fixture)

        return decorator

    module.fixture = _asyncio_fixture  # type: ignore[assignment,attr-defined]
    sys.modules.setdefault("pytest_asyncio", module)  # type: ignore[assignment]

if not HAS_PYTEST_HTTPX:
    module = types.ModuleType("pytest_httpx")
    module.HTTPXMock = Any  # type: ignore[assignment,attr-defined]
    sys.modules.setdefault("pytest_httpx", module)  # type: ignore[assignment]

if not HAS_PYTEST_HTTPX:

    @pytest.fixture
    def httpx_mock():  # type: ignore[no-redef]
        pytest.skip("pytest_httpx not installed")


def pytest_collection_modifyitems(config, items):  # type: ignore[no-untyped-def]
    # Optimized: Single pass through items to minimize overhead with large test suites
    # Cache markers and options outside the loop
    skip_httpx = None
    if not HAS_PYTEST_HTTPX:
        skip_httpx = pytest.mark.skip(reason="pytest_httpx not installed")

    skip_asyncio = None
    if not HAS_PYTEST_ASYNCIO:
        skip_asyncio = pytest.mark.skip(reason="pytest_asyncio not installed")

    integration_marker = pytest.mark.integration
    integration_path_str = "integration"

    # Default-deselect slow/codex tests without using `-m ...` (pytest-testmon
    # disables selection when `-m` is used).
    markexpr = getattr(config.option, "markexpr", "")
    need_deselection = False
    run_slow = False
    run_codex = False
    deselected: list[pytest.Item] = []
    selected: list[pytest.Item] = []

    if not markexpr:
        run_slow = config.getoption("run_slow")
        run_codex = config.getoption("run_codex")
        need_deselection = True
        codex_path_marker = "/tests/codex/"

    # Single loop through all items
    for item in items:
        # Check httpx_mock fixture
        if skip_httpx is not None:
            fixturenames = getattr(item, "fixturenames", ())
            if "httpx_mock" in fixturenames:  # pragma: no branch
                item.add_marker(skip_httpx)

        # Check asyncio marker
        if skip_asyncio is not None and item.get_closest_marker("asyncio"):
            item.add_marker(skip_asyncio)

        # Auto-mark tests in the integration folder with @pytest.mark.integration
        # Cache fspath string conversion once per item
        item_path_str = str(item.fspath)
        if integration_path_str in item_path_str and not item.get_closest_marker(
            "integration"
        ):
            item.add_marker(integration_marker)

        # Check for slow/codex deselection
        if need_deselection:
            # Cache path string conversion and normalization
            item_path = item_path_str.replace("\\", "/")
            # Cache marker lookups
            codex_marker = item.get_closest_marker("codex")
            slow_marker = item.get_closest_marker("slow")
            is_codex = codex_marker is not None or codex_path_marker in f"/{item_path}/"
            is_slow = slow_marker is not None

            if (is_slow and not run_slow) or (is_codex and not run_codex):
                deselected.append(item)
            else:
                selected.append(item)

    # Apply deselection if needed
    if need_deselection and deselected:
        config.hook.pytest_deselected(items=deselected)
        items[:] = selected

    # Run the "stall linter" test as early as possible to fail fast on patterns
    # that can wedge xdist workers (e.g., recursive monkeypatching of asyncio.sleep).
    stall_linter_nodeid = "tests/unit/test_stall_linter.py"
    stall_linter_items = [item for item in items if stall_linter_nodeid in item.nodeid]
    if stall_linter_items:
        stall_linter_ids = {id(item) for item in stall_linter_items}
        items[:] = stall_linter_items + [
            item for item in items if id(item) not in stall_linter_ids
        ]

    # Run the "time usage linter" test early to fail fast on unsafe real-time reads
    # before xdist worker fan-out.
    time_usage_linter_nodeid = "tests/unit/test_time_usage_linter.py"
    time_usage_linter_items = [
        item for item in items if time_usage_linter_nodeid in item.nodeid
    ]
    if time_usage_linter_items:
        # Only reorder if stall linter wasn't already moved
        if not stall_linter_items:
            time_usage_linter_ids = {id(item) for item in time_usage_linter_items}
            items[:] = time_usage_linter_items + [
                item for item in items if id(item) not in time_usage_linter_ids
            ]
        else:
            # If stall linter was already moved, insert time usage linter right after it
            time_usage_linter_ids = {id(item) for item in time_usage_linter_items}
            # Find position after stall linter items
            stall_count = len(stall_linter_items)
            items[:] = (
                items[:stall_count]
                + time_usage_linter_items
                + [
                    item
                    for item in items[stall_count:]
                    if id(item) not in time_usage_linter_ids
                ]
            )


def pytest_addoption(parser) -> None:  # type: ignore[no-untyped-def]
    group = parser.getgroup("llm-interactive-proxy")
    group.addoption(
        "--run-slow",
        action="store_true",
        default=False,
        dest="run_slow",
        help="Include tests marked with @pytest.mark.slow (excluded by default).",
    )
    group.addoption(
        "--run-codex",
        action="store_true",
        default=False,
        dest="run_codex",
        help="Include tests marked with @pytest.mark.codex (excluded by default).",
    )
    group.addoption(
        "--run-black",
        action="store_true",
        default=False,
        dest="run_black",
        help="Include black formatting tests (excluded by default when ruff passes).",
    )


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
def test_client() -> Generator[TestClient, None, None]:
    """A basic TestClient using the default test app with auth disabled."""
    # Lazy import to avoid heavy initialization during collection
    from fastapi.testclient import TestClient
    from src.core.app.test_builder import build_test_app

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
    _install_test_client_tracker()
    _ensure_windows_selector_event_loop_policy()
    global _SESSION_LOOP
    try:
        _SESSION_LOOP = asyncio.get_event_loop()
    except RuntimeError:
        _SESSION_LOOP = asyncio.new_event_loop()
        asyncio.set_event_loop(_SESSION_LOOP)


def pytest_sessionfinish(session, exitstatus) -> None:  # type: ignore[no-untyped-def]
    """Cleanup potential artifacts after the test session finishes."""
    _cleanup_root_artifacts()
    _close_tracked_test_clients()
    global _SESSION_LOOP
    if _SESSION_LOOP is not None:
        try:
            asyncio.set_event_loop(None)
        finally:
            with contextlib.suppress(Exception):
                asyncio.set_event_loop_policy(_ORIGINAL_EVENT_LOOP_POLICY)
        _SESSION_LOOP = None


# Apply a global, message-targeted filter for Windows ProactorEventLoop noise
pytestmark = pytest.mark.filterwarnings(
    "ignore:unclosed event loop <ProactorEventLoop.*:ResourceWarning"
)


def pytest_configure(config) -> None:  # type: ignore[no-untyped-def]
    """Install warning filters in each worker process (xdist) and configure PID-based logging."""
    _install_global_warning_filters()
    config.addinivalue_line(
        "markers", "httpx_mock: mark tests that require pytest_httpx"
    )
    config.addinivalue_line(
        "markers", "asyncio: mark tests that require pytest_asyncio"
    )
    config.addinivalue_line(
        "markers",
        "real_time: marks tests that legitimately require real system wall-clock time (requires reason parameter)",
    )

    # Enable JUnit XML generation in CI environments or when explicitly requested
    # This reduces I/O overhead during local development
    if os.environ.get("CI") and (
        not hasattr(config.option, "junitxml") or not config.option.junitxml
    ):
        config.option.junitxml = "test-results.xml"

    # Configure timestamp-based logging
    log_file = config.getini("log_file")
    if log_file:
        # Create ./var/logs/ directory if it doesn't exist
        log_dir = Path("./var/logs")
        log_dir.mkdir(parents=True, exist_ok=True)

        # Generate log filename with timestamp (HHMM)
        timestamp = datetime.now().strftime("%H%M")
        log_path = log_dir / f"pytest-{timestamp}.log"

        # Update pytest configuration with timestamp-based log file
        config.option.log_file = str(log_path)
        config.option.log_file_level = config.getini("log_file_level")


# Test helper utilities expected by some tests
def get_backend_instance(app: Any, backend_type: str) -> Any:  # type: ignore[no-untyped-def]
    """Inject and return a backend instance used by BackendService.

    If the backend is not yet created, insert a simple placeholder object under
    BackendService._backends so tests can patch its methods before requests run.
    """
    from src.core.interfaces.backend_service_interface import IBackendService

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


def get_session_service_from_app(app: Any) -> ISessionService:  # type: ignore[no-untyped-def]
    """Resolve the ISessionService from DI."""
    from src.core.interfaces.session_service_interface import ISessionService

    service_provider = getattr(app.state, "service_provider", None)
    if service_provider is None:
        raise RuntimeError("service_provider not found on app.state")
    return service_provider.get_required_service(ISessionService)  # type: ignore[return-value,no-any-return]


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

    policy_type = type(asyncio.get_event_loop_policy())
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
        asyncio.set_event_loop_policy(policy_type())
        if _SESSION_LOOP is not None and not _SESSION_LOOP.is_closed():
            asyncio.set_event_loop(_SESSION_LOOP)

    return True


def _install_global_warning_filters() -> None:
    warnings.filterwarnings("ignore", category=PendingDeprecationWarning)
    warnings.filterwarnings("ignore", category=DeprecationWarning)
    warnings.filterwarnings("ignore", category=ResourceWarning)
    warnings.filterwarnings("ignore", category=RuntimeWarning)
    warnings.filterwarnings("ignore", category=ImportWarning)
    warnings.filterwarnings("ignore", category=UserWarning)


def _install_test_client_tracker() -> None:
    try:
        from starlette.testclient import TestClient as StarletteTestClient
    except Exception:
        return

    if getattr(StarletteTestClient, "_llm_proxy_tracking", False):
        return

    original_init = StarletteTestClient.__init__

    def _tracking_init(self, *args, **kwargs):  # type: ignore[no-untyped-def]
        original_init(self, *args, **kwargs)
        _TEST_CLIENTS.add(self)

    StarletteTestClient.__init__ = _tracking_init  # type: ignore[method-assign]
    StarletteTestClient._llm_proxy_tracking = True  # type: ignore[attr-defined]


def _close_tracked_test_clients() -> None:
    for client in list(_TEST_CLIENTS):
        with contextlib.suppress(Exception):
            client.close()


def pytest_cmdline_main(config) -> None:  # type: ignore[no-untyped-def]
    """No-op: do not rewrite pytest CLI args in tests."""
