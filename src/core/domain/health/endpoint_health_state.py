"""Endpoint health state domain model.

This module defines the mutable state container for tracking health status
of unique backend API URLs.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass, field
from datetime import datetime, timezone


@dataclass
class EndpointHealthState:
    """Mutable health state for a unique backend API URL.

    This class tracks the current health status and history of an endpoint.
    It is designed to be updated by the health check state manager based on
    incoming health check events.

    Note: This is intentionally a mutable dataclass (not frozen) because
    health state changes over time based on check results.

    Attributes:
        api_url: The unique API URL this state tracks.
        ping_check_success: Current ping health status (True = healthy).
        http_check_success: Current HTTP health status (True = healthy).
        last_ping_check_timestamp: When the last ping check was performed.
        last_http_check_timestamp: When the last HTTP check was performed.
        last_successful_ping_timestamp: When the last successful ping occurred.
        last_successful_http_timestamp: When the last successful HTTP check occurred.
        last_ping_state_transition_timestamp: When ping state last changed.
        last_http_state_transition_timestamp: When HTTP state last changed.
        consecutive_ping_failures: Count of consecutive ping failures.
        consecutive_http_failures: Count of consecutive HTTP failures.
        last_ping_latency_ms: Latency of last successful ping in milliseconds.
        last_http_latency_ms: Latency of last successful HTTP check in milliseconds.
        last_http_status_code: HTTP status code from last successful check.
        last_ping_error: Error message from last failed ping.
        last_http_error: Error message from last failed HTTP check.
    """

    api_url: str

    # Current health status (optimistic defaults - assume healthy until proven otherwise)
    ping_check_success: bool = True
    http_check_success: bool = True

    # Timestamps for last check attempts
    last_ping_check_timestamp: datetime | None = None
    last_http_check_timestamp: datetime | None = None

    # Timestamps for last successful checks
    last_successful_ping_timestamp: datetime | None = None
    last_successful_http_timestamp: datetime | None = None

    # Timestamps for state transitions
    last_ping_state_transition_timestamp: datetime | None = None
    last_http_state_transition_timestamp: datetime | None = None

    # Failure tracking
    consecutive_ping_failures: int = 0
    consecutive_http_failures: int = 0

    # Last check metrics (for observability)
    last_ping_latency_ms: float | None = None
    last_http_latency_ms: float | None = None
    last_http_status_code: int | None = None

    # Last error messages
    last_ping_error: str | None = None
    last_http_error: str | None = None

    # Thread safety lock (not included in eq/hash/repr)
    _lock: threading.Lock = field(
        default_factory=threading.Lock, repr=False, compare=False
    )

    @property
    def is_healthy(self) -> bool:
        """Return True if the endpoint is considered healthy.

        An endpoint is healthy if both ping and HTTP checks are passing.
        """
        return self.ping_check_success and self.http_check_success

    @property
    def hostname(self) -> str:
        """Extract hostname from the API URL."""
        from urllib.parse import urlparse

        parsed = urlparse(self.api_url)
        return parsed.hostname or self.api_url

    def record_ping_success(self, latency_ms: float) -> bool:
        """Record a successful ping check.

        Args:
            latency_ms: Round-trip latency in milliseconds.

        Returns:
            True if state transitioned from unhealthy to healthy.
        """
        with self._lock:
            now = datetime.now(timezone.utc)
            old_state = self.ping_check_success

            self.last_ping_check_timestamp = now
            self.last_successful_ping_timestamp = now
            self.last_ping_latency_ms = latency_ms
            self.consecutive_ping_failures = 0
            self.last_ping_error = None

            if not old_state:
                # State transition: unhealthy -> healthy
                self.ping_check_success = True
                self.last_ping_state_transition_timestamp = now
                return True

            return False

    def record_ping_failure(self, error: str, failure_threshold: int) -> bool:
        """Record a failed ping check.

        Args:
            error: Error message describing the failure.
            failure_threshold: Number of consecutive failures before marking unhealthy.

        Returns:
            True if state transitioned from healthy to unhealthy.
        """
        with self._lock:
            now = datetime.now(timezone.utc)
            old_state = self.ping_check_success

            self.last_ping_check_timestamp = now
            self.consecutive_ping_failures += 1
            self.last_ping_error = error

            if old_state and self.consecutive_ping_failures >= failure_threshold:
                # State transition: healthy -> unhealthy
                self.ping_check_success = False
                self.last_ping_state_transition_timestamp = now
                return True

            return False

    def record_http_success(self, status_code: int, latency_ms: float) -> bool:
        """Record a successful HTTP check.

        Args:
            status_code: HTTP response status code.
            latency_ms: Request latency in milliseconds.

        Returns:
            True if state transitioned from unhealthy to healthy.
        """
        with self._lock:
            now = datetime.now(timezone.utc)
            old_state = self.http_check_success

            self.last_http_check_timestamp = now
            self.last_successful_http_timestamp = now
            self.last_http_latency_ms = latency_ms
            self.last_http_status_code = status_code
            self.consecutive_http_failures = 0
            self.last_http_error = None

            if not old_state:
                # State transition: unhealthy -> healthy
                self.http_check_success = True
                self.last_http_state_transition_timestamp = now
                return True

            return False

    def record_http_failure(self, error: str, failure_threshold: int) -> bool:
        """Record a failed HTTP check.

        Args:
            error: Error message describing the failure.
            failure_threshold: Number of consecutive failures before marking unhealthy.

        Returns:
            True if state transitioned from healthy to unhealthy.
        """
        with self._lock:
            now = datetime.now(timezone.utc)
            old_state = self.http_check_success

            self.last_http_check_timestamp = now
            self.consecutive_http_failures += 1
            self.last_http_error = error

            if old_state and self.consecutive_http_failures >= failure_threshold:
                # State transition: healthy -> unhealthy
                self.http_check_success = False
                self.last_http_state_transition_timestamp = now
                return True

            return False

    def to_dict(self) -> dict[str, object]:
        """Convert state to a dictionary for serialization/logging."""
        return {
            "api_url": self.api_url,
            "is_healthy": self.is_healthy,
            "ping_check_success": self.ping_check_success,
            "http_check_success": self.http_check_success,
            "last_ping_check_timestamp": (
                self.last_ping_check_timestamp.isoformat()
                if self.last_ping_check_timestamp
                else None
            ),
            "last_http_check_timestamp": (
                self.last_http_check_timestamp.isoformat()
                if self.last_http_check_timestamp
                else None
            ),
            "last_successful_ping_timestamp": (
                self.last_successful_ping_timestamp.isoformat()
                if self.last_successful_ping_timestamp
                else None
            ),
            "last_successful_http_timestamp": (
                self.last_successful_http_timestamp.isoformat()
                if self.last_successful_http_timestamp
                else None
            ),
            "consecutive_ping_failures": self.consecutive_ping_failures,
            "consecutive_http_failures": self.consecutive_http_failures,
            "last_ping_latency_ms": self.last_ping_latency_ms,
            "last_http_latency_ms": self.last_http_latency_ms,
            "last_http_status_code": self.last_http_status_code,
            "last_ping_error": self.last_ping_error,
            "last_http_error": self.last_http_error,
        }

    def __repr__(self) -> str:
        """Provide a concise representation."""
        status = "healthy" if self.is_healthy else "unhealthy"
        return f"<EndpointHealthState url={self.api_url} status={status}>"
