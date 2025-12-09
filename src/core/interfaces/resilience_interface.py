"""
Resilience layer interfaces.

This module defines protocols for the resilience layer which handles
rate limiting, error recovery, and backend availability tracking.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import TYPE_CHECKING, Any, Protocol

if TYPE_CHECKING:
    pass


class ActionType(Enum):
    """Types of actions the resilience layer can take."""

    PROCEED = "proceed"  # Request can proceed
    REJECT = "reject"  # Request should be rejected (cooldown active)
    COOLDOWN = "cooldown"  # Set cooldown for instance/model
    DISABLE_INSTANCE = "disable_instance"  # Permanently disable instance
    FALLBACK = "fallback"  # Try fallback backends (future)
    RETRY = "retry"  # Retry with backoff (future)


@dataclass
class ResilienceDecision:
    """Result of checking availability before a request."""

    action: ActionType
    reason: str = ""
    cooldown_remaining: float | None = None  # Seconds remaining in cooldown
    instance_id: str | None = None
    model: str | None = None

    def should_proceed(self) -> bool:
        """Check if the request should proceed."""
        return self.action == ActionType.PROCEED


@dataclass
class ResilienceAction:
    """Action taken after processing an error."""

    type: ActionType
    duration: float = 0.0  # Cooldown duration in seconds
    reason: str = ""
    permanent: bool = False  # True for DISABLE_INSTANCE
    fallback_backends: list[str] = field(default_factory=list)  # For FALLBACK action


@dataclass
class ErrorContext:
    """Context passed to error handlers."""

    instance_id: str
    model: str
    error: Exception
    request_id: str | None = None
    extra: dict[str, Any] = field(default_factory=dict)


class IResilienceCoordinator(Protocol):
    """Coordinates resilience decisions before/after backend calls.

    This is the main entry point for the resilience layer, used by
    BackendService to check availability and record outcomes.
    """

    def check_availability(self, instance_id: str, model: str) -> ResilienceDecision:
        """Check if a request to the given instance/model should proceed.

        Args:
            instance_id: Backend connector instance identifier (e.g., "openai.1")
            model: Model name being requested

        Returns:
            ResilienceDecision indicating whether to proceed or reject
        """
        ...

    def record_success(self, instance_id: str, model: str) -> None:
        """Record a successful request, potentially clearing cooldowns.

        Args:
            instance_id: Backend connector instance identifier
            model: Model name that succeeded
        """
        ...

    def record_failure(
        self, instance_id: str, model: str, error: Exception
    ) -> ResilienceAction:
        """Process a failure and determine the appropriate action.

        Args:
            instance_id: Backend connector instance identifier
            model: Model name that failed
            error: The exception that occurred

        Returns:
            ResilienceAction describing what was done (cooldown set, instance disabled, etc.)
        """
        ...


class IErrorHandler(Protocol):
    """Chain of Responsibility handler for specific error types.

    Error handlers form a chain where each handler decides if it can
    handle an error, and if not, passes to the next handler.
    """

    def can_handle(self, error: Exception) -> bool:
        """Check if this handler can process the given error.

        Args:
            error: The exception to check

        Returns:
            True if this handler should process the error
        """
        ...

    def handle(self, context: ErrorContext) -> ResilienceAction:
        """Handle the error and return the action taken.

        Args:
            context: Error context with instance, model, and error details

        Returns:
            ResilienceAction describing what was done
        """
        ...

    def set_next(self, handler: IErrorHandler) -> IErrorHandler:
        """Set the next handler in the chain.

        Args:
            handler: The next handler to call if this one can't handle

        Returns:
            The handler that was set (for fluent chaining)
        """
        ...


class IRecoveryStrategy(Protocol):
    """Strategy pattern interface for recovery behavior.

    Different strategies can define how to recover from failures:
    - Quiet fallback to other backends
    - Exponential backoff with retries
    - Circuit breaker pattern
    """

    def get_recovery_action(self, context: ErrorContext) -> ResilienceAction:
        """Determine the recovery action for the given error context.

        Args:
            context: Error context with instance, model, and error details

        Returns:
            ResilienceAction describing the recovery approach
        """
        ...
