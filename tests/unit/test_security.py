import os
from unittest.mock import ANY, patch

import pytest
from src.core.config.app_config import AppConfig


@pytest.mark.asyncio
async def test_cli_disable_auth_forces_localhost():
    """Test that Single User Mode (default) enforces localhost.

    Updated for access mode feature: Single User Mode now refuses to start
    with non-localhost binding instead of forcing localhost.
    Requirement 2.2: Single User Mode rejects non-localhost hosts.
    """
    from unittest.mock import AsyncMock, MagicMock

    # Test that the CLI properly enforces localhost in Single User Mode
    with (
        patch.dict(os.environ, {}, clear=True),
        patch(
            "src.core.cli_support.server_lifecycle_manager.uvicorn.Server"
        ) as mock_server_cls,
        patch(
            "src.core.cli_support.server_lifecycle_manager.uvicorn.Config"
        ) as mock_config_cls,
        patch("src.core.cli_support.logging_configurator.logging.basicConfig"),
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

        from src.core.cli import main

        # Test with localhost - should work
        await main(["--disable-auth", "--host", "127.0.0.1", "--port", "8080"])
        mock_config_cls.assert_any_call(
            ANY, host="127.0.0.1", port=8080, log_config=ANY
        )

        mock_config_cls.reset_mock()
        mock_server_cls.reset_mock()

        # Test with different host in Single User Mode - should refuse to start
        with pytest.raises(SystemExit) as exc_info:
            await main(["--disable-auth", "--host", "0.0.0.0", "--port", "8081"])
        assert exc_info.value.code == 1


@pytest.mark.asyncio
async def test_env_disable_auth_forces_localhost():
    """Test that Single User Mode (default) enforces localhost with env vars.

    Updated for access mode feature: Single User Mode now refuses to start
    with non-localhost binding instead of forcing localhost.
    Requirement 2.2: Single User Mode rejects non-localhost hosts.
    """
    from unittest.mock import MagicMock

    from src.core.cli import main

    with (
        patch.dict(
            os.environ, {"DISABLE_AUTH": "true", "PROXY_HOST": "0.0.0.0"}, clear=True
        ),
        patch(
            "src.core.cli_support.logging_configurator.LoggingConfigurator.configure"
        ),
        patch(
            "src.core.cli_support.privilege_checker.PrivilegeChecker.check_privileges"
        ),
        patch(
            "src.core.app.application_builder.build_app_async"
        ) as mock_build_app_async,
    ):
        mock_build_app_async.return_value = MagicMock()

        # Single User Mode (default) should refuse to start with non-localhost host
        with pytest.raises(SystemExit) as exc_info:
            await main(["--port", "8080"])

        # Should exit with code 1
        assert exc_info.value.code == 1


@pytest.mark.asyncio
async def test_auth_enabled_allows_custom_host():
    """Test that Multi User Mode allows custom host when authentication is enabled.

    Updated for access mode feature: Non-localhost binding now requires
    Multi User Mode. Single User Mode enforces localhost-only.
    Requirement 5.3: Multi User Mode allows non-localhost with auth.
    """
    from unittest.mock import AsyncMock, MagicMock

    from src.core.cli import main

    with (
        patch.dict(
            os.environ, {"DISABLE_AUTH": "false", "APP_HOST": "0.0.0.0"}, clear=True
        ),
        patch(
            "src.core.cli_support.server_lifecycle_manager.uvicorn.Server"
        ) as mock_server_cls,
        patch(
            "src.core.cli_support.server_lifecycle_manager.uvicorn.Config"
        ) as mock_config_cls,
        patch("src.core.cli_support.logging_configurator.logging.basicConfig"),
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

        from src.core.cli import main

        # Use Multi User Mode to allow non-localhost binding with auth
        await main(["--port", "8080", "--multi-user-mode"])
        mock_config_cls.assert_any_call(ANY, host="0.0.0.0", port=8080, log_config=ANY)


def test_config_disable_auth_forces_localhost():
    """Test that the legacy _enforce_localhost_if_auth_disabled function still works.

    Note: This function is now superseded by access mode validation, but remains
    for backward compatibility. Access mode validation runs first and would reject
    non-localhost in Single User Mode before this function is called.
    """
    from src.core.cli import _enforce_localhost_if_auth_disabled
    from src.core.config.app_config import AuthConfig

    # Create a config with auth disabled and non-localhost host
    auth_config = AuthConfig(disable_auth=True)
    test_config = AppConfig(host="192.168.1.100", auth=auth_config)

    # The enforcement function still forces localhost (legacy behavior)
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
