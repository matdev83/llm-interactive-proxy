"""Integration tests for CLI backward compatibility.

Requirements:
- 7.2: Verify full CLI invocation with various argument combinations behaves as expected
- 9.4: End-to-end integration tests
"""

from unittest.mock import AsyncMock, patch

import pytest
from fastapi import FastAPI
from src.core import cli
from src.core.config.app_config import AppConfig


@pytest.mark.asyncio
async def test_full_cli_invocation_simulation():
    """Test full CLI invocation flow with mocked dependencies.

    This simulates what happens when `python -m src.core.cli ...` is run.
    """
    test_args = [
        "--host",
        "127.0.0.1",
        "--port",
        "9999",
        "--log-level",
        "DEBUG",
        "--disable-auth",
    ]

    # We mock out the actual server startup to avoid binding ports or hanging,
    # and the app build to avoid heavy staged initialization (~2s savings)
    with (
        patch(
            "src.core.cli_support.server_lifecycle_manager.ServerLifecycleManager.start_servers",
            new_callable=AsyncMock,
        ) as mock_start,
        patch(
            "src.core.cli_support.server_lifecycle_manager.ServerLifecycleManager.check_ports"
        ),
        patch(
            "src.core.cli.build_app_async",
            new_callable=AsyncMock,
            return_value=FastAPI(),
        ),
    ):
        # Execute main with test args
        await cli.main(argv=test_args)

        # Verify start_servers was called with expected config
        mock_start.assert_called_once()
        call_args = mock_start.call_args
        call_args[0][0]  # first arg is app
        cfg = call_args[0][1]  # second arg is cfg

        assert isinstance(cfg, AppConfig)
        assert cfg.host == "127.0.0.1"
        assert cfg.port == 9999
        assert cfg.logging.level.name == "DEBUG"
        assert cfg.auth.disable_auth is True


@pytest.mark.asyncio
async def test_cli_daemon_mode_simulation():
    """Test CLI daemon mode handling simulation."""
    test_args = ["--daemon", "--log", "./test.log"]

    with patch(
        "src.core.cli_support.server_lifecycle_manager.ServerLifecycleManager.handle_daemon_mode",
        return_value=True,
    ) as mock_daemon:
        # Execute main
        await cli.main(argv=test_args)

        # Should have returned early, so start_servers should NOT be called
        # But we need to verify handle_daemon_mode was called
        mock_daemon.assert_called_once()

        # If handle_daemon_mode returned True, main() returns immediately.
        # We can also mock start_servers to ensure it wasn't called
        with patch(
            "src.core.cli_support.server_lifecycle_manager.ServerLifecycleManager.start_servers",
            new_callable=AsyncMock,
        ) as mock_start:
            await cli.main(argv=test_args)
            mock_start.assert_not_called()


def test_cli_parsing_roundtrip():
    """Test parsing arguments and applying them results in expected config."""
    # This tests the interaction between build_cli_parser and apply_cli_args
    # (which now use the new services)

    argv = ["--default-backend", "openai", "--thinking-budget", "1024", "--enable-sso"]

    args = cli.parse_cli_args(argv)
    cfg = cli.apply_cli_args(args)

    assert cfg.backends.default_backend == "openai"
    assert cfg.session.planning_phase.overrides["thinking_budget"] == 1024
    assert cfg.sso.enabled is True
