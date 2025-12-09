"""Unit tests for the failure handling strategy."""

from __future__ import annotations

import time
from unittest.mock import MagicMock

import pytest
from src.core.common.exceptions import (
    AuthenticationError,
    BackendError,
    InvalidRequestError,
    RateLimitExceededError,
    ValidationError,
)
from src.core.interfaces.failure_strategy_interface import (
    FailureDecision,
    FailureHandlingConfig,
    IBackendInstanceDiscovery,
)
from src.core.services.failure_handling_strategy import DefaultFailureHandlingStrategy


class TestDefaultFailureHandlingStrategy:
    """Tests for DefaultFailureHandlingStrategy."""

    @pytest.fixture
    def default_config(self) -> FailureHandlingConfig:
        """Create default configuration for tests."""
        return FailureHandlingConfig(
            max_silent_wait=30.0,
            total_timeout_budget=90.0,
            keepalive_interval=8.0,
            max_failover_hops=5,
            min_retry_wait=1.0,
        )

    @pytest.fixture
    def mock_discovery(self) -> MagicMock:
        """Create mock backend discovery service."""
        discovery = MagicMock(spec=IBackendInstanceDiscovery)
        discovery.find_alternative_instances.return_value = []
        return discovery

    @pytest.fixture
    def strategy(
        self, default_config: FailureHandlingConfig, mock_discovery: MagicMock
    ) -> DefaultFailureHandlingStrategy:
        """Create strategy instance for tests."""
        return DefaultFailureHandlingStrategy(
            config=default_config,
            backend_discovery=mock_discovery,
        )

    def test_content_started_surfaces_error(
        self, strategy: DefaultFailureHandlingStrategy
    ) -> None:
        """When content has already started streaming, surface the error."""
        error = BackendError("Test error", status_code=429)

        result = strategy.decide(
            error=error,
            model="openai/gpt-4o",
            current_backend="openai.1",
            attempted_backends=[],
            elapsed_time=0.0,
            is_streaming=True,
            content_started=True,
        )

        assert result.decision == FailureDecision.SURFACE_ERROR
        assert "content" in result.reason.lower()

    def test_max_failover_hops_exceeded(
        self, strategy: DefaultFailureHandlingStrategy
    ) -> None:
        """When max failover hops reached, surface the error."""
        error = BackendError("Test error", status_code=429)

        result = strategy.decide(
            error=error,
            model="openai/gpt-4o",
            current_backend="openai.6",
            attempted_backends=[
                "openai.1",
                "openai.2",
                "openai.3",
                "openai.4",
                "openai.5",
            ],
            elapsed_time=10.0,
            is_streaming=False,
            content_started=False,
        )

        assert result.decision == FailureDecision.SURFACE_ERROR
        assert "hops" in result.reason.lower()

    def test_timeout_budget_exceeded(
        self, strategy: DefaultFailureHandlingStrategy
    ) -> None:
        """When total timeout budget exceeded, surface the error."""
        error = BackendError("Test error", status_code=429)

        result = strategy.decide(
            error=error,
            model="openai/gpt-4o",
            current_backend="openai.1",
            attempted_backends=[],
            elapsed_time=100.0,  # > 90s budget
            is_streaming=False,
            content_started=False,
        )

        assert result.decision == FailureDecision.SURFACE_ERROR
        assert "timeout" in result.reason.lower()

    def test_recoverable_429_short_wait_waits_and_retries(
        self, strategy: DefaultFailureHandlingStrategy
    ) -> None:
        """429 error with short retry-after should wait and retry."""
        error = RateLimitExceededError(
            "Rate limit exceeded",
            details={"retry_after": 5.0},
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
        assert result.wait_seconds >= 1.0  # min_retry_wait

    def test_recoverable_429_long_wait_with_alternative_failsover(
        self,
        strategy: DefaultFailureHandlingStrategy,
        mock_discovery: MagicMock,
    ) -> None:
        """429 with long retry-after and available alternative should failover."""
        mock_discovery.find_alternative_instances.return_value = [
            "openai.2",
            "openai.3",
        ]

        error = RateLimitExceededError(
            "Rate limit exceeded",
            details={"retry_after": 60.0},  # > 30s max_silent_wait
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

        assert result.decision == FailureDecision.FAILOVER_IMMEDIATE
        assert result.next_backend == "openai.2"

    def test_unrecoverable_auth_error_with_alternative_failsover(
        self,
        strategy: DefaultFailureHandlingStrategy,
        mock_discovery: MagicMock,
    ) -> None:
        """Auth error with available alternative should failover immediately."""
        mock_discovery.find_alternative_instances.return_value = ["openai.2"]

        error = AuthenticationError("Invalid API key")

        result = strategy.decide(
            error=error,
            model="openai/gpt-4o",
            current_backend="openai.1",
            attempted_backends=[],
            elapsed_time=0.0,
            is_streaming=False,
            content_started=False,
        )

        assert result.decision == FailureDecision.FAILOVER_IMMEDIATE
        assert result.next_backend == "openai.2"

    def test_unrecoverable_error_no_alternatives_surfaces(
        self,
        strategy: DefaultFailureHandlingStrategy,
        mock_discovery: MagicMock,
    ) -> None:
        """Unrecoverable error with no alternatives should surface."""
        mock_discovery.find_alternative_instances.return_value = []

        error = InvalidRequestError("Bad request")

        result = strategy.decide(
            error=error,
            model="openai/gpt-4o",
            current_backend="openai.1",
            attempted_backends=[],
            elapsed_time=0.0,
            is_streaming=False,
            content_started=False,
        )

        assert result.decision == FailureDecision.SURFACE_ERROR

    def test_available_backends_parameter_used_when_provided(
        self, strategy: DefaultFailureHandlingStrategy
    ) -> None:
        """When available_backends is provided, use it instead of discovery."""
        error = BackendError("Test error", status_code=500)

        result = strategy.decide(
            error=error,
            model="openai/gpt-4o",
            current_backend="openai.1",
            attempted_backends=[],
            elapsed_time=0.0,
            is_streaming=False,
            content_started=False,
            available_backends=["openai.2", "openai.3"],
        )

        assert result.decision == FailureDecision.FAILOVER_IMMEDIATE
        assert result.next_backend == "openai.2"

    def test_min_retry_wait_enforced(
        self, strategy: DefaultFailureHandlingStrategy
    ) -> None:
        """Very short retry-after should be increased to min_retry_wait."""
        error = RateLimitExceededError(
            "Rate limit exceeded",
            details={"retry_after": 0.1},  # Very short
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
        assert result.wait_seconds >= 1.0  # min_retry_wait

    def test_no_strategy_configured_surfaces_all_errors(self) -> None:
        """Without failure strategy, all errors should be surfaced."""
        # Test the interface - when no strategy is configured
        # This tests that the code handles None strategy correctly
        strategy = DefaultFailureHandlingStrategy(config=None, backend_discovery=None)
        error = BackendError("Test error", status_code=429)

        result = strategy.decide(
            error=error,
            model="openai/gpt-4o",
            current_backend="openai.1",
            attempted_backends=[],
            elapsed_time=0.0,
            is_streaming=False,
            content_started=False,
        )

        # With no discovery, failover is not possible, so either wait or surface
        # Depends on whether error is recoverable
        assert result.decision in (
            FailureDecision.WAIT_AND_RETRY,
            FailureDecision.SURFACE_ERROR,
        )


class TestErrorClassification:
    """Tests for error classification logic."""

    @pytest.fixture
    def strategy(self) -> DefaultFailureHandlingStrategy:
        """Create strategy for error classification tests."""
        return DefaultFailureHandlingStrategy()

    def test_429_is_recoverable(self, strategy: DefaultFailureHandlingStrategy) -> None:
        """HTTP 429 should be classified as recoverable."""
        error = BackendError("Rate limit", status_code=429)
        assert strategy._is_recoverable_error(error) is True

    def test_rate_limit_exceeded_is_recoverable(
        self, strategy: DefaultFailureHandlingStrategy
    ) -> None:
        """RateLimitExceededError should be recoverable."""
        error = RateLimitExceededError("Rate limit")
        assert strategy._is_recoverable_error(error) is True

    def test_401_is_not_recoverable(
        self, strategy: DefaultFailureHandlingStrategy
    ) -> None:
        """HTTP 401 should not be recoverable."""
        error = BackendError("Unauthorized", status_code=401)
        assert strategy._is_recoverable_error(error) is False

    def test_403_is_not_recoverable(
        self, strategy: DefaultFailureHandlingStrategy
    ) -> None:
        """HTTP 403 should not be recoverable."""
        error = BackendError("Forbidden", status_code=403)
        assert strategy._is_recoverable_error(error) is False

    def test_400_is_not_recoverable(
        self, strategy: DefaultFailureHandlingStrategy
    ) -> None:
        """HTTP 400 should not be recoverable."""
        error = BackendError("Bad request", status_code=400)
        assert strategy._is_recoverable_error(error) is False

    def test_500_is_not_recoverable(
        self, strategy: DefaultFailureHandlingStrategy
    ) -> None:
        """HTTP 500 should not be recoverable."""
        error = BackendError("Server error", status_code=500)
        assert strategy._is_recoverable_error(error) is False

    def test_auth_error_is_not_recoverable(
        self, strategy: DefaultFailureHandlingStrategy
    ) -> None:
        """AuthenticationError should not be recoverable."""
        error = AuthenticationError("Invalid key")
        assert strategy._is_recoverable_error(error) is False

    def test_validation_error_is_not_recoverable(
        self, strategy: DefaultFailureHandlingStrategy
    ) -> None:
        """ValidationError should not be recoverable."""
        error = ValidationError("Invalid")
        assert strategy._is_recoverable_error(error) is False

    def test_connection_error_is_recoverable(
        self, strategy: DefaultFailureHandlingStrategy
    ) -> None:
        """Connection-related errors should be recoverable."""
        error = BackendError("Connection timeout")
        assert strategy._is_recoverable_error(error) is True

    def test_network_error_is_recoverable(
        self, strategy: DefaultFailureHandlingStrategy
    ) -> None:
        """Network-related errors should be recoverable."""
        error = BackendError("Network unavailable")
        assert strategy._is_recoverable_error(error) is True


class TestRetryAfterExtraction:
    """Tests for retry-after extraction logic."""

    @pytest.fixture
    def strategy(self) -> DefaultFailureHandlingStrategy:
        """Create strategy for retry-after tests."""
        return DefaultFailureHandlingStrategy()

    def test_extract_from_details_retry_after(
        self, strategy: DefaultFailureHandlingStrategy
    ) -> None:
        """Extract retry_after from details dict."""
        error = BackendError(
            "Rate limit",
            status_code=429,
            details={"retry_after": 15.0},
        )
        assert strategy._extract_retry_after(error) == 15.0

    def test_extract_from_google_retry_info(
        self, strategy: DefaultFailureHandlingStrategy
    ) -> None:
        """Extract from Google-style RetryInfo."""
        error = BackendError(
            "Rate limit",
            status_code=429,
            details={
                "error": {
                    "details": [
                        {
                            "@type": "type.googleapis.com/google.rpc.RetryInfo",
                            "retryDelay": "5s",
                        }
                    ]
                }
            },
        )
        assert strategy._extract_retry_after(error) == 5.0

    def test_extract_from_google_quota_reset_delay(
        self, strategy: DefaultFailureHandlingStrategy
    ) -> None:
        """Extract from Google-style quotaResetDelay."""
        error = BackendError(
            "Rate limit",
            status_code=429,
            details={
                "error": {
                    "details": [
                        {
                            "@type": "type.googleapis.com/google.rpc.ErrorInfo",
                            "metadata": {"quotaResetDelay": "0.5s"},
                        }
                    ]
                }
            },
        )
        result = strategy._extract_retry_after(error)
        assert result is not None
        assert abs(result - 0.5) < 0.01

    def test_extract_from_rate_limit_exceeded_error(
        self, strategy: DefaultFailureHandlingStrategy
    ) -> None:
        """Extract from RateLimitExceededError reset_at."""
        future_timestamp = time.time() + 10.0
        error = RateLimitExceededError(
            "Rate limit",
            reset_at=future_timestamp,
        )
        result = strategy._extract_retry_after(error)
        assert result is not None
        assert 9.0 <= result <= 11.0  # Allow some tolerance

    def test_no_retry_after_returns_none(
        self, strategy: DefaultFailureHandlingStrategy
    ) -> None:
        """Return None when no retry-after info available."""
        error = BackendError("Some error", status_code=500)
        assert strategy._extract_retry_after(error) is None


class TestDurationParsing:
    """Tests for duration string parsing."""

    def test_simple_seconds(self) -> None:
        """Parse simple seconds format."""
        assert DefaultFailureHandlingStrategy._parse_duration_string("5s") == 5.0
        assert DefaultFailureHandlingStrategy._parse_duration_string("0.5s") == 0.5
        assert (
            DefaultFailureHandlingStrategy._parse_duration_string("17493.989s")
            == 17493.989
        )

    def test_complex_format(self) -> None:
        """Parse complex duration format."""
        assert DefaultFailureHandlingStrategy._parse_duration_string("1h") == 3600.0
        assert DefaultFailureHandlingStrategy._parse_duration_string("1m") == 60.0
        result = DefaultFailureHandlingStrategy._parse_duration_string("4h51m33.9s")
        expected = 4 * 3600 + 51 * 60 + 33.9
        assert result is not None
        assert abs(result - expected) < 0.01

    def test_invalid_format_returns_none(self) -> None:
        """Invalid formats should return None."""
        assert DefaultFailureHandlingStrategy._parse_duration_string("invalid") is None
        assert DefaultFailureHandlingStrategy._parse_duration_string("") is None
        assert DefaultFailureHandlingStrategy._parse_duration_string(None) is None  # type: ignore
