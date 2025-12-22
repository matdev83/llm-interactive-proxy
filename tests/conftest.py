from __future__ import annotations

import asyncio
import contextlib
import importlib.util
import inspect
import os
import sys
import types
import warnings
import xml.etree.ElementTree
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
HAS_PYTEST_XDIST = _module_is_available("xdist")
HAS_PYTEST_TESTMON = _module_is_available("pytest_testmon")
_SESSION_LOOP: asyncio.AbstractEventLoop | None = None


def _has_user_test_selection(args: list[str]) -> bool:
    if any(arg for arg in args if not arg.startswith("-")):
        return True
    for arg in args:
        if arg in ("-k", "-m", "--lf", "--last-failed", "--ff", "--failed-first"):
            return True
        if arg.startswith(("-k", "-m")):
            return True
    return False


def _should_enable_testmon(args: list[str]) -> bool:
    if any(arg in ("--help", "--version", "--fixtures") for arg in args):
        return False
    return HAS_PYTEST_TESTMON and not _has_user_test_selection(args)


def _has_verbosity_flag(args: list[str]) -> bool:
    for arg in args:
        if arg in ("--verbose", "--quiet"):
            return True
        if arg.startswith(("-v", "-q")):
            return True
    return False


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
    # Cache marker lookups and path operations to avoid repeated work
    if not HAS_PYTEST_HTTPX:
        skip_httpx = pytest.mark.skip(reason="pytest_httpx not installed")
        for item in items:
            fixturenames = getattr(item, "fixturenames", ())
            if "httpx_mock" in fixturenames:  # pragma: no branch
                item.add_marker(skip_httpx)

    if not HAS_PYTEST_ASYNCIO:
        skip_asyncio = pytest.mark.skip(reason="pytest_asyncio not installed")
        for item in items:
            if item.get_closest_marker("asyncio"):
                item.add_marker(skip_asyncio)

    # Auto-mark tests in the integration folder with @pytest.mark.integration
    # (handy for `pytest -m integration` runs and reporting)
    # Cache path strings to avoid repeated str() calls
    integration_marker = pytest.mark.integration
    integration_path_str = "integration"
    for item in items:
        # Cache fspath string conversion
        item_path_str = str(item.fspath)
        # Check if test file path contains 'integration' and marker not present
        if integration_path_str in item_path_str and not item.get_closest_marker(
            "integration"
        ):
            item.add_marker(integration_marker)

    # Default-deselect slow/codex tests without using `-m ...` (pytest-testmon
    # disables selection when `-m` is used).
    markexpr = getattr(config.option, "markexpr", "")
    if not markexpr:
        run_slow = config.getoption("run_slow")
        run_codex = config.getoption("run_codex")

        deselected: list[pytest.Item] = []
        selected: list[pytest.Item] = []
        codex_path_marker = "/tests/codex/"
        for item in items:
            # Cache path string conversion and normalization
            item_path = str(item.fspath).replace("\\", "/")
            # Cache marker lookups
            codex_marker = item.get_closest_marker("codex")
            slow_marker = item.get_closest_marker("slow")
            is_codex = codex_marker is not None or codex_path_marker in f"/{item_path}/"
            is_slow = slow_marker is not None

            if (is_slow and not run_slow) or (is_codex and not run_codex):
                deselected.append(item)
            else:
                selected.append(item)

        if deselected:
            config.hook.pytest_deselected(items=deselected)
            items[:] = selected


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
    global _SESSION_LOOP
    try:
        _SESSION_LOOP = asyncio.get_event_loop()
    except RuntimeError:
        _SESSION_LOOP = asyncio.new_event_loop()
        asyncio.set_event_loop(_SESSION_LOOP)


def pytest_sessionfinish(session, exitstatus) -> None:  # type: ignore[no-untyped-def]
    """Cleanup potential artifacts after the test session finishes."""
    _cleanup_root_artifacts()
    global _SESSION_LOOP
    if _SESSION_LOOP is not None:
        try:
            if not _SESSION_LOOP.is_closed():
                _SESSION_LOOP.close()
        finally:
            asyncio.set_event_loop_policy(asyncio.DefaultEventLoopPolicy())
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


