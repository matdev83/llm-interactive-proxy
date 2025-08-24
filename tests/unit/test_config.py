import os
from unittest.mock import patch

import pytest
from src.core.config.config_loader import ConfigLoader, _collect_api_keys


def test_collect_api_keys_single() -> None:
    """Test collecting a single API key."""
    with patch.dict(os.environ, {"TEST_API_KEY": "test-key"}, clear=True):
        keys = _collect_api_keys("TEST_API_KEY")
        assert keys == {"TEST_API_KEY": "test-key"}


def test_collect_api_keys_numbered() -> None:
    """Test collecting numbered API keys."""
    with patch.dict(
        os.environ, {"TEST_API_KEY_1": "key1", "TEST_API_KEY_2": "key2"}, clear=True
    ):
        keys = _collect_api_keys("TEST_API_KEY")
        assert keys == {"TEST_API_KEY_1": "key1", "TEST_API_KEY_2": "key2"}


def test_collect_api_keys_prioritizes_numbered() -> None:
    """Test that numbered keys take priority over single key."""
    with (
        patch.dict(
            os.environ,
            {"TEST_API_KEY": "single-key", "TEST_API_KEY_1": "key1"},
            clear=True,
        ),
        patch("src.core.config.config_loader.logger") as mock_logger,
    ):
        keys = _collect_api_keys("TEST_API_KEY")
        assert keys == {"TEST_API_KEY_1": "key1"}
        mock_logger.warning.assert_called_once()


@pytest.mark.asyncio
async def test_load_config_basic() -> None:
    """Test basic configuration loading."""
    with patch.dict(os.environ, {}, clear=True):
        loader = ConfigLoader()
        config = loader.load_config()
        assert config["proxy_host"] == "127.0.0.1"
        assert config["proxy_port"] == 8000
        assert config["disable_auth"] is False


@pytest.mark.asyncio
async def test_load_config_custom_values() -> None:
    """Test configuration loading with custom values."""
    with patch.dict(
        os.environ,
        {"PROXY_HOST": "0.0.0.0", "PROXY_PORT": "9000", "DISABLE_AUTH": "false"},
        clear=True,
    ):
        loader = ConfigLoader()
        config = loader.load_config()
        assert config["proxy_host"] == "0.0.0.0"
        assert config["proxy_port"] == 9000
        assert config["disable_auth"] is False


def test_load_config_disable_auth_forces_localhost() -> None:
    """Test that disable_auth forces host to localhost."""
    with (
        patch.dict(
            os.environ, {"DISABLE_AUTH": "true", "PROXY_HOST": "0.0.0.0"}, clear=True
        ),
        patch("src.core.config.config_loader.logger") as mock_logger,
    ):
        loader = ConfigLoader()
        config = loader.load_config()
        assert config["proxy_host"] == "127.0.0.1"
        assert config["disable_auth"] is True
        # Should log a warning about forcing localhost
        mock_logger.warning.assert_called_once()
        warning_call = mock_logger.warning.call_args[0][0]
        assert "Forcing to 127.0.0.1 for security" in warning_call


def test_load_config_disable_auth_with_localhost_no_warning() -> None:
    """Test that disable_auth with localhost doesn't trigger warning."""
    with (
        patch.dict(
            os.environ, {"DISABLE_AUTH": "true", "PROXY_HOST": "127.0.0.1"}, clear=True
        ),
        patch("src.core.config.config_loader.logger") as mock_logger,
    ):
        loader = ConfigLoader()
        config = loader.load_config()
        assert config["proxy_host"] == "127.0.0.1"
        assert config["disable_auth"] is True
        # Should not log a warning since host is already localhost
        mock_logger.warning.assert_not_called()


def test_load_config_auth_enabled_allows_custom_host() -> None:
    """Test that custom host is allowed when auth is enabled."""
    with (
        patch.dict(
            os.environ, {"DISABLE_AUTH": "false", "PROXY_HOST": "0.0.0.0"}, clear=True
        ),
        patch("src.core.config.config_loader.logger") as mock_logger,
    ):
        loader = ConfigLoader()
        config = loader.load_config()
        assert config["proxy_host"] == "0.0.0.0"
        assert config["disable_auth"] is False
        # Should not log any warnings
        mock_logger.warning.assert_not_called()


def test_load_config_str_to_bool_variations() -> None:
    """Test various string to boolean conversions."""
    test_cases = [
        ("true", True),
        ("1", True),
        ("yes", True),
        ("on", True),
        ("false", False),
        ("0", False),
        ("no", False),
        ("off", False),
        ("none", False),
        ("", False),
        ("invalid", False),
    ]

    for value, expected in test_cases:
        with patch.dict(os.environ, {"DISABLE_AUTH": value}, clear=True):
            loader = ConfigLoader()
            config = loader.load_config()
            assert config["disable_auth"] is expected
