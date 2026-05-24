"""Unit tests for ConfigurationApplicator.

**Feature: cli-god-object-refactoring, Task 5: ConfigurationApplicator (TDD)**

Requirements:
- 1.2: CLI module delegates to ConfigurationApplicator for applying arguments
- 1.3: ConfigurationApplicator records parameter sources via ParameterResolution
- 6.1: Coordinates domain-specific applicators
- 7.1: Backward compatibility with existing apply_cli_args behavior
- 8.3: No direct file I/O in ConfigurationApplicator (delegates to services)
- 9.1: Unit tests for ConfigurationApplicator
"""

from __future__ import annotations

import argparse
from typing import Any
from unittest.mock import MagicMock, patch

from src.core.cli_support.protocols import CliArgs, CliOverrides
from src.core.config.parameter_resolution import ParameterResolution, ParameterSource


class MockApplicator:
    """Mock domain applicator for testing."""

    def __init__(self, domain_key: str, value: Any) -> None:
        self.domain_key = domain_key
        self.value = value
        self.apply_called = False

    def apply(
        self,
        args: CliArgs,
        overrides: CliOverrides,
        resolution: ParameterResolution,
    ) -> None:
        """Apply mock configuration."""
        self.apply_called = True
        overrides[self.domain_key] = self.value
        resolution.record(
            self.domain_key, self.value, ParameterSource.CLI, origin="--mock"
        )


def create_mock_cfg() -> MagicMock:
    """Create a mock AppConfig for testing."""
    mock_cfg = MagicMock()
    mock_cfg.model_dump.return_value = {}
    mock_cfg.logging = MagicMock(log_file="./logs/test.log")
    mock_cfg.command_prefix = "/proxy"
    mock_cfg.model_copy.return_value = mock_cfg
    return mock_cfg


class TestConfigurationApplicatorBasic:
    """Basic unit tests for ConfigurationApplicator."""

    def test_import_configuration_applicator(self) -> None:
        """Test that ConfigurationApplicator can be imported."""
        from src.core.cli_support.configuration_applicator import (
            ConfigurationApplicator,
        )

        assert ConfigurationApplicator is not None

    def test_instantiate_with_default_applicators(self) -> None:
        """Test that ConfigurationApplicator can be instantiated with default applicators."""
        from src.core.cli_support.configuration_applicator import (
            ConfigurationApplicator,
        )

        applicator = ConfigurationApplicator()
        assert applicator is not None
        # Should have default applicators
        assert len(applicator._applicators) > 0

    def test_instantiate_with_custom_applicators(self) -> None:
        """Test that ConfigurationApplicator can be instantiated with custom applicators."""
        from src.core.cli_support.configuration_applicator import (
            ConfigurationApplicator,
        )

        mock_applicator = MockApplicator("test_key", "test_value")
        applicator = ConfigurationApplicator(domain_applicators=[mock_applicator])
        assert len(applicator._applicators) == 1
        assert applicator._applicators[0] is mock_applicator