@pytest.hookimpl(wrapper=True)
def pytest_cmdline_parse(pluginmanager, args):
    """
    Dynamically modifies pytest arguments before test collection.
    """
    config = yield

    # Skip argument modification when xdist is active (master or workers)
    # to avoid collection mismatches and deadlocks
    # Check for xdist usage via:
    # 1. Environment variable (worker processes)
    # 2. Config option (after config is created)
    # 3. Plugin registration (fallback)
    # Skip XML parsing during collection-only mode to speed up collection
    is_collect_only = "--collect-only" in args or "--co" in args

    # Disable xdist during collection-only mode to speed up collection
    # xdist workers add overhead during collection and aren't needed
    # Do this BEFORE checking xdist status to prevent workers from starting
    if is_collect_only and HAS_PYTEST_XDIST and hasattr(config.option, "numprocesses"):
        # Disable xdist by setting numprocesses to 0 (no workers)
        # This prevents worker startup overhead during collection
        config.option.numprocesses = 0

    # Skip argument modification when xdist is active (but not during collection-only)
    # to avoid collection mismatches and deadlocks
    if HAS_PYTEST_XDIST and not is_collect_only:
        is_xdist_worker = os.environ.get("PYTEST_XDIST_WORKER") is not None
        # Check if xdist is configured (numprocesses option is set and > 0)
        # Note: numprocesses=0 means xdist is disabled, so we should continue
        has_xdist_config = (
            hasattr(config.option, "numprocesses")
            and config.option.numprocesses is not None
            and config.option.numprocesses > 0
        )
        xdist_plugin_registered = pluginmanager.hasplugin("xdist")

        if is_xdist_worker or has_xdist_config or xdist_plugin_registered:
            return

    original_args = list(args)
    modified_args = args.copy()  # Don't modify original args

    use_testmon = _should_enable_testmon(original_args)
    if use_testmon:
        if "--testmon" not in modified_args:
            modified_args.append("--testmon")
    elif "--testmon" in modified_args:
        modified_args = [arg for arg in modified_args if arg != "--testmon"]

    has_test_paths = any(arg for arg in modified_args if not arg.startswith("-"))
    has_maxfail = any(arg.startswith("--maxfail") for arg in modified_args)
    has_lf = "--lf" in modified_args

    # Handle test paths and add default configuration
    if not has_test_paths and not any(
        arg in ("--version", "--help", "--fixtures") for arg in modified_args
    ):
        # Use testpaths from the config file
        testpaths = config.getini("testpaths")
        modified_args = testpaths + modified_args

        # Skip XML parsing during collection-only mode
        if not has_maxfail and not has_lf and not is_collect_only:
            try:
                tree = xml.etree.ElementTree.parse("test-results.xml")
                root = tree.getroot()
                testsuite = root.find("testsuite")
                if testsuite is not None:
                    failures = int(testsuite.attrib.get("failures", 0))
                    if failures > 0:
                        if "--ff" not in modified_args:
                            modified_args.append("--ff")
                        modified_args.append(f"--maxfail={failures}")
                    else:
                        modified_args.append("--maxfail=1")
                else:
                    modified_args.append("--maxfail=1")
            except (xml.etree.ElementTree.ParseError, FileNotFoundError):
                modified_args.append("--maxfail=1")
        elif not has_maxfail and not has_lf:
            # During collection-only, just add default maxfail
            modified_args.append("--maxfail=1")

        # Add -q for quiet output unless user specified a verbosity level
        has_verbosity_flag = _has_verbosity_flag(modified_args)
        if not has_verbosity_flag:
            modified_args.append("-q")

        if "-rfE" not in modified_args:
            modified_args.append("-rfE")

    # Update config args and return
    config.args = modified_args


def pytest_cmdline_main(config):
    """
    Backward compatibility function for testing pytest_cmdline_main.
    """
    # Skip argument modification when xdist is active to avoid conflicts
    if HAS_PYTEST_XDIST:
        is_xdist_worker = os.environ.get("PYTEST_XDIST_WORKER") is not None
        has_xdist_config = (
            hasattr(config.option, "numprocesses")
            and config.option.numprocesses is not None
        )
        if is_xdist_worker or has_xdist_config:
            return

    # Skip XML parsing during collection-only mode to speed up collection
    is_collect_only = "--collect-only" in config.args or "--co" in config.args

    invocation_params = getattr(config, "invocation_params", None)
    original_args = None
    if invocation_params is not None:
        invocation_args = getattr(invocation_params, "args", None)
        if isinstance(invocation_args, list | tuple):
            original_args = list(invocation_args)
    if original_args is None:
        original_args = list(config.args)

    use_testmon = _should_enable_testmon(original_args)
    if use_testmon:
        if "--testmon" not in config.args:
            config.args.append("--testmon")
    elif "--testmon" in config.args:
        config.args = [arg for arg in config.args if arg != "--testmon"]

    # Disable xdist during collection-only mode to speed up collection
    if is_collect_only and HAS_PYTEST_XDIST and hasattr(config.option, "numprocesses"):
        # Disable xdist by setting numprocesses to 0 (no workers)
        config.option.numprocesses = 0

    has_test_paths = any(arg for arg in config.args if not arg.startswith("-"))
    has_maxfail = any(arg.startswith("--maxfail") for arg in config.args)
    has_lf = "--lf" in config.args

    if not has_test_paths and not any(
        arg in ("--version", "--help", "--fixtures") for arg in config.args
    ):
        # Use testpaths from the config file
        config.args = config.getini("testpaths") + config.args

        # Skip XML parsing during collection-only mode
        if not has_maxfail and not has_lf and not is_collect_only:
            try:
                tree = xml.etree.ElementTree.parse("test-results.xml")
                root = tree.getroot()
                testsuite = root.find("testsuite")
                if testsuite is not None:
                    failures = int(testsuite.attrib.get("failures", 0))
                    if failures > 0:
                        if "--ff" not in config.args:
                            config.args.append("--ff")
                        config.args.append(f"--maxfail={failures}")
                    else:
                        config.args.append("--maxfail=1")
                else:
                    config.args.append("--maxfail=1")
            except (xml.etree.ElementTree.ParseError, FileNotFoundError):
                config.args.append("--maxfail=1")
        elif not has_maxfail and not has_lf:
            # During collection-only, just add default maxfail
            config.args.append("--maxfail=1")

        # Add -q for quiet output unless user specified a verbosity level
        has_verbosity_flag = _has_verbosity_flag(config.args)
        if not has_verbosity_flag:
            config.args.append("-q")

        if "-rfE" not in config.args:
            config.args.append("-rfE")
