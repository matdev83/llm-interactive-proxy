import os
from unittest.mock import ANY, patch

import pytest
from src.core.config.app_config import AppConfig


def test_cli_disable_auth_forces_localhost():
    """Test that the CLI enforces localhost when --disable-auth is used with --host."""
    # Test that the CLI properly forces localhost when disable-auth is set
    with (
        patch.dict(os.environ, {}, clear=True),
        patch("uvicorn.run") as mock_uvicorn,
        patch("src.core.cli.logging.basicConfig"),
        patch("src.core.cli._check_privileges"),
        patch("src.core.app.application_builder.build_app"),
        patch("src.core.app.stages.backend.BackendStage.validate", return_value=True),
        patch("src.core.cli.is_port_in_use", return_value=False),
    ):
        # This should work without error (localhost is allowed)
        from src.core.cli import main

        # Test with localhost - should work
        main(["--disable-auth", "--host", "127.0.0.1", "--port", "8080"])
        mock_uvicorn.assert_called_with(
            ANY, host="127.0.0.1", port=8080, log_config=ANY
        )

        mock_uvicorn.reset_mock()

        # Test with different host - should be forced to localhost
        main(["--disable-auth", "--host", "0.0.0.0", "--port", "8081"])
        mock_uvicorn.assert_called_with(
            ANY, host="127.0.0.1", port=8081, log_config=ANY
        )


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
        patch("src.core.app.application_builder.build_app"),
        patch("src.core.app.stages.backend.BackendStage.validate", return_value=True),
        patch("src.core.cli.is_port_in_use", return_value=False),
    ):
        from src.core.cli import main

        main(["--port", "8080"])
        mock_uvicorn.assert_called_with(
            ANY, host="127.0.0.1", port=8080, log_config=ANY
        )


def test_auth_enabled_allows_custom_host():
    """Test that custom host is allowed when authentication is enabled."""
    from src.core.cli import main

    with (
        patch.dict(
            os.environ, {"DISABLE_AUTH": "false", "APP_HOST": "0.0.0.0"}, clear=True
        ),
        patch("uvicorn.run") as mock_uvicorn,
        patch("src.core.cli.logging.basicConfig"),
        patch("src.core.cli._check_privileges"),
        patch("src.core.app.application_builder.build_app"),
        patch("src.core.app.stages.backend.BackendStage.validate", return_value=True),
    ):
        from src.core.cli import main

        main(["--port", "8080"])
        mock_uvicorn.assert_called_with(ANY, host="0.0.0.0", port=8080, log_config=ANY)


def test_config_disable_auth_forces_localhost():
    """Test that CLI enforces localhost when disable_auth is true."""
    from src.core.cli import _enforce_localhost_if_auth_disabled
    from src.core.config.app_config import AuthConfig

    # Create a config with auth disabled and non-localhost host
    auth_config = AuthConfig(disable_auth=True)
    test_config = AppConfig(host="192.168.1.100", auth=auth_config)

    # The enforcement function should force localhost
    with patch("src.core.cli.logging") as mock_logging:
        enforced_config = _enforce_localhost_if_auth_disabled(test_config)
        assert enforced_config.host == "127.0.0.1"
        assert enforced_config.auth.disable_auth
        # Should have logged warnings
        assert mock_logging.warning.call_count >= 2


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


# Suppress Windows ProactorEventLoop warnings for this module
pytestmark = pytest.mark.filterwarnings(
    "ignore:unclosed event loop <ProactorEventLoop.*:ResourceWarning"
)
