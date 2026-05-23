"""Tests for the EndpointHealthState class."""

from __future__ import annotations

from src.core.domain.health.endpoint_health_state import EndpointHealthState


class TestEndpointHealthState:
    """Tests for EndpointHealthState."""

    def test_initial_state_is_healthy(self) -> None:
        """Test that initial state is healthy (optimistic)."""
        state = EndpointHealthState(api_url="https://api.openai.com/v1")

        assert state.ping_check_success is True
        assert state.http_check_success is True
        assert state.is_healthy is True

    def test_record_ping_success(self) -> None:
        """Test recording a successful ping."""
        state = EndpointHealthState(api_url="https://api.openai.com/v1")

        transitioned = state.record_ping_success(latency_ms=50.0)

        assert transitioned is False  # Already healthy
        assert state.ping_check_success is True
        assert state.last_ping_latency_ms == 50.0
        assert state.consecutive_ping_failures == 0
        assert state.last_ping_check_timestamp is not None
        assert state.last_successful_ping_timestamp is not None

    def test_record_ping_failure_under_threshold(self) -> None:
        """Test recording ping failures under threshold."""
        state = EndpointHealthState(api_url="https://api.openai.com/v1")
        threshold = 3

        # First failure - should not transition
        transitioned = state.record_ping_failure("timeout", threshold)
        assert transitioned is False
        assert state.ping_check_success is True  # Still healthy
        assert state.consecutive_ping_failures == 1

        # Second failure - still under threshold
        transitioned = state.record_ping_failure("timeout", threshold)
        assert transitioned is False
        assert state.ping_check_success is True
        assert state.consecutive_ping_failures == 2

    def test_record_ping_failure_reaches_threshold(self) -> None:
        """Test recording ping failures reaching threshold."""
        state = EndpointHealthState(api_url="https://api.openai.com/v1")
        threshold = 3

        # Three failures to reach threshold
        state.record_ping_failure("timeout", threshold)
        state.record_ping_failure("timeout", threshold)
        transitioned = state.record_ping_failure("timeout", threshold)

        assert transitioned is True
        assert state.ping_check_success is False  # Now unhealthy
        assert state.consecutive_ping_failures == 3
        assert state.last_ping_state_transition_timestamp is not None

    def test_record_ping_success_after_failure(self) -> None:
        """Test recovery from ping failure."""
        state = EndpointHealthState(api_url="https://api.openai.com/v1")
        threshold = 2

        # Fail and transition to unhealthy
        state.record_ping_failure("timeout", threshold)
        state.record_ping_failure("timeout", threshold)
        assert state.ping_check_success is False

        # Success should transition back to healthy
        transitioned = state.record_ping_success(latency_ms=25.0)
        assert transitioned is True
        assert state.ping_check_success is True
        assert state.consecutive_ping_failures == 0

    def test_record_http_success(self) -> None:
        """Test recording a successful HTTP check."""
        state = EndpointHealthState(api_url="https://api.openai.com/v1")

        transitioned = state.record_http_success(status_code=200, latency_ms=100.0)

        assert transitioned is False  # Already healthy
        assert state.http_check_success is True
        assert state.last_http_latency_ms == 100.0
        assert state.last_http_status_code == 200
        assert state.consecutive_http_failures == 0

    def test_record_http_failure_reaches_threshold(self) -> None:
        """Test recording HTTP failures reaching threshold."""
        state = EndpointHealthState(api_url="https://api.openai.com/v1")
        threshold = 2

        # Two failures to reach threshold
        state.record_http_failure("connection error", threshold)
        transitioned = state.record_http_failure("connection error", threshold)

        assert transitioned is True
        assert state.http_check_success is False
        assert state.consecutive_http_failures == 2

    def test_is_healthy_requires_both_checks(self) -> None:
        """Test that is_healthy requires both ping and HTTP to pass."""
        state = EndpointHealthState(api_url="https://api.openai.com/v1")

        # Fail ping
        state.record_ping_failure("timeout", 1)
        assert state.is_healthy is False  # Ping failed

        # Reset
        state = EndpointHealthState(api_url="https://api.openai.com/v1")

        # Fail HTTP
        state.record_http_failure("error", 1)
        assert state.is_healthy is False  # HTTP failed

    def test_hostname_extraction(self) -> None:
        """Test hostname property."""
        state = EndpointHealthState(api_url="https://api.openai.com/v1")
        assert state.hostname == "api.openai.com"

        state = EndpointHealthState(api_url="https://api.openai.com:8080/v1")
        assert state.hostname == "api.openai.com"

    def test_to_dict(self) -> None:
        """Test serialization to dict."""
        state = EndpointHealthState(api_url="https://api.openai.com/v1")
        state.record_ping_success(latency_ms=50.0)
        state.record_http_success(status_code=200, latency_ms=100.0)

        data = state.to_dict()

        assert data["api_url"] == "https://api.openai.com/v1"
        assert data["is_healthy"] is True
        assert data["ping_check_success"] is True
        assert data["http_check_success"] is True
        assert data["last_ping_latency_ms"] == 50.0
        assert data["last_http_latency_ms"] == 100.0
        assert data["last_http_status_code"] == 200

    def test_repr(self) -> None:
        """Test string representation."""
        state = EndpointHealthState(api_url="https://api.openai.com/v1")
        repr_str = repr(state)
        assert "api.openai.com" in repr_str
        assert "healthy" in repr_str
