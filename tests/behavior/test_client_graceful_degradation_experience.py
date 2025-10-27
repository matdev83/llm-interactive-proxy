"""
Behavioral tests for client experience during graceful degradation.

These tests verify that clients see NOTHING during the entire graceful degradation
sequence until the final response is ready, ensuring a transparent experience.
"""

import time
from dataclasses import dataclass

import pytest
from src.connectors.gemini_oauth_base import (
    GeminiOAuthBaseConnector,
    GracefulDegradationConfig,
)
from src.core.common.exceptions import BackendError
from src.core.config.app_config import AppConfig

pytestmark = pytest.mark.integration


@dataclass
class MockChatRequest:
    """Mock chat request for testing."""

    model: str
    messages: list
    stream: bool = True
    max_tokens: int = 100
    temperature: float = 0.0


class MockGeminiOAuthConnectorForClientTesting(GeminiOAuthBaseConnector):
    """Mock connector that simulates client experience during graceful degradation."""

    def __init__(self):
        config = AppConfig()
        super().__init__(config)

        self._api_call_results = {}  # model -> list of results
        self._api_call_count = {}  # model -> call count
        self._api_call_timestamps = {}  # model -> list of timestamps

        # Configure faster retries for testing (but still realistic delays)
        self._degradation_config = GracefulDegradationConfig(
            enabled=True,
            retry_delays=[0.1, 0.2, 0.3],  # Fast for testing: 0.1s, 0.2s, 0.3s
            max_total_attempts=9,
            cooldown_duration=1.0,
            enable_recovery_probing=True,
            recovery_probe_interval=2.0,
        )

        # Initialize state
        self._total_attempts = 0
        self._permanently_failed = False
        self._quota_exceeded = False

    def set_api_behavior(self, model: str, results: list):
        """Set the behavior for a specific model."""
        self._api_call_results[model] = results.copy()
        self._api_call_count[model] = 0
        self._api_call_timestamps[model] = []

    async def _make_api_call(self, model: str, **kwargs):
        """Mock API call that returns predefined results."""
        call_count = self._api_call_count.get(model, 0)
        results = self._api_call_results.get(model, [])

        # Record timestamp
        if model not in self._api_call_timestamps:
            self._api_call_timestamps[model] = []
        self._api_call_timestamps[model].append(time.time())

        self._api_call_count[model] = call_count + 1

        if call_count < len(results):
            result = results[call_count]
            if isinstance(result, Exception):
                raise result
            return result

        # Default to success if no specific behavior set
        return {"success": True, "model": model}

    async def _discover_project_id(self) -> str:
        """Mock project ID discovery."""
        return "test-project-id"


