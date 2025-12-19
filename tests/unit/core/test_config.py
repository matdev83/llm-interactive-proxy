"""Tests for the configuration module."""

from pathlib import Path
from unittest.mock import Mock

import pytest
from src.core.config.app_config import (
    AppConfig,
    LogLevel,
    load_config,
)


def test_app_config_defaults() -> None:
    """Test default values in AppConfig."""
    # Arrange & Act
    config = AppConfig()

    # Assert
    assert config.host == "127.0.0.1"  # Default to localhost for security
    assert config.port == 8000
    assert config.proxy_timeout == 120
    assert config.command_prefix == "!/"
    assert config.backends.default_backend == "openai"
    assert config.auth.disable_auth is False
    assert config.session.cleanup_enabled is True
    assert config.logging.level == LogLevel.INFO


def test_app_config_validation() -> None:
    """Test validation in AppConfig."""
    # Arrange & Act & Assert
    with pytest.raises(ValueError):
        # Create config with invalid backend URL
        from src.core.config.app_config import BackendConfig, BackendSettings

        AppConfig(backends=BackendSettings(openai=BackendConfig(api_url="invalid-url")))


def test_app_config_from_env(mock_env_vars: dict[str, str]) -> None:
    """Test creation from environment variables."""
    # Arrange & Act
    config = AppConfig.from_env()

    # Assert
    assert config.host == mock_env_vars["APP_HOST"]
    assert config.port == int(mock_env_vars["APP_PORT"])

    # Check that the API keys are set (but don't check exact values as they might be modified
    # in test environments by BackendFactory.ensure_backend)
    assert config.backends.openai.api_key
    assert config.backends.openrouter.api_key
    assert config.auth.disable_auth is True


def test_command_service_respects_strict_command_env(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Command service should enable strict mode via environment flag."""
    from src.core.commands.parser import CommandParser
    from src.core.commands.service import NewCommandService

    monkeypatch.setenv("STRICT_COMMAND_DETECTION", "true")

    service = NewCommandService(
        session_service=Mock(),
        command_parser=CommandParser(),
        strict_command_detection=False,
        command_state_service=Mock(),
        command_policy_service=Mock(),
    )

    assert service.strict_command_detection is True

    monkeypatch.delenv("STRICT_COMMAND_DETECTION")


# def test_legacy_config_loader():
#     """Test the legacy config loader."""
#     # Act
#     config = _load_config()

#     # Assert
#     assert isinstance(config, dict)
#     assert "backend" in config
#     assert "proxy_port" in config


def test_load_config(temp_config_path: Path) -> None:
    """Test the load_config function."""
    # Arrange & Act
    config = load_config(temp_config_path)

    # Assert
    assert isinstance(config, AppConfig)
    assert config.host == "localhost"
    assert config.port == 9000
