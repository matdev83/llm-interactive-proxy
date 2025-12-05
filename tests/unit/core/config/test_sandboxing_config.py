"""Tests for sandboxing configuration loading and precedence."""

from pathlib import Path
from typing import Any

import pytest
import yaml
from src.core.config.app_config import AppConfig, load_config
from src.core.config.parameter_resolution import ParameterResolution, ParameterSource
from src.core.domain.configuration.sandboxing_config import SandboxingConfiguration


class TestSandboxingConfigurationDefaults:
    """Test default values in SandboxingConfiguration."""

    def test_default_values(self) -> None:
        """Test that SandboxingConfiguration has correct default values."""
        config = SandboxingConfiguration()

        assert config.enabled is False
        assert config.strict_mode is False
        assert config.allow_parent_access is False
        assert config.custom_tool_patterns == []
        assert config.excluded_tools == []
        assert len(config.default_tool_patterns) > 0
        assert len(config.path_parameter_names) > 0

    def test_default_tool_patterns_include_common_tools(self) -> None:
        """Test that default tool patterns include common file-changing tools."""
        config = SandboxingConfiguration()

        expected_patterns = [
            "write_to_file",
            "write_file",
            "fsWrite",
            "replace_in_file",
            "str_replace",
            "strReplace",
            "edit_file",
            "delete_file",
            "create_file",
        ]

        for pattern in expected_patterns:
            assert pattern in config.default_tool_patterns

    def test_path_parameter_names_include_common_names(self) -> None:
        """Test that path parameter names include common variations."""
        config = SandboxingConfiguration()

        expected_names = [
            "path",
            "file_path",
            "filepath",
            "file",
            "target",
            "destination",
            "source",
            "paths",
            "files",
        ]

        for name in expected_names:
            assert name in config.path_parameter_names


class TestSandboxingConfigurationValidation:
    """Test validation in SandboxingConfiguration."""

    def test_invalid_custom_tool_pattern_raises_error(self) -> None:
        """Test that invalid regex patterns in custom_tool_patterns raise ValueError."""
        with pytest.raises(ValueError, match="Invalid regex patterns"):
            SandboxingConfiguration(custom_tool_patterns=["[invalid(regex"])

    def test_invalid_excluded_tool_pattern_raises_error(self) -> None:
        """Test that invalid regex patterns in excluded_tools raise ValueError."""
        with pytest.raises(ValueError, match="Invalid regex patterns"):
            SandboxingConfiguration(excluded_tools=["[invalid(regex"])

    def test_valid_custom_tool_patterns_accepted(self) -> None:
        """Test that valid regex patterns are accepted."""
        config = SandboxingConfiguration(
            custom_tool_patterns=["custom_write_.*", "my_file_editor"]
        )

        assert len(config.custom_tool_patterns) == 2

    def test_empty_path_parameter_names_raises_error(self) -> None:
        """Test that empty path_parameter_names raises ValueError."""
        with pytest.raises(ValueError, match="path_parameter_names cannot be empty"):
            SandboxingConfiguration(path_parameter_names=[])

    def test_validate_configuration_method(self) -> None:
        """Test the validate_configuration method."""
        config = SandboxingConfiguration(enabled=True)
        errors = config.validate_configuration()

        # Should have no errors for valid configuration
        assert len(errors) == 0

    def test_validate_configuration_detects_conflicting_settings(self) -> None:
        """Test that validate_configuration detects conflicting settings."""
        config = SandboxingConfiguration(enabled=False, strict_mode=True)
        errors = config.validate_configuration()

        # Should detect that strict_mode is enabled but sandboxing is disabled
        assert len(errors) > 0
        assert any("strict_mode" in error for error in errors)


class TestAppConfigSandboxingField:
    """Test that AppConfig properly includes sandboxing configuration."""

    def test_app_config_has_sandboxing_field(self) -> None:
        """Test that AppConfig has a sandboxing field."""
        config = AppConfig()

        assert hasattr(config, "sandboxing")
        assert isinstance(config.sandboxing, SandboxingConfiguration)

    def test_app_config_sandboxing_defaults(self) -> None:
        """Test that AppConfig sandboxing has correct defaults."""
        config = AppConfig()

        assert config.sandboxing.enabled is False
        assert config.sandboxing.strict_mode is False
        assert config.sandboxing.allow_parent_access is False


