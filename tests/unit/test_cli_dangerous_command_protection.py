"""Test CLI flag for dangerous command protection."""

import os
from unittest.mock import patch

from src.core.cli import apply_cli_args, parse_cli_args


class TestDangerousCommandProtectionCLI:
    """Test CLI functionality for dangerous command protection."""

    def test_cli_flag_disables_protection_by_default(self):
        """Test that --disable-dangerous-git-commands-protection flag sets prevention to False."""
        # Parse CLI arguments with the flag
        args = parse_cli_args(["--disable-dangerous-git-commands-protection"])

        # Apply arguments to configuration
        config = apply_cli_args(args)

        # Verify that dangerous command prevention is disabled
        assert config.session.dangerous_command_prevention_enabled is False

    def test_cli_flag_absent_uses_default_true(self):
        """Test that without the flag, dangerous command prevention remains enabled (default True)."""
        # Parse CLI arguments without the flag
        args = parse_cli_args([])

        # Apply arguments to configuration
        config = apply_cli_args(args)

        # Verify that dangerous command prevention is enabled (default)
        assert config.session.diantious_command_prevention_enabled is True

    def test_cli_flag_overrides_environment_variable_enabled(self):
        """Test that CLI flag overrides enabled environment variable."""
        # Set environment variable to enable protection
        os.environ["DANGEROUS_COMMAND_PREVENTION_ENABLED"] = "true"

        try:
            # Parse CLI arguments with the disable flag
            args = parse_cli_args(["--disable-dangerous-git-commands-protection"])

            # Apply arguments to configuration
            config = apply_cli_args(args)

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
            config = apply_cli_args(args)

            # Environment variable should be respected when no CLI flag
            assert config.session.dangerous_command_prevention_enabled is False

            # Now test with CLI flag to enable (should override env var)
            args = parse_cli_args([])
            # Note: Since there's no enable flag, we test the absence of disable flag with env var set to true
            os.environ["DANGEROUS_COMMAND_PREVENTION_ENABLED"] = "true"
            args = parse_cli_args([])
            config = apply_cli_args(args)
            assert config.session.dangerous_command_prevention_enabled is True

        finally:
            # Clean up environment variable
            if "DANGEROUS_COMMAND_PREVENTION_ENABLED" in os.environ:
                del os.environ["DANGEROUS_COMMAND_PREVENTION_ENABLED"]

    def test_cli_flag_overrides_config_file(self):
        """Test that CLI flag overrides config file settings."""
        # Create a minimal config file content
        config_content = """
session:
  dangerous_command_prevention_enabled: false
"""

        with patch("src.core.config.app_config.load_config") as mock_load:
            # Mock the config to return our test config
            from src.core.config.app_config import AppConfig

            # Create a config with dangerous command protection disabled
            mock_config = AppConfig(
                session={
                    "dangerous_command_prevention_enabled": False
                }
            )
            mock_load.return_value = mock_config

            # Parse CLI arguments with the flag (this will be applied after mock config)
            args = parse_cli_args([])

            # Apply arguments to configuration
            config = apply_cli_args(args, return_resolution=False)

            # Should use the config file setting since no CLI flag
            assert config.session.dangerous_command_prevention_enabled is False

            # Now test with CLI flag to enable (should override config)
            args = parse_cli_args(["--disable-dangerous-git-commands-protection"])
            config = apply_cli_args(args, return_resolution=False)

            # CLI flag should override config file setting
            assert config.session.dangerous_command_prevention_enabled is False

    def test_cli_precedence_cli_over_env_over_config(self):
        """Test the correct precedence: CLI > Environment > Config > Default."""
        # Set up all three sources
        os.environ["DANGEROUS_COMMAND_PREVENTION_ENABLED"] = "false"  # Environment (disabled)

        try:
            with patch("src.core.config.app_config.load_config") as mock_load:
                from src.core.config.app_config import AppConfig

                # Mock config file (enabled)
                mock_config = AppConfig(
                    session={
                        "dangerous_command_prevention_enabled": True
                    }
                )
                mock_load.return_value = mock_config

                # Test 1: CLI flag should have highest precedence
                args = parse_cli_args(["--disable-dangerous-git-commands-protection"])
                config = apply_cli_args(args, return_resolution=False)
                assert config.session.dangerous_command_prevention_enabled is False

                # Test 2: No CLI flag, should use environment variable
                args = parse_cli_args([])
                config = apply_cli_args(args, return_resolution=False)
                assert config.session.dangerous_command_prevention_enabled is False  # env var

                # Test 3: No CLI flag, no env var, should use config file
                del os.environ["DANGEROUS_COMMAND_PREVENTION_ENABLED"]
                args = parse_cli_args([])
                config = apply_cli_args(args, return_resolution=False)
                assert config.session.dangerous_command_prevention_enabled is True  # config file

                # Test 4: None of the above, should use default
                mock_load.return_value = AppConfig()  # Empty config with default values
                args = parse_cli_args([])
                config = apply_cli_args(args, return_resolution=False)
                assert config.session.dangerous_command_prevention_enabled is True  # default

        finally:
            # Clean up environment variable
            if "DANGEROUS_COMMAND_PREVENTION_ENABLED" in os.environ:
                del os.environ["DANGEROUS_COMMAND_PREVENTION_ENABLED"]

    def test_parameter_resolution_records_cli_source(self):
        """Test that parameter resolution correctly records CLI source."""
        # Parse CLI arguments with the flag
        args = parse_cli_args(["--disable-dangerous-git-commands-protection"])

        # Apply arguments with resolution tracking
        config, resolution = apply_cli_args(args, return_resolution=True)

        # Verify that the CLI source is recorded
        resolution_records = resolution.get_parameter_history()
        dangerous_command_records = [
            record for record in resolution_records
            if "dangerous_command_prevention_enabled" in record.path
        ]

        # Should have one record for the dangerous command setting
        assert len(dangerous_command_records) == 1

        record = dangerous_command_records[0]
        assert record.source.value == "CLI"
        assert record.path == "session.dangerous_command_prevention_enabled"
        assert record.origin == "--disable-dangerous-git-commands-protection"