class TestConfigurationApplicatorApply:
    """Tests for the apply method of ConfigurationApplicator."""

    def test_apply_delegates_to_domain_applicators(self) -> None:
        """Test that apply() delegates to all domain applicators."""
        from src.core.cli_support.configuration_applicator import (
            ConfigurationApplicator,
        )

        mock1 = MockApplicator("domain1", "value1")
        mock2 = MockApplicator("domain2", "value2")

        applicator = ConfigurationApplicator(domain_applicators=[mock1, mock2])

        args = argparse.Namespace(config_file=None, log_file=None)

        with patch("src.core.config.app_config.load_config") as mock_load_config:
            mock_cfg = create_mock_cfg()
            mock_load_config.return_value = mock_cfg

            with patch("src.core.config.app_config.AppConfig") as mock_app_config:
                mock_app_config.model_validate.return_value = mock_cfg

                applicator.apply(args)

        assert mock1.apply_called
        assert mock2.apply_called

    def test_apply_returns_app_config_by_default(self) -> None:
        """Test that apply() returns AppConfig by default."""
        from src.core.cli_support.configuration_applicator import (
            ConfigurationApplicator,
        )

        applicator = ConfigurationApplicator(domain_applicators=[])

        args = argparse.Namespace(config_file=None, log_file=None)

        with patch("src.core.config.app_config.load_config") as mock_load_config:
            mock_cfg = create_mock_cfg()
            mock_load_config.return_value = mock_cfg

            with patch("src.core.config.app_config.AppConfig") as mock_app_config:
                mock_app_config.model_validate.return_value = mock_cfg

                result = applicator.apply(args)

        # Should return just the config, not a tuple
        assert result is mock_cfg

    def test_apply_returns_tuple_when_return_resolution_true(self) -> None:
        """Test that apply() returns (AppConfig, ParameterResolution) when return_resolution=True."""
        from src.core.cli_support.configuration_applicator import (
            ConfigurationApplicator,
        )

        applicator = ConfigurationApplicator(domain_applicators=[])

        args = argparse.Namespace(config_file=None, log_file=None)

        with patch("src.core.config.app_config.load_config") as mock_load_config:
            mock_cfg = create_mock_cfg()
            mock_load_config.return_value = mock_cfg

            with patch("src.core.config.app_config.AppConfig") as mock_app_config:
                mock_app_config.model_validate.return_value = mock_cfg

                result = applicator.apply(args, return_resolution=True)

        assert isinstance(result, tuple)
        assert len(result) == 2
        assert isinstance(result[1], ParameterResolution)

    def test_apply_uses_provided_resolution(self) -> None:
        """Test that apply() uses a provided ParameterResolution."""
        from src.core.cli_support.configuration_applicator import (
            ConfigurationApplicator,
        )

        mock_applicator = MockApplicator("test_key", "test_value")
        applicator = ConfigurationApplicator(domain_applicators=[mock_applicator])

        args = argparse.Namespace(config_file=None, log_file=None)
        resolution = ParameterResolution()
        resolution.record("pre_existing", "value", ParameterSource.CONFIG_FILE)

        with patch("src.core.config.app_config.load_config") as mock_load_config:
            mock_cfg = create_mock_cfg()
            mock_load_config.return_value = mock_cfg

            with patch("src.core.config.app_config.AppConfig") as mock_app_config:
                mock_app_config.model_validate.return_value = mock_cfg

                result_cfg, result_res = applicator.apply(
                    args, return_resolution=True, resolution=resolution
                )

        # Should have both the pre-existing record and the new one from mock applicator
        assert result_res.is_set("pre_existing")
        assert result_res.is_set("test_key")


class TestConfigurationApplicatorParameterRecording:
    """Tests for ParameterResolution recording by ConfigurationApplicator."""

    def test_records_cli_parameters(self) -> None:
        """Test that CLI parameters are recorded in ParameterResolution."""
        from src.core.cli_support.configuration_applicator import (
            ConfigurationApplicator,
        )

        mock_applicator = MockApplicator("host", "127.0.0.1")
        applicator = ConfigurationApplicator(domain_applicators=[mock_applicator])

        args = argparse.Namespace(config_file=None, log_file=None)

        with patch("src.core.config.app_config.load_config") as mock_load_config:
            mock_cfg = create_mock_cfg()
            mock_load_config.return_value = mock_cfg

            with patch("src.core.config.app_config.AppConfig") as mock_app_config:
                mock_app_config.model_validate.return_value = mock_cfg

                _, resolution = applicator.apply(args, return_resolution=True)

        assert resolution.is_set("host")
        cli_entries = resolution.latest_by_source(ParameterSource.CLI)
        assert "host" in cli_entries

    def test_maintains_parameter_source_chain(self) -> None:
        """Test that parameter sources are properly chained through history."""
        from src.core.cli_support.configuration_applicator import (
            ConfigurationApplicator,
        )

        applicator = ConfigurationApplicator(domain_applicators=[])
        resolution = ParameterResolution()

        # Pre-load with config source
        resolution.record(
            "backends.default_backend", "openai", ParameterSource.CONFIG_FILE
        )

        args = argparse.Namespace(
            config_file=None, default_backend="anthropic", log_file=None
        )

        with patch("src.core.config.app_config.load_config") as mock_load_config:
            mock_cfg = create_mock_cfg()
            mock_load_config.return_value = mock_cfg

            with patch("src.core.config.app_config.AppConfig") as mock_app_config:
                mock_app_config.model_validate.return_value = mock_cfg

                _, result_resolution = applicator.apply(
                    args, return_resolution=True, resolution=resolution
                )

        # The pre-existing CONFIG_FILE source should still be recorded
        assert result_resolution.is_set("backends.default_backend")


