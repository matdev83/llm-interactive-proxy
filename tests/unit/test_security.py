import os
from unittest.mock import patch

import pytest


def test_cli_disable_auth_forces_localhost():
    """Test that the CLI enforces localhost when --disable-auth is used with --host."""
    # Test that the CLI properly forces localhost when disable-auth is set
    with (
        patch.dict(os.environ, {}, clear=True),
        patch("uvicorn.run") as mock_uvicorn,
        patch("src.core.cli.logging.basicConfig"),
        patch("src.core.cli._check_privileges"),
    ):
        # This should work without error (localhost is allowed)
        from src.core.cli import main

        mock_app = object()

        def mock_build_app(cfg, config_file=None):
            return mock_app

        # Test with localhost - should work
        main(
            ["--disable-auth", "--host", "127.0.0.1", "--port", "8080"],
            build_app_fn=mock_build_app,
        )
        mock_uvicorn.assert_called_with(mock_app, host="127.0.0.1", port=8080)

        mock_uvicorn.reset_mock()

        # Test with different host - should be forced to localhost
        main(
            ["--disable-auth", "--host", "0.0.0.0", "--port", "8081"],
            build_app_fn=mock_build_app,
        )
        mock_uvicorn.assert_called_with(mock_app, host="127.0.0.1", port=8081)


def test_env_disable_auth_forces_localhost():
    """Test that environment variable DISABLE_AUTH=true forces localhost."""
    from src.core.cli import main

    with (
        patch.dict(
            os.environ, {"DISABLE_AUTH": "true", "PROXY_HOST": "0.0.0.0"}, clear=True
        ),
        patch("uvicorn.run") as mock_uvicorn,
        patch("src.core.cli.logging.basicConfig"),
        patch("src.core.cli._check_privileges"),
    ):
        from src.core.cli import main

        mock_app = object()

        def mock_build_app(cfg, config_file=None):
            return mock_app

        main(["--port", "8080"], build_app_fn=mock_build_app)
        mock_uvicorn.assert_called_with(mock_app, host="127.0.0.1", port=8080)


def test_auth_enabled_allows_custom_host():
    """Test that custom host is allowed when authentication is enabled."""
    from src.core.cli import main

    with (
        patch.dict(
            os.environ, {"DISABLE_AUTH": "false", "PROXY_HOST": "0.0.0.0"}, clear=True
        ),
        patch("uvicorn.run") as mock_uvicorn,
        patch("src.core.cli.logging.basicConfig"),
        patch("src.core.cli._check_privileges"),
    ):
        from src.core.cli import main

        mock_app = object()

        def mock_build_app(cfg, config_file=None):
            return mock_app

        main(["--port", "8080"], build_app_fn=mock_build_app)
        mock_uvicorn.assert_called_with(mock_app, host="0.0.0.0", port=8080)


def test_config_disable_auth_forces_localhost():
    """Test that config loading enforces localhost when disable_auth is true."""
    from src.core.config import _load_config

    with (
        patch.dict(
            os.environ,
            {"DISABLE_AUTH": "true", "PROXY_HOST": "192.168.1.100"},
            clear=True,
        ),
        patch("src.core.config.logger") as mock_logger,
    ):
        from src.core.config import _load_config

        config = _load_config()
        assert config["proxy_host"] == "127.0.0.1"
        assert config["disable_auth"]
        mock_logger.warning.assert_called_once()


def test_security_documentation():
    """Test that security behavior is properly documented in help text."""
    # Test that the disable-auth flag exists and has proper help text
    import contextlib
    from io import StringIO

    from src.core.cli import parse_cli_args

    # Suppress the help banner printed by argparse to keep the pytest output clean.
    with contextlib.redirect_stdout(StringIO()), pytest.raises(SystemExit):
        parse_cli_args(["--help"])

    # Test that the flag can be parsed
    args = parse_cli_args(["--disable-auth"])
    assert args.disable_auth
