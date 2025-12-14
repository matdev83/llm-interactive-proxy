"""Behavioral tests for failure handling strategy.

These tests verify the end-to-end behavior of the failure handling strategy
in realistic scenarios.
"""

from __future__ import annotations

import asyncio
from unittest.mock import MagicMock

import pytest
from src.core.common.exceptions import BackendError, RateLimitExceededError
from src.core.interfaces.failure_strategy_interface import (
    FailureDecision,
    FailureHandlingConfig,
)
from src.core.services.failure_handling_strategy import DefaultFailureHandlingStrategy


class TestFailoverScenarios:
    """Tests for failover behavior in realistic scenarios."""

    @pytest.fixture
    def config(self) -> FailureHandlingConfig:
        """Create test configuration with shorter timeouts."""
        return FailureHandlingConfig(
            max_silent_wait=5.0,  # Shorter for testing
            total_timeout_budget=15.0,
            keepalive_interval=1.0,
            max_failover_hops=3,
            min_retry_wait=0.1,
        )

    @pytest.fixture
    def mock_discovery(self) -> MagicMock:
        """Create mock backend discovery."""
        discovery = MagicMock()
        discovery.find_alternative_instances.return_value = []
        return discovery

    @pytest.fixture
    def strategy(
        self, config: FailureHandlingConfig, mock_discovery: MagicMock
    ) -> DefaultFailureHandlingStrategy:
        """Create strategy with test config."""
        return DefaultFailureHandlingStrategy(
            config=config,
            backend_discovery=mock_discovery,
        )

    def test_single_backend_short_429_waits_and_retries(
        self, strategy: DefaultFailureHandlingStrategy
    ) -> None:
        """Single backend with short 429 should wait and retry."""
        error = RateLimitExceededError(
            "Rate limit",
            details={"retry_after": 2.0},
        )

        result = strategy.decide(
            error=error,
            model="openai/gpt-4o",
            current_backend="openai.1",
            attempted_backends=[],
            elapsed_time=0.0,
            is_streaming=False,
            content_started=False,
        )

        assert result.decision == FailureDecision.WAIT_AND_RETRY
        assert result.wait_seconds is not None
        assert result.wait_seconds <= 5.0  # Within max_silent_wait

    def test_multiple_backends_failover_chain(
        self,
        strategy: DefaultFailureHandlingStrategy,
        mock_discovery: MagicMock,
    ) -> None:
        """Multiple backends should be tried in sequence."""
        # Setup: 3 backends available
        mock_discovery.find_alternative_instances.side_effect = [
            ["openai.2", "openai.3"],  # First call
            ["openai.3"],  # After openai.2 tried
            [],  # After openai.3 tried
        ]

        error = BackendError("Server error", status_code=500)

        # First failure -> failover to openai.2
        result1 = strategy.decide(
            error=error,
            model="openai/gpt-4o",
            current_backend="openai.1",
            attempted_backends=[],
            elapsed_time=0.0,
            is_streaming=False,
            content_started=False,
        )
        assert result1.decision == FailureDecision.FAILOVER_IMMEDIATE
        assert result1.next_backend == "openai.2"

        # Second failure -> failover to openai.3
        result2 = strategy.decide(
            error=error,
            model="openai/gpt-4o",
            current_backend="openai.2",
            attempted_backends=["openai.1"],
            elapsed_time=1.0,
            is_streaming=False,
            content_started=False,
        )
        assert result2.decision == FailureDecision.FAILOVER_IMMEDIATE
        assert result2.next_backend == "openai.3"

        # Third failure -> no more backends, surface error
        result3 = strategy.decide(
            error=error,
            model="openai/gpt-4o",
            current_backend="openai.3",
            attempted_backends=["openai.1", "openai.2"],
            elapsed_time=2.0,
            is_streaming=False,
            content_started=False,
        )
        assert result3.decision == FailureDecision.SURFACE_ERROR

    def test_long_retry_triggers_failover(
        self,
        strategy: DefaultFailureHandlingStrategy,
        mock_discovery: MagicMock,
    ) -> None:
        """Long retry-after should trigger failover instead of waiting."""
        mock_discovery.find_alternative_instances.return_value = ["openai.2"]

        error = RateLimitExceededError(
            "Rate limit",
            details={"retry_after": 60.0},  # > max_silent_wait
        )

        result = strategy.decide(
            error=error,
            model="openai/gpt-4o",
            current_backend="openai.1",
            attempted_backends=[],
            elapsed_time=0.0,
            is_streaming=False,
            content_started=False,
        )

        # Should failover instead of waiting 60s
        assert result.decision == FailureDecision.FAILOVER_IMMEDIATE
        assert result.next_backend == "openai.2"

    def test_timeout_budget_exhaustion(
        self, strategy: DefaultFailureHandlingStrategy
    ) -> None:
        """Timeout budget should prevent infinite retries."""
        error = RateLimitExceededError(
            "Rate limit",
            details={"retry_after": 3.0},
        )

        # First attempt - should wait
        result1 = strategy.decide(
            error=error,
            model="openai/gpt-4o",
            current_backend="openai.1",
            attempted_backends=[],
            elapsed_time=0.0,
            is_streaming=False,
            content_started=False,
        )
        assert result1.decision == FailureDecision.WAIT_AND_RETRY

        # Near budget exhaustion - should surface error
        result2 = strategy.decide(
            error=error,
            model="openai/gpt-4o",
            current_backend="openai.1",
            attempted_backends=[],
            elapsed_time=14.0,  # > total_timeout_budget - retry_after
            is_streaming=False,
            content_started=False,
        )
        assert result2.decision == FailureDecision.SURFACE_ERROR


