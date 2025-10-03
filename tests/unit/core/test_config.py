"""
Tests for the configuration module.
"""

from pathlib import Path

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
    assert config.host == "0.0.0.0"
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
        AppConfig(backends={"openai": {"api_url": "invalid-url"}})


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
    assert len(config.backends.openrouter.api_key) > 0
    assert config.auth.disable_auth is True


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


def test_load_config_debug(temp_config_path: Path) -> None:
    """Test the load_config function."""
    # Arrange & Act
    import os

    from src.core.config.app_config import AppConfig, _merge_dicts

    print(f"APP_HOST env var: {os.environ.get('APP_HOST')}")

    config_from_env = AppConfig.from_env()
    env_dict = config_from_env.model_dump()
    print(f"Config from env: {env_dict}")

    import yaml

    with open(temp_config_path) as f:
        file_config = yaml.safe_load(f)
    print(f"File config: {file_config}")

    merged_config_dict = _merge_dicts(env_dict, file_config)
    print(f"Merged config: {merged_config_dict}")

    config = AppConfig.model_validate(merged_config_dict)
    print(f"Final config host: {config.host}")

    # Assert
    assert isinstance(config, AppConfig)
    assert config.host == "localhost"
    assert config.port == 9000
