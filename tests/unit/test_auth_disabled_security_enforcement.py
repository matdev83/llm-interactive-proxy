"""
Test case to ensure that when authentication is disabled, the proxy is forced to bind to localhost (127.0.0.1) for security.
This test will fail if the security enforcement is ever removed or bypassed.
"""

import os
from unittest.mock import patch

from src.core.config.app_config import AppConfig, AuthConfig


def test_auth_disabled_forces_localhost_binding():
    """Test that disabling authentication forces the host to 127.0.0.1 for security."""
    # Test with auth disabled and host set to 0.0.0.0
    config = AppConfig(host="0.0.0.0", auth=AuthConfig(disable_auth=True))

    # The security enforcement should force host to 127.0.0.1
    from src.core.cli import _enforce_localhost_if_auth_disabled

    secured_config = _enforce_localhost_if_auth_disabled(config)

    assert (
        secured_config.host == "127.0.0.1"
    ), f"Expected host to be forced to '127.0.0.1' when auth is disabled, but got '{secured_config.host}'"
    assert secured_config.auth.disable_auth is True


def test_auth_disabled_forces_localhost_binding_any_non_localhost():
    """Test that disabling authentication forces the host to 127.0.0.1 even with any non-localhost address."""
    # Test with auth disabled and host set to a public IP
    config = AppConfig(host="192.168.1.100", auth=AuthConfig(disable_auth=True))

    # The security enforcement should force host to 127.0.0.1
    from src.core.cli import _enforce_localhost_if_auth_disabled

    secured_config = _enforce_localhost_if_auth_disabled(config)

    assert (
        secured_config.host == "127.0.0.1"
    ), f"Expected host to be forced to '127.0.0.1' when auth is disabled, but got '{secured_config.host}'"
    assert secured_config.auth.disable_auth is True


def test_auth_enabled_allows_any_host():
    """Test that when authentication is enabled, any host address is allowed."""
    # Test with auth enabled and host set to 0.0.0.0
    config = AppConfig(host="0.0.0.0", auth=AuthConfig(disable_auth=False))

    # The security enforcement should not change the host
    from src.core.cli import _enforce_localhost_if_auth_disabled

    secured_config = _enforce_localhost_if_auth_disabled(config)

    assert (
        secured_config.host == "0.0.0.0"
    ), f"Expected host to remain '0.0.0.0' when auth is enabled, but got '{secured_config.host}'"
    assert secured_config.auth.disable_auth is False


def test_auth_disabled_localhost_remains_unchanged():
    """Test that when authentication is disabled but host is already localhost, it remains unchanged."""
    # Test with auth disabled and host already set to localhost
    config = AppConfig(host="127.0.0.1", auth=AuthConfig(disable_auth=True))

    # The security enforcement should not change the host since it's already localhost
    from src.core.cli import _enforce_localhost_if_auth_disabled

    secured_config = _enforce_localhost_if_auth_disabled(config)

    assert (
        secured_config.host == "127.0.0.1"
    ), f"Expected host to remain '127.0.0.1' when auth is disabled and already localhost, but got '{secured_config.host}'"
    assert secured_config.auth.disable_auth is True


def test_auth_disabled_with_environment_variables():
    """Test that the security enforcement works correctly with environment variables."""
    # Test with environment variables that disable auth and set host to 0.0.0.0
    env_vars = {"DISABLE_AUTH": "true", "APP_HOST": "0.0.0.0"}

    with patch.dict(os.environ, env_vars, clear=True):
        config = AppConfig.from_env()

        # The security enforcement should force host to 127.0.0.1
        from src.core.cli import _enforce_localhost_if_auth_disabled

        secured_config = _enforce_localhost_if_auth_disabled(config)

        assert (
            secured_config.host == "127.0.0.1"
        ), f"Expected host to be forced to '127.0.0.1' when auth is disabled via env, but got '{secured_config.host}'"
        assert secured_config.auth.disable_auth is True


if __name__ == "__main__":
    # Run the tests manually if executed as script
    test_auth_disabled_forces_localhost_binding()
    test_auth_disabled_forces_localhost_binding_any_non_localhost()
    test_auth_enabled_allows_any_host()
    test_auth_disabled_localhost_remains_unchanged()
    test_auth_disabled_with_environment_variables()
    print("All authentication security enforcement tests passed!")
