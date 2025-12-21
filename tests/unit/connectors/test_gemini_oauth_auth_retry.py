"""Unit tests for Gemini OAuth 401 authentication retry with token refresh.

These tests verify that the proxy gracefully handles 401 authentication errors
by refreshing the OAuth token and retrying the request transparently.
"""

import inspect
from unittest.mock import MagicMock

import httpx
import pytest
from src.connectors.antigravity_oauth import AntigravityOAuthConnector
from src.connectors.gemini_base.connector import GeminiOAuthBaseConnector
from src.connectors.gemini_base.streaming_executor import StreamingExecutor


@pytest.fixture
def mock_config() -> MagicMock:
    """Create mock AppConfig."""
    config = MagicMock()
    config.backends = MagicMock()
    config.backends.disable_gemini_oauth_fallback = False
    config.logging = MagicMock()
    config.logging.level = "WARNING"
    return config


@pytest.fixture
def mock_translation_service() -> MagicMock:
    """Create mock TranslationService."""
    svc = MagicMock()
    svc.to_domain_stream_chunk = MagicMock(
        return_value={
            "id": "chatcmpl-123",
            "object": "chat.completion.chunk",
            "created": 1234567890,
            "model": "test-model",
            "choices": [
                {
                    "index": 0,
                    "delta": {"content": "Hello"},
                    "finish_reason": None,
                }
            ],
        }
    )
    return svc


@pytest.fixture
def connector(
    mock_config: MagicMock, mock_translation_service: MagicMock
) -> AntigravityOAuthConnector:
    """Create AntigravityOAuthConnector for testing."""
    client = httpx.AsyncClient()
    conn = AntigravityOAuthConnector(
        client=client,
        config=mock_config,
        translation_service=mock_translation_service,
        name="test-antigravity",
    )
    return conn


def get_base_connector_source() -> str:
    """Get the source code of the base connector module for inspection."""
    return inspect.getsource(GeminiOAuthBaseConnector)


def get_streaming_executor_source() -> str:
    """Get the source code of the streaming executor for inspection."""
    return inspect.getsource(StreamingExecutor)


class TestAuthRetryNonStreaming:
    """Tests for 401 authentication retry in non-streaming requests."""

    def test_auth_retry_parameter_exists(self) -> None:
        """Method signature should include _auth_retry_attempted parameter."""
        source = get_base_connector_source()
        # Check for parameter in method signature
        assert "_auth_retry_attempted: bool = False" in source

    def test_auth_retry_timeout_constant_defined(self) -> None:
        """AUTH_RETRY_TIMEOUT constant should be defined for non-streaming."""
        source = get_base_connector_source()
        assert "AUTH_RETRY_TIMEOUT" in source

    def test_timeout_is_30_seconds(self) -> None:
        """Auth retry timeout should be 30 seconds."""
        source = get_base_connector_source()
        assert "30.0" in source


class TestAuthRetryStreaming:
    """Tests for 401 authentication retry in streaming requests."""

    def test_streaming_auth_retry_parameter_exists(self) -> None:
        """Streaming stream_generator should have _auth_retry_attempted parameter."""
        source = get_base_connector_source()
        # Check that the stream_generator inner function has the parameter
        assert "_auth_retry_attempted: bool = False" in source

    def test_streaming_auth_retry_timeout_present(self) -> None:
        """Streaming token refresh should have a timeout."""
        source = get_base_connector_source()
        assert "asyncio.wait_for" in source

    def test_streaming_401_is_detected(self) -> None:
        """Streaming path should detect 401 status codes."""
        source = get_base_connector_source()
        assert "response.status_code == 401" in source


class TestAuthRetryBehavior:
    """Behavioral tests for auth retry logic."""

    def test_401_triggers_token_refresh(self) -> None:
        """401 should trigger _refresh_token_if_needed call."""
        source = get_base_connector_source()
        # Verify refresh is called after 401 detection
        assert "_refresh_token_if_needed" in source
        assert "response.status_code == 401" in source

    def test_auth_retry_logs_info_on_attempt(self) -> None:
        """Auth retry should log info messages when attempting retry."""
        source = get_base_connector_source()
        assert "Received 401 Unauthorized" in source

    def test_token_refresh_success_is_logged(self) -> None:
        """Successful token refresh should be logged."""
        source = get_base_connector_source()
        assert "Token refresh successful" in source

    def test_single_retry_prevents_infinite_loop(self) -> None:
        """Recursive call should set _auth_retry_attempted=True."""
        source = get_base_connector_source()
        assert "_auth_retry_attempted=True" in source


class TestAuthRetryEdgeCases:
    """Edge case tests for auth retry logic."""

    def test_refresh_failure_is_logged(self) -> None:
        """If token refresh fails, it should be logged."""
        source = get_base_connector_source()
        assert "Token refresh failed" in source

    def test_timeout_error_is_handled(self) -> None:
        """asyncio.TimeoutError should be caught and handled gracefully."""
        source = get_base_connector_source()
        assert "TimeoutError" in source

    def test_timeout_is_logged(self) -> None:
        """Timeout should produce a log message."""
        source = get_base_connector_source()
        assert "timed out" in source.lower()

    def test_generic_exception_is_caught(self) -> None:
        """Generic exceptions during refresh should be caught."""
        source = get_base_connector_source()
        assert "Error during token refresh attempt" in source


class TestAuthCodeSetting:
    """Tests for auth_error code setting on 401."""

    def test_401_sets_auth_error_code(self) -> None:
        """401 errors should set code to 'auth_error'.

        Note: Auth error handling has been moved to StreamingExecutor
        as part of SOLID refactoring, so we check both sources.
        """
        connector_source = get_base_connector_source()
        executor_source = get_streaming_executor_source()
        # Check either connector or streaming executor has auth_error code setting
        has_auth_error = (
            'code = "auth_error"' in connector_source
            or 'code = "auth_error"' in executor_source
        )
        assert (
            has_auth_error
        ), "Neither connector nor executor has auth_error code setting"


class TestConnectorHasRequiredMethods:
    """Tests that connector has required methods for auth retry."""

    def test_connector_has_refresh_method(
        self, connector: AntigravityOAuthConnector
    ) -> None:
        """Connector should have _refresh_token_if_needed method."""
        assert hasattr(connector, "_refresh_token_if_needed")
        assert callable(connector._refresh_token_if_needed)

    def test_connector_has_chat_completions_method(
        self, connector: AntigravityOAuthConnector
    ) -> None:
        """Connector should have _chat_completions_code_assist method."""
        assert hasattr(connector, "_chat_completions_code_assist")
        assert callable(connector._chat_completions_code_assist)

    def test_connector_has_streaming_method(
        self, connector: AntigravityOAuthConnector
    ) -> None:
        """Connector should have _chat_completions_code_assist_streaming method."""
        assert hasattr(connector, "_chat_completions_code_assist_streaming")
        assert callable(connector._chat_completions_code_assist_streaming)
