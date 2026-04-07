"""In-memory circuit breaker state manager for backend resilience."""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass

from src.core.config.models.misc import CircuitBreakerConfig

_STATE_CLOSED = "closed"
_STATE_OPEN = "open"
_STATE_HALF_OPEN = "half_open"


@dataclass(slots=True)
class CircuitBreakerState:
    """Mutable per-instance circuit breaker state."""

    state: str = _STATE_CLOSED
    consecutive_failures: int = 0
    open_until: float | None = None
    half_open_inflight: int = 0
    half_open_successes: int = 0
    last_failure_reason: str = ""


@dataclass(frozen=True, slots=True)
class CircuitBreakerDecision:
    """Decision emitted by a circuit breaker availability check."""

    should_proceed: bool
    state: str
    cooldown_remaining: float | None
    reason: str


class CircuitBreakerStateManager:
    """Thread-safe, in-memory state machine for backend circuit breakers."""

    def __init__(self, config: CircuitBreakerConfig | None = None) -> None:
        self._config = config or CircuitBreakerConfig()
        self._lock = threading.Lock()
        self._states: dict[str, CircuitBreakerState] = {}

    def check(self, instance_id: str) -> CircuitBreakerDecision:
        """Return whether a request should be allowed for the instance."""
        if not self._config.enabled:
            return CircuitBreakerDecision(
                should_proceed=True,
                state=_STATE_CLOSED,
                cooldown_remaining=None,
                reason="circuit_breaker_disabled",
            )

        with self._lock:
            state = self._states.get(instance_id)
            if state is None:
                return CircuitBreakerDecision(
                    should_proceed=True,
                    state=_STATE_CLOSED,
                    cooldown_remaining=None,
                    reason="circuit_closed",
                )
            now = time.monotonic()

            if state.state == _STATE_OPEN:
                open_until = state.open_until
                if open_until is not None and now < open_until:
                    return CircuitBreakerDecision(
                        should_proceed=False,
                        state=_STATE_OPEN,
                        cooldown_remaining=max(0.0, open_until - now),
                        reason="circuit_open",
                    )
                self._transition_to_half_open(state)

            if state.state == _STATE_HALF_OPEN:
                if state.half_open_inflight >= self._config.half_open_max_inflight:
                    return CircuitBreakerDecision(
                        should_proceed=False,
                        state=_STATE_HALF_OPEN,
                        cooldown_remaining=None,
                        reason="half_open_probe_inflight",
                    )
                return CircuitBreakerDecision(
                    should_proceed=True,
                    state=_STATE_HALF_OPEN,
                    cooldown_remaining=None,
                    reason="half_open_probe_allowed",
                )

            return CircuitBreakerDecision(
                should_proceed=True,
                state=_STATE_CLOSED,
                cooldown_remaining=None,
                reason="circuit_closed",
            )

    def try_acquire_half_open_probe(self, instance_id: str) -> bool:
        """Try to reserve one half-open probe slot for the instance."""
        if not self._config.enabled:
            return True

        with self._lock:
            state = self._states.get(instance_id)
            if state is None:
                return True

            now = time.monotonic()
            if state.state == _STATE_OPEN:
                open_until = state.open_until
                if open_until is not None and now < open_until:
                    return False
                self._transition_to_half_open(state)

            if state.state != _STATE_HALF_OPEN:
                return True

            if state.half_open_inflight >= self._config.half_open_max_inflight:
                return False

            state.half_open_inflight += 1
            return True

    def release_half_open_probe(self, instance_id: str) -> None:
        """Release a previously acquired half-open probe slot, if one exists."""
        if not self._config.enabled:
            return

        with self._lock:
            state = self._states.get(instance_id)
            if state is None:
                return
            if state.state == _STATE_HALF_OPEN and state.half_open_inflight > 0:
                state.half_open_inflight -= 1

    def record_failure(self, instance_id: str, *, reason: str) -> None:
        """Record a transient failure for the instance."""
        if not self._config.enabled:
            return

        with self._lock:
            state = self._states.setdefault(instance_id, CircuitBreakerState())
            now = time.monotonic()
            state.last_failure_reason = reason

            if state.state == _STATE_HALF_OPEN:
                if state.half_open_inflight > 0:
                    state.half_open_inflight -= 1
                self._transition_to_open(state, now)
                return

            if state.state == _STATE_OPEN:
                self._transition_to_open(state, now)
                return

            state.consecutive_failures += 1
            state.half_open_successes = 0

            if state.consecutive_failures >= self._config.failure_threshold:
                self._transition_to_open(state, now)

    def record_success(self, instance_id: str) -> None:
        """Record a successful request for the instance."""
        if not self._config.enabled:
            return

        with self._lock:
            state = self._states.get(instance_id)
            if state is None:
                return

            if state.state == _STATE_HALF_OPEN:
                if state.half_open_inflight > 0:
                    state.half_open_inflight -= 1
                state.half_open_successes += 1
                if (
                    state.half_open_successes
                    >= self._config.half_open_success_threshold
                ):
                    self._transition_to_closed(state)
                    self._evict_if_pristine(instance_id, state)
                return

            if state.state == _STATE_CLOSED:
                state.consecutive_failures = 0
                state.last_failure_reason = ""
                self._evict_if_pristine(instance_id, state)

    def _transition_to_open(self, state: CircuitBreakerState, now: float) -> None:
        state.state = _STATE_OPEN
        state.open_until = now + self._config.open_cooldown_seconds
        state.half_open_inflight = 0
        state.half_open_successes = 0

    @staticmethod
    def _transition_to_half_open(state: CircuitBreakerState) -> None:
        state.state = _STATE_HALF_OPEN
        state.open_until = None
        state.consecutive_failures = 0
        state.half_open_inflight = 0
        state.half_open_successes = 0

    @staticmethod
    def _transition_to_closed(state: CircuitBreakerState) -> None:
        state.state = _STATE_CLOSED
        state.open_until = None
        state.consecutive_failures = 0
        state.half_open_inflight = 0
        state.half_open_successes = 0
        state.last_failure_reason = ""

    def _evict_if_pristine(self, instance_id: str, state: CircuitBreakerState) -> None:
        if (
            state.state == _STATE_CLOSED
            and state.consecutive_failures == 0
            and state.open_until is None
            and state.half_open_inflight == 0
            and state.half_open_successes == 0
            and not state.last_failure_reason
        ):
            self._states.pop(instance_id, None)


__all__ = [
    "CircuitBreakerConfig",
    "CircuitBreakerDecision",
    "CircuitBreakerState",
    "CircuitBreakerStateManager",
]
