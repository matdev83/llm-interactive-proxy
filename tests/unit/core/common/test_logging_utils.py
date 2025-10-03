"""Unit tests for logging utilities."""

import logging
import os
from unittest.mock import MagicMock, patch

import pytest
from src.core.common.logging_utils import (
    ApiKeyRedactionFilter,
    discover_api_keys_from_config_and_env,
    install_api_key_redaction_filter,
    redact_text,
)


class TestApiKeyRedactionFilter:
    """Test suite for ApiKeyRedactionFilter."""

    def test_init_with_keys(self):
        """Test initialization with API keys."""
        keys = ["sk-1234567890abcdefg", "Bearer abcdefghijklmnopqrst"]
        filter_instance = ApiKeyRedactionFilter(keys)
        assert len(filter_instance.patterns) > 0

    def test_init_without_keys(self):
        """Test initialization without API keys."""
        filter_instance = ApiKeyRedactionFilter()
        # Should still have patterns for common API key formats
        assert len(filter_instance.patterns) > 0

    def test_sanitize_string(self):
        """Test sanitizing a string."""
        keys = ["sk-1234567890abcdefg"]
        filter_instance = ApiKeyRedactionFilter(keys)

        # Test with API key in string
        result = filter_instance._sanitize("My API key is sk-1234567890abcdefg")
        assert "sk-1234567890abcdefg" not in result
        assert "***" in result

        # Test with Bearer token
        result = filter_instance._sanitize(
            "Authorization: Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9"
        )
        assert "Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9" not in result
        assert "Bearer ***" in result

    def test_sanitize_dict(self):
        """Test sanitizing a dictionary."""
        keys = ["sk-1234567890abcdefg"]
        filter_instance = ApiKeyRedactionFilter(keys)

        # Test with API key in dict
        test_dict = {"api_key": "sk-1234567890abcdefg", "model": "gpt-4"}
        result = filter_instance._sanitize(test_dict)
        assert result["api_key"] != "sk-1234567890abcdefg"
        assert "***" in result["api_key"]
        assert result["model"] == "gpt-4"

    def test_sanitize_list(self):
        """Test sanitizing a list."""
        keys = ["sk-1234567890abcdefg"]
        filter_instance = ApiKeyRedactionFilter(keys)

        # Test with API key in list
        test_list = ["sk-1234567890abcdefg", "normal text"]
        result = filter_instance._sanitize(test_list)
        assert "sk-1234567890abcdefg" not in result[0]
        assert "***" in result[0]
        assert result[1] == "normal text"

    def test_filter_log_record(self):
        """Test filtering a log record."""
        keys = ["sk-1234567890abcdefg"]
        filter_instance = ApiKeyRedactionFilter(keys)

        # Create a log record with API key in message
        record = logging.LogRecord(
            name="test",
            level=logging.INFO,
            pathname="test.py",
            lineno=1,
            msg="API key: sk-1234567890abcdefg",
            args=(),
            exc_info=None,
        )

        # Filter the record
        filter_instance.filter(record)

        # Check that the API key was redacted
        assert "sk-1234567890abcdefg" not in record.msg
        assert "***" in record.msg


class TestDiscoverApiKeysFromConfigAndEnv:
    """Test suite for discover_api_keys_from_config_and_env."""

    @pytest.fixture
    def mock_env(self):
        """Set up mock environment variables."""
        original_environ = os.environ.copy()

        # Set test environment variables
        os.environ.update(
            {
                "OPENAI_API_KEY": "sk-1234567890abcdefg",
                "GEMINI_API_KEY_1": "AIzaSyD-abcdefghijklmn",
                "GEMINI_API_KEY_14": "AIzaSyD-numbered14keyabcdef",
                "ANTHROPIC_API_KEY": "sk-ant-api03-abcdefghijklmn",
                "AUTH_TOKEN": "Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9",
                "NORMAL_ENV_VAR": "this is a normal value",
            }
        )

        yield

        # Restore original environment
        os.environ.clear()
        os.environ.update(original_environ)

    def test_discover_from_env(self, mock_env):
        """Test discovering API keys from environment variables."""
        keys = discover_api_keys_from_config_and_env()

        # Check that all API keys were discovered
        assert len(keys) >= 5
        assert any("sk-1234567890abcdefg" in k for k in keys)
        assert any("AIzaSyD-abcdefghijklmn" in k for k in keys)
        assert any("AIzaSyD-numbered14keyabcdef" in k for k in keys)
        assert any("sk-ant-api03-abcdefghijklmn" in k for k in keys)
        assert any("eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9" in k for k in keys)

        # Check that normal values were not discovered
        assert "this is a normal value" not in keys

    def test_discover_from_config_with_security_warnings(self):
        """Test that API keys are discovered from config with security warnings."""
        # Create a mock config object with API keys in it
        mock_config = MagicMock()
        mock_config.auth.api_keys = ["sk-config-1234567890abcdefg"]

        mock_backend = MagicMock()
        mock_backend.api_key = ["sk-backend-1234567890abcdefg"]

        mock_backends = MagicMock()
        mock_backends.openai = mock_backend

        # Mock backend registry to return registered backends
        with patch(
            "src.core.services.backend_registry.backend_registry"
        ) as mock_registry:
            mock_registry.get_registered_backends.return_value = ["openai"]

            # Set backends attribute on mock config
            mock_config.backends = mock_backends

            # Discover API keys
            with patch("src.core.common.logging_utils.get_logger") as mock_get_logger:
                mock_logger = MagicMock()
                mock_get_logger.return_value = mock_logger

                keys = discover_api_keys_from_config_and_env(mock_config)

                # API keys from config should be discovered for redaction purposes
                assert any("sk-config-1234567890abcdefg" in k for k in keys)
                assert any("sk-backend-1234567890abcdefg" in k for k in keys)

                # Security warnings should be logged
                mock_logger.warning.assert_called()
                warning_calls = [
                    call.args[0] for call in mock_logger.warning.call_args_list
                ]
                assert any("SECURITY WARNING" in call for call in warning_calls)


class TestInstallApiKeyRedactionFilter:
    """Test suite for install_api_key_redaction_filter."""

    def test_install_filter(self):
        """Test installing the API key redaction filter."""
        # Get root logger
        root_logger = logging.getLogger()

        # Count initial filters
        initial_filters = len(root_logger.filters)

        # Install filter
        install_api_key_redaction_filter(["sk-test-1234567890abcdefg"])

        # Check that a filter was added
        assert len(root_logger.filters) > initial_filters

        # Clean up
        root_logger.filters = root_logger.filters[:initial_filters]


class TestRedactText:
    """Test suite for redact_text."""

    def test_redact_text(self):
        """Test redacting text."""
        # Test with API key
        result = redact_text("API key: sk_test_1234567890abcdefg")
        assert "sk_test_1234567890abcdefg" not in result

        # Test with Bearer token
        result = redact_text("Authorization: Bearer abcdefghijklmnopqrst")
        assert "Bearer abcdefghijklmnopqrst" not in result