class TestStreamingBehavior:
    """Tests for streaming-specific behavior."""

    @pytest.fixture
    def strategy(self) -> DefaultFailureHandlingStrategy:
        """Create strategy for streaming tests."""
        return DefaultFailureHandlingStrategy(
            config=FailureHandlingConfig(
                max_silent_wait=10.0,
                total_timeout_budget=30.0,
            )
        )

    def test_streaming_without_content_can_failover(
        self, strategy: DefaultFailureHandlingStrategy
    ) -> None:
        """Streaming request without content started can failover."""
        error = BackendError("Error", status_code=500)

        result = strategy.decide(
            error=error,
            model="openai/gpt-4o",
            current_backend="openai.1",
            attempted_backends=[],
            elapsed_time=0.0,
            is_streaming=True,
            content_started=False,
            available_backends=["openai.2"],
        )

        assert result.decision == FailureDecision.FAILOVER_IMMEDIATE

    def test_streaming_with_content_cannot_failover(
        self, strategy: DefaultFailureHandlingStrategy
    ) -> None:
        """Streaming request with content started cannot failover."""
        error = BackendError("Error", status_code=500)

        result = strategy.decide(
            error=error,
            model="openai/gpt-4o",
            current_backend="openai.1",
            attempted_backends=[],
            elapsed_time=0.0,
            is_streaming=True,
            content_started=True,  # Content already sent
            available_backends=["openai.2"],
        )

        # Must surface error, can't restart stream
        assert result.decision == FailureDecision.SURFACE_ERROR


class TestKeepAliveGeneration:
    """Tests for keepalive chunk generation."""

    @pytest.mark.asyncio
    async def test_keepalive_chunks_generated_at_interval(self) -> None:
        """Keepalive chunks should be generated at configured interval."""
        from src.core.services.streaming_keepalive import generate_keepalive_chunks

        chunks = []
        start = asyncio.get_event_loop().time()

        async for chunk in generate_keepalive_chunks(
            interval_seconds=0.1,
            total_duration=0.35,
        ):
            chunks.append(chunk)

        elapsed = asyncio.get_event_loop().time() - start

        # Should have generated 3 or 4 chunks depending on timing
        assert len(chunks) in (3, 4)
        assert elapsed >= 0.3
        # Check that chunks are marked as keepalive in metadata
        assert all(chunk.metadata.get("_keepalive") for chunk in chunks)

    @pytest.mark.asyncio
    async def test_keepalive_with_status(self) -> None:
        """Keepalive with status should include countdown."""
        from src.core.services.streaming_keepalive import generate_keepalive_with_status

        chunks = []
        async for chunk in generate_keepalive_with_status(
            wait_seconds=0.25,
            interval_seconds=0.1,
        ):
            chunks.append(chunk)

        # Should have status hints
        assert len(chunks) >= 2
        # Check that metadata is present
        assert all(chunk.metadata.get("_keepalive") for chunk in chunks)
        # Note: Previous check for 'retry' string in content is removed as
        # keepalive mechanism now returns structured ProcessedResponse objects
        # without embedded status text in content.


