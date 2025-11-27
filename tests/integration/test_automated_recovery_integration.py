"""
Integration test for automated recovery system.

This test demonstrates the complete automated recovery functionality
with real-world timing to prove the system works as intended.
"""

import asyncio
import contextlib
import time
from dataclasses import dataclass
from unittest.mock import MagicMock

import pytest
from src.connectors.gemini_oauth_base import (
    GeminiOAuthBaseConnector,
    GracefulDegradationConfig,
    GracefulDegradationMetrics,
    ModelRetryState,
)
from src.core.common.exceptions import BackendError
from src.core.config.app_config import AppConfig

pytestmark = pytest.mark.integration


@dataclass
class MockChatRequest:
    """Mock chat request for testing."""

    model: str
    messages: list
    stream: bool = False
    max_tokens: int = 100
    temperature: float = 0.0


class MockGeminiOAuthConnector(GeminiOAuthBaseConnector):
    """Mock connector that simulates real API behavior for recovery testing."""

    def __init__(self, fast_recovery=False):
        # Initialize with minimal required components
        self.config = AppConfig()
        self.name = "recovery-test-connector"
        self.is_functional = True
        self._oauth_credentials = {"access_token": "test-token"}
        self._credentials_path = None
        self._last_modified = 0
        self._refresh_token = None
        self._token_refresh_lock = asyncio.Lock()
        self.translation_service = MagicMock()
        self._file_observer = None
        self._credential_validation_errors = []
        self._initialization_failed = False
        self._last_validation_time = 0.0
        self._pending_reload_task = None
        self._reload_task_lock = asyncio.Lock()
        self._reload_scheduling_in_progress = False
        self._last_cli_refresh_attempt = 0.0
        self._cli_refresh_process = None
        self._main_loop = None
        self._quota_exceeded = False
        self._request_counter = None
        self._health_checked = True

        # Initialize graceful degradation metrics and configuration
        self._graceful_metrics = GracefulDegradationMetrics()
        self._degradation_config = GracefulDegradationConfig.from_config(self.config)
        if fast_recovery:
            # Speed up for testing
            self._degradation_config.retry_delays = [1, 2, 4]
            self._degradation_config.cooldown_duration = 10.0
            self._degradation_config.recovery_probe_interval = 3.0

        self._model_retry_states: dict[str, ModelRetryState] = {}
        self._total_attempts = 0
        self._permanently_failed = False
        self._recovery_probe_task = None

        # Mock API call behavior
        self._api_call_results = {}
        self._api_call_count = {}
        self._recovery_timeline = {}  # Track recovery timeline
        self._fast_recovery = fast_recovery

    def set_api_behavior(self, model: str, results: list):
        """Set the sequence of results for API calls to a specific model."""
        self._api_call_results[model] = results
        self._api_call_count[model] = 0

    def set_recovery_timeline(self, model: str, recovery_time: float):
        """Set when a model should recover (simulates quota reset)."""
        self._recovery_timeline[model] = recovery_time

    async def _chat_completions_code_assist(
        self, request_data, processed_messages, effective_model, **kwargs
    ):
        """Mock API call that simulates real recovery behavior."""
        call_count = self._api_call_count.get(effective_model, 0)
        self._api_call_count[effective_model] = call_count + 1

        # Check if model should recover based on timeline
        recovery_time = self._recovery_timeline.get(effective_model, float("inf"))
        current_time = time.time()
        should_recover = current_time >= recovery_time

        results = self._api_call_results.get(
            effective_model, [BackendError("No results configured", status_code=500)]
        )

        if should_recover and call_count >= len(results):
            # Model has recovered, return success
            return {
                "choices": [
                    {
                        "message": {
                            "content": f"Recovered response from {effective_model}"
                        }
                    }
                ]
            }

        if call_count < len(results):
            result = results[call_count]
            if isinstance(result, Exception):
                raise result
            return result

        # If no more configured results and haven't recovered, raise 429
        raise BackendError(
            f"Rate limit exceeded for {effective_model}", status_code=429
        )

    async def _chat_completions_code_assist_streaming(
        self, request_data, processed_messages, effective_model, **kwargs
    ):
        """Mock streaming API call."""
        return await self._chat_completions_code_assist(
            request_data, processed_messages, effective_model, **kwargs
        )

    async def _discover_project_id(self, auth_session):
        """Mock project ID discovery."""
        return "recovery-test-project"


