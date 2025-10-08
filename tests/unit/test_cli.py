import argparse
import socket
from unittest.mock import patch

import pytest
from src.core.cli import (
    _maybe_run_as_daemon,
    apply_cli_args,
    is_port_in_use,
    parse_cli_args,
)
from src.core.config.app_config import AppConfig

# Make sure all connectors are imported and registered
from src.core.services import backend_imports  # noqa: F401
from src.core.services.backend_registry import backend_registry


def test_cli_allows_all_registered_backends() -> None:
    """
    Verify that the CLI accepts all dynamically discovered backends for the --default-backend argument.
    """
    registered_backends = backend_registry.get_registered_backends()
    assert registered_backends  # Ensure we have some backends registered

    for backend_name in registered_backends:
        with patch("src.core.config.app_config.load_config", return_value=AppConfig()):
            # Test parsing
            args = parse_cli_args(["--default-backend", backend_name])
            assert args.default_backend == backend_name

            # Test application of args
            config = apply_cli_args(args)
            assert config.backends.default_backend == backend_name


def test_is_port_in_use_handles_wildcard_host() -> None:
    """Ensure wildcard host detection checks loopback addresses."""

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
        listener.bind(("127.0.0.1", 0))
        listener.listen(1)
        port = listener.getsockname()[1]

        assert is_port_in_use("0.0.0.0", port) is True


def test_cli_strict_command_detection_flags() -> None:
    """
    Test that CLI flag for strict command detection works correctly.
    """
    # Patch load_config where it is looked up (in the 'cli' module)
    with patch("src.core.cli.load_config") as mock_load_config:
        # 1. Test --strict-command-detection flag
        mock_load_config.return_value = AppConfig()
        args_enable = parse_cli_args(["--strict-command-detection"])
        assert args_enable.strict_command_detection is True
        config_enable = apply_cli_args(args_enable)
        assert config_enable.strict_command_detection is True

        # 2. Test default behavior (None) when no flag is provided
        # Let's create a config where it's initially False to see if it's preserved.
        initial_config_false = AppConfig()
        initial_config_false.strict_command_detection = False
        mock_load_config.return_value = initial_config_false

        args_none = parse_cli_args([])
        assert args_none.strict_command_detection is None
        config_none = apply_cli_args(args_none)
        assert not config_none.strict_command_detection  # Should remain False

        # And if it was initially True
        initial_config_true = AppConfig()
        initial_config_true.strict_command_detection = True
        mock_load_config.return_value = initial_config_true
        config_none_true = apply_cli_args(args_none)
        assert config_none_true.strict_command_detection is True  # Should remain True

        # 3. Test that flag overrides initial config
        # Initial config is False
        initial_config_override = AppConfig()
        initial_config_override.strict_command_detection = False
        mock_load_config.return_value = initial_config_override
        # but we enable it with the flag
        config_override = apply_cli_args(args_enable)
        assert config_override.strict_command_detection is True


def test_cli_rejects_non_existent_backend() -> None:
    """
    Verify that the CLI rejects a backend name that is not registered.
    """
    non_existent_backend = "non-existent-backend-12345"
    registered_backends = backend_registry.get_registered_backends()
    assert non_existent_backend not in registered_backends

    # Argparse exits the program on invalid choices, which pytest captures as SystemExit
    with pytest.raises(SystemExit):
        parse_cli_args(["--default-backend", non_existent_backend])


def test_cli_backend_choices_match_registry() -> None:
    """
    Verify that the choices for --default-backend in the CLI's argument parser
    are identical to the list of registered backends.

    This test ensures that there is no discrepancy between the implemented
    backends and the backends offered by the CLI.
    """
    registered_backends = backend_registry.get_registered_backends()

    # Patch the ArgumentParser class within the module where it is used (src.core.cli)
    with patch("src.core.cli.argparse.ArgumentParser") as MockArgumentParser:
        # The return_value of the class mock is the instance that will be created
        mock_parser_instance = MockArgumentParser.return_value

        # Call the function that creates the parser
        parse_cli_args([])

        # Find the specific call to add_argument for '--default-backend'
        found_call = None
        for call in mock_parser_instance.add_argument.call_args_list:
            # Check if '--default-backend' is one of the positional arguments
            if "--default-backend" in call.args:
                found_call = call
                break

        assert (
            found_call is not None
        ), "Could not find the add_argument call for --default-backend"

        # Check that the 'choices' keyword argument is identical to the registered backends
        cli_choices = found_call.kwargs.get("choices")
        assert (
            cli_choices is not None
        ), "CLI argument '--default-backend' has no choices"
        assert sorted(cli_choices) == sorted(registered_backends)


def test_cli_context_window_override_argument_parsing() -> None:
    """Test that the --force-context-window CLI argument is parsed correctly."""
    with patch("src.core.config.app_config.load_config", return_value=AppConfig()):
        # Test parsing with context window override
        args = parse_cli_args(["--force-context-window", "5000"])
        assert args.force_context_window == 5000

        # Test application of args to config
        config = apply_cli_args(args)
        assert config.context_window_override == 5000

        # Test with different values
        args2 = parse_cli_args(["--force-context-window", "100000"])
        config2 = apply_cli_args(args2)
        assert config2.context_window_override == 100000


