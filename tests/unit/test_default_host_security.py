"""
Test case to ensure the proxy defaults to binding to localhost (127.0.0.1) for security.
This test will fail if the default host is ever changed back to 0.0.0.0 or any other
address that would expose the proxy to external networks by default.
"""

import os
import sys
from unittest.mock import patch

# Add the project root to the Python path when running as a script
if __name__ == "__main__":
    import pathlib

    project_root = pathlib.Path(__file__).parent.parent.parent
    sys.path.insert(0, str(project_root))

try:
    from src.core.config.app_config import AppConfig
except ImportError:
    print(
        "Error: Cannot import AppConfig. This test should be run with pytest or with proper Python path setup."
    )
    print("Run with: python -m pytest tests/unit/test_default_host_security.py")
    sys.exit(1)


def test_default_host_is_localhost():
    """Test that the default host is 127.0.0.1, not 0.0.0.0 or any other address."""
    # Create a default config without any environment variables set
    with patch.dict(os.environ, {}, clear=True):
        config = AppConfig()
        assert (
            config.host == "127.0.0.1"
        ), f"Expected default host to be '127.0.0.1', but got '{config.host}'"
        assert (
            config.host != "0.0.0.0"
        ), "Security regression: default host should not be '0.0.0.0'"


def test_default_host_from_env_still_uses_localhost():
    """Test that when no APP_HOST is set in environment, it defaults to 127.0.0.1."""
    # Remove any existing APP_HOST environment variable
    env_copy = os.environ.copy()
    env_copy.pop("APP_HOST", None)

    with patch.dict(os.environ, env_copy, clear=True):
        config = AppConfig.from_env()
        assert (
            config.host == "127.0.0.1"
        ), f"Expected default host to be '127.0.0.1' from env, but got '{config.host}'"


def test_host_can_be_overridden():
    """Test that the host can still be overridden when explicitly set."""
    # Test with environment variable override
    with patch.dict(os.environ, {"APP_HOST": "0.0.0.0"}):
        config = AppConfig.from_env()
        assert (
            config.host == "0.0.0.0"
        ), f"Expected host to be '0.0.0.0' when explicitly set, but got '{config.host}'"

    # Test with direct configuration override
    config = AppConfig(host="0.0.0.0")
    assert (
        config.host == "0.0.0.0"
    ), f"Expected host to be '0.0.0.0' when explicitly set, but got '{config.host}'"


def test_default_config_host_field():
    """Test the default value of the host field in AppConfig model."""
    # Check the default value directly from the model field
    config = AppConfig()
    assert config.host == "127.0.0.1"

    # Verify it's not any other unsafe default
    unsafe_defaults = ["0.0.0.0", "::", "0.0.0.0", ""]
    assert (
        config.host not in unsafe_defaults
    ), f"Host should not default to any of {unsafe_defaults}"


if __name__ == "__main__":
    # Run the tests manually if executed as script
    test_default_host_is_localhost()
    test_default_host_from_env_still_uses_localhost()
    test_host_can_be_overridden()
    test_default_config_host_field()
    print("All security tests passed!")
