"""
Tests for the configuration module.
"""

from pathlib import Path

import pytest
from src.core.config_adapter import AppConfig, _load_config, load_config


def test_app_config_defaults():
    """Test default values in AppConfig."""
    # Arrange & Act
    config = AppConfig()
    
    # Assert
    assert config.host == "0.0.0.0"
    assert config.port == 8000
    assert config.proxy_timeout == 120
    assert config.command_prefix == "!/"
    assert config.backends.default_backend == "openai"
    assert config.auth.disable_auth is False
    assert config.session.cleanup_enabled is True
    assert config.logging.level == AppConfig.LogLevel.INFO


def test_app_config_validation():
    """Test validation in AppConfig."""
    # Arrange & Act & Assert
    with pytest.raises(ValueError):
        # Invalid backend URL
        AppConfig(
            backends=AppConfig.BackendSettings(
                openai=AppConfig.BackendConfig(
                    api_url="invalid-url"  # Missing http:// or https://
                )
            )
        )


def test_app_config_to_legacy_config():
    """Test conversion to legacy config format."""
    # Arrange
    config = AppConfig(
        host="localhost",
        port=9000,
        backends=AppConfig.BackendSettings(
            default_backend="openai",
            openai=AppConfig.BackendConfig(
                api_key="test_key",
                api_url="https://api.example.com",
                timeout=30,
                extra={"foo": "bar"},
            ),
        ),
    )
    
    # Act
    legacy_config = config.to_legacy_config()
    
    # Assert
    assert legacy_config["host"] == "localhost"
    assert legacy_config["port"] == 9000
    assert legacy_config["default_backend"] == "openai"
    assert legacy_config["openai_api_key"] == "test_key"
    assert legacy_config["openai_api_url"] == "https://api.example.com"
    assert legacy_config["openai_timeout"] == 30
    assert legacy_config["openai_foo"] == "bar"


def test_app_config_from_legacy_config():
    """Test creation from legacy config format."""
    # Arrange
    legacy_config = {
        "host": "localhost",
        "port": 9000,
        "default_backend": "openai",
        "openai_api_key": "test_key",
        "openai_api_url": "https://api.example.com",
        "openai_timeout": 30,
        "openai_foo": "bar",
    }
    
    # Act
    config = AppConfig.from_legacy_config(legacy_config)
    
    # Assert
    assert config.host == "localhost"
    assert config.port == 9000
    assert config.backends.default_backend == "openai"
    assert config.backends.openai.api_key == "test_key"
    assert config.backends.openai.api_url == "https://api.example.com"
    assert config.backends.openai.timeout == 30
    assert config.backends.openai.extra == {"foo": "bar"}


def test_app_config_from_env(mock_env_vars: dict[str, str]):
    """Test creation from environment variables."""
    # Arrange & Act
    config = AppConfig.from_env()
    
    # Assert
    assert config.host == mock_env_vars["APP_HOST"]
    assert config.port == int(mock_env_vars["APP_PORT"])
    assert config.backends.openai.api_key == mock_env_vars["OPENAI_API_KEY"]
    assert config.backends.openrouter.api_key == mock_env_vars["OPENROUTER_API_KEY"]
    assert config.auth.disable_auth is True


def test_legacy_config_loader():
    """Test the legacy config loader."""
    # Act
    config = _load_config()
    
    # Assert
    assert isinstance(config, dict)
    assert "backend" in config
    assert "proxy_port" in config


def test_load_config(temp_config_path: Path):
    """Test the load_config function."""
    # Arrange & Act
    config = load_config(temp_config_path)
    
    # Assert
    assert isinstance(config, AppConfig)
    assert config.host == "localhost"
    assert config.port == 9000
