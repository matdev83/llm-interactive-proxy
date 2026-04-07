"""Unit tests for CircuitBreakerStateManager state transitions."""

from __future__ import annotations

import pytest
import src.core.services.resilience.circuit_breaker_state as circuit_breaker_state_module
from src.core.config.models.misc import CircuitBreakerConfig
from src.core.services.resilience.circuit_breaker_state import (
    CircuitBreakerStateManager,
)


class _FakeClock:
    def __init__(self) -> None:
        self._now = 1000.0

    def monotonic(self) -> float:
        return self._now

    def advance(self, seconds: float) -> None:
        self._now += seconds


@pytest.fixture
def fake_clock(monkeypatch: pytest.MonkeyPatch) -> _FakeClock:
    clock = _FakeClock()
    monkeypatch.setattr(circuit_breaker_state_module.time, "monotonic", clock.monotonic)
    return clock


def test_check_allows_requests_while_closed(fake_clock: _FakeClock) -> None:
    manager = CircuitBreakerStateManager(CircuitBreakerConfig())

    decision = manager.check("backend.1")

    assert decision.should_proceed is True
    assert decision.state == "closed"
    assert decision.cooldown_remaining is None


def test_failure_threshold_opens_circuit(fake_clock: _FakeClock) -> None:
    manager = CircuitBreakerStateManager(
        CircuitBreakerConfig(failure_threshold=2, open_cooldown_seconds=30.0)
    )

    manager.record_failure("backend.1", reason="timeout")
    assert manager.check("backend.1").should_proceed is True

    manager.record_failure("backend.1", reason="timeout")
    decision = manager.check("backend.1")

    assert decision.should_proceed is False
    assert decision.state == "open"
    assert decision.cooldown_remaining is not None
    assert decision.cooldown_remaining > 0


def test_open_cooldown_expiry_transitions_to_half_open_with_bounded_probe(
    fake_clock: _FakeClock,
) -> None:
    manager = CircuitBreakerStateManager(
        CircuitBreakerConfig(
            failure_threshold=1,
            open_cooldown_seconds=10.0,
            half_open_max_inflight=1,
        )
    )
    manager.record_failure("backend.1", reason="upstream_500")
    assert manager.check("backend.1").should_proceed is False

    fake_clock.advance(10.1)
    first_probe = manager.check("backend.1")
    second_probe = manager.check("backend.1")
    acquired = manager.try_acquire_half_open_probe("backend.1")
    second_acquire = manager.try_acquire_half_open_probe("backend.1")
    constrained_probe = manager.check("backend.1")

    assert first_probe.should_proceed is True
    assert first_probe.state == "half_open"
    assert second_probe.should_proceed is True
    assert second_probe.state == "half_open"
    assert acquired is True
    assert second_acquire is False
    assert constrained_probe.should_proceed is False
    assert constrained_probe.state == "half_open"
    assert constrained_probe.reason == "half_open_probe_inflight"


def test_check_does_not_create_state_entries_for_healthy_instances(
    fake_clock: _FakeClock,
) -> None:
    manager = CircuitBreakerStateManager(CircuitBreakerConfig())

    for idx in range(250):
        decision = manager.check(f"backend.{idx}")
        assert decision.should_proceed is True
        assert decision.state == "closed"

    assert manager._states == {}


def test_half_open_success_closes_circuit_and_resets_counters(
    fake_clock: _FakeClock,
) -> None:
    manager = CircuitBreakerStateManager(
        CircuitBreakerConfig(
            failure_threshold=2,
            open_cooldown_seconds=10.0,
            half_open_success_threshold=1,
        )
    )

    manager.record_failure("backend.1", reason="timeout")
    manager.record_failure("backend.1", reason="timeout")
    assert manager.check("backend.1").state == "open"

    fake_clock.advance(10.1)
    assert manager.check("backend.1").state == "half_open"

    manager.record_success("backend.1")
    assert manager.check("backend.1").state == "closed"

    manager.record_failure("backend.1", reason="timeout")
    assert manager.check("backend.1").should_proceed is True


def test_half_open_failure_reopens_circuit(fake_clock: _FakeClock) -> None:
    manager = CircuitBreakerStateManager(
        CircuitBreakerConfig(failure_threshold=1, open_cooldown_seconds=5.0)
    )
    manager.record_failure("backend.1", reason="timeout")
    assert manager.check("backend.1").state == "open"

    fake_clock.advance(5.1)
    assert manager.check("backend.1").state == "half_open"
    manager.record_failure("backend.1", reason="timeout")

    reopened = manager.check("backend.1")
    assert reopened.should_proceed is False
    assert reopened.state == "open"
    assert reopened.cooldown_remaining is not None
    assert reopened.cooldown_remaining > 4.0


def test_success_in_closed_state_resets_consecutive_failures(
    fake_clock: _FakeClock,
) -> None:
    manager = CircuitBreakerStateManager(
        CircuitBreakerConfig(failure_threshold=2, open_cooldown_seconds=30.0)
    )

    manager.record_failure("backend.1", reason="timeout")
    manager.record_success("backend.1")
    manager.record_failure("backend.1", reason="timeout")

    still_closed = manager.check("backend.1")
    assert still_closed.should_proceed is True
    assert still_closed.state == "closed"

    manager.record_failure("backend.1", reason="timeout")
    opened = manager.check("backend.1")
    assert opened.should_proceed is False
    assert opened.state == "open"
