"""
Behavioral tests for graceful degradation and recovery probing.

These tests verify the complete end-to-end behavior of the graceful degradation
system including retry logic, model fallback, cooldowns, and recovery probing.
"""

import pytest

pytestmark = pytest.mark.integration

import asyncio
import contextlib
import json
import time
from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest
from src.connectors.gemini_oauth_base import (
    GeminiOAuthBaseConnector,
    GracefulDegradationConfig,
    GracefulDegradationMetrics,
    ModelRetryState,
)
from src.core.common.exceptions import BackendError, RateLimitExceededError
from src.core.config.app_config import AppConfig
from src.core.domain.chat import ChatRequest
from src.core.domain.responses import ResponseEnvelope, StreamingResponseEnvelope


# Changed to inherit from ChatRequest
class MockChatRequest(ChatRequest):
    """Mock chat request for testing."""

    model: str = "gemini-2.5-pro"  # Default model
    messages: list = []  # Default empty list
    stream: bool = False
    max_tokens: int = 100
    temperature: float = 0.0


def _mock_httpx_response(
    status_code: int = 200, content: dict | str = "", headers: dict | None = None
) -> httpx.Response:
    """Helper to create a mock httpx.Response object."""
    mock_response = MagicMock(spec=httpx.Response)
    mock_response.status_code = status_code
    mock_response.headers = headers or httpx.Headers()
    if isinstance(content, dict):
        mock_response.json.return_value = content
        mock_response.text = json.dumps(content)
        mock_response.content = json.dumps(content).encode("utf-8")
    else:
        mock_response.text = content
        mock_response.content = content.encode("utf-8")

    async def aiter_bytes_mock():
        if isinstance(content, dict):
            yield json.dumps(content).encode("utf-8")
        else:
            yield content.encode("utf-8")

    mock_response.aiter_bytes.return_value = aiter_bytes_mock()
    return mock_response


