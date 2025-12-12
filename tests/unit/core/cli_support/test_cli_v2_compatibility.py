"""Unit tests for CLI v2 compatibility layer."""

from unittest.mock import MagicMock, patch

from src.core import cli_v2


def test_cli_v2_main_delegation():
    """Test that cli_v2.main delegates to cli.main."""
    with patch("src.core.cli.main") as mock_main:
        # Mock main to be a regular function or simple coroutine mock
        # Since cli_v2.main calls asyncio.run(cli.main(...)),
        # cli.main must return a coroutine object.

        async def mock_coro(*args, **kwargs):
            pass

        mock_main.return_value = mock_coro()

        argv = ["--help"]
        cli_v2.main(argv=argv)

        mock_main.assert_called_once()
        assert mock_main.call_args[1]["argv"] == argv


def test_cli_v2_parse_cli_args_delegation():
    """Test that cli_v2.parse_cli_args delegates to cli.parse_cli_args."""
    with patch("src.core.cli.parse_cli_args") as mock_parse:
        argv = ["--version"]
        cli_v2.parse_cli_args(argv)
        mock_parse.assert_called_once_with(argv)


def test_cli_v2_apply_cli_args_delegation():
    """Test that cli_v2.apply_cli_args delegates to cli.apply_cli_args."""
    with patch("src.core.cli.apply_cli_args") as mock_apply:
        args = MagicMock()
        cli_v2.apply_cli_args(args)
        mock_apply.assert_called_once_with(args)


def test_cli_v2_is_port_in_use_delegation():
    """Test that cli_v2.is_port_in_use delegates to cli.is_port_in_use."""
    with patch("src.core.cli.is_port_in_use") as mock_is_port_in_use:
        cli_v2.is_port_in_use("localhost", 8080)
        mock_is_port_in_use.assert_called_once_with("localhost", 8080)
