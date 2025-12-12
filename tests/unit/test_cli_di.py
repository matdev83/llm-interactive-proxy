import os
from pathlib import Path
from unittest.mock import ANY, MagicMock, patch

import pytest

pytestmark = pytest.mark.filterwarnings(
    "ignore:unclosed event loop <ProactorEventLoop.*:ResourceWarning"
)

from fastapi.testclient import TestClient
from src.constants import DEFAULT_COMMAND_PREFIX
from src.core.app.test_builder import build_test_app as app_main_build_app
from src.core.cli import apply_cli_args, main, parse_cli_args
from src.core.config.app_config import AppConfig, LogLevel, load_config
from src.core.interfaces.session_service_interface import ISessionService

from tests.utils.test_di_utils import get_required_service_from_app


def test_apply_cli_args_sets_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("LLM_BACKEND", raising=False)
    monkeypatch.delenv("PROXY_PORT", raising=False)
    monkeypatch.delenv("COMMAND_PREFIX", raising=False)
    for i in range(1, 21):
        monkeypatch.delenv(f"GEMINI_API_KEY_{i}", raising=False)
    args = parse_cli_args(
        [
            "--default-backend",
            "gemini",
            "--gemini-api-key",
            "TESTKEY",
            "--port",
            "1234",
            "--command-prefix",
            "$/",
        ]
    )
    with patch(
        "src.core.cli.load_config", return_value=AppConfig()
    ) as mock_load_config:
        monkeypatch.setenv("LLM_BACKEND", "gemini")
        cfg = apply_cli_args(args)
        mock_load_config.assert_called()
    if isinstance(cfg, tuple):
        cfg = cfg[0]
    assert os.environ.get("LLM_BACKEND") == "gemini"
    assert os.environ.get("GEMINI_API_KEY") == "TESTKEY"
    assert os.environ.get("PROXY_PORT") == "1234"
    assert os.environ.get("COMMAND_PREFIX") == "$" + "/"
    assert cfg.backends.default_backend == "gemini"
    assert cfg.backends.gemini.api_key == "TESTKEY"
    assert cfg.port == 1234
    assert cfg.command_prefix == "$/"
    # cleanup environment variables set by apply_cli_args
    # The environment variables should not be set, so no need to delete them.


