import argparse
import os
import socket
from unittest.mock import patch

import pytest
from src.core.cli import _maybe_run_as_daemon, apply_cli_args, parse_cli_args
from src.core.config.app_config import AppConfig, ParameterResolution

# Make sure all connectors are imported and registered
from src.core.services import backend_imports  # noqa: F401
from src.core.services.backend_registry import backend_registry


@pytest.fixture(autouse=True)
def clean_cli_environment():
    """Ensure clean environment for CLI tests to prevent contamination."""
    # Store original values
    original_env = {}
    env_vars_to_clean = ["COMMAND_PREFIX", "MODEL_ALIASES", "STATIC_ROUTE"]

    for var in env_vars_to_clean:
        original_env[var] = os.environ.get(var)
        if var in os.environ:
            del os.environ[var]

    yield

    # Restore original values
    for var, value in original_env.items():
        if value is not None:
            os.environ[var] = value
        elif var in os.environ:
            del os.environ[var]


def _unwrap_config(
    result: AppConfig | tuple[AppConfig, ParameterResolution],
) -> AppConfig:
    return result[0] if isinstance(result, tuple) else result


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
            config = _unwrap_config(apply_cli_args(args))
            if isinstance(config, tuple):
                config = config[0]
            assert config.backends.default_backend == backend_name


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
        config_enable = _unwrap_config(apply_cli_args(args_enable))
        assert config_enable.strict_command_detection is True

        # 2. Test default behavior (None) when no flag is provided
        # Let's create a config where it's initially False to see if it's preserved.
        initial_config_false = AppConfig(strict_command_detection=False)
        mock_load_config.return_value = initial_config_false

        args_none = parse_cli_args([])
        assert args_none.strict_command_detection is None
        config_none = _unwrap_config(apply_cli_args(args_none))
        assert not config_none.strict_command_detection  # Should remain False

        # And if it was initially True
        initial_config_true = AppConfig(strict_command_detection=True)
        mock_load_config.return_value = initial_config_true
        config_none_true = _unwrap_config(apply_cli_args(args_none))
        assert config_none_true.strict_command_detection is True  # Should remain True

        # 3. Test that flag overrides initial config
        # Initial config is False
        initial_config_override = AppConfig(strict_command_detection=False)
        mock_load_config.return_value = initial_config_override
        # but we enable it with the flag
        config_override = _unwrap_config(apply_cli_args(args_enable))
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


def test_is_port_in_use_supports_ipv6() -> None:
    """is_port_in_use should gracefully handle IPv6 hosts."""

    if not socket.has_ipv6:
        pytest.skip("IPv6 is not supported on this platform")

    from src.core.cli import is_port_in_use

    with socket.socket(socket.AF_INET6, socket.SOCK_STREAM) as server:
        server.bind(("::1", 0))
        server.listen(1)
        port = server.getsockname()[1]
        assert is_port_in_use("::1", port) is True

    assert is_port_in_use("::1", port) is False


def test_cli_context_window_override_argument_parsing() -> None:
    """Test that the --force-context-window CLI argument is parsed correctly."""
    with patch("src.core.config.app_config.load_config", return_value=AppConfig()):
        # Test parsing with context window override
        args = parse_cli_args(["--force-context-window", "5000"])
        assert args.force_context_window == 5000

        # Test application of args to config
        config = _unwrap_config(apply_cli_args(args))
        assert config.context_window_override == 5000

        # Test with different values
        args2 = parse_cli_args(["--force-context-window", "100000"])
        config2 = _unwrap_config(apply_cli_args(args2))
        assert config2.context_window_override == 100000


def test_cli_context_window_override_defaults_to_none() -> None:
    """Test that context window override defaults to None when not specified."""
    with patch("src.core.config.app_config.load_config", return_value=AppConfig()):
        # Test parsing without the argument
        args = parse_cli_args([])
        assert args.force_context_window is None

        # Test application of args to config
        config = _unwrap_config(apply_cli_args(args))
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
            config = _unwrap_config(apply_cli_args(args))

            assert config.context_window_override == 7500
            assert os.environ.get("FORCE_CONTEXT_WINDOW") == "7500"

        finally:
            # Restore original environment variable
            if original_env is not None:
                os.environ["FORCE_CONTEXT_WINDOW"] = original_env
            elif "FORCE_CONTEXT_WINDOW" in os.environ:
                del os.environ["FORCE_CONTEXT_WINDOW"]


def test_cli_force_model_argument_parsing() -> None:
    """Test that the --force-model CLI argument forces static routing to the specified model."""

    with patch("src.core.config.app_config.load_config", return_value=AppConfig()):
        args = parse_cli_args(["--force-model", "gemini-2.5-pro"])
        assert args.force_model == "gemini-2.5-pro"

        config = _unwrap_config(apply_cli_args(args))
        assert config.backends.static_route == "gemini-2.5-pro"
        assert os.environ.get("STATIC_ROUTE") == "gemini-2.5-pro"