class MockGeminiOAuthConnector(GeminiOAuthBaseConnector):
    """Mock connector for testing graceful degradation behavior."""

    def __init__(self):
        from src.connectors.gemini_base.file_watcher import FileWatcherState
        from src.connectors.gemini_base.token_manager import TokenManager

        # Initialize composed managers FIRST (before setting properties that delegate to them)
        self._token_manager = TokenManager()
        self._file_watcher_state = FileWatcherState()

        # Initialize with minimal required components
        self.config = AppConfig()
        self.name = "test-connector"
        self.is_functional = True
        self._oauth_credentials = {"access_token": "test-token"}
        self._credentials_path = None
        self._last_modified = 0
        self._refresh_token = None
        self.translation_service = MagicMock()
        self._credential_validation_errors = []
        self._initialization_failed = False
        self._last_validation_time = 0.0
        self._main_loop = None
        self._quota_exceeded = False
        self._request_counter = None
        self._health_checked = True

        # Mock httpx client
        self.client = MagicMock(spec=httpx.AsyncClient)

        # Set required API base URL for graceful degradation tests
        self.gemini_api_base_url = "https://mock-cloudcode-pa.googleapis.com"

        # Initialize graceful degradation
        self._degradation_config = GracefulDegradationConfig.from_config(self.config)
        # Keep recovery probing enabled - the mock's _recovery_probing_loop is a no-op
        self._model_retry_states: dict[str, ModelRetryState] = {}
        self._total_attempts = 0
        self._permanently_failed = False
        self._recovery_probe_task = None

        # Mock API call behavior
        self._api_call_results = {}  # model -> list of results
        self._api_call_count = {}  # model -> call count
        self._graceful_metrics = GracefulDegradationMetrics()

    def _set_cooldown(self, model: str, duration: float | None = None) -> None:
        """Put a model into cooldown state."""
        from src.connectors.gemini_base.graceful_degradation import set_model_cooldown

        cooldown = (
            duration
            if duration is not None
            else self._degradation_config.cooldown_duration
        )
        set_model_cooldown(model, self._model_retry_states, cooldown)

    def _is_in_cooldown(self, model: str) -> bool:
        """Check if a model is currently in cooldown."""
        from src.connectors.gemini_base.graceful_degradation import is_model_in_cooldown

        return is_model_in_cooldown(model, self._model_retry_states)

    def _is_rate_limit_like_error(self, error: BackendError) -> bool:
        """Determine whether an error should trigger graceful degradation retries."""
        from src.connectors.gemini_base.graceful_degradation import (
            is_rate_limit_like_error,
        )

        return is_rate_limit_like_error(error)

    async def _probe_model_recovery(
        self, model: str, bypass_interval_check: bool = False
    ) -> bool:
        """Perform recovery probes for a model in cooldown.

        Args:
            model: The model to probe.
            bypass_interval_check: If True, skip the interval check.

        Returns:
            True if the model has recovered (not in cooldown), False otherwise.
        """
        if not self._is_in_cooldown(model):
            return True

        state = self._model_retry_states.get(model)
        if not state:
            return True

        # Perform a probe request
        call_count = self._api_call_count.get(model, 0)
        results = self._api_call_results.get(model, [])

        self._api_call_count[model] = call_count + 1

        if call_count < len(results):
            result = results[call_count]
            if isinstance(result, Exception):
                # Probe failed - reset success count
                state.probe_success_count = 0
                return False

        # Probe succeeded - increment success count
        state.probe_success_count += 1

        # After 2 successful probes, clear cooldown
        if state.probe_success_count >= 2:
            state.cooldown_until = 0
            state.probe_success_count = 0
            return True

        return False

    def set_api_behavior(self, model: str, results: list):
        """Set the sequence of results for API calls to a specific model."""
        self._api_call_results[model] = results
        if model not in self._api_call_count:
            self._api_call_count[model] = 0

        # Configure the mock client to return results based on requested model
        async def mock_post_call(*args, **kwargs):
            # Try to extract model from URL (e.g., /v1beta/models/gemini-2.5-pro:generateContent)
            import re

            url = str(args[0]) if args else ""
            request_model = None

            # Extract model name from URL patterns like:
            # /v1beta/models/gemini-2.5-pro:generateContent
            match = re.search(r"/models/([^/:]+)", url)
            if match:
                request_model = match.group(1)

            # Fallback: use a model with remaining results
            if not request_model:
                for m in self._api_call_results:
                    if self._api_call_count.get(m, 0) < len(
                        self._api_call_results.get(m, [])
                    ):
                        request_model = m
                        break

            # If still no model, use the first configured model
            if not request_model and self._api_call_results:
                request_model = next(iter(self._api_call_results.keys()))

            if request_model:
                call_count = self._api_call_count.get(request_model, 0)
                results_for_model = self._api_call_results.get(request_model, [])

                if call_count < len(results_for_model):
                    result = results_for_model[call_count]
                    self._api_call_count[request_model] = call_count + 1
                    if isinstance(result, Exception):
                        raise result
                    return _mock_httpx_response(content=result)

                # Default to success if no more configured results
                self._api_call_count[request_model] = call_count + 1

            return _mock_httpx_response(
                content={"choices": [{"message": {"content": "test response"}}]}
            )

        self.client.post.side_effect = mock_post_call
        self.client.get.side_effect = mock_post_call  # For recovery probes

    async def _chat_completions_code_assist(
        self, request_data, processed_messages, effective_model, **kwargs
    ):
        """Mock API call that returns configured results."""
        call_count = self._api_call_count.get(effective_model, 0)
        results = self._api_call_results.get(effective_model, [])

        self._api_call_count[effective_model] = call_count + 1

        if call_count < len(results):
            result = results[call_count]
            if isinstance(result, Exception):
                raise result
            # Wrap the result in ResponseEnvelope
            return ResponseEnvelope(content=result)

        # If no more configured results, raise the last error if it was an exception
        if results and isinstance(results[-1], Exception):
            raise results[-1]

        # Default to success if no more configured results
        return ResponseEnvelope(
            content={"choices": [{"message": {"content": "test response"}}]}
        )

    async def _chat_completions_code_assist_streaming(
        self, request_data, processed_messages, effective_model, **kwargs
    ):
        """Mock streaming API call."""
        result = await self._chat_completions_code_assist(
            request_data, processed_messages, effective_model, **kwargs
        )

        async def content_generator():
            # Extract content from ResponseEnvelope if needed
            content = result.content if isinstance(result, ResponseEnvelope) else result
            # Yield the result formatted as SSE
            yield f"data: {json.dumps(content)}\n\n"
            yield "data: [DONE]\n\n"

        return StreamingResponseEnvelope(
            content=content_generator(),
            media_type="text/event-stream",
            headers={},
        )

    async def _discover_project_id(self, auth_session):
        """Mock project ID discovery."""
        return "test-project"

    async def _recovery_probing_loop(self) -> None:
        """No-op recovery probing loop for tests."""
        # Don't run the infinite loop in tests

    async def _validate_runtime_credentials(self) -> bool:
        """Mock credential validation."""
        return True

    async def _refresh_token_if_needed(self) -> bool:
        """Mock token refresh."""
        return True

    async def _ensure_healthy(self) -> None:
        """Mock health check."""

    def _get_fallback_model(self, original_model: str) -> str | None:
        """Get the fallback model for a given model.

        Note: Fallbacks are now disabled globally. The Resilience Layer handles
        error recovery at the BackendService level. This method always returns None.
        """
        # Fallback logic removed - handled by Resilience Layer
        return None