class TestSandboxingConfigFromEnvironment:
    """Test loading sandboxing configuration from environment variables."""

    def test_enable_sandboxing_from_env(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test that ENABLE_SANDBOXING environment variable is loaded."""
        monkeypatch.setenv("ENABLE_SANDBOXING", "true")
        monkeypatch.setenv("OPENAI_API_KEY", "test-key")

        config = AppConfig.from_env()

        assert config.sandboxing.enabled is True

    def test_sandboxing_strict_mode_from_env(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Test that SANDBOXING_STRICT_MODE environment variable is loaded."""
        monkeypatch.setenv("SANDBOXING_STRICT_MODE", "true")
        monkeypatch.setenv("OPENAI_API_KEY", "test-key")

        config = AppConfig.from_env()

        assert config.sandboxing.strict_mode is True

    def test_sandboxing_allow_parent_access_from_env(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Test that SANDBOXING_ALLOW_PARENT_ACCESS environment variable is loaded."""
        monkeypatch.setenv("SANDBOXING_ALLOW_PARENT_ACCESS", "true")
        monkeypatch.setenv("OPENAI_API_KEY", "test-key")

        config = AppConfig.from_env()

        assert config.sandboxing.allow_parent_access is True

    def test_all_sandboxing_env_vars_together(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Test loading all sandboxing environment variables together."""
        monkeypatch.setenv("ENABLE_SANDBOXING", "true")
        monkeypatch.setenv("SANDBOXING_STRICT_MODE", "true")
        monkeypatch.setenv("SANDBOXING_ALLOW_PARENT_ACCESS", "true")
        monkeypatch.setenv("OPENAI_API_KEY", "test-key")

        config = AppConfig.from_env()

        assert config.sandboxing.enabled is True
        assert config.sandboxing.strict_mode is True
        assert config.sandboxing.allow_parent_access is True

    def test_parameter_resolution_tracks_env_vars(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Test that parameter resolution tracks sandboxing environment variables."""
        monkeypatch.setenv("ENABLE_SANDBOXING", "true")
        monkeypatch.setenv("OPENAI_API_KEY", "test-key")

        resolution = ParameterResolution()
        AppConfig.from_env(resolution=resolution)

        # Check that the parameter was recorded
        env_params = resolution.latest_by_source(ParameterSource.ENVIRONMENT)
        assert "sandboxing.enabled" in env_params


class TestSandboxingConfigFromYAML:
    """Test loading sandboxing configuration from YAML files."""

    def test_load_sandboxing_from_yaml(self, tmp_path: Path) -> None:
        """Test loading sandboxing configuration from YAML file."""
        config_data = {
            "host": "localhost",
            "port": 9000,
            "backends": {},
            "sandboxing": {
                "enabled": True,
                "strict_mode": True,
                "allow_parent_access": False,
            },
        }

        config_path = tmp_path / "config.yaml"
        with config_path.open("w", encoding="utf-8") as f:
            yaml.safe_dump(config_data, f)

        config = load_config(config_path)

        assert config.sandboxing.enabled is True
        assert config.sandboxing.strict_mode is True
        assert config.sandboxing.allow_parent_access is False

    def test_load_sandboxing_with_custom_patterns_from_yaml(
        self, tmp_path: Path
    ) -> None:
        """Test loading sandboxing with custom tool patterns from YAML."""
        config_data = {
            "host": "localhost",
            "port": 9000,
            "backends": {},
            "sandboxing": {
                "enabled": True,
                "custom_tool_patterns": ["custom_write_.*", "my_file_editor"],
                "excluded_tools": ["read_file", "list_files"],
            },
        }

        config_path = tmp_path / "config.yaml"
        with config_path.open("w", encoding="utf-8") as f:
            yaml.safe_dump(config_data, f)

        config = load_config(config_path)

        assert config.sandboxing.enabled is True
        assert len(config.sandboxing.custom_tool_patterns) == 2
        assert "custom_write_.*" in config.sandboxing.custom_tool_patterns
        assert len(config.sandboxing.excluded_tools) == 2


class TestSandboxingConfigPrecedence:
    """Test configuration precedence: CLI > Environment > YAML."""

    def test_cli_overrides_env_and_yaml(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Test that CLI arguments override environment and YAML configuration."""
        # Set up YAML config
        config_data: dict[str, Any] = {
            "host": "localhost",
            "port": 9000,
            "backends": {},
            "sandboxing": {"enabled": False, "strict_mode": False},
        }

        config_path = tmp_path / "config.yaml"
        with config_path.open("w", encoding="utf-8") as f:
            yaml.safe_dump(config_data, f)

        # Set up environment variables
        monkeypatch.setenv("ENABLE_SANDBOXING", "false")
        monkeypatch.setenv("SANDBOXING_STRICT_MODE", "false")
        monkeypatch.setenv("OPENAI_API_KEY", "test-key")

        # Load config from file and env
        config = load_config(config_path)

        # Verify YAML/env values are loaded
        assert config.sandboxing.enabled is False
        assert config.sandboxing.strict_mode is False

        # Now simulate CLI override by creating a new config with CLI values
        # (In actual usage, this would be done by the CLI argument parser)
        cli_config_data = config.model_dump()
        cli_config_data["sandboxing"]["enabled"] = True
        cli_config_data["sandboxing"]["strict_mode"] = True

        cli_config = AppConfig.model_validate(cli_config_data)

        # Verify CLI values override
        assert cli_config.sandboxing.enabled is True
        assert cli_config.sandboxing.strict_mode is True

    def test_env_overrides_yaml(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Test that environment variables override YAML configuration."""
        import os

        # Set up YAML config with sandboxing disabled
        config_data: dict[str, Any] = {
            "host": "localhost",
            "port": 9000,
            "backends": {},
            "sandboxing": {"enabled": False, "strict_mode": False},
        }

        config_path = tmp_path / "config.yaml"
        with config_path.open("w", encoding="utf-8") as f:
            yaml.safe_dump(config_data, f)

        # Set up environment variables to enable sandboxing
        monkeypatch.setenv("ENABLE_SANDBOXING", "true")
        monkeypatch.setenv("SANDBOXING_STRICT_MODE", "true")
        monkeypatch.setenv("OPENAI_API_KEY", "test-key")

        # Load config - env should override YAML
        config = load_config(config_path, environ=os.environ)

        assert config.sandboxing.enabled is True
        assert config.sandboxing.strict_mode is True

    def test_yaml_provides_defaults_when_no_env(self, tmp_path: Path) -> None:
        """Test that YAML configuration is used when no environment variables are set."""
        config_data: dict[str, Any] = {
            "host": "localhost",
            "port": 9000,
            "backends": {},
            "sandboxing": {
                "enabled": True,
                "strict_mode": True,
                "allow_parent_access": True,
            },
        }

        config_path = tmp_path / "config.yaml"
        with config_path.open("w", encoding="utf-8") as f:
            yaml.safe_dump(config_data, f)

        # Load config without environment variables
        config = load_config(config_path, environ={})

        assert config.sandboxing.enabled is True
        assert config.sandboxing.strict_mode is True
        assert config.sandboxing.allow_parent_access is True


class TestSandboxingConfigSerialization:
    """Test serialization and deserialization of sandboxing configuration."""

    def test_model_dump_includes_sandboxing(self) -> None:
        """Test that model_dump includes sandboxing configuration."""
        config = AppConfig(
            sandboxing=SandboxingConfiguration(
                enabled=True, strict_mode=True, allow_parent_access=False
            )
        )

        dumped = config.model_dump()

        assert "sandboxing" in dumped
        assert dumped["sandboxing"]["enabled"] is True
        assert dumped["sandboxing"]["strict_mode"] is True
        assert dumped["sandboxing"]["allow_parent_access"] is False

    def test_save_and_load_preserves_sandboxing(self, tmp_path: Path) -> None:
        """Test that saving and loading config preserves sandboxing settings."""
        config = AppConfig(
            sandboxing=SandboxingConfiguration(
                enabled=True,
                strict_mode=True,
                allow_parent_access=False,
                custom_tool_patterns=["custom_.*"],
            )
        )

        config_path = tmp_path / "config.yaml"
        # Since we are creating a test config, we need to ensure minimal required fields are set
        # to pass schema validation during load
        if not config.backends.openai.api_key:
            object.__setattr__(config.backends.openai, "api_key", "test-key")

        config.save(config_path)

        # Load the saved config
        loaded_config = load_config(config_path)

        assert loaded_config.sandboxing.enabled is True
        assert loaded_config.sandboxing.strict_mode is True
        assert loaded_config.sandboxing.allow_parent_access is False
        assert "custom_.*" in loaded_config.sandboxing.custom_tool_patterns