class TestConfigurationApplicatorDefaultLogFile:
    """Tests for default log file handling."""

    def test_sets_default_log_file_when_not_specified(self) -> None:
        """Test that default log file is set when neither CLI nor config specifies one."""
        from src.core.cli_support.configuration_applicator import (
            ConfigurationApplicator,
        )

        applicator = ConfigurationApplicator(domain_applicators=[])

        args = argparse.Namespace(config_file=None, log_file=None)

        with patch("src.core.config.app_config.load_config") as mock_load_config:
            mock_cfg = MagicMock()
            mock_cfg.model_dump.return_value = {}
            mock_cfg.logging = MagicMock(log_file=None)  # No log file in config
            mock_cfg.command_prefix = "/proxy"
            mock_cfg.model_copy.return_value = mock_cfg
            mock_load_config.return_value = mock_cfg

            with patch("src.core.config.app_config.AppConfig") as mock_app_config:
                captured_data: list[dict[str, Any]] = []

                def capture_validate_call(data: dict[str, Any]) -> MagicMock:
                    # Store the data for inspection
                    captured_data.append(data.copy())
                    mock_result = MagicMock()
                    mock_result._validated_data = data
                    mock_result.command_prefix = "/proxy"
                    mock_result.model_copy.return_value = mock_result
                    return mock_result

                mock_app_config.model_validate.side_effect = capture_validate_call

                applicator.apply(args)

        # The model_validate should have been called with logging containing log_file
        assert len(captured_data) == 1
        assert "logging" in captured_data[0]
        assert "log_file" in captured_data[0]["logging"]


class TestConfigurationApplicatorCommandPrefixValidation:
    """Tests for command prefix validation and defaults."""

    def test_applies_default_command_prefix_when_none(self) -> None:
        """Test that command prefix is never left as None."""
        from src.core.cli_support.configuration_applicator import (
            ConfigurationApplicator,
        )

        applicator = ConfigurationApplicator(domain_applicators=[])

        args = argparse.Namespace(config_file=None, command_prefix=None, log_file=None)

        with patch("src.core.config.app_config.load_config") as mock_load_config:
            mock_cfg = MagicMock()
            # Simulate base config having None command_prefix
            mock_cfg.model_dump.return_value = {"command_prefix": None}
            mock_cfg.logging = MagicMock(log_file="./logs/test.log")
            mock_cfg.command_prefix = None
            mock_load_config.return_value = mock_cfg

            with patch("src.core.config.app_config.AppConfig") as mock_app_config:
                # Create a mock that has command_prefix = "!/" (the default) after merge
                # because merge logic sets it if None
                validated_cfg = MagicMock()
                validated_cfg.command_prefix = "!/"

                mock_app_config.model_validate.return_value = validated_cfg

                result = applicator.apply(args)

        # Result should have the default prefix
        assert result.command_prefix == "!/"


