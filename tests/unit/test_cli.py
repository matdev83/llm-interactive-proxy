from unittest.mock import patch

import pytest
from src.core.cli import apply_cli_args, parse_cli_args
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