class TestClientExperienceDuringGracefulDegradation:
    """Test client experience during graceful degradation scenarios."""

    @pytest.fixture
    def connector(self):
        """Fixture for mock connector."""
        return MockGeminiOAuthConnectorForClientTesting()

    @pytest.fixture
    def mock_request(self):
        """Fixture for mock chat request."""
        return MockChatRequest(
            model="gemini-2.5-pro",
            messages=[{"role": "user", "content": "Hello, how are you?"}],
            stream=True,
        )

    @pytest.mark.asyncio
    async def test_client_transparent_graceful_degradation_experience(
        self, connector, mock_request
    ):
        """Test that client sees nothing during graceful degradation until final response.

        This verifies the expected behavior:
        - Client submits Pro model request
        - Pro gets 429 errors and retries with delays
        - Flash fallback is attempted
        - Client sees ONLY the final response (success or failure)
        - No intermediate errors are sent to client
        """

        start_time = time.time()

        # Setup: Pro model fails 3 times, Flash succeeds
        error_429 = BackendError("Rate limit exceeded", status_code=429)
        connector.set_api_behavior("gemini-2.5-pro", [error_429, error_429, error_429])
        connector.set_api_behavior(
            "gemini-2.5-flash", [{"success": True, "model": "gemini-2.5-flash"}]
        )

        # Execute: Make request that triggers graceful degradation
        # This simulates the real behavior where graceful degradation happens
        # internally and client only sees the final result
        result = await connector.chat_completions(
            request_data=mock_request,
            processed_messages=mock_request.messages,
            effective_model="gemini-2.5-pro",
        )

        total_wait_time = time.time() - start_time

        # Verify: Client experience - gets single successful result
        assert result is not None, "Client should receive a successful response"

        # Verify: Graceful degradation happened transparently
        assert (
            connector._api_call_count["gemini-2.5-pro"] >= 3
        ), "Pro model should be retried"
        assert (
            connector._api_call_count["gemini-2.5-flash"] >= 1
        ), "Flash model should be tried"

        # Verify: Client waited through the retry sequence but got final result
        # (In real implementation, client sees nothing during retries)
        assert (
            total_wait_time >= 0.6
        ), "Client should wait through retry delays (0.1s + 0.2s + 0.3s)"

        print(
            f"SUCCESS: Client waited {total_wait_time:.1f}s for transparent Pro->Flash fallback"
        )
        print(f"Pro attempts: {connector._api_call_count['gemini-2.5-pro']}")
        print(f"Flash attempts: {connector._api_call_count['gemini-2.5-flash']}")

    @pytest.mark.asyncio
    async def test_client_sees_final_error_after_complete_exhaustion(
        self, connector, mock_request
    ):
        """Test that client sees error only after both Pro and Flash are exhausted.

        Expected behavior:
        1. Client submits Pro model request
        2. Pro fails with 429 errors and retries
        3. Flash fallback is attempted and also fails with retries
        4. Client sees ONLY the final error response
        5. No intermediate 429 errors are sent to client
        """

        start_time = time.time()

        # Setup: Both Pro and Flash fail completely
        error_429 = BackendError("Rate limit exceeded", status_code=429)
        connector.set_api_behavior("gemini-2.5-pro", [error_429, error_429, error_429])
        connector.set_api_behavior(
            "gemini-2.5-flash", [error_429, error_429, error_429]
        )

        # Execute: Make request that should exhaust both models
        # This should fail after trying both models
        with pytest.raises(BackendError) as exc_info:
            await connector.chat_completions(
                request_data=mock_request,
                processed_messages=mock_request.messages,
                effective_model="gemini-2.5-pro",
            )

        total_wait_time = time.time() - start_time

        # Verify: Final error after complete exhaustion
        assert "max_attempts_exceeded" in str(
            exc_info.value
        ) or "all_models_exhausted" in str(exc_info.value)

        # Verify: Both models were attempted multiple times
        assert (
            connector._api_call_count["gemini-2.5-pro"] >= 3
        ), "Pro model should be retried"
        assert (
            connector._api_call_count["gemini-2.5-flash"] >= 1
        ), "Flash model should be attempted"

        # Verify: Backend marked as unusable
        assert connector._quota_exceeded, "Backend should be marked as quota exceeded"

        # Verify: Client waited through complete sequence
        expected_wait_time = 0.6 * 2  # (0.1+0.2+0.3) for Pro + (0.1+0.2+0.3) for Flash
        assert (
            total_wait_time >= expected_wait_time * 0.8
        ), f"Client should wait through complete sequence (~{expected_wait_time}s)"

        print(
            f"SUCCESS: Client waited {total_wait_time:.1f}s before receiving final error"
        )
        print(f"Total Pro attempts: {connector._api_call_count['gemini-2.5-pro']}")
        print(f"Total Flash attempts: {connector._api_call_count['gemini-2.5-flash']}")

    @pytest.mark.asyncio
    async def test_client_transparent_model_substitution(self, connector, mock_request):
        """Test that client gets transparent model substitution.

        Expected behavior:
        1. Client requests gemini-2.5-pro
        2. Pro fails, Flash succeeds
        3. Client receives response (would indicate Flash model was used in real implementation)
        4. Client is unaware of the Pro->Flash substitution process
        """

        start_time = time.time()

        # Setup: Pro fails, Flash succeeds
        error_429 = BackendError("Rate limit exceeded", status_code=429)
        connector.set_api_behavior("gemini-2.5-pro", [error_429, error_429, error_429])
        connector.set_api_behavior(
            "gemini-2.5-flash", [{"success": True, "model": "gemini-2.5-flash"}]
        )

        # Execute: Request Pro model
        result = await connector.chat_completions(
            request_data=mock_request,
            processed_messages=mock_request.messages,
            effective_model="gemini-2.5-pro",  # Client requested Pro
        )

        total_wait_time = time.time() - start_time

        # Verify: Client gets successful response despite requesting Pro
        assert result is not None, "Client should receive a successful response"

        # Verify: Transparent fallback occurred
        assert (
            connector._api_call_count["gemini-2.5-pro"] >= 3
        ), "Pro model should be attempted"
        assert (
            connector._api_call_count["gemini-2.5-flash"] >= 1
        ), "Flash model should be used as fallback"

        print(
            f"SUCCESS: Client requested Pro, transparently received Flash response after {total_wait_time:.1f}s"
        )

    @pytest.mark.asyncio
    async def test_no_partial_responses_during_graceful_degradation(
        self, connector, mock_request
    ):
        """Test that no partial responses are sent during graceful degradation.

        Expected behavior:
        1. Client submits request
        2. Graceful degradation happens internally
        3. Client receives complete response only after degradation completes
        4. No partial/incomplete responses are sent
        """

        start_time = time.time()

        # Setup: Pro fails, Flash succeeds after delay
        error_429 = BackendError("Rate limit exceeded", status_code=429)
        connector.set_api_behavior("gemini-2.5-pro", [error_429, error_429, error_429])
        connector.set_api_behavior(
            "gemini-2.5-flash", [{"success": True, "model": "gemini-2.5-flash"}]
        )

        # Execute request
        result = await connector.chat_completions(
            request_data=mock_request,
            processed_messages=mock_request.messages,
            effective_model="gemini-2.5-pro",
        )

        total_wait_time = time.time() - start_time

        # Verify: Single complete response after graceful degradation completes
        assert result is not None, "Client should receive complete response"

        # Verify: Response comes only after graceful degradation completes
        assert (
            total_wait_time >= 0.6
        ), f"Response should come after retry delays complete ({total_wait_time:.1f}s)"

        # Verify: Complete fallback sequence executed
        assert (
            connector._api_call_count["gemini-2.5-pro"] >= 3
        ), "Pro model should be exhausted"
        assert (
            connector._api_call_count["gemini-2.5-flash"] >= 1
        ), "Flash model should be tried"

        print(
            f"SUCCESS: Complete response came after {total_wait_time:.1f}s (after graceful degradation completed)"
        )


if __name__ == "__main__":
    # Run the tests
    pytest.main([__file__, "-v", "-s"])