def test_cli_pytest_compression_flags() -> None:
    """Test that --enable-pytest-compression and --disable-pytest-compression flags work."""
    # Patch load_config where it is looked up (in the 'cli' module)
    with patch("src.core.cli.load_config") as mock_load_config:
        # Create base config
        base_config = AppConfig()
        mock_load_config.return_value = base_config

        args_enable = parse_cli_args(["--enable-pytest-compression"])
        config_enable = _unwrap_config(apply_cli_args(args_enable))
        assert config_enable.session.pytest_compression_enabled is True
        assert (
            config_enable.session.pytest_compression_min_lines
            == base_config.session.pytest_compression_min_lines
        )

        args_disable = parse_cli_args(["--disable-pytest-compression"])
        config_disable = _unwrap_config(apply_cli_args(args_disable))
        assert config_disable.session.pytest_compression_enabled is False

        args_none = parse_cli_args([])
        config_none = _unwrap_config(apply_cli_args(args_none))
        assert (
            config_none.session.pytest_compression_enabled
            == base_config.session.pytest_compression_enabled
        )

        custom_config = base_config.model_copy(
            update={
                "session": base_config.session.model_copy(
                    update={"pytest_compression_enabled": True}
                )
            }
        )
        mock_load_config.return_value = custom_config
        config_none_true = _unwrap_config(apply_cli_args(args_none))
        assert config_none_true.session.pytest_compression_enabled is True

        initial_config_override = base_config.model_copy(
            update={
                "session": base_config.session.model_copy(
                    update={"pytest_compression_enabled": False}
                )
            }
        )
        mock_load_config.return_value = initial_config_override
        config_override = _unwrap_config(apply_cli_args(args_enable))
        assert config_override.session.pytest_compression_enabled is True


def test_cli_pytest_full_suite_steering_flags() -> None:
    """Test CLI flags controlling pytest full-suite steering."""

    with patch("src.core.cli.load_config") as mock_load_config:
        # Enable flag should override configuration
        mock_load_config.return_value = AppConfig()
        args_enable = parse_cli_args(["--enable-pytest-full-suite-steering"])
        assert args_enable.pytest_full_suite_steering_enabled is True
        config_enable = _unwrap_config(apply_cli_args(args_enable))
        reactor_config = config_enable.session.tool_call_reactor
        assert reactor_config.pytest_full_suite_steering_enabled is True

        # Disable flag should override configuration
        mock_load_config.return_value = AppConfig()
        args_disable = parse_cli_args(["--disable-pytest-full-suite-steering"])
        assert args_disable.pytest_full_suite_steering_enabled is False
        config_disable = _unwrap_config(apply_cli_args(args_disable))
        reactor_config = config_disable.session.tool_call_reactor
        assert reactor_config.pytest_full_suite_steering_enabled is False

        # Default behaviour should preserve existing configuration state
        existing_config = AppConfig(
            session=AppConfig().session.model_copy(
                update={"pytest_full_suite_steering_enabled": True}
            )
        )
        mock_load_config.return_value = existing_config
        args_default = parse_cli_args([])
        assert args_default.pytest_full_suite_steering_enabled is None
        config_default = _unwrap_config(apply_cli_args(args_default))
        reactor_config = config_default.session.tool_call_reactor
        assert reactor_config.pytest_full_suite_steering_enabled is True


def test_maybe_run_as_daemon_posix_continues(monkeypatch: pytest.MonkeyPatch) -> None:
    """Ensure daemon mode continues execution on POSIX systems."""
    from src.core.config.app_config import LoggingConfig

    # Prepare CLI arguments and configuration
    args = argparse.Namespace(daemon=True)
    # Create config with logging settings
    logging_config = LoggingConfig(log_file="logs/proxy.log")
    cfg = AppConfig(logging=logging_config)

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

        config = _unwrap_config(apply_cli_args(args))
        assert config.logging.capture_max_bytes == 1024
        assert config.logging.capture_truncate_bytes == 256
        assert config.logging.capture_max_files == 3


@pytest.mark.parametrize(
    ("flag", "backend_name", "env_var"),
    [
        ("--openrouter-api-key", "openrouter", None),
        ("--gemini-api-key", "gemini", "GEMINI_API_KEY"),
        ("--zai-api-key", "zai", None),
    ],
)
def test_cli_api_keys_are_stored_as_lists(
    monkeypatch: pytest.MonkeyPatch,
    flag: str,
    backend_name: str,
    env_var: str | None,
) -> None:
    """CLI API key flags should normalize single keys into singleton lists."""

    if env_var:
        monkeypatch.delenv(env_var, raising=False)

    with patch("src.core.cli.load_config", return_value=AppConfig()):
        args = parse_cli_args([flag, "test-key"])
        config = _unwrap_config(apply_cli_args(args))

    backend_config = config.backends[backend_name]
    assert backend_config.api_key == ["test-key"]

    # The environment variable should not be set
    if env_var:
        assert os.environ.get(env_var) == "test-key"