def test_app_config_from_env_loads_zenmux(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ZENMUX_API_KEY", "zen-key")
    monkeypatch.setenv("ZENMUX_API_BASE_URL", "https://custom.zenmux/api")
    monkeypatch.setenv("ZENMUX_TIMEOUT", "45")

    config = AppConfig.from_env()
    assert config.backends.zenmux.api_key == "zen-key"
    assert config.backends.zenmux.api_url == "https://custom.zenmux/api"
    assert config.backends.zenmux.timeout == 45


def test_configuration_precedence(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    cfg_file = tmp_path / "proxy.yaml"
    cfg_file.write_text("host: config-host\n")

    # config-only
    monkeypatch.delenv("APP_HOST", raising=False)
    config_only = load_config(str(cfg_file))
    assert config_only.host == "config-host"

    # env overrides config
    monkeypatch.setenv("APP_HOST", "env-host")
    env_args = parse_cli_args(["--config", str(cfg_file)])
    env_config, _ = apply_cli_args(env_args, return_resolution=True)
    assert env_config.host == "env-host"

    # CLI overrides env
    cli_args = parse_cli_args(["--config", str(cfg_file), "--host", "cli-host"])
    cli_config, resolution = apply_cli_args(cli_args, return_resolution=True)
    assert cli_config.host == "cli-host"
    assert any(
        entry.source.name == "CLI" and entry.name == "host"
        for entry in resolution.build_report(cli_config)
    )

    monkeypatch.delenv("APP_HOST", raising=False)


def test_cli_interactive_mode(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("DEFAULT_INTERACTIVE_MODE", raising=False)
    args = parse_cli_args(["--disable-interactive-mode"])
    cfg = apply_cli_args(args)
    if isinstance(cfg, tuple):
        cfg = cfg[0]
    assert os.environ["DEFAULT_INTERACTIVE_MODE"] == "false"
    assert cfg.session.default_interactive_mode is False
    monkeypatch.delenv("DEFAULT_INTERACTIVE_MODE", raising=False)


def test_cli_redaction_flag(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("REDACT_API_KEYS_IN_PROMPTS", raising=False)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    for i in range(1, 21):
        monkeypatch.delenv(f"GEMINI_API_KEY_{i}", raising=False)
    args = parse_cli_args(["--disable-redact-api-keys-in-prompts"])
    cfg = apply_cli_args(args)
    if isinstance(cfg, tuple):
        cfg = cfg[0]
    assert cfg.auth.redact_api_keys_in_prompts is False
    monkeypatch.delenv("REDACT_API_KEYS_IN_PROMPTS", raising=False)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    for i in range(1, 21):
        monkeypatch.delenv(f"GEMINI_API_KEY_{i}", raising=False)
    args = parse_cli_args(["--disable-interactive-mode"])
    cfg = apply_cli_args(args)
    if isinstance(cfg, tuple):
        cfg = cfg[0]
    assert os.environ["DEFAULT_INTERACTIVE_MODE"] == "false"
    assert cfg.session.default_interactive_mode is False
    # Clean up to prevent test pollution
    monkeypatch.delenv("DEFAULT_INTERACTIVE_MODE", raising=False)


def test_cli_force_set_project(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("FORCE_SET_PROJECT", raising=False)
    # Test setting the flag
    args = parse_cli_args(["--force-set-project"])
    cfg = apply_cli_args(args)
    if isinstance(cfg, tuple):
        cfg = cfg[0]
    assert os.environ.get("FORCE_SET_PROJECT") == "true"
    assert cfg.session.force_set_project is True
    monkeypatch.delenv("FORCE_SET_PROJECT", raising=False)


def test_cli_normalizes_backend_api_keys(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    for i in range(1, 21):
        monkeypatch.delenv(f"GEMINI_API_KEY_{i}", raising=False)
    args = parse_cli_args(
        [
            "--gemini-api-key",
            " gemini-key ",
            "--openrouter-api-key",
            "openrouter-key",
            "--zai-api-key",
            "zai-key",
        ]
    )

    cfg = apply_cli_args(args)
    if isinstance(cfg, tuple):
        cfg = cfg[0]

    assert cfg.backends.gemini.api_key == "gemini-key"
    assert cfg.backends.openrouter.api_key == "openrouter-key"
    assert cfg.backends.zai.api_key == "zai-key"


def test_cli_planning_phase_overrides_merge(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("THINKING_BUDGET", raising=False)
    args = parse_cli_args(
        [
            "--thinking-budget",
            "321",
            "--planning-phase-temperature",
            "0.42",
        ]
    )

    cfg = apply_cli_args(args)
    if isinstance(cfg, tuple):
        cfg = cfg[0]

    overrides = cfg.session.planning_phase.overrides
    assert overrides.get("thinking_budget") == 321
    assert overrides.get("temperature") == 0.42


def test_cli_disable_interactive_commands(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("DISABLE_INTERACTIVE_COMMANDS", raising=False)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    for i in range(1, 21):
        monkeypatch.delenv(f"GEMINI_API_KEY_{i}", raising=False)
    args = parse_cli_args(["--disable-interactive-commands"])
    cfg = apply_cli_args(args)
    if isinstance(cfg, tuple):
        cfg = cfg[0]
    assert cfg.session.disable_interactive_commands is True
    monkeypatch.delenv("DISABLE_INTERACTIVE_COMMANDS", raising=False)


def test_cli_log_argument(tmp_path: Path) -> None:
    args = parse_cli_args(["--log", str(tmp_path / "out.log")])
    assert args.log_file == str(tmp_path / "out.log")


def test_apply_cli_args_preserves_config_log_file(tmp_path: Path) -> None:
    from src.core.config.app_config import LoggingConfig

    existing_log = tmp_path / "configured.log"
    # Create config with existing log file setting
    logging_cfg = LoggingConfig(log_file=str(existing_log))
    config = AppConfig(logging=logging_cfg)

    with patch("src.core.cli.load_config", return_value=config):
        args = parse_cli_args([])
        applied = apply_cli_args(args)
        # Handle tuple return from apply_cli_args
        if isinstance(applied, tuple):
            applied = applied[0]

    assert applied.logging.log_file == str(existing_log)


def test_apply_cli_args_respects_existing_log_level() -> None:
    from src.core.config.app_config import LoggingConfig

    # Create config with existing log level setting
    logging_cfg = LoggingConfig(level=LogLevel.DEBUG)
    config = AppConfig(logging=logging_cfg)

    with patch("src.core.cli.load_config", return_value=config):
        args = parse_cli_args([])
        applied = apply_cli_args(args)
        # Handle tuple return from apply_cli_args
        if isinstance(applied, tuple):
            applied = applied[0]

    assert applied.logging.level is LogLevel.DEBUG


@pytest.mark.asyncio
async def test_main_log_file(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    import logging

    import src.core.cli as cli

    log_file = tmp_path / "srv.log"

    root_logger = logging.getLogger()
    original_handlers = root_logger.handlers[:]
    root_logger.handlers.clear()

    from unittest.mock import AsyncMock, MagicMock, patch

    with (
        patch(
            "src.core.cli_support.server_lifecycle_manager.uvicorn.Server"
        ) as mock_server_cls,
        patch(
            "src.core.cli_support.privilege_checker.PrivilegeChecker.check_privileges",
            lambda *args, **kwargs: None,
        ),
        patch(
            "src.core.app.application_builder.build_app_async"
        ) as mock_build_app_async,
        patch("src.core.app.stages.backend.BackendStage.validate", return_value=True),
        patch(
            "src.core.cli_support.server_lifecycle_manager.ServerLifecycleManager.is_port_in_use",
            return_value=False,
        ),
    ):
        mock_build_app_async.return_value = MagicMock()

        # Mock server instance and serve method
        mock_server_instance = MagicMock()
        mock_server_instance.serve = AsyncMock(return_value=None)
        mock_server_cls.return_value = mock_server_instance

        try:
            # Use a different port to avoid conflicts during parallel test execution
            await cli.main(["--log", str(log_file), "--port", "9999"])

            file_handlers = [
                h for h in root_logger.handlers if isinstance(h, logging.FileHandler)
            ]
            assert len(file_handlers) == 1
            # The actual log file will have a PID suffix added by _apply_pid_suffixes
            # Check that the handler's filename contains the base log file path
            handler_path = file_handlers[0].baseFilename
            # Extract the base name without PID suffix for comparison
            # Format is: srv-pid-12345.log
            import os

            assert handler_path.startswith(str(tmp_path))
            assert "srv" in os.path.basename(handler_path)
            assert handler_path.endswith(".log")
        finally:
            for handler in root_logger.handlers:
                handler.close()
            root_logger.handlers[:] = original_handlers


@pytest.mark.asyncio
async def test_build_app_uses_interactive_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    for i in range(1, 21):
        monkeypatch.delenv(f"GEMINI_API_KEY_{i}", raising=False)
        monkeypatch.delenv(f"OPENROUTER_API_KEY_{i}", raising=False)
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    monkeypatch.delenv("DISABLE_INTERACTIVE_MODE", raising=False)
    monkeypatch.delenv("DISABLE_INTERACTIVE_COMMANDS", raising=False)
    # Use gemini backend with a dummy key since it doesn't require API keys for testing
    monkeypatch.setenv("LLM_BACKEND", "gemini")
    monkeypatch.setenv("GEMINI_API_KEY", "dummy-key-for-testing")
    monkeypatch.setenv("LLM_INTERACTIVE_PROXY_API_KEY", "test-key")
    app = app_main_build_app()

    with TestClient(app):  # Ensure lifespan runs
        # Get session service using proper DI
        session_service = get_required_service_from_app(app, ISessionService)
        session = await session_service.get_session("s1")
        assert session.state.interactive_mode is True


def test_default_command_prefix_from_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("COMMAND_PREFIX", raising=False)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    for i in range(1, 21):
        monkeypatch.delenv(f"GEMINI_API_KEY_{i}", raising=False)
        monkeypatch.delenv(f"OPENROUTER_API_KEY_{i}", raising=False)
    args = parse_cli_args([])
    cfg = apply_cli_args(args)
    if isinstance(cfg, tuple):
        cfg = cfg[0]
    assert cfg.command_prefix == DEFAULT_COMMAND_PREFIX


@pytest.mark.parametrize("prefix", ["!", "!!", "prefix with space", "12345678901"])
def test_invalid_command_prefix_cli(
    monkeypatch: pytest.MonkeyPatch, prefix: str
) -> None:
    for i in range(1, 21):
        monkeypatch.delenv(f"GEMINI_API_KEY_{i}", raising=False)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)

    # apply_cli_args modifies os.environ["COMMAND_PREFIX"] directly, so we need to manually cleanup
    original_prefix = os.environ.get("COMMAND_PREFIX")

    try:
        args = parse_cli_args(["--command-prefix", prefix])
        with pytest.raises(ValueError):
            apply_cli_args(args)
    finally:
        # Restore environment
        if original_prefix is None:
            if "COMMAND_PREFIX" in os.environ:
                del os.environ["COMMAND_PREFIX"]
        else:
            os.environ["COMMAND_PREFIX"] = original_prefix


def test_check_privileges_root(monkeypatch: pytest.MonkeyPatch) -> None:
    from src.core.cli import _check_privileges

    # Simulate elevated privileges regardless of platform
    monkeypatch.setattr("src.core.cli._is_admin", lambda: True)

    expected_message = (
        "Refusing to run as root user"
        if os.name != "nt"
        else "Refusing to run with administrative privileges"
    )

    with pytest.raises(SystemExit) as exc_info:
        _check_privileges()

    assert str(exc_info.value) == expected_message


def test_check_privileges_non_root(monkeypatch: pytest.MonkeyPatch) -> None:
    from src.core.cli import _check_privileges

    # Mock all the group checking functions to avoid false positives
    try:
        import grp

        monkeypatch.setattr(grp, "getgrnam", lambda name: None, raising=False)
    except ImportError:
        # grp module doesn't exist on Windows
        pass

    # Mock Unix/Linux non-root check
    monkeypatch.setattr(os, "geteuid", lambda: 1000, raising=False)
    _check_privileges()


@pytest.mark.skipif(os.name != "nt", reason="Windows-specific test")
def test_check_privileges_admin_windows(monkeypatch: pytest.MonkeyPatch) -> None:
    import ctypes

    from src.core.cli import _check_privileges

    # Mock Windows admin check
    mock_shell32 = MagicMock()
    mock_shell32.IsUserAnAdmin.return_value = 1
    monkeypatch.setattr(ctypes, "windll", MagicMock())
    monkeypatch.setattr(ctypes.windll, "shell32", mock_shell32)

    with pytest.raises(SystemExit):
        _check_privileges()


@pytest.mark.skipif(os.name != "nt", reason="Windows-specific test")
def test_check_privileges_non_admin_windows(monkeypatch: pytest.MonkeyPatch) -> None:
    import ctypes

    from src.core.cli import _check_privileges

    # Mock Windows non-admin check
    mock_shell32 = MagicMock()
    mock_shell32.IsUserAnAdmin.return_value = 0
    monkeypatch.setattr(ctypes, "windll", MagicMock())
    monkeypatch.setattr(ctypes.windll, "shell32", mock_shell32)

    _check_privileges()


def test_check_privileges_admin(monkeypatch: pytest.MonkeyPatch) -> None:
    """Test admin privilege detection (cross-platform)."""
    from src.core.cli import _check_privileges, _has_privilege_functionality

    # Skip test if platform doesn't support privilege checking
    if not _has_privilege_functionality():
        pytest.skip("Platform doesn't support privilege checks")

    if os.name != "nt":
        # Mock Unix/Linux admin check (root user)
        monkeypatch.setattr(os, "geteuid", lambda: 0, raising=False)

        with pytest.raises(SystemExit, match="Refusing to run as root user"):
            _check_privileges()
    else:
        # Mock Windows admin check
        import ctypes

        monkeypatch.setattr(ctypes, "windll", MagicMock())
        mock_shell32 = MagicMock()
        mock_shell32.IsUserAnAdmin.return_value = 1
        monkeypatch.setattr(ctypes.windll, "shell32", mock_shell32)

        with pytest.raises(
            SystemExit, match="Refusing to run with administrative privileges"
        ):
            _check_privileges()


def test_check_privileges_non_admin(monkeypatch: pytest.MonkeyPatch) -> None:
    """Test non-admin privilege detection (cross-platform)."""
    from src.core.cli import _check_privileges, _has_privilege_functionality

    # Skip test if platform doesn't support privilege checking
    if not _has_privilege_functionality():
        pytest.skip("Platform doesn't support privilege checks")

    if os.name != "nt":
        # Mock all the group checking functions to avoid false positives
        import grp

        monkeypatch.setattr(grp, "getgrnam", lambda name: None, raising=False)

        # Mock Unix/Linux non-admin check (regular user)
        monkeypatch.setattr(os, "geteuid", lambda: 1000, raising=False)

        # Should not raise an exception for non-admin users
        _check_privileges()
    else:
        # Mock Windows non-admin check
        import ctypes

        monkeypatch.setattr(ctypes, "windll", MagicMock())
        mock_shell32 = MagicMock()
        mock_shell32.IsUserAnAdmin.return_value = 0
        monkeypatch.setattr(ctypes.windll, "shell32", mock_shell32)

        # Should not raise an exception for non-admin users
        _check_privileges()


def test_check_privileges_is_admin(monkeypatch: pytest.MonkeyPatch) -> None:
    """Test the _is_admin utility function (cross-platform)."""
    from src.core.cli import _has_privilege_functionality, _is_admin

    # Skip test if platform doesn't support privilege checking
    if not _has_privilege_functionality():
        pytest.skip("Platform doesn't support privilege checks")

    if os.name != "nt":
        # Mock all the group checking functions to avoid false positives
        import grp

        monkeypatch.setattr(grp, "getgrnam", lambda name: None, raising=False)

        # Test Unix/Linux admin detection (root user)
        monkeypatch.setattr(os, "geteuid", lambda: 0, raising=False)
        assert _is_admin() is True

        # Test Unix/Linux non-admin detection (regular user)
        monkeypatch.setattr(os, "geteuid", lambda: 1000, raising=False)
        assert _is_admin() is False

        # Test Unix/Linux with missing geteuid (fallback)
        monkeypatch.delattr(os, "geteuid", raising=False)
        assert _is_admin() is False
    else:
        # Test Windows admin detection
        import ctypes

        monkeypatch.setattr(ctypes, "windll", MagicMock())
        mock_shell32 = MagicMock()
        mock_shell32.IsUserAnAdmin.return_value = 1
        monkeypatch.setattr(ctypes.windll, "shell32", mock_shell32)
        assert _is_admin() is True

        # Test Windows non-admin detection
        mock_shell32.IsUserAnAdmin.return_value = 0
        assert _is_admin() is False

        # Test Windows with missing windll (fallback)
        monkeypatch.delattr(ctypes, "windll", raising=False)
        assert _is_admin() is False


def test_check_privileges_has_functionality() -> None:
    """Test the _has_privilege_functionality utility function."""
    from src.core.cli import _has_privilege_functionality

    # Should return True on both Unix/Linux and Windows platforms
    # (assuming the platform supports the necessary functions)
    result = _has_privilege_functionality()
    assert isinstance(result, bool)

    # The function should return True on most modern systems
    # that support privilege checking functionality
    if os.name != "nt":
        # Unix/Linux systems should have geteuid
        assert result is True
    else:
        # Windows systems should have ctypes.windll
        assert result is True


def test_parse_cli_args_basic() -> None:
    """Test basic CLI argument parsing."""
    args = parse_cli_args(["--port", "8080", "--host", "0.0.0.0"])
    assert args.port == 8080
    assert args.host == "0.0.0.0"


def test_parse_cli_args_disable_auth() -> None:
    """Test parsing disable-auth flag."""
    args = parse_cli_args(["--disable-auth"])
    assert args.disable_auth is True


def test_apply_cli_args_basic() -> None:
    """Test basic CLI argument application."""
    args = parse_cli_args(["--port", "8080"])
    with patch.dict(os.environ, {}, clear=True):
        cfg = apply_cli_args(args)
        if isinstance(cfg, tuple):
            cfg = cfg[0]
        assert cfg.port == 8080


def test_apply_cli_args_disable_auth_does_not_force_localhost() -> None:
    """Test that disable_auth via CLI does NOT force host to localhost in apply_cli_args."""
    args = parse_cli_args(["--disable-auth", "--host", "0.0.0.0"])
    with (
        patch.dict(os.environ, {}, clear=True),
        patch("src.core.cli.logging") as mock_logging,
    ):
        cfg = apply_cli_args(args)
        if isinstance(cfg, tuple):
            cfg = cfg[0]
        assert cfg.host == "0.0.0.0"
        assert cfg.auth.disable_auth is True
        # No warnings should be logged at this stage
        mock_logging.warning.assert_not_called()


def test_apply_cli_args_disable_auth_with_localhost_no_force() -> None:
    """Test that disable_auth with localhost doesn't force host and logs no warnings."""
    args = parse_cli_args(["--disable-auth", "--host", "127.0.0.1"])
    with (
        patch.dict(os.environ, {}, clear=True),
        patch("src.core.cli.logging") as mock_logging,
    ):
        cfg = apply_cli_args(args)
        if isinstance(cfg, tuple):
            cfg = cfg[0]
        assert cfg.host == "127.0.0.1"
        assert cfg.auth.disable_auth is True
        # No warnings should be logged at this stage
        mock_logging.warning.assert_not_called()


@pytest.mark.asyncio
async def test_main_disable_auth_forces_localhost() -> None:
    """Test that main function forces localhost when disable_auth is set."""
    from unittest.mock import AsyncMock

    with (
        patch.dict(
            os.environ, {"DISABLE_AUTH": "true", "PROXY_HOST": "0.0.0.0"}, clear=True
        ),
        patch(
            "src.core.cli_support.logging_configurator.LoggingConfigurator.configure"
        ),
        patch("src.core.cli.logging") as mock_logging,
        patch(
            "src.core.cli_support.server_lifecycle_manager.uvicorn.Server"
        ) as mock_server_cls,
        patch(
            "src.core.cli_support.privilege_checker.PrivilegeChecker.check_privileges"
        ),
        patch(
            "src.core.app.application_builder.build_app_async"
        ) as mock_build_app_async,
        patch("src.core.app.stages.backend.BackendStage.validate", return_value=True),
        patch(
            "src.core.cli_support.server_lifecycle_manager.ServerLifecycleManager.is_port_in_use",
            return_value=False,
        ),
        patch(
            "src.core.cli_support.server_lifecycle_manager.create_anthropic_app_async",
            new_callable=AsyncMock,
        ),
    ):
        mock_build_app_async.return_value = MagicMock()

        # Mock server instance and serve method
        mock_server_instance = MagicMock()
        mock_server_instance.serve = AsyncMock(return_value=None)
        mock_server_cls.return_value = mock_server_instance

        await main(["--port", "8080", "--disable-auth", "--host", "0.0.0.0"])

        # Should force host to localhost. Check Config initialization
        call_args = mock_server_cls.call_args
        assert call_args is not None
        # uvicorn.Config is passed as first arg or 'config' kwarg
        # In implementation: uvicorn.Config(app, host=..., ...)
        # We need to check the arguments passed to uvicorn.Config, BUT
        # cli.py creates uvicorn.Config object first and passes it to Server.
        # We need to mock uvicorn.Config too to inspect it, or inspect the Server call args
        # implementation:
        # main_config = uvicorn.Config(app, host=cfg.host, port=cfg.port, ...)
        # main_server = uvicorn.Server(main_config)

        # Let's patch uvicorn.Config as well to check arguments easily
        with patch(
            "src.core.cli_support.server_lifecycle_manager.uvicorn.Config"
        ) as mock_config_cls:
            await main(["--port", "8080", "--disable-auth", "--host", "0.0.0.0"])

            # Check that Config was initialized with forced localhost
            mock_config_cls.assert_any_call(
                ANY, host="127.0.0.1", port=8080, log_config=ANY
            )

        # Should log warning about auth being disabled
        warning_calls = [str(call) for call in mock_logging.warning.call_args_list]
        auth_disabled_warnings = [
            call for call in warning_calls if "authentication is DISABLED" in call
        ]
        assert len(auth_disabled_warnings) >= 1


@pytest.mark.asyncio
async def test_main_disable_auth_with_localhost_no_force() -> None:
    """Test that main function doesn't force localhost when it's already localhost."""
    from unittest.mock import AsyncMock

    with (
        patch.dict(
            os.environ, {"DISABLE_AUTH": "true", "PROXY_HOST": "127.0.0.1"}, clear=True
        ),
        patch(
            "src.core.cli_support.logging_configurator.LoggingConfigurator.configure"
        ),
        patch("src.core.cli.logging") as mock_logging,
        patch(
            "src.core.cli_support.server_lifecycle_manager.uvicorn.Server"
        ) as mock_server_cls,
        patch(
            "src.core.cli_support.privilege_checker.PrivilegeChecker.check_privileges"
        ),
        patch(
            "src.core.app.application_builder.build_app_async"
        ) as mock_build_app_async,
        patch("src.core.app.stages.backend.BackendStage.validate", return_value=True),
        patch(
            "src.core.cli_support.server_lifecycle_manager.ServerLifecycleManager.is_port_in_use",
            return_value=False,
        ),
        patch(
            "src.core.cli_support.server_lifecycle_manager.create_anthropic_app_async",
            new_callable=AsyncMock,
        ),
    ):
        mock_build_app_async.return_value = MagicMock()

        # Mock server instance
        mock_server_instance = MagicMock()
        mock_server_instance.serve = AsyncMock(return_value=None)
        mock_server_cls.return_value = mock_server_instance

        with patch(
            "src.core.cli_support.server_lifecycle_manager.uvicorn.Config"
        ) as mock_config_cls:
            await main(["--port", "8080", "--disable-auth", "--host", "127.0.0.1"])

            # Should use localhost
            mock_config_cls.assert_any_call(
                ANY, host="127.0.0.1", port=8080, log_config=ANY
            )

        # Should log warning about auth being disabled but not about forcing host
        warning_calls = [str(call) for call in mock_logging.warning.call_args_list]
        auth_disabled_warnings = [
            call for call in warning_calls if "authentication is DISABLED" in call
        ]
        assert len(auth_disabled_warnings) >= 1


@pytest.mark.asyncio
async def test_main_auth_enabled_allows_custom_host() -> None:
    """Test that main function allows custom host when auth is enabled."""
    from unittest.mock import AsyncMock

    with (
        patch.dict(
            os.environ, {"DISABLE_AUTH": "false", "PROXY_HOST": "0.0.0.0"}, clear=True
        ),
        patch(
            "src.core.cli_support.logging_configurator.LoggingConfigurator.configure"
        ),
        patch("src.core.cli.logging") as mock_logging,
        patch(
            "src.core.cli_support.server_lifecycle_manager.uvicorn.Server"
        ) as mock_server_cls,
        patch(
            "src.core.cli_support.privilege_checker.PrivilegeChecker.check_privileges"
        ),
        patch(
            "src.core.app.application_builder.build_app_async"
        ) as mock_build_app_async,
        patch("src.core.app.stages.backend.BackendStage.validate", return_value=True),
        patch(
            "src.core.cli_support.server_lifecycle_manager.ServerLifecycleManager.is_port_in_use",
            return_value=False,
        ),
        patch(
            "src.core.cli_support.server_lifecycle_manager.create_anthropic_app_async",
            new_callable=AsyncMock,
        ),
    ):
        mock_build_app_async.return_value = MagicMock()

        # Mock server instance
        mock_server_instance = MagicMock()
        mock_server_instance.serve = AsyncMock(return_value=None)
        mock_server_cls.return_value = mock_server_instance

        with patch(
            "src.core.cli_support.server_lifecycle_manager.uvicorn.Config"
        ) as mock_config_cls:
            await main(["--port", "8080", "--host", "0.0.0.0"])

            # Should use custom host when auth is enabled
            mock_config_cls.assert_any_call(
                ANY, host="0.0.0.0", port=8080, log_config=ANY
            )

        # Should not log warning about auth being disabled
        auth_warnings = [
            call
            for call in mock_logging.warning.call_args_list
            if "authentication is DISABLED" in str(call)
        ]
        assert len(auth_warnings) == 0
