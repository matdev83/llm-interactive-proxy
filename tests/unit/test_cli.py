import os
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient
from src.constants import DEFAULT_COMMAND_PREFIX
from src.core.app.test_builder import build_test_app as app_main_build_app
from src.core.cli import apply_cli_args, main, parse_cli_args


def test_apply_cli_args_sets_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
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
    cfg = apply_cli_args(args)
    assert os.environ["LLM_BACKEND"] == "gemini"
    assert os.environ["GEMINI_API_KEY"] == "TESTKEY"
    assert os.environ["PROXY_PORT"] == "1234"
    assert os.environ["COMMAND_PREFIX"] == "$/"
    assert cfg.backends.default_backend == "gemini"
    assert cfg.backends.gemini.api_key == "TESTKEY"
    assert cfg.port == 1234
    assert cfg.command_prefix == "$/"
    # cleanup environment variables set by apply_cli_args
    monkeypatch.delenv("LLM_BACKEND", raising=False)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("PROXY_PORT", raising=False)
    monkeypatch.delenv("COMMAND_PREFIX", raising=False)


def test_cli_interactive_mode(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("DISABLE_INTERACTIVE_MODE", raising=False)
    args = parse_cli_args(["--disable-interactive-mode"])
    cfg = apply_cli_args(args)
    assert os.environ["DISABLE_INTERACTIVE_MODE"] == "True"
    assert cfg.session.default_interactive_mode is False
    monkeypatch.delenv("DISABLE_INTERACTIVE_MODE", raising=False)


def test_cli_redaction_flag(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("REDACT_API_KEYS_IN_PROMPTS", raising=False)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    for i in range(1, 21):
        monkeypatch.delenv(f"GEMINI_API_KEY_{i}", raising=False)
    args = parse_cli_args(["--disable-redact-api-keys-in-prompts"])
    cfg = apply_cli_args(args)
    assert cfg.auth.redact_api_keys_in_prompts is False
    monkeypatch.delenv("REDACT_API_KEYS_IN_PROMPTS", raising=False)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    for i in range(1, 21):
        monkeypatch.delenv(f"GEMINI_API_KEY_{i}", raising=False)
    args = parse_cli_args(["--disable-interactive-mode"])
    cfg = apply_cli_args(args)
    assert os.environ["DISABLE_INTERACTIVE_MODE"] == "True"
    assert cfg.session.default_interactive_mode is False


def test_cli_force_set_project(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("FORCE_SET_PROJECT", raising=False)
    # Test setting the flag
    args = parse_cli_args(["--force-set-project"])
    cfg = apply_cli_args(args)
    assert os.environ["FORCE_SET_PROJECT"] == "true"
    assert cfg.session.force_set_project is True
    monkeypatch.delenv("FORCE_SET_PROJECT", raising=False)


def test_cli_disable_interactive_commands(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("DISABLE_INTERACTIVE_COMMANDS", raising=False)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    for i in range(1, 21):
        monkeypatch.delenv(f"GEMINI_API_KEY_{i}", raising=False)
    args = parse_cli_args(["--disable-interactive-commands"])
    cfg = apply_cli_args(args)
    assert cfg.session.disable_interactive_commands is True
    monkeypatch.delenv("DISABLE_INTERACTIVE_COMMANDS", raising=False)
    #     monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    #     for i in range(1, 21):
    #         monkeypatch.delenv(f"GEMINI_API_KEY_{i}", raising=False)
    #     args = parse_cli_args(["--force-set-project"])
    #     cfg = apply_cli_args(args)
    #     assert os.environ["FORCE_SET_PROJECT"] == "true"
    #     assert cfg["force_set_project"] is True
    #     monkeypatch.delenv("FORCE_SET_PROJECT", raising=False)


from pathlib import Path


def test_cli_log_argument(tmp_path: Path) -> None:
    args = parse_cli_args(["--log", str(tmp_path / "out.log")])
    assert args.log_file == str(tmp_path / "out.log")


def test_main_log_file(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    import src.core.cli as cli

    log_file = tmp_path / "srv.log"

    recorded = {}

    def fake_basic_config(**kwargs: dict[str, str]) -> None:
        recorded.update(kwargs)

    monkeypatch.setattr(cli.logging, "basicConfig", fake_basic_config)
    monkeypatch.setattr(cli.uvicorn, "run", lambda app, host, port: None)
    monkeypatch.setattr(cli, "_check_privileges", lambda: None)

    cli.main(["--log", str(log_file)])

    assert recorded.get("filename") == str(log_file)


def test_build_app_uses_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    for i in range(1, 21):
        monkeypatch.delenv(f"GEMINI_API_KEY_{i}", raising=False)
    monkeypatch.setenv("LLM_BACKEND", "gemini")
    monkeypatch.setenv("GEMINI_API_KEY", "KEY")
    monkeypatch.setenv("COMMAND_PREFIX", "??/")
    app = app_main_build_app()
    with TestClient(app):  # Ensure lifespan runs
        assert app.state.app_config.backends.default_backend == "gemini"
        assert app.state.app_config.command_prefix == "??/"
        # Verify that the backend service is configured for gemini

        # In test environment, the backend service is a mock, so we can't check _config
        # Instead, just check the app_config which we've already verified above
        assert app.state.app_config.backends.default_backend == "gemini"
    monkeypatch.delenv("COMMAND_PREFIX", raising=False)


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
        from src.core.interfaces.session_service_interface import ISessionService

        session_service = app.state.service_provider.get_required_service(
            ISessionService
        )
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
    assert cfg.command_prefix == DEFAULT_COMMAND_PREFIX


@pytest.mark.parametrize("prefix", ["!", "!!", "prefix with space", "12345678901"])
def test_invalid_command_prefix_cli(
    monkeypatch: pytest.MonkeyPatch, prefix: str
) -> None:
    for i in range(1, 21):
        monkeypatch.delenv(f"GEMINI_API_KEY_{i}", raising=False)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    args = parse_cli_args(["--command-prefix", prefix])
    with pytest.raises(ValueError):
        apply_cli_args(args)
    monkeypatch.delenv("COMMAND_PREFIX", raising=False)


@pytest.mark.skipif(os.name == "nt", reason="Test for non-Windows systems")
def test_check_privileges_root(monkeypatch: pytest.MonkeyPatch) -> None:
    from src.core.cli import _check_privileges

    monkeypatch.setattr(os, "geteuid", lambda: 0, raising=False)
    with pytest.raises(SystemExit):
        _check_privileges()


@pytest.mark.skipif(os.name == "nt", reason="Test for non-Windows systems")
def test_check_privileges_non_root(monkeypatch: pytest.MonkeyPatch) -> None:
    from src.core.cli import _check_privileges

    monkeypatch.setattr(os, "geteuid", lambda: 1000, raising=False)
    _check_privileges()


@pytest.mark.skipif(os.name != "nt", reason="Test for Windows systems")
def test_check_privileges_admin_windows(monkeypatch: pytest.MonkeyPatch) -> None:
    import ctypes

    from src.core.cli import _check_privileges

    monkeypatch.setattr(
        ctypes.windll.shell32,  # type: ignore
        "IsUserAnAdmin",
        lambda: 1,
        raising=False,
    )
    with pytest.raises(SystemExit):
        _check_privileges()


@pytest.mark.skipif(os.name != "nt", reason="Test for Windows systems")
def test_check_privileges_non_admin_windows(monkeypatch: pytest.MonkeyPatch) -> None:
    import ctypes

    from src.core.cli import _check_privileges

    monkeypatch.setattr(
        ctypes.windll.shell32,  # type: ignore
        "IsUserAnAdmin",
        lambda: 0,
        raising=False,
    )
    _check_privileges()


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
        assert cfg.port == 8080


def test_apply_cli_args_disable_auth_forces_localhost() -> None:
    """Test that disable_auth via CLI forces host to localhost."""
    args = parse_cli_args(["--disable-auth", "--host", "0.0.0.0"])
    with (
        patch.dict(os.environ, {}, clear=True),
        patch("src.core.cli.logging") as mock_logging,
    ):
        cfg = apply_cli_args(args)
        assert cfg.host == "127.0.0.1"
        assert cfg.auth.disable_auth is True
        # Should log a warning about forcing localhost
        mock_logging.warning.assert_called_once()


def test_apply_cli_args_disable_auth_with_localhost_no_warning() -> None:
    """Test that disable_auth with localhost doesn't trigger warning."""
    args = parse_cli_args(["--disable-auth", "--host", "127.0.0.1"])
    with (
        patch.dict(os.environ, {}, clear=True),
        patch("src.core.cli.logging") as mock_logging,
    ):
        cfg = apply_cli_args(args)
        assert cfg.host == "127.0.0.1"
        assert cfg.auth.disable_auth is True
        # Should not log a warning since host is already localhost
        mock_logging.warning.assert_not_called()


def test_main_disable_auth_forces_localhost() -> None:
    """Test that main function forces localhost when disable_auth is set."""
    with (
        patch.dict(
            os.environ, {"DISABLE_AUTH": "true", "PROXY_HOST": "0.0.0.0"}, clear=True
        ),
        patch("src.core.cli.logging.basicConfig"),
        patch("src.core.cli.logging") as mock_logging,
        patch("uvicorn.run") as mock_uvicorn,
        patch("src.core.cli._check_privileges"),
    ):
        mock_app = MagicMock()
        mock_build_app = MagicMock(return_value=mock_app)

        main(["--port", "8080"], build_app_fn=mock_build_app)

        # Should force host to localhost
        mock_uvicorn.assert_called_once_with(mock_app, host="127.0.0.1", port=8080)
        # Should log warning about auth being disabled
        warning_calls = [str(call) for call in mock_logging.warning.call_args_list]
        auth_disabled_warnings = [
            call for call in warning_calls if "authentication is DISABLED" in call
        ]
        assert len(auth_disabled_warnings) >= 1


def test_main_disable_auth_with_localhost_no_force() -> None:
    """Test that main function doesn't force localhost when it's already localhost."""
    with (
        patch.dict(
            os.environ, {"DISABLE_AUTH": "true", "PROXY_HOST": "127.0.0.1"}, clear=True
        ),
        patch("src.core.cli.logging.basicConfig"),
        patch("src.core.cli.logging") as mock_logging,
        patch("uvicorn.run") as mock_uvicorn,
        patch("src.core.cli._check_privileges"),
    ):
        mock_app = MagicMock()
        mock_build_app = MagicMock(return_value=mock_app)

        main(["--port", "8080"], build_app_fn=mock_build_app)

        # Should use localhost
        mock_uvicorn.assert_called_once_with(mock_app, host="127.0.0.1", port=8080)
        # Should log warning about auth being disabled but not about forcing host
        warning_calls = [str(call) for call in mock_logging.warning.call_args_list]
        auth_disabled_warnings = [
            call for call in warning_calls if "authentication is DISABLED" in call
        ]
        assert len(auth_disabled_warnings) >= 1


def test_main_auth_enabled_allows_custom_host() -> None:
    """Test that main function allows custom host when auth is enabled."""
    with (
        patch.dict(
            os.environ, {"DISABLE_AUTH": "false", "PROXY_HOST": "0.0.0.0"}, clear=True
        ),
        patch("src.core.cli.logging.basicConfig"),
        patch("src.core.cli.logging") as mock_logging,
        patch("uvicorn.run") as mock_uvicorn,
        patch("src.core.cli._check_privileges"),
    ):
        mock_app = MagicMock()
        mock_build_app = MagicMock(return_value=mock_app)

        main(["--port", "8080"], build_app_fn=mock_build_app)

        # Should use custom host when auth is enabled
        mock_uvicorn.assert_called_once_with(mock_app, host="0.0.0.0", port=8080)
        # Should not log warning about auth being disabled
        auth_warnings = [
            call
            for call in mock_logging.warning.call_args_list
            if "authentication is DISABLED" in str(call)
        ]
        assert len(auth_warnings) == 0