class TestConfigurationApplicatorDefaultApplicators:
    """Tests for default applicator list."""

    def test_includes_all_domain_applicators(self) -> None:
        """Test that default applicators include all domain applicators."""
        from src.core.cli_support.configuration_applicator import (
            ConfigurationApplicator,
        )

        applicator = ConfigurationApplicator()

        # Get the applicator class names
        applicator_names = [type(a).__name__ for a in applicator._applicators]

        # Should include all key domain applicators
        expected_applicators = [
            "ServerApplicator",
            "LoggingApplicator",
            "AccessModeApplicator",
            "NotificationApplicator",
            "BackendApplicator",
            "SessionApplicator",
            "AuthApplicator",
            "MemoryApplicator",
            "FailureHandlingApplicator",
            "ReplacementApplicator",
            "ResilienceApplicator",
            "EditPrecisionApplicator",
            "IdentityApplicator",
            "RoutingApplicator",
            "CompactionApplicator",
            "SandboxingApplicator",
        ]

        for expected in expected_applicators:
            assert expected in applicator_names, f"Missing applicator: {expected}"


class TestConfigurationApplicatorMergeLogic:
    """Tests for configuration merge logic."""

    def test_cli_overrides_merge_onto_config(self) -> None:
        """Test that CLI overrides are merged onto base config correctly."""
        from src.core.cli_support.configuration_applicator import (
            ConfigurationApplicator,
        )

        mock_applicator = MockApplicator("host", "192.168.1.1")
        applicator = ConfigurationApplicator(domain_applicators=[mock_applicator])

        args = argparse.Namespace(config_file=None, log_file=None)

        with patch("src.core.config.app_config.load_config") as mock_load_config:
            mock_cfg = MagicMock()
            # Base config has host = 127.0.0.1
            mock_cfg.model_dump.return_value = {"host": "127.0.0.1"}
            mock_cfg.logging = MagicMock(log_file="./logs/test.log")
            mock_cfg.command_prefix = "/proxy"
            mock_load_config.return_value = mock_cfg

            with patch("src.core.config.app_config.AppConfig") as mock_app_config:
                captured_data: list[dict[str, Any]] = []

                def capture_validate(data: dict[str, Any]) -> MagicMock:
                    captured_data.append(data.copy())
                    result_cfg = MagicMock()
                    result_cfg.command_prefix = "/proxy"
                    result_cfg.model_copy.return_value = result_cfg
                    return result_cfg

                mock_app_config.model_validate.side_effect = capture_validate

                applicator.apply(args)

        # CLI override should have overwritten the base config
        assert len(captured_data) == 1
        assert captured_data[0]["host"] == "192.168.1.1"


class TestConfigurationApplicatorIntegration:
    """Integration-like tests using real applicators."""

    def test_real_host_port_override(self) -> None:
        """Test that real host/port CLI args are applied correctly."""
        from src.core.cli_support.applicators.server_applicator import ServerApplicator
        from src.core.cli_support.configuration_applicator import (
            ConfigurationApplicator,
        )

        applicator = ConfigurationApplicator(domain_applicators=[ServerApplicator()])

        args = argparse.Namespace(
            config_file=None,
            log_file=None,
            host="0.0.0.0",
            port=9000,
            anthropic_port=None,
            timeout=None,
            command_prefix=None,
            force_context_window=None,
            enable_activity_tracking=None,
            request_dedup_window=None,
            disable_request_dedup=None,
            thinking_budget=None,
        )

        with patch("src.core.config.app_config.load_config") as mock_load_config:
            mock_cfg = MagicMock()
            mock_cfg.model_dump.return_value = {"host": "127.0.0.1", "port": 8080}
            mock_cfg.logging = MagicMock(log_file="./logs/test.log")
            mock_cfg.command_prefix = "/proxy"
            mock_load_config.return_value = mock_cfg

            with patch("src.core.config.app_config.AppConfig") as mock_app_config:
                captured_data: list[dict[str, Any]] = []

                def capture_validate(data: dict[str, Any]) -> MagicMock:
                    captured_data.append(data.copy())
                    result_cfg = MagicMock()
                    result_cfg.command_prefix = "/proxy"
                    result_cfg.model_copy.return_value = result_cfg
                    return result_cfg

                mock_app_config.model_validate.side_effect = capture_validate

                _, resolution = applicator.apply(args, return_resolution=True)

        assert len(captured_data) == 1
        assert captured_data[0]["host"] == "0.0.0.0"
        assert captured_data[0]["port"] == 9000
        assert resolution.is_set("host")
        assert resolution.is_set("port")