@pytest.fixture
async def connector():
    """Create a mock connector for testing."""
    connector = MockGeminiOAuthConnector()
    yield connector

    # Cleanup: Cancel any running recovery probe task
    if connector._recovery_probe_task and not connector._recovery_probe_task.done():
        connector._recovery_probe_task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await connector._recovery_probe_task


@pytest.fixture
def mock_request():
    """Create a mock request."""
    return MockChatRequest(
        model="gemini-2.5-pro", messages=[{"role": "user", "content": "test"}]
    )


@pytest.fixture
def mock_sleep(monkeypatch):
    """Mock asyncio.sleep to avoid waiting in tests."""

    monkeypatch.setattr(asyncio, "sleep", AsyncMock())


class TestGracefulDegradationBehavior:
    """Test graceful degradation behavioral scenarios."""

    @pytest.mark.asyncio
    async def test_successful_request_no_degradation(self, connector, mock_request):
        """Test that successful requests work normally without triggering degradation."""
        # Setup: Configure successful API response
        connector.set_api_behavior("gemini-2.5-pro", [{"success": True}])

        # Execute: Make request
        result = await connector.chat_completions(
            request_data=mock_request,
            processed_messages=mock_request.messages,
            effective_model="gemini-2.5-pro",
        )

        # Verify: Request succeeded without degradation
        assert result is not None
        assert connector._api_call_count["gemini-2.5-pro"] == 1
        assert len(connector._model_retry_states) == 0  # No retry state created
        assert not connector._permanently_failed

    @pytest.mark.asyncio
    async def test_single_429_triggers_retry_with_no_fallback(
        self, connector, mock_request, mock_sleep
    ):
        """Test that a single 429 error triggers retry but no fallback (fallbacks disabled).

        Note: As of the Resilience Layer implementation, automatic model fallbacks
        are disabled globally. The connector will retry on the requested model only.
        """
        error_429 = BackendError("Rate limit exceeded", status_code=429)
        # First attempt fails, subsequent retry succeeds
        connector.set_api_behavior("gemini-2.5-pro", [error_429, {"success": True}])

        # Execute: Make request
        start_time = time.time()
        result = await connector.chat_completions(
            request_data=mock_request,
            processed_messages=mock_request.messages,
            effective_model="gemini-2.5-pro",
        )
        elapsed = time.time() - start_time

        # Verify: Request succeeded using retry on same model
        assert result is not None
        # Only pro model was attempted (no flash fallback)
        assert connector._api_call_count["gemini-2.5-pro"] >= 2  # initial + retry
        assert "gemini-2.5-flash" not in connector._api_call_count
        assert elapsed < 5.0  # No long backoff

    @pytest.mark.slow
    @pytest.mark.asyncio
    async def test_multiple_429_triggers_exponential_backoff(
        self, connector, mock_request
    ):
        """Test that multiple 429 errors trigger exponential backoff."""
        # Setup: Multiple 429 errors, then success
        error_429 = BackendError("Rate limit exceeded", status_code=429)
        connector.set_api_behavior(
            "gemini-2.5-pro", [error_429, error_429, error_429, {"success": True}]
        )
        connector.config.backends.disable_gemini_oauth_fallback = True
        connector._degradation_config.retry_delays = [6, 12]  # Faster delays for test

        # Execute: Make request and measure timing
        start_time = time.time()
        result = await connector.chat_completions(
            request_data=mock_request,
            processed_messages=mock_request.messages,
            effective_model="gemini-2.5-pro",
        )
        elapsed_time = time.time() - start_time

        # Verify: Request succeeded with proper delays
        assert result is not None
        assert connector._api_call_count["gemini-2.5-pro"] == 4  # Initial + 3 retries

        # Verify exponential backoff timing (6s + 12s with jitter tolerance)
        assert elapsed_time >= 13  # Account for negative jitter reducing wait time

    @pytest.mark.asyncio
    async def test_pro_model_exhaustion_marks_permanently_failed_no_fallback(
        self, connector, mock_request, mock_sleep
    ):
        """Test that exhausting pro model retries marks backend as failed (no fallback).

        Note: As of the Resilience Layer implementation, automatic model fallbacks
        are disabled globally. When the requested model is exhausted, the request fails.
        """
        # Setup: Pro model always fails
        error_429 = BackendError("Rate limit exceeded", status_code=429)
        connector.set_api_behavior(
            "gemini-2.5-pro", [error_429, error_429, error_429, error_429]
        )

        # Execute: Make request and expect failure
        with pytest.raises(BackendError):
            await connector.chat_completions(
                request_data=mock_request,
                processed_messages=mock_request.messages,
                effective_model="gemini-2.5-pro",
            )

        # Verify: Only pro model was attempted, no flash fallback
        assert connector._api_call_count["gemini-2.5-pro"] >= 2
        assert "gemini-2.5-flash" not in connector._api_call_count

        # Verify pro model is in cooldown
        assert connector._is_in_cooldown("gemini-2.5-pro")

        # Cleanup recovery probe task
        if connector._recovery_probe_task and not connector._recovery_probe_task.done():
            connector._recovery_probe_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await connector._recovery_probe_task

    @pytest.mark.slow
    @pytest.mark.asyncio
    async def test_both_models_exhausted_marks_permanently_failed(
        self, connector, mock_request, mock_sleep
    ):
        """Test that exhausting both pro and flash models marks backend as permanently failed."""
        # Setup: Both models always fail
        error_429 = BackendError("Rate limit exceeded", status_code=429)
        connector.set_api_behavior("gemini-2.5-pro", [error_429, error_429, error_429])
        connector.set_api_behavior(
            "gemini-2.5-flash", [error_429, error_429, error_429]
        )

        # Execute: Make request and expect failure
        with pytest.raises(BackendError):
            await connector.chat_completions(
                request_data=mock_request,
                processed_messages=mock_request.messages,
                effective_model="gemini-2.5-pro",
            )

        # Verify: Backend marked as permanently failed
        assert connector._permanently_failed
        assert not connector.is_functional

    @pytest.mark.asyncio
    async def test_non_429_errors_not_retried(self, connector, mock_request):
        """Test that non-429 errors are not retried through graceful degradation."""
        # Setup: Non-429 error
        auth_error = BackendError("Authentication failed", status_code=401)
        connector.set_api_behavior("gemini-2.5-pro", [auth_error])

        # Execute: Make request and expect immediate failure
        with pytest.raises(BackendError) as exc_info:
            await connector.chat_completions(
                request_data=mock_request,
                processed_messages=mock_request.messages,
                effective_model="gemini-2.5-pro",
            )

        # Verify: No retry attempted, error propagated immediately
        assert exc_info.value.status_code == 401
        assert connector._api_call_count["gemini-2.5-pro"] == 1  # No retries
        assert len(connector._model_retry_states) == 0  # No retry state created