class TestBackendDiscoveryIntegration:
    """Tests for backend discovery integration."""

    def test_discovery_excludes_attempted_backends(self) -> None:
        """Discovery should exclude already-attempted backends."""
        mock_discovery = MagicMock()
        mock_discovery.find_alternative_instances.return_value = ["openai.3"]

        strategy = DefaultFailureHandlingStrategy(
            config=FailureHandlingConfig(),
            backend_discovery=mock_discovery,
        )

        error = BackendError("Error", status_code=500)

        strategy.decide(
            error=error,
            model="openai/gpt-4o",
            current_backend="openai.2",
            attempted_backends=["openai.1"],
            elapsed_time=0.0,
            is_streaming=False,
            content_started=False,
        )

        # Verify discovery was called with exclusion list
        mock_discovery.find_alternative_instances.assert_called_once()
        call_args = mock_discovery.find_alternative_instances.call_args
        exclude_list = call_args[0][1]
        assert "openai.1" in exclude_list
        assert "openai.2" in exclude_list


class TestEdgeCases:
    """Tests for edge cases and boundary conditions."""

    @pytest.fixture
    def strategy(self) -> DefaultFailureHandlingStrategy:
        """Create strategy for edge case tests."""
        return DefaultFailureHandlingStrategy()

    def test_zero_retry_after_uses_minimum(
        self, strategy: DefaultFailureHandlingStrategy
    ) -> None:
        """Zero retry-after should use minimum wait."""
        error = RateLimitExceededError(
            "Rate limit",
            details={"retry_after": 0.0},
        )

        result = strategy.decide(
            error=error,
            model="openai/gpt-4o",
            current_backend="openai.1",
            attempted_backends=[],
            elapsed_time=0.0,
            is_streaming=False,
            content_started=False,
        )

        if result.decision == FailureDecision.WAIT_AND_RETRY:
            assert result.wait_seconds is not None
            assert result.wait_seconds >= strategy.config.min_retry_wait

    def test_negative_retry_after_treated_as_no_info(
        self, strategy: DefaultFailureHandlingStrategy
    ) -> None:
        """Negative retry-after should be treated as no retry info."""
        error = RateLimitExceededError(
            "Rate limit",
            details={"retry_after": -5.0},
        )

        # Should not crash
        result = strategy.decide(
            error=error,
            model="openai/gpt-4o",
            current_backend="openai.1",
            attempted_backends=[],
            elapsed_time=0.0,
            is_streaming=False,
            content_started=False,
        )

        assert result.decision in (
            FailureDecision.SURFACE_ERROR,
            FailureDecision.WAIT_AND_RETRY,
            FailureDecision.FAILOVER_IMMEDIATE,
        )

    def test_empty_model_string_handled(
        self, strategy: DefaultFailureHandlingStrategy
    ) -> None:
        """Empty model string should be handled gracefully."""
        error = BackendError("Error", status_code=500)

        # Should not crash
        result = strategy.decide(
            error=error,
            model="",
            current_backend="openai.1",
            attempted_backends=[],
            elapsed_time=0.0,
            is_streaming=False,
            content_started=False,
        )

        assert result.decision in (
            FailureDecision.SURFACE_ERROR,
            FailureDecision.FAILOVER_IMMEDIATE,
        )

    def test_very_large_elapsed_time(
        self, strategy: DefaultFailureHandlingStrategy
    ) -> None:
        """Very large elapsed time should surface error."""
        error = BackendError("Error", status_code=429)

        result = strategy.decide(
            error=error,
            model="openai/gpt-4o",
            current_backend="openai.1",
            attempted_backends=[],
            elapsed_time=1e9,  # Huge elapsed time
            is_streaming=False,
            content_started=False,
        )

        assert result.decision == FailureDecision.SURFACE_ERROR
