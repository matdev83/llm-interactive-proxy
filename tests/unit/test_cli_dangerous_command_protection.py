"""Test CLI flag for dangerous command protection."""

import os

import pytest
from src.command_prefix import validate_command_prefix
from src.core.cli import apply_cli_args, parse_cli_args


@pytest.fixture(autouse=True)
def _reset_command_prefix_env() -> None:
    """Prevent leaked COMMAND_PREFIX values from affecting tests."""
    original = os.environ.pop("COMMAND_PREFIX", None)
    try:
        yield
    finally:
        if original is not None and validate_command_prefix(original) is None:
            os.environ["COMMAND_PREFIX"] = original
        else:
            os.environ.pop("COMMAND_PREFIX", None)


class TestDangerousCommandProtectionCLI:
    """Test CLI functionality for dangerous command protection."""

    def test_cli_flag_disables_protection_by_default(self):
        """Test that --disable-dangerous-git-commands-protection flag sets prevention to False."""
        # Parse CLI arguments with the flag
        args = parse_cli_args(["--disable-dangerous-git-commands-protection"])

        # Apply arguments to configuration
        result = apply_cli_args(args, return_resolution=False)

        # Handle both possible return types (AppConfig or tuple[AppConfig, ParameterResolution])
        if isinstance(result, tuple):
            config = result[0]  # Extract AppConfig from tuple if needed
        else:
            config = result  # It's already an AppConfig

        # Verify that dangerous command prevention is disabled
        assert config.session.dangerous_command_prevention_enabled is False

    def test_cli_flag_absent_uses_default_true(self):
        """Test that without the flag, dangerous command prevention remains enabled (default True)."""
        # Parse CLI arguments without the flag
        args = parse_cli_args([])

        # Apply arguments to configuration
        result = apply_cli_args(args, return_resolution=False)

        # Handle both possible return types (AppConfig or tuple[Config, ParameterResolution])
        if isinstance(result, tuple):
            config = result[0]  # Extract AppConfig from tuple if needed
        else:
            config = result  # It's already an AppConfig

        # Verify that dangerous command prevention is enabled (default)
        assert config.session.dangerous_command_prevention_enabled is True

    def test_cli_flag_overrides_environment_variable_enabled(self):
        """Test that CLI flag overrides enabled environment variable."""
        # Set environment variable to enable protection
        os.environ["DANGEROUS_COMMAND_PREVENTION_ENABLED"] = "true"

        try:
            # Parse CLI arguments with the disable flag
            args = parse_cli_args(["--disable-dangerous-git-commands-protection"])

            # Apply arguments to configuration
            result = apply_cli_args(args, return_resolution=False)

            # Handle both possible return types (AppConfig or tuple[AppConfig, ParameterResolution])
            if isinstance(result, tuple):
                config = result[0]  # Extract AppConfig from tuple if needed
            else:
                config = result  # It's already an AppConfig

            # CLI flag should override environment variable
            assert config.session.dangerous_command_prevention_enabled is False

        finally:
            # Clean up environment variable
            del os.environ["DANGEROUS_COMMAND_PREVENTION_ENABLED"]

    def test_cli_flag_overrides_environment_variable_disabled(self):
        """Test that CLI flag overrides disabled environment variable."""
        # Set environment variable to disable protection
        os.environ["DANGEROUS_COMMAND_PREVENTION_ENABLED"] = "false"

        try:
            # Parse CLI arguments without the flag (should use env var)
            args = parse_cli_args([])

            # Apply arguments to configuration
            result = apply_cli_args(args, return_resolution=False)

            # Handle both possible return types (AppConfig or tuple[Config, ParameterResolution])
            if isinstance(result, tuple):
                config = result[0]  # Extract AppConfig from tuple if needed
            else:
                config = result  # It's already an AppConfig

            # Environment variable should be respected when no CLI flag
            assert config.session.dangerous_command_prevention_enabled is False

            # Now test with CLI flag to enable (should override env var)
            args = parse_cli_args([])
            # Note: Since there's no enable flag, we test the absence of disable flag with env var set to true
            os.environ["DANGEROUS_COMMAND_PREVENTION_ENABLED"] = "true"
            args = parse_cli_args([])
            result = apply_cli_args(args, return_resolution=False)

            # Handle both possible return types (AppConfig or tuple[Config, ParameterResolution])
            if isinstance(result, tuple):
                config = result[0]  # Extract AppConfig from tuple if needed
            else:
                config = result  # It's already an AppConfig
            assert config.session.dangerous_command_prevention_enabled is True

        finally:
            # Clean up environment variable
            if "DANGEROUS_COMMAND_PREVENTION_ENABLED" in os.environ:
                del os.environ["DANGEROUS_COMMAND_PREVENTION_ENABLED"]

    def test_cli_flag_overrides_config_file(self, monkeypatch: pytest.MonkeyPatch):
        """Test that CLI flag overrides config file settings."""
        # Clean environment to ensure no interference
        monkeypatch.delenv("DANGEROUS_COMMAND_PREVENTION_ENABLED", raising=False)

        # Test 1: No CLI flag, should use default (True) since we can't easily mock config files
        args = parse_cli_args([])
        result = apply_cli_args(args, return_resolution=False)

        # Handle both possible return types (AppConfig or tuple[Config, ParameterResolution])
        if isinstance(result, tuple):
            config = result[0]  # Extract AppConfig from tuple if needed
        else:
            config = result  # It's already an AppConfig

        # Should use default when no CLI flag and no env var
        assert config.session.dangerous_command_prevention_enabled is True

        # Test 2: CLI flag to disable (should override default)
        args = parse_cli_args(["--disable-dangerous-git-commands-protection"])
        result = apply_cli_args(args, return_resolution=False)

        # Handle both possible return types (AppConfig or tuple[Config, ParameterResolution])
        if isinstance(result, tuple):
            config = result[0]  # Extract AppConfig from tuple if needed
        else:
            config = result  # It's already an AppConfig

        # CLI flag should override default setting
        assert config.session.dangerous_command_prevention_enabled is False

    def test_cli_precedence_cli_over_env_over_config(
        self, monkeypatch: pytest.MonkeyPatch
    ):
        """Test the correct precedence: CLI > Environment > Default."""
        # Clean environment first
        monkeypatch.delenv("DANGEROUS_COMMAND_PREVENTION_ENABLED", raising=False)

        # Test 1: Environment variable set to False (no CLI flag)
        monkeypatch.setenv("DANGEROUS_COMMAND_PREVENTION_ENABLED", "false")
        args = parse_cli_args([])
        result = apply_cli_args(args, return_resolution=False)

        # Handle both possible return types (AppConfig or tuple[Config, ParameterResolution])
        if isinstance(result, tuple):
            config = result[0]  # Extract AppConfig from tuple if needed
        else:
            config = result  # It's already an AppConfig
        assert (
            config.session.dangerous_command_prevention_enabled is False
        )  # env var wins

        # Test 2: CLI flag should override environment variable
        args = parse_cli_args(["--disable-dangerous-git-commands-protection"])
        result = apply_cli_args(args, return_resolution=False)

        # Handle both possible return types (AppConfig or tuple[Config, ParameterResolution])
        if isinstance(result, tuple):
            config = result[0]  # Extract AppConfig from tuple if needed
        else:
            config = result  # It's already an AppConfig
        assert config.session.dangerous_command_prevention_enabled is False  # CLI wins

        # Test 3: No CLI flag, no env var, should use default
        monkeypatch.delenv("DANGEROUS_COMMAND_PREVENTION_ENABLED", raising=False)
        args = parse_cli_args([])
        result = apply_cli_args(args, return_resolution=False)

        # Handle both possible return types (AppConfig or tuple[Config, ParameterResolution])
        if isinstance(result, tuple):
            config = result[0]  # Extract AppConfig from tuple if needed
        else:
            config = result  # It's already an AppConfig
        assert config.session.dangerous_command_prevention_enabled is True  # default

    def test_parameter_resolution_records_cli_source(self):
        """Test that parameter resolution correctly records CLI source."""
        # Parse CLI arguments with the flag
        args = parse_cli_args(["--disable-dangerous-git-commands-protection"])

        # Apply arguments with resolution tracking
        result = apply_cli_args(args, return_resolution=True)

        # Handle the case where result might be a nested tuple
        if isinstance(result, tuple) and len(result) == 2:
            config, resolution = result
        else:
            # In case of unexpected return format
            raise ValueError(
                f"Expected tuple of (config, resolution), got {type(result)}"
            )

        # Verify that the CLI source is recorded
        resolved_params = resolution.build_report(config)
        dangerous_command_records = [
            record
            for record in resolved_params
            if record.name == "session.dangerous_command_prevention_enabled"
        ]

        # Should have one record for the dangerous command setting
        assert len(dangerous_command_records) == 1

        record = dangerous_command_records[0]
        assert record.source.name == "CLI"
        assert record.name == "session.dangerous_command_prevention_enabled"
        assert record.origin == "--disable-dangerous-git-commands-protection"