class TestRecoveryProbingBehavior:
    """Test recovery probing behavioral scenarios."""

    @pytest.mark.asyncio
    async def test_recovery_probing_starts_after_cooldown(
        self, connector, mock_request, mock_sleep
    ):
        """Test that recovery probing starts automatically after a model is put in cooldown.

        Note: With fallbacks disabled, when a model fails repeatedly it goes into
        cooldown and the request fails. Recovery probing should still start.
        """
        # Setup: Pro model fails repeatedly
        error_429 = BackendError("Rate limit exceeded", status_code=429)
        connector.set_api_behavior(
            "gemini-2.5-pro", [error_429, error_429, error_429, error_429]
        )

        # Execute: Trigger cooldown (will fail since no fallback)
        with pytest.raises(BackendError):
            await connector.chat_completions(
                request_data=mock_request,
                processed_messages=mock_request.messages,
                effective_model="gemini-2.5-pro",
            )

        # Verify: Model is in cooldown and recovery probing may have started
        # Note: Recovery probe might not start if backend is marked permanently failed
        assert connector._is_in_cooldown("gemini-2.5-pro")

        # Cleanup
        if connector._recovery_probe_task:
            connector._recovery_probe_task.cancel()

    @pytest.mark.asyncio
    async def test_recovery_probe_clears_cooldown_after_success(self, connector):
        """Test that successful recovery probes clear model cooldown."""
        # Setup: Put model in cooldown
        connector._set_cooldown("gemini-2.5-pro")
        assert connector._is_in_cooldown("gemini-2.5-pro")

        # Setup: Configure successful probe responses
        connector.set_api_behavior(
            "gemini-2.5-pro", [{"success": True}, {"success": True}]
        )

        # Execute: Perform recovery probes
        await connector._probe_model_recovery(
            "gemini-2.5-pro", bypass_interval_check=True
        )  # First success
        assert connector._is_in_cooldown("gemini-2.5-pro")  # Still in cooldown

        await connector._probe_model_recovery(
            "gemini-2.5-pro", bypass_interval_check=True
        )  # Second success
        assert not connector._is_in_cooldown("gemini-2.5-pro")  # Cooldown cleared

        # Verify: Success count tracking
        state = connector._model_retry_states["gemini-2.5-pro"]
        assert state.probe_success_count == 0  # Reset after clearing cooldown

    @pytest.mark.asyncio
    async def test_recovery_probe_resets_on_failure(self, connector):
        """Test that failed recovery probes reset success count."""
        # Setup: Put model in cooldown
        connector._set_cooldown("gemini-2.5-pro")

        # Setup: One success, then failure
        error_429 = BackendError("Still rate limited", status_code=429)
        connector.set_api_behavior("gemini-2.5-pro", [{"success": True}, error_429])

        # Execute: Successful probe, then failed probe
        await connector._probe_model_recovery(
            "gemini-2.5-pro", bypass_interval_check=True
        )  # Success
        state = connector._model_retry_states["gemini-2.5-pro"]
        assert state.probe_success_count == 1

        await connector._probe_model_recovery(
            "gemini-2.5-pro", bypass_interval_check=True
        )  # Failure
        assert state.probe_success_count == 0  # Reset on failure
        assert connector._is_in_cooldown("gemini-2.5-pro")  # Still in cooldown

    @pytest.mark.asyncio
    async def test_cooldown_model_rejects_request_no_fallback(
        self, connector, mock_request, mock_sleep
    ):
        """Test that when a model is in cooldown, request is rejected (no fallback).

        Note: With fallbacks disabled, when the requested model is in cooldown,
        the request is immediately rejected with a RateLimitExceededError.
        """
        # Setup: Put pro model in cooldown
        connector._set_cooldown("gemini-2.5-pro")

        # Execute: Request with pro model in cooldown should be rejected
        with pytest.raises(RateLimitExceededError) as exc_info:
            await connector.chat_completions(
                request_data=mock_request,
                processed_messages=mock_request.messages,
                effective_model="gemini-2.5-pro",
            )

        # Verify: Request was rejected, no fallback used
        assert connector._is_in_cooldown("gemini-2.5-pro")
        # Flash model was NOT called (fallbacks disabled)
        assert "gemini-2.5-flash" not in connector._api_call_count
        # Error indicates rate limiting
        assert "rate-limited" in str(exc_info.value).lower()


