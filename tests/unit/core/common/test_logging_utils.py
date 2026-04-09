"""Unit tests for logging utilities."""

import logging
import os
from unittest.mock import MagicMock, patch

import pytest
from src.core.common.logging_utils import (
    ApiKeyRedactionFilter,
    _discover_api_keys_from_config_backends,
    discover_api_keys_from_config_and_env,
    format_for_debug_log,
    install_api_key_redaction_filter,
    redact_text,
    truncate_for_debug_log,
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

    def test_sanitize_tuple(self):
        """Test sanitizing a tuple."""
        keys = ["sk-1234567890abcdefg"]
        filter_instance = ApiKeyRedactionFilter(keys)

        test_tuple = ("sk-1234567890abcdefg", "other")
        result = filter_instance._sanitize(test_tuple)
        assert isinstance(result, tuple)
        assert "sk-1234567890abcdefg" not in result[0]
        assert "***" in result[0]
        assert result[1] == "other"

    def test_filter_handles_tuple_args(self):
        """Test filtering log records with tuple args."""
        keys = ["sk-1234567890abcdefg"]
        filter_instance = ApiKeyRedactionFilter(keys)

        record = logging.LogRecord(
            name="test",
            level=logging.INFO,
            pathname="test.py",
            lineno=1,
            msg="Masked values: %s",
            args=("sk-1234567890abcdefg",),
            exc_info=None,
        )

        filter_instance.filter(record)

        formatted = record.getMessage()
        assert "sk-1234567890abcdefg" not in formatted
        assert "***" in formatted
        assert all("sk-1234567890abcdefg" not in str(arg) for arg in record.args)

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
                "OPENCODE_GO_API_KEY": "opencode-go-primary-key",
                "OPENCODE_GO_API_KEY_1": "opencode-go-numbered-key",
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
        assert any("opencode-go-primary-key" in k for k in keys)
        assert any("opencode-go-numbered-key" in k for k in keys)
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
            # Patch _logged_security_warnings to ensure we start with a clean state
            # This prevents interference from other tests that might have already logged warnings
            with (
                patch(
                    "src.core.common.logging_utils._logged_security_warnings", new=set()
                ),
                patch("src.core.common.logging_utils.get_logger") as mock_get_logger,
            ):
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

        # Test with modern hyphenated API key
        modern_key = "sk-proj-1234567890abcdef1234567890"
        result = redact_text(f"Leaked key: {modern_key}")
        assert modern_key not in result

        # Test with Bearer token
        result = redact_text("Authorization: Bearer abcdefghijklmnopqrst")
        assert "Bearer abcdefghijklmnopqrst" not in result


class TestTruncateForDebugLog:
    def test_short_string_unchanged(self) -> None:
        assert truncate_for_debug_log("hi", max_chars=512) == "hi"

    def test_truncation_suffix(self) -> None:
        long = "x" * 600
        out = truncate_for_debug_log(long, max_chars=100)
        assert out.endswith("... [truncated, total_chars=600]")
        assert len(out) < len(long)

    def test_format_for_debug_log_dict(self) -> None:
        out = format_for_debug_log({"a": "b"}, max_chars=512)
        assert '"a": "b"' in out

    def test_format_for_debug_log_truncates(self) -> None:
        out = format_for_debug_log({"k": "v" * 800}, max_chars=80)
        assert "truncated" in out


class TestSecurityWarningFalsePositive:
    """Regression tests for false-positive SECURITY WARNING.

    The API key in config can be populated via
    get_env_value_with_windows_persistent_fallback() which reads from
    the Windows persistent registry when the process-level env is stale.
    The false-positive check must account for this, not just os.getenv().
    """

    def _make_config(self, backend_name: str, api_key_value: str) -> MagicMock:
        mock_backend = MagicMock()
        mock_backend.api_key = api_key_value
        mock_backends = MagicMock()
        setattr(mock_backends, backend_name, mock_backend)
        mock_config = MagicMock()
        mock_config.backends = mock_backends
        return mock_config

    def test_no_warning_when_key_matches_env_var(self):
        """No warning when config key matches the process env var."""
        key = "sk-from-env-12345678"
        mock_config = self._make_config("some-backend", key)

        with (
            patch(
                "src.core.services.backend_registry.backend_registry"
            ) as mock_registry,
            patch.dict(os.environ, {"SOME_BACKEND_API_KEY": key}, clear=False),
            patch("src.core.common.logging_utils._logged_security_warnings", new=set()),
            patch("src.core.common.logging_utils.get_logger") as mock_get_logger,
            patch(
                "src.core.common.env_utils.get_env_value_with_windows_persistent_fallback",
                side_effect=lambda _name, **_kw: (os.environ.get(_name), "process"),
            ),
        ):
            mock_registry.get_registered_backends.return_value = ["some-backend"]
            mock_logger = MagicMock()
            mock_get_logger.return_value = mock_logger

            found: set[str] = set()
            _discover_api_keys_from_config_backends(mock_config, found)

            warning_calls = [
                call.args[0] for call in mock_logger.warning.call_args_list
            ]
            assert not any("SECURITY WARNING" in w for w in warning_calls)
            assert key in found

    def test_no_false_positive_when_key_from_persistent_fallback(
        self,
    ):
        """No warning when key is absent from os.environ but resolves via
        get_env_value_with_windows_persistent_fallback (Windows registry)."""
        key = "sk-from-registry-99999"
        mock_config = self._make_config("zai-coding-plan", key)
        os.environ.pop("ZAI_CODING_PLAN_API_KEY", None)

        with (
            patch(
                "src.core.services.backend_registry.backend_registry"
            ) as mock_registry,
            patch("src.core.common.logging_utils._logged_security_warnings", new=set()),
            patch("src.core.common.logging_utils.get_logger") as mock_get_logger,
            patch(
                "src.core.common.env_utils.get_env_value_with_windows_persistent_fallback",
                return_value=(key, "windows-user"),
            ),
        ):
            mock_registry.get_registered_backends.return_value = ["zai-coding-plan"]
            mock_logger = MagicMock()
            mock_get_logger.return_value = mock_logger

            found: set[str] = set()
            _discover_api_keys_from_config_backends(mock_config, found)

            warning_calls = [
                call.args[0] for call in mock_logger.warning.call_args_list
            ]
            assert not any("SECURITY WARNING" in w for w in warning_calls)
            assert key in found

    def test_warning_when_key_truly_hardcoded(self):
        """Warning IS emitted when key is NOT from any env source."""
        key = "sk-hardcoded-in-config-0000"
        mock_config = self._make_config("some-backend", key)

        with (
            patch(
                "src.core.services.backend_registry.backend_registry"
            ) as mock_registry,
            patch("src.core.common.logging_utils._logged_security_warnings", new=set()),
            patch("src.core.common.logging_utils.get_logger") as mock_get_logger,
            patch(
                "src.core.common.env_utils.get_env_value_with_windows_persistent_fallback",
                return_value=(None, "missing"),
            ),
        ):
            mock_registry.get_registered_backends.return_value = ["some-backend"]
            mock_logger = MagicMock()
            mock_get_logger.return_value = mock_logger

            found: set[str] = set()
            _discover_api_keys_from_config_backends(mock_config, found)

            warning_calls = [
                call.args[0] for call in mock_logger.warning.call_args_list
            ]
            assert any("SECURITY WARNING" in w for w in warning_calls)
            assert key in found

    def test_no_false_positive_list_keys_from_persistent_fallback(
        self,
    ):
        """No warning for list-type api_key that matches persistent fallback."""
        key = "sk-registry-list-key"
        mock_backend = MagicMock()
        mock_backend.api_key = [key]
        mock_backends = MagicMock()
        setattr(mock_backends, "some-backend", mock_backend)
        mock_config = MagicMock()
        mock_config.backends = mock_backends

        with (
            patch(
                "src.core.services.backend_registry.backend_registry"
            ) as mock_registry,
            patch("src.core.common.logging_utils._logged_security_warnings", new=set()),
            patch("src.core.common.logging_utils.get_logger") as mock_get_logger,
            patch(
                "src.core.common.env_utils.get_env_value_with_windows_persistent_fallback",
                return_value=(key, "windows-user"),
            ),
        ):
            mock_registry.get_registered_backends.return_value = ["some-backend"]
            mock_logger = MagicMock()
            mock_get_logger.return_value = mock_logger

            found: set[str] = set()
            _discover_api_keys_from_config_backends(mock_config, found)

            warning_calls = [
                call.args[0] for call in mock_logger.warning.call_args_list
            ]
            assert not any("SECURITY WARNING" in w for w in warning_calls)
            assert key in found
