"""
Tests for logging utilities.
"""

import logging
from unittest.mock import MagicMock, patch

import pytest
import structlog
from src.core.common.logging_utils import (
    LogContext,
    get_logger,
    log_async_call,
    log_call,
    redact,
    redact_dict,
    redact_text,
)

# Suppress Windows ProactorEventLoop ResourceWarnings for this module
pytestmark = pytest.mark.filterwarnings(
    "ignore:unclosed event loop <ProactorEventLoop.*:ResourceWarning"
)


class TestRedaction:
    """Test redaction functions."""

    def test_redact(self) -> None:
        """Test redacting a value."""
        # Test with a long string
        assert redact("api_key_12345678") == "ap***78"

        # Test with a short string
        assert redact("key") == "***"

        # Test with an empty string
        assert redact("") == ""

        # Test with a custom mask
        assert redact("password123", mask="[REDACTED]") == "pa[REDACTED]23"

    def test_redact_dict(self) -> None:
        """Test redacting a dictionary."""
        # Test with sensitive fields
        data = {
            "api_key": "sk_12345678",
            "name": "test",
            "config": {"password": "secret123", "public": "public_value"},
            "items": [{"secret": "hidden", "visible": "shown"}, "not_a_dict"],
        }

        result = redact_dict(data)

        assert result["api_key"] != "sk_12345678"  # Redacted
        assert result["name"] == "test"  # Not redacted
        assert result["config"]["password"] != "secret123"  # Redacted
        assert result["config"]["public"] == "public_value"  # Not redacted
        assert result["items"][0]["secret"] != "hidden"  # Redacted
        assert result["items"][0]["visible"] == "shown"  # Not redacted
        assert result["items"][1] == "not_a_dict"  # Not a dict, not redacted

        # Test with custom redacted fields
        result = redact_dict(data, redacted_fields={"name"})

        assert result["api_key"] == "sk_12345678"
        assert result["name"] == "***"

        # Test with custom mask
        result = redact_dict(data, mask="[REDACTED]")

        assert result["api_key"] == "sk[REDACTED]78"

    def test_redact_text_with_secrets(self) -> None:
        """Test redacting text with secrets."""
        # Test with a simple text
        text = "This is a test"
        result = redact_text(text)
        # Just verify it returns a string without changing the original
        assert isinstance(result, str)
        assert result == text  # No sensitive data to redact

        # Test with a custom mask
        text_with_api_key = "API key: sk_1234567890abcdefghij"
        result = redact_text(text_with_api_key, mask="[REDACTED]")
        assert isinstance(result, str)
        # Just verify it's not the same as the original (redaction happened)
        assert result != text_with_api_key

        # Ensure hyphenated keys are redacted
        modern_key = "sk-proj-1234567890abcdef1234567890"
        modern_result = redact_text(modern_key)
        assert modern_result != modern_key
        assert "sk-proj" not in modern_result


class TestLogging:
    """Test logging functions."""

    def test_get_logger(self) -> None:
        """Test get_logger function."""
        # Patch structlog.get_logger
        with patch("structlog.get_logger") as mock_get_logger:
            # Setup mock
            mock_logger = MagicMock(spec=structlog.stdlib.BoundLogger)
            mock_get_logger.return_value = mock_logger

            # Call get_logger
            logger = get_logger("test_logger")

            # Verify
            mock_get_logger.assert_called_once_with("test_logger")
            assert logger == mock_logger

    def test_log_call(self) -> None:
        """Test log_call decorator."""
        mock_logger = MagicMock()

        with patch(
            "src.core.common.logging_utils.get_logger", return_value=mock_logger
        ):
            # Define a decorated function
            @log_call(level=logging.INFO)
            def test_function() -> str:
                return "result"

            # Mock isEnabledFor
            mock_logger.isEnabledFor.return_value = True

            # Call the function
            result = test_function()

            # Verify the result
            assert result == "result"

            # Verify logging
            assert mock_logger.log.call_count == 2
            mock_logger.log.assert_any_call(
                20,  # logging.INFO value
                "Calling test_function",
                function="test_function",
                module="tests.unit.core.test_logging_utils",  # full module name
            )
            mock_logger.log.assert_any_call(
                20,  # logging.INFO value
                "Finished test_function",
                function="test_function",
                module="tests.unit.core.test_logging_utils",  # full module name
            )

    async def test_log_async_call(self) -> None:
        """Test log_async_call decorator."""
        mock_logger = MagicMock()

        with patch(
            "src.core.common.logging_utils.get_logger", return_value=mock_logger
        ):
            # Define a decorated function
            @log_async_call(level=logging.INFO)
            async def test_async_function() -> str:
                return "async result"

            # Mock isEnabledFor
            mock_logger.isEnabledFor.return_value = True

            # Call the function
            result = await test_async_function()

            # Verify the result
            assert result == "async result"

            # Verify logging
            assert mock_logger.log.call_count == 2
            mock_logger.log.assert_any_call(
                20,  # logging.INFO value
                "Calling test_async_function",
                function="test_async_function",
                module="tests.unit.core.test_logging_utils",  # full module name
            )
            mock_logger.log.assert_any_call(
                20,  # logging.INFO value
                "Finished test_async_function",
                function="test_async_function",
                module="tests.unit.core.test_logging_utils",  # full module name
            )

    def test_log_context(self) -> None:
        """Test LogContext class."""
        mock_logger = MagicMock()
        mock_bound_logger = MagicMock()
        mock_logger.bind.return_value = mock_bound_logger

        # Use the context manager
        with LogContext(mock_logger, request_id="123", user_id="456") as logger:
            # Verify the logger is bound
            assert logger == mock_bound_logger

            # Verify bind was called with the correct context
            mock_logger.bind.assert_called_once_with(request_id="123", user_id="456")