def test_cli_context_window_override_defaults_to_none() -> None:
    """Test that context window override defaults to None when not specified."""
    with patch("src.core.config.app_config.load_config", return_value=AppConfig()):
        # Test parsing without the argument
        args = parse_cli_args([])
        assert args.force_context_window is None

        # Test application of args to config
        config = apply_cli_args(args)
        assert config.context_window_override is None


def test_cli_context_window_override_environment_variable() -> None:
    """Test that FORCE_CONTEXT_WINDOW environment variable is set when CLI argument is provided."""
    import os

    with patch("src.core.config.app_config.load_config", return_value=AppConfig()):
        # Store original environment variable
        original_env = os.environ.get("FORCE_CONTEXT_WINDOW")

        try:
            # Clear the environment variable first
            if "FORCE_CONTEXT_WINDOW" in os.environ:
                del os.environ["FORCE_CONTEXT_WINDOW"]

            # Test application of args sets environment variable
            args = parse_cli_args(["--force-context-window", "7500"])
            config = apply_cli_args(args)

            assert config.context_window_override == 7500
            assert os.environ.get("FORCE_CONTEXT_WINDOW") == "7500"

        finally:
            # Restore original environment variable
            if original_env is not None:
                os.environ["FORCE_CONTEXT_WINDOW"] = original_env
            elif "FORCE_CONTEXT_WINDOW" in os.environ:
                del os.environ["FORCE_CONTEXT_WINDOW"]


def test_cli_pytest_compression_flags() -> None:
    """Test that --enable-pytest-compression and --disable-pytest-compression flags work."""
    # Patch load_config where it is looked up (in the 'cli' module)
    with patch("src.core.cli.load_config") as mock_load_config:
        # 1. Test --enable-pytest-compression
        mock_load_config.return_value = AppConfig()
        args_enable = parse_cli_args(["--enable-pytest-compression"])
        assert args_enable.pytest_compression_enabled is True
        config_enable = apply_cli_args(args_enable)
        assert config_enable.session.pytest_compression_enabled is True

        # 2. Test --disable-pytest-compression
        mock_load_config.return_value = AppConfig()
        args_disable = parse_cli_args(["--disable-pytest-compression"])
        assert args_disable.pytest_compression_enabled is False
        config_disable = apply_cli_args(args_disable)
        assert config_disable.session.pytest_compression_enabled is False

        # 3. Test default behavior (None) when no flag is provided
        # Let's create a config where it's initially False to see if it's preserved.
        initial_config_false = AppConfig()
        initial_config_false.session.pytest_compression_enabled = False
        mock_load_config.return_value = initial_config_false

        args_none = parse_cli_args([])
        assert args_none.pytest_compression_enabled is None
        config_none = apply_cli_args(args_none)
        assert not config_none.session.pytest_compression_enabled  # Should remain False

        # And if it was initially True
        initial_config_true = AppConfig()
        initial_config_true.session.pytest_compression_enabled = True
        mock_load_config.return_value = initial_config_true
        config_none_true = apply_cli_args(args_none)
        assert (
            config_none_true.session.pytest_compression_enabled is True
        )  # Should remain True

        # 4. Test that flags override initial config
        # Initial config is False
        initial_config_override = AppConfig()
        initial_config_override.session.pytest_compression_enabled = False
        mock_load_config.return_value = initial_config_override
        # but we enable it with the flag
        config_override = apply_cli_args(args_enable)
        assert config_override.session.pytest_compression_enabled is True


def test_maybe_run_as_daemon_posix_continues(monkeypatch: pytest.MonkeyPatch) -> None:
    """Ensure daemon mode continues execution on POSIX systems."""

    # Prepare CLI arguments and configuration
    args = argparse.Namespace(daemon=True)
    cfg = AppConfig()
    cfg.logging.log_file = "logs/proxy.log"

    daemonized = {"called": False}

    def fake_daemonize() -> None:
        daemonized["called"] = True

    import src.core.cli as cli

    monkeypatch.setattr(cli, "_daemonize", fake_daemonize)
    monkeypatch.setattr(cli.os, "name", "posix", raising=False)

    should_exit = _maybe_run_as_daemon(args, cfg)

    assert daemonized["called"] is True
    assert should_exit is False


def test_cli_capture_limits_arguments() -> None:
    """Ensure CLI options for capture limits are parsed and applied."""
    with patch("src.core.cli.load_config", return_value=AppConfig()):
        args = parse_cli_args(
            [
                "--capture-max-bytes",
                "1024",
                "--capture-truncate-bytes",
                "256",
                "--capture-max-files",
                "3",
            ]
        )

        assert args.capture_max_bytes == 1024
        assert args.capture_truncate_bytes == 256
        assert args.capture_max_files == 3

        config = apply_cli_args(args)
        assert config.logging.capture_max_bytes == 1024
        assert config.logging.capture_truncate_bytes == 256
        assert config.logging.capture_max_files == 3