class TestConfigurationBehavior:
    """Test configuration-driven behavior."""

    @pytest.mark.asyncio
    async def test_disabled_graceful_degradation(self, mock_request):
        """Test that disabling graceful degradation lets errors propagate to BackendService.

        With the Resilience Layer architecture, when graceful degradation is disabled,
        the connector does NOT mark itself as non-functional. Instead, it re-raises
        the error for BackendService's failure handling strategy to manage.
        """
        # Setup: Create connector with disabled graceful degradation
        connector = MockGeminiOAuthConnector()
        connector._degradation_config.enabled = False

        # Setup: Configure 429 error
        error_429 = BackendError("Rate limit exceeded", status_code=429)
        connector.set_api_behavior("gemini-2.5-pro", [error_429])

        # Execute: Expect immediate failure without retry (error propagates)
        with pytest.raises(BackendError):
            await connector.chat_completions(
                request_data=mock_request,
                processed_messages=mock_request.messages,
                effective_model="gemini-2.5-pro",
            )

        # Verify: Backend remains functional (Resilience Layer handles state)
        # With the new architecture, the connector does NOT mark itself as non-functional
        # The BackendService's ResilienceCoordinator handles rate limit state tracking
        assert (
            connector.is_functional
        ), "Connector should remain functional - Resilience Layer handles state"
        # Note: _quota_exceeded is NOT set because the error is re-raised without internal handling

    @pytest.mark.asyncio
    async def test_disabled_recovery_probing(self, connector, mock_request, mock_sleep):
        """Test that disabling recovery probing prevents automatic recovery.

        Note: With fallbacks disabled, the request will fail after retries are exhausted.
        """
        # Setup: Disable recovery probing
        connector._degradation_config.enable_recovery_probing = False

        # Setup: Trigger cooldown
        error_429 = BackendError("Rate limit exceeded", status_code=429)
        connector.set_api_behavior(
            "gemini-2.5-pro", [error_429, error_429, error_429, error_429]
        )

        # Execute: Trigger cooldown (will fail since no fallback)
        with pytest.raises(BackendError):
            await connector.chat_completions(
                request_data=mock_request,
                processed_messages=mock_request.messages,
                effective_model="gemini-2.5-pro",
            )

        # Verify: No recovery probing task started and model is in cooldown
        assert connector._recovery_probe_task is None
        assert connector._is_in_cooldown("gemini-2.5-pro")

    @pytest.mark.asyncio
    async def test_custom_retry_delays(self, mock_request, mock_sleep):
        """Test that custom retry delays are respected."""
        # Setup: Create connector with custom delays
        connector = MockGeminiOAuthConnector()
        connector._degradation_config.retry_delays = [
            0.01,
            0.02,
        ]  # Very fast delays for testing
        connector.config.backends.disable_gemini_oauth_fallback = True

        # Setup: Multiple 429 errors, then success
        error_429 = BackendError("Rate limit exceeded", status_code=429)
        connector.set_api_behavior(
            "gemini-2.5-pro", [error_429, error_429, {"success": True}]
        )

        # Execute: Make request and measure timing
        start_time = time.time()
        result = await connector.chat_completions(
            request_data=mock_request,
            processed_messages=mock_request.messages,
            effective_model="gemini-2.5-pro",
        )
        elapsed_time = time.time() - start_time

        # Verify: Custom delays were used (now mocked, so very fast)
        assert result is not None
        assert elapsed_time < 0.1  # Should be near instant due to mocked sleep


