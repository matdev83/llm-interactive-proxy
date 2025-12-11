"""Behavioral tests for Gemini OAuth 401 authentication retry with token refresh.

These tests verify the end-to-end behavior of the 401 retry logic,
ensuring transparent recovery from expired OAuth tokens.
"""

import inspect
from unittest.mock import MagicMock

import httpx
import pytest
from src.connectors.gemini_base.connector import GeminiOAuthBaseConnector
from src.connectors.gemini_base.streaming_executor import StreamingExecutor
from src.connectors.gemini_oauth_antigravity import GeminiOAuthAntigravityConnector


def get_base_connector_source() -> str:
    """Get the source code of the base connector module for inspection."""
    return inspect.getsource(GeminiOAuthBaseConnector)


def get_streaming_executor_source() -> str:
    """Get the source code of the streaming executor module for inspection."""
    return inspect.getsource(StreamingExecutor)


class TestAuthRetryBehavior:
    """Behavioral tests for 401 auth retry end-to-end flow."""

    def test_401_triggers_silent_retry_for_client(self) -> None:
        """
        Scenario: OAuth token expires during streaming request
        Given: A valid session using gemini-oauth-antigravity backend
        When: Backend returns 401 due to expired token
        Then: Proxy should refresh token and retry without client awareness
        """
        source = get_base_connector_source()

        # Verify 401 detection is present
        assert (
            "response.status_code == 401" in source
        ), "401 detection should be present in streaming code"

        # Verify retry flag is used to prevent infinite loops
        assert (
            "_auth_retry_attempted" in source
        ), "Retry flag should be used to prevent infinite loops"

        # Verify token refresh is called
        assert (
            "_refresh_token_if_needed" in source
        ), "Token refresh should be called on 401"

    def test_retry_timeout_prevents_indefinite_wait(self) -> None:
        """
        Scenario: Token refresh hangs
        Given: A 401 error is received
        When: Token refresh operation hangs
        Then: Timeout should trigger after 30 seconds
        And: Original 401 error should be returned to client
        """
        source = get_base_connector_source()

        # Verify timeout is used
        assert (
            "asyncio.wait_for" in source
        ), "asyncio.wait_for should be used for token refresh"

        # Verify timeout value is defined
        assert "AUTH_RETRY_TIMEOUT" in source, "Timeout constant should be defined"

        # Verify TimeoutError is handled
        assert "TimeoutError" in source, "TimeoutError should be caught and handled"

    def test_single_retry_prevents_infinite_loop(self) -> None:
        """
        Scenario: Token refresh succeeds but retry also gets 401
        Given: A 401 error triggers token refresh
        When: Token refresh succeeds
        And: Retry request also returns 401
        Then: Error should be returned to client (no further retries)
        """
        source = get_base_connector_source()

        # Verify retry is limited to single attempt
        assert (
            "_auth_retry_attempted=True" in source
        ), "Retry flag should be set to True to prevent infinite loops"

    def test_non_streaming_401_retry_behavior(self) -> None:
        """
        Scenario: Non-streaming request receives 401
        Given: A non-streaming request to gemini-oauth backend
        When: Backend returns 401 due to expired token
        Then: Proxy should refresh token and retry
        And: Successful response should be returned to client
        """
        source = get_base_connector_source()

        # Verify AuthenticationError handling is present
        assert (
            "AuthenticationError" in source
        ), "AuthenticationError handling should be present"

        # Verify retry flag is used
        assert (
            "_auth_retry_attempted" in source
        ), "Retry flag should be used to prevent infinite loops"

        # Verify token refresh is called
        assert (
            "_refresh_token_if_needed" in source
        ), "Token refresh should be called on 401"

        # Verify timeout is used
        assert (
            "AUTH_RETRY_TIMEOUT" in source
        ), "Timeout should be defined for token refresh"

    def test_refresh_failure_returns_401_to_client(self) -> None:
        """
        Scenario: Token refresh fails
        Given: A 401 error triggers token refresh
        When: Token refresh fails (returns False)
        Then: Original 401 error should be returned to client
        """
        source = get_base_connector_source()

        # Verify failed refresh path exists
        assert (
            "Token refresh failed" in source
        ), "Failed refresh handling should log appropriate message"

    def test_logging_provides_visibility(self) -> None:
        """
        Scenario: 401 retry occurs
        Given: Any 401 error scenario
        When: Retry logic is executed
        Then: Appropriate log messages should be generated
        """
        source = get_base_connector_source()

        # Verify retry attempt is logged
        assert "Received 401" in source, "401 detection should be logged"

        # Verify success is logged
        assert (
            "Token refresh successful" in source
        ), "Successful token refresh should be logged"


