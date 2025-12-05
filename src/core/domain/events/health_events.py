"""Health check events for the event bus.

This module defines stateless events emitted by health check processes
and stateful state transition events emitted when health states change.

Event Types:
- Stateless check events: Emitted after each health check attempt
- State transition events: Emitted when health state changes

All events are immutable dataclasses inheriting from InfrastructureEvent.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import ClassVar

from src.core.domain.events import InfrastructureEvent

# =============================================================================
# Stateless Check Events (emitted by health checkers)
# =============================================================================


@dataclass(frozen=True)
class PingCheckSucceeded(InfrastructureEvent):
    """Event emitted when an ICMP ping check succeeds.

    Attributes:
        api_url: The API URL that was pinged (hostname extracted).
        latency_ms: Round-trip latency in milliseconds.
    """

    event_type: ClassVar[str] = "ping_check_succeeded"

    api_url: str = ""
    latency_ms: float = 0.0


@dataclass(frozen=True)
class PingCheckFailed(InfrastructureEvent):
    """Event emitted when an ICMP ping check fails.

    Attributes:
        api_url: The API URL that was pinged.
        error: Description of the failure.
    """

    event_type: ClassVar[str] = "ping_check_failed"

    api_url: str = ""
    error: str = ""


@dataclass(frozen=True)
class HttpCheckSucceeded(InfrastructureEvent):
    """Event emitted when an HTTP health check succeeds.

    Attributes:
        api_url: The API URL that was probed.
        status_code: HTTP response status code.
        latency_ms: Request latency in milliseconds.
    """

    event_type: ClassVar[str] = "http_check_succeeded"

    api_url: str = ""
    status_code: int = 0
    latency_ms: float = 0.0


@dataclass(frozen=True)
class HttpCheckFailed(InfrastructureEvent):
    """Event emitted when an HTTP health check fails.

    Attributes:
        api_url: The API URL that was probed.
        error: Description of the failure.
    """

    event_type: ClassVar[str] = "http_check_failed"

    api_url: str = ""
    error: str = ""


# =============================================================================
# State Transition Events (emitted by state manager)
# =============================================================================


@dataclass(frozen=True)
class PingHealthStateTransition(InfrastructureEvent):
    """Event emitted when ping health state changes.

    Attributes:
        api_url: The API URL whose state changed.
        old_state: Previous health state (True = healthy).
        new_state: New health state (True = healthy).
        consecutive_failures: Number of consecutive failures (if transitioning to unhealthy).
    """

    event_type: ClassVar[str] = "ping_health_state_transition"

    api_url: str = ""
    old_state: bool = True
    new_state: bool = True
    consecutive_failures: int = 0


@dataclass(frozen=True)
class HttpHealthStateTransition(InfrastructureEvent):
    """Event emitted when HTTP health state changes.

    Attributes:
        api_url: The API URL whose state changed.
        old_state: Previous health state (True = healthy).
        new_state: New health state (True = healthy).
        consecutive_failures: Number of consecutive failures (if transitioning to unhealthy).
    """

    event_type: ClassVar[str] = "http_health_state_transition"

    api_url: str = ""
    old_state: bool = True
    new_state: bool = True
    consecutive_failures: int = 0


# =============================================================================
# Combined Health State Events
# =============================================================================


@dataclass(frozen=True)
class EndpointHealthChanged(InfrastructureEvent):
    """Event emitted when overall endpoint health status changes.

    This is a higher-level event that indicates the combined health status
    of an endpoint has changed (considering both ping and HTTP checks).

    Attributes:
        api_url: The API URL whose health changed.
        is_healthy: Whether the endpoint is now considered healthy.
        ping_healthy: Current ping health state.
        http_healthy: Current HTTP health state.
    """

    event_type: ClassVar[str] = "endpoint_health_changed"

    api_url: str = ""
    is_healthy: bool = True
    ping_healthy: bool = True
    http_healthy: bool = True


__all__ = [
    # Stateless check events
    "PingCheckSucceeded",
    "PingCheckFailed",
    "HttpCheckSucceeded",
    "HttpCheckFailed",
    # State transition events
    "PingHealthStateTransition",
    "HttpHealthStateTransition",
    # Combined events
    "EndpointHealthChanged",
]