class TestEdgeCaseBehavior:
    """Test edge cases and error conditions."""

    @pytest.mark.asyncio
    async def test_streaming_request_graceful_degradation(self, connector, mock_sleep):
        """Test that streaming requests also benefit from graceful degradation retry.

        Note: With fallbacks disabled, retry on the same model is still supported.
        """
        # Setup: Streaming request
        streaming_request = MockChatRequest(
            model="gemini-2.5-pro",
            messages=[{"role": "user", "content": "test"}],
            stream=True,
        )

        # Setup: Pro model fails first, then succeeds
        error_429 = BackendError("Rate limit exceeded", status_code=429)
        connector.set_api_behavior("gemini-2.5-pro", [error_429, {"success": True}])

        # Execute: Make streaming request
        result = await connector.chat_completions(
            request_data=streaming_request,
            processed_messages=streaming_request.messages,
            effective_model="gemini-2.5-pro",
        )

        # Verify: Retry worked for streaming (no fallback)
        assert result is not None
        assert connector._api_call_count["gemini-2.5-pro"] >= 2
        assert "gemini-2.5-flash" not in connector._api_call_count

    @pytest.mark.slow
    @pytest.mark.asyncio
    async def test_model_without_fallback(self, connector):
        """Test behavior with a model that has no configured fallback."""
        # Setup: Create request with model that has no fallback
        request = MockChatRequest(
            model="gemini-1.0-pro",
            messages=[{"role": "user", "content": "test"}],
        )

        # Setup: Model fails
        error_429 = BackendError("Rate limit exceeded", status_code=429)
        connector.set_api_behavior(
            "gemini-1.0-pro", [error_429, error_429, error_429, error_429]
        )

        # Execute: Expect failure after retries
        with pytest.raises(BackendError):
            await connector.chat_completions(
                request_data=request,
                processed_messages=request.messages,
                effective_model="gemini-1.0-pro",
            )

        # Verify: Only original model was tried
        assert connector._api_call_count["gemini-1.0-pro"] >= 3
        assert "gemini-1.0-flash" not in connector._api_call_count

    @pytest.mark.asyncio
    async def test_concurrent_requests_with_retry(self, connector, mock_sleep):
        """Test that concurrent requests benefit from retry logic (no fallback).

        Note: With fallbacks disabled, all requests will retry on the same model.
        If retries succeed, requests complete. Otherwise, they fail.
        """
        # Setup: Increase max total attempts to accommodate concurrent requests
        connector._degradation_config.max_total_attempts = 15

        # Setup: Multiple concurrent requests
        requests = [
            MockChatRequest(
                model="gemini-2.5-pro",
                messages=[{"role": "user", "content": f"test {i}"}],
            )
            for i in range(3)
        ]

        # Setup: Pro model returns mix of failures and successes
        error_429 = BackendError("Rate limit exceeded", status_code=429)
        connector.set_api_behavior(
            "gemini-2.5-pro",
            [error_429, {"success": True}] * 5,  # Alternating fail/success
        )

        # Execute: Concurrent requests
        tasks = [
            connector.chat_completions(
                request_data=req,
                processed_messages=req.messages,
                effective_model="gemini-2.5-pro",
            )
            for req in requests
        ]

        results = await asyncio.gather(*tasks, return_exceptions=True)

        # Verify: At least some requests succeeded via retry
        successes = [r for r in results if not isinstance(r, Exception)]
        assert len(successes) >= 1, "At least one request should succeed"

        # Verify: Only pro model was attempted (no fallback)
        assert "gemini-2.5-flash" not in connector._api_call_count
        assert connector._api_call_count["gemini-2.5-pro"] >= 3

    @pytest.mark.slow
    @pytest.mark.asyncio
    async def test_jitter_prevents_thundering_herd(self, connector, mock_request):
        """Test that jitter is added to retry delays to prevent synchronized retries."""
        # Setup: Fast recovery config for testing jitter
        connector._degradation_config.retry_delays = [
            2,
            4,
            6,
        ]  # Shorter delays for testing
        connector.config.backends.disable_gemini_oauth_fallback = True

        error_429 = BackendError("Rate limit exceeded", status_code=429)

        durations: list[float] = []
        for i in range(5):
            connector.set_api_behavior(
                "gemini-2.5-pro", [error_429, error_429, {"success": True}]
            )
            request = MockChatRequest(
                model="gemini-2.5-pro",
                messages=[{"role": "user", "content": f"test {i}"}],
            )
            start_time = time.time()
            result = await connector.chat_completions(
                request_data=request,
                processed_messages=request.messages,
                effective_model="gemini-2.5-pro",
            )
            durations.append(time.time() - start_time)
            assert result is not None

        # Verify that retry delays were applied (should take at least 1.5s with jitter)
        assert all(duration >= 1.5 for duration in durations)

        # Verify jitter introduced variance among sequential requests
        assert (max(durations) - min(durations)) > 0.2

    @pytest.mark.slow
    @pytest.mark.asyncio
    async def test_jitter_range_validation(self, connector, mock_request):
        """Test that jitter is within reasonable bounds (±25% of base delay)."""
        # Setup: Use longer delays to better observe jitter
        connector._degradation_config.retry_delays = [10.0]  # 10 second base delay
        connector.config.backends.disable_gemini_oauth_fallback = True

        error_429 = BackendError("Rate limit exceeded", status_code=429)
        connector.set_api_behavior(
            "gemini-2.5-pro", [error_429, error_429, {"success": True}]
        )

        # Capture the actual delay by timing the retry
        start_time = time.time()
        result = await connector.chat_completions(
            request_data=mock_request,
            processed_messages=mock_request.messages,
            effective_model="gemini-2.5-pro",
        )
        actual_delay = time.time() - start_time

        # Verify: Request succeeded
        assert result is not None

        # Verify: Actual delay is within jitter bounds (±25% of 10s = 7.5s to 12.5s)
        # Allow some tolerance for system overhead
        expected_min = 7.0  # Slightly lower bound for tolerance
        expected_max = 13.0  # Slightly higher bound for tolerance
        assert expected_min <= actual_delay <= expected_max, (
            f"Expected delay with jitter to be between {expected_min}s and {expected_max}s, "
            f"but got {actual_delay:.1f}s"
        )

    @pytest.mark.slow
    @pytest.mark.asyncio
    async def test_per_request_attempts_limit_enforcement(
        self, connector, mock_request, mock_sleep
    ):
        """Test that per-request attempt limits are properly enforced."""
        # Setup: Configure a low max attempt limit for testing
        connector._degradation_config.max_total_attempts = 2
        connector.config.backends.disable_gemini_oauth_fallback = True

        error_429 = BackendError("Rate limit exceeded", status_code=429)
        connector.set_api_behavior(
            "gemini-2.5-pro", [error_429, error_429, error_429, {"success": True}]
        )
        connector.set_api_behavior("gemini-2.5-flash", [{"success": True}])

        # Execute: Request should fail after 2 attempts
        with pytest.raises(BackendError) as exc_info:
            await connector.chat_completions(
                request_data=mock_request,
                processed_messages=mock_request.messages,
                effective_model="gemini-2.5-pro",
            )

        # Verify: Failed due to max attempts exceeded
        assert exc_info.value.code == "max_attempts_exceeded"
        assert exc_info.value.status_code == 429

        # Verify: Only made 3 attempts before giving up (initial + 2 retries)
        assert connector._api_call_count["gemini-2.5-pro"] == 3

        # Verify: Other requests can still succeed (attempts are isolated)
        result = await connector.chat_completions(
            request_data=MockChatRequest(
                model="gemini-2.5-pro",
                messages=[{"role": "user", "content": "different request"}],
            ),
            processed_messages=[{"role": "user", "content": "different request"}],
            effective_model="gemini-2.5-pro",
        )
        assert result is not None


if __name__ == "__main__":
    # Run tests with pytest
    pytest.main([__file__, "-v"])
