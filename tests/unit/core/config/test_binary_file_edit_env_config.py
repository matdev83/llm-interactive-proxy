"""Tests for binary file edit steering ENV configuration."""

from __future__ import annotations

import pytest
from src.core.config.app_config import load_config


@pytest.mark.unit
def test_disable_binary_file_edit_steering_env_variable():
    """Test that DISABLE_BINARY_FILE_EDIT_STEERING ENV var disables the policy."""
    # Act: Load config with ENV var set
    config = load_config(
        config_path=None,
        environ={"DISABLE_BINARY_FILE_EDIT_STEERING": "true"},
    )

    # Assert: Feature should be disabled
    assert config.session.tool_call_reactor.binary_file_edit_steering_enabled is False


@pytest.mark.unit
def test_binary_file_edit_steering_enabled_by_default():
    """Test that binary file edit steering is enabled by default."""
    # Act: Load config with no ENV vars
    config = load_config(config_path=None, environ={})

    # Assert: Feature should be enabled by default
    assert config.session.tool_call_reactor.binary_file_edit_steering_enabled is True


@pytest.mark.unit
def test_binary_file_edit_steering_custom_message_env():
    """Test that BINARY_FILE_EDIT_STEERING_MESSAGE ENV var sets custom message."""
    # Arrange
    custom_message = "Custom binary file warning!"

    # Act: Load config with custom message
    config = load_config(
        config_path=None,
        environ={"BINARY_FILE_EDIT_STEERING_MESSAGE": custom_message},
    )

    # Assert: Custom message should be set
    assert (
        config.session.tool_call_reactor.binary_file_edit_steering_message
        == custom_message
    )


@pytest.mark.unit
def test_binary_file_edit_steering_message_none_by_default():
    """Test that binary file edit steering message is None by default."""
    # Act: Load config with no ENV vars
    config = load_config(config_path=None, environ={})

    # Assert: Message should be None (use default)
    assert config.session.tool_call_reactor.binary_file_edit_steering_message is None
