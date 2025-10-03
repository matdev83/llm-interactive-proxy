"""
Shared test fixtures for AppConfig objects.

This module provides consistent fixtures for creating AppConfig objects
with reasonable defaults for testing purposes.
"""

from typing import Any

import pytest
from src.core.config.app_config import (
    AppConfig,
    AuthConfig,
    BackendConfig,
    BackendSettings,
    LoggingConfig,
    SessionConfig,
)


def make_test_app_config(overrides: dict[str, Any] | None = None) -> AppConfig:
    """Create a test AppConfig with sensible defaults.

    Args:
        overrides: Dictionary of values to override the defaults

    Returns:
        AppConfig object configured for testing
    """
    defaults = {
        "host": "localhost",
        "port": 9000,
        "proxy_timeout": 30,
        "command_prefix": "!/",
        "backends": BackendSettings(
            default_backend="openai",
            openai=BackendConfig(api_key=["test_openai_key"]),
            openrouter=BackendConfig(api_key=["test_openrouter_key"]),
            anthropic=BackendConfig(api_key=["test_anthropic_key"]),
            gemini=BackendConfig(api_key=["test_gemini_key"]),
            zai=BackendConfig(api_key=["test_zai_key"]),
        ),
        "auth": AuthConfig(disable_auth=True, api_keys=["test_api_key"]),
        "session": SessionConfig(
            cleanup_enabled=False,
            default_interactive_mode=True,
        ),
        "logging": LoggingConfig(
            level="INFO",
            request_logging=False,
            response_logging=False,
        ),
    }

    if overrides:
        # Deep merge overrides with defaults
        merged = _deep_merge(defaults, overrides)
        return AppConfig(**merged)

    return AppConfig(**defaults)


def _deep_merge(base: dict[str, Any], overrides: dict[str, Any]) -> dict[str, Any]:
    """Deep merge two dictionaries."""
    result = base.copy()

    for key, value in overrides.items():
        if key in result and isinstance(result[key], dict) and isinstance(value, dict):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = value

    return result


@pytest.fixture
def test_app_config() -> AppConfig:
    """Fixture providing a standard test AppConfig."""
    return make_test_app_config()


@pytest.fixture
def test_app_config_with_auth() -> AppConfig:
    """Fixture providing a test AppConfig with authentication enabled."""
    return make_test_app_config(
        {"auth": {"disable_auth": False, "api_keys": ["test_key_1", "test_key_2"]}}
    )


@pytest.fixture
def test_app_config_minimal() -> AppConfig:
    """Fixture providing a minimal AppConfig for basic tests."""
    return make_test_app_config(
        {
            "backends": {
                "default_backend": "openai",
                "openai": {"api_key": ["minimal_key"]},
            }
        }
    )
