"""Interface for failure handling strategies in the proxy.

This module defines the contract for failure handling strategies that decide
how to respond to backend failures - whether to wait and retry, failover to
another backend instance, or surface the error to the client.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Protocol


class FailureDecision(Enum):
    """Decision on how to handle a backend failure."""

    WAIT_AND_RETRY = "wait_and_retry"
    """Wait for retry-after period, then retry the same backend."""

    FAILOVER_IMMEDIATE = "failover"
    """Immediately try the next available backend instance."""

    SURFACE_ERROR = "surface"
    """No recovery possible, return error to the client."""


@dataclass
class FailureHandlingResult:
    """Result of a failure handling decision.

    Attributes:
        decision: The decision on how to handle the failure.
        wait_seconds: For WAIT_AND_RETRY, how long to wait before retrying.
        next_backend: For FAILOVER_IMMEDIATE, the backend instance to try next.
        error_to_surface: For SURFACE_ERROR, the error to return to the client.
        reason: Human-readable explanation of the decision.
    """

    decision: FailureDecision
    wait_seconds: float | None = None
    next_backend: str | None = None
    error_to_surface: Exception | None = None
    reason: str = ""


@dataclass
class FailureHandlingConfig:
    """Configuration for failure handling behavior.

    Attributes:
        max_silent_wait: Maximum seconds to wait for retry-after before failover.
        total_timeout_budget: Maximum total seconds across all failover attempts.
        keepalive_interval: Seconds between SSE keepalive comments during waits.
        max_failover_hops: Maximum number of backend instances to try.
        min_retry_wait: Minimum wait time even for sub-second retry-after.
    """

    max_silent_wait: float = 60.0
    total_timeout_budget: float = 90.0
    keepalive_interval: float = 8.0
    max_failover_hops: int = 5
    min_retry_wait: float = 1.0


class IFailureHandlingStrategy(Protocol):
    """Protocol for failure handling strategies.

    Implementations decide how to respond to backend failures based on
    the error type, elapsed time, available alternatives, and other factors.
    """

    def decide(
        self,
        error: Exception,
        model: str,
        current_backend: str,
        attempted_backends: list[str],
        elapsed_time: float,
        is_streaming: bool,
        content_started: bool,
        available_backends: list[str] | None = None,
    ) -> FailureHandlingResult:
        """Decide how to handle a backend failure.

        Args:
            error: The backend error that occurred.
            model: Fully qualified model name (e.g., "openai/gpt-4o").
            current_backend: Name of the backend instance that failed.
            attempted_backends: List of backend instances already tried.
            elapsed_time: Total seconds elapsed since the original request started.
            is_streaming: Whether this is a streaming request.
            content_started: Whether content has already been sent to the client.
            available_backends: Optional list of available backend instances for this model.

        Returns:
            FailureHandlingResult with the decision and relevant parameters.
        """
        ...


class IBackendInstanceDiscovery(Protocol):
    """Protocol for discovering backend instances that can serve a model."""

    def find_alternative_instances(
        self,
        model: str,
        exclude: list[str],
    ) -> list[str]:
        """Find backend instances that can serve the given model.

        Args:
            model: Fully qualified model name (e.g., "openai/gpt-4o").
            exclude: List of backend instance names to exclude (already tried).

        Returns:
            List of backend instance names that can serve the model.
        """
        ...


__all__ = [
    "FailureDecision",
    "FailureHandlingResult",
    "FailureHandlingConfig",
    "IFailureHandlingStrategy",
    "IBackendInstanceDiscovery",
]