@pytest.fixture
async def connector():
    """Create a mock connector for recovery testing."""
    connector = MockGeminiOAuthConnector(fast_recovery=True)
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
        model="gemini-2.5-pro", messages=[{"role": "user", "content": "test recovery"}]
    )


class TestAutomatedRecoveryIntegration:
    """Integration tests for automated recovery system."""

    @pytest.mark.asyncio
    async def test_complete_automated_recovery_scenario(self, connector, mock_request):
        """
        Test complete automated recovery scenario:
        1. Pro model hits rate limit and goes into cooldown
        2. Flash model is used as fallback
        3. Automated recovery probes detect when pro model is available
        4. Pro model automatically comes back online
        5. Subsequent requests use pro model again
        """
        events = []
        recovery_times = {}

        def track_event(event_name):
            events.append((event_name, time.time()))
            print(f"[{time.time():.1f}] {event_name}")

        track_event("test_start")

        # Setup: Pro model fails initially, recovers after 8 seconds
        current_time = time.time()
        pro_recovery_time = current_time + 8.0  # Recovers after 8 seconds

        error_429 = BackendError("Rate limit exceeded", status_code=429)
        connector.set_api_behavior("gemini-2.5-pro", [error_429, error_429, error_429])
        connector.set_api_behavior("gemini-2.5-flash", [{"success": True}])
        connector.set_recovery_timeline("gemini-2.5-pro", pro_recovery_time)

        track_event("configuration_complete")

        # Stage 1: Request pro model - graceful degradation should fallback to flash
        # With graceful degradation, pro fails but flash succeeds as fallback
        result = await connector.chat_completions(
            request_data=mock_request,
            processed_messages=mock_request.messages,
            effective_model="gemini-2.5-pro",
        )
        # Graceful degradation succeeded with fallback
        assert result is not None
        track_event("pro_model_fallback_to_flash")

        # Verify pro model is in cooldown and recovery probing started
        assert connector._is_in_cooldown("gemini-2.5-pro")
        assert connector._recovery_probe_task is not None
        assert not connector._recovery_probe_task.done()

        track_event("recovery_probing_started")

        # Stage 2: Subsequent request should still use flash fallback (pro in cooldown)
        # Flash was already used once, so we need to add more successful results
        connector.set_api_behavior(
            "gemini-2.5-flash", [{"success": True}, {"success": True}]
        )
        result = await connector.chat_completions(
            request_data=mock_request,
            processed_messages=mock_request.messages,
            effective_model="gemini-2.5-pro",
        )
        assert result is not None
        # Flash should have been called (first from graceful degradation, second from this call)
        assert connector._api_call_count["gemini-2.5-flash"] >= 1
        track_event("flash_fallback_used")

        # Stage 3: Wait for automated recovery (should happen automatically)
        max_wait_time = 15  # seconds
        recovery_start = time.time()

        while (
            connector._is_in_cooldown("gemini-2.5-pro")
            and (time.time() - recovery_start) < max_wait_time
        ):
            await asyncio.sleep(0.5)

        recovery_time = time.time() - recovery_start
        recovery_times["pro_model"] = recovery_time

        track_event(f"pro_model_recovered_after_{recovery_time:.1f}s")

        # Verify pro model is no longer in cooldown
        assert not connector._is_in_cooldown("gemini-2.5-pro")

        # Stage 4: Subsequent request should use pro model again
        result = await connector.chat_completions(
            request_data=mock_request,
            processed_messages=mock_request.messages,
            effective_model="gemini-2.5-pro",
        )
        assert result is not None

        # Verify this used the recovered pro model
        pro_calls = connector._api_call_count.get("gemini-2.5-pro", 0)
        assert pro_calls >= 4  # Initial failures + recovery probes + final success

        track_event("pro_model_working_normally")

        # Stage 5: Verify recovery timeline is reasonable
        # Should have recovered around the 8-second mark we configured
        assert 7.0 <= recovery_times["pro_model"] <= 12.0  # Allow some tolerance

        # Verify event sequence
        event_names = [event[0] for event in events]
        expected_events = [
            "test_start",
            "configuration_complete",
            "pro_model_fallback_to_flash",
            "recovery_probing_started",
            "flash_fallback_used",
            "pro_model_recovered_after_",
            "pro_model_working_normally",
        ]

        for i, expected_event in enumerate(expected_events):
            if "after_" in expected_event:
                # Partial match for timed events
                assert any(
                    expected_event.replace("after_", "").split("_")[0] in event
                    for event in event_names[i : i + 3]
                )
            else:
                assert (
                    expected_event in event_names[i : i + 3]
                ), f"Expected {expected_event} around position {i}"

        # Verify recovery system is still active
        assert connector._recovery_probe_task is not None
        assert not connector._permanently_failed
        assert connector.is_functional

        track_event("test_completed_successfully")

    @pytest.mark.slow
    @pytest.mark.timeout(120)
    @pytest.mark.asyncio
    async def test_recovery_system_resilience(self, connector, mock_request):
        """
        Test that the recovery system is resilient to multiple failures
        and can handle repeated cooldown/recovery cycles.
        """
        events = []

        def track_event(event_name):
            events.append((event_name, time.time()))
            print(f"[{time.time():.1f}] {event_name}")

        track_event("resilience_test_start")

        # Setup: Multiple failure/recovery cycles
        current_time = time.time()

        # Cycle 1: Fail now, recover at 3s (before first recovery probe)
        # With fast_recovery mode: cooldown=10s, probe_interval=3s
        connector.set_recovery_timeline("gemini-2.5-pro", current_time + 3.0)

        error_429 = BackendError("Rate limit exceeded", status_code=429)
        # Only one error for initial failure, then recovery probes will succeed
        connector.set_api_behavior("gemini-2.5-pro", [error_429])
        connector.set_api_behavior("gemini-2.5-flash", [{"success": True}] * 10)

        track_event("cycle_1_start")

        # Cycle 1: Trigger cooldown - graceful degradation will fallback to flash
        result = await connector.chat_completions(
            request_data=mock_request,
            processed_messages=mock_request.messages,
            effective_model="gemini-2.5-pro",
        )
        # Graceful degradation succeeds with flash fallback
        assert result is not None

        assert connector._is_in_cooldown("gemini-2.5-pro")
        track_event("cycle_1_cooldown")

        # Wait for recovery probes to detect recovery (need 2 successful probes)
        # Probes run every 3s, need ~6s for 2 successful probes after recovery timeline
        await asyncio.sleep(8)
        assert not connector._is_in_cooldown("gemini-2.5-pro")
        track_event("cycle_1_recovered")

        # Cycle 2: Trigger another cooldown immediately after recovery
        # Update recovery timeline for second cycle
        connector.set_recovery_timeline("gemini-2.5-pro", time.time() + 3.0)

        # Reset API behavior for second cycle - only one error for initial failure
        connector._api_call_count["gemini-2.5-pro"] = 0
        connector.set_api_behavior("gemini-2.5-pro", [error_429])

        # Graceful degradation will fallback to flash
        result = await connector.chat_completions(
            request_data=mock_request,
            processed_messages=mock_request.messages,
            effective_model="gemini-2.5-pro",
        )
        assert result is not None

        assert connector._is_in_cooldown("gemini-2.5-pro")
        track_event("cycle_2_cooldown")

        # Wait for recovery probes to detect recovery
        await asyncio.sleep(8)
        assert not connector._is_in_cooldown("gemini-2.5-pro")
        track_event("cycle_2_recovered")

        # Verify system is still functional after multiple cycles
        result = await connector.chat_completions(
            request_data=mock_request,
            processed_messages=mock_request.messages,
            effective_model="gemini-2.5-pro",
        )
        assert result is not None
        track_event("final_request_succeeded")

        # Verify resilience
        assert not connector._permanently_failed
        assert connector.is_functional
        assert connector._recovery_probe_task is not None

        # Should have used flash fallback during cooldowns
        flash_calls = connector._api_call_count.get("gemini-2.5-flash", 0)
        assert flash_calls >= 2  # Should have used flash in both cycles

        track_event("resilience_test_passed")

    @pytest.mark.slow
    @pytest.mark.timeout(180)
    @pytest.mark.asyncio
    async def test_recovery_with_new_configuration(self, connector, mock_request):
        """
        Test recovery behavior with the new increased configuration:
        - 15s, 30s, 60s retry delays
        - 9 max attempts
        - 10 minute cooldown
        - 2 minute recovery probe interval
        """
        # Override fast recovery for this test to use new real configuration
        connector._fast_recovery = False
        connector._degradation_config = GracefulDegradationConfig.from_config(
            connector.config
        )

        events = []

        def track_event(event_name):
            events.append((event_name, time.time()))
            print(f"[{time.time():.1f}] {event_name}")

        track_event("new_config_test_start")

        # Verify new configuration is loaded
        assert connector._degradation_config.retry_delays == [15, 30, 60]
        assert connector._degradation_config.max_total_attempts == 9
        assert connector._degradation_config.cooldown_duration == 600.0
        assert connector._degradation_config.recovery_probe_interval == 120.0

        track_event("new_config_verified")

        # Setup: Pro model fails initially, recovers after 5 seconds (for faster testing)
        current_time = time.time()
        connector.set_recovery_timeline("gemini-2.5-pro", current_time + 5.0)

        error_429 = BackendError("Rate limit exceeded", status_code=429)
        # Only one error so recovery probes can succeed after timeline
        connector.set_api_behavior("gemini-2.5-pro", [error_429])
        connector.set_api_behavior("gemini-2.5-flash", [{"success": True}])

        track_event("api_behavior_configured")

        # Trigger cooldown - graceful degradation will fallback to flash
        result = await connector.chat_completions(
            request_data=mock_request,
            processed_messages=mock_request.messages,
            effective_model="gemini-2.5-pro",
        )
        assert result is not None  # Flash fallback succeeded

        # Verify cooldown duration is 10 minutes
        pro_state = connector._model_retry_states["gemini-2.5-pro"]
        expected_cooldown_end = time.time() + 600.0
        actual_cooldown_end = pro_state.cooldown_until
        assert abs(actual_cooldown_end - expected_cooldown_end) < 5.0

        track_event("cooldown_duration_verified")

        # Verify recovery probe interval is 2 minutes
        assert connector._degradation_config.recovery_probe_interval == 120.0

        # Wait for recovery timeline (5 seconds) then manually trigger probes
        await asyncio.sleep(6)

        # Manual recovery probe (simulating the background task)
        # First probe should succeed but return False (need 2 probes for full recovery)
        recovery_success = await connector._probe_model_recovery(
            "gemini-2.5-pro", bypass_interval_check=True
        )
        # First probe returns False (probe succeeded but need 2 for full recovery)
        # Check that probe_success_count was incremented
        pro_state = connector._model_retry_states["gemini-2.5-pro"]
        assert pro_state.probe_success_count == 1

        # Second probe should clear cooldown (need 2 successful probes)
        recovery_success = await connector._probe_model_recovery(
            "gemini-2.5-pro", bypass_interval_check=True
        )
        assert recovery_success
        assert not connector._is_in_cooldown("gemini-2.5-pro")

        track_event("recovery_probes_successful")

        # Verify recovered model works
        result = await connector.chat_completions(
            request_data=mock_request,
            processed_messages=mock_request.messages,
            effective_model="gemini-2.5-pro",
        )
        assert result is not None

        track_event("new_config_test_completed")

        # Verify all configuration values were properly applied
        event_names = [event[0] for event in events]
        assert "new_config_verified" in event_names
        assert "cooldown_duration_verified" in event_names
        assert "recovery_probes_successful" in event_names


if __name__ == "__main__":
    # Run tests with pytest
    pytest.main([__file__, "-v", "-s"])