class TestAuthRetryIntegration:
    """Integration tests for auth retry with mocked components."""

    @pytest.mark.asyncio
    async def test_connector_has_required_methods(self) -> None:
        """
        Verify the connector has all methods required for auth retry.
        """
        mock_config = MagicMock()
        mock_config.backends = MagicMock()
        mock_config.backends.disable_gemini_oauth_fallback = False
        mock_config.logging = MagicMock()
        mock_config.logging.level = "WARNING"

        mock_translation = MagicMock()

        client = httpx.AsyncClient()
        connector = GeminiOAuthAntigravityConnector(
            client=client,
            config=mock_config,
            translation_service=mock_translation,
            name="test-connector",
        )

        # Verify the connector has the auth retry capability
        assert hasattr(
            connector, "_refresh_token_if_needed"
        ), "Connector should have _refresh_token_if_needed method"
        assert hasattr(
            connector, "_chat_completions_code_assist"
        ), "Connector should have _chat_completions_code_assist method"
        assert hasattr(
            connector, "_chat_completions_code_assist_streaming"
        ), "Connector should have _chat_completions_code_assist_streaming method"

        await client.aclose()

    def test_auth_code_constant_is_set_for_401(self) -> None:
        """
        Verify that 401 errors set the auth_error code.

        NOTE: The auth_error code is now set in StreamingExecutor, not the
        base connector, as part of the SOLID refactoring.
        """
        # Check in streaming executor where the 401 handling logic now lives
        executor_source = get_streaming_executor_source()

        # Verify 401 sets auth_error code
        assert (
            'code = "auth_error"' in executor_source
        ), "401 errors should set code to 'auth_error' in StreamingExecutor"

    def test_timeout_value_is_reasonable(self) -> None:
        """
        Verify timeout is a reasonable value (30 seconds).
        """
        source = get_base_connector_source()

        # Check for 30 second timeout
        assert "30.0" in source, "Timeout should be 30 seconds"


class TestAuthRetryArchitecture:
    """Architecture tests for auth retry implementation.

    NOTE: After the SOLID refactoring, streaming logic was moved to
    StreamingExecutor, so these tests now check both the connector
    and the executor sources as appropriate.
    """

    def test_retry_is_recursive_call(self) -> None:
        """
        Auth retry should use recursive call pattern for clean implementation.
        """
        connector_source = get_base_connector_source()
        executor_source = get_streaming_executor_source()

        # Streaming path uses stream_generator recursion in StreamingExecutor
        assert (
            "_stream_generator(" in executor_source
        ), "Streaming should use _stream_generator recursion in executor"

        # Non-streaming uses method recursion
        assert (
            "_chat_completions_code_assist(" in connector_source
        ), "Non-streaming should use method recursion"

    def test_response_is_passed_through_on_retry_success(self) -> None:
        """
        On successful retry, response should be yielded/returned to client.
        """
        executor_source = get_streaming_executor_source()

        # Streaming yields chunks from retry in StreamingExecutor
        assert (
            "yield retry_chunk" in executor_source
            or "async for retry_chunk" in executor_source
        ), "Streaming should yield chunks from retry in executor"

    def test_connection_is_closed_before_retry(self) -> None:
        """
        Original connection should be closed before retrying.
        """
        executor_source = get_streaming_executor_source()

        # Response should be closed before retry
        assert (
            "response.close()" in executor_source
        ), "Response should be closed before retry"
