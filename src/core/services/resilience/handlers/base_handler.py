"""
Base error handler for Chain of Responsibility pattern.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

from src.core.interfaces.resilience_interface import (
    ActionType,
    ErrorContext,
    IErrorHandler,
    ResilienceAction,
)

if TYPE_CHECKING:
    from src.core.services.resilience.rate_limit_state import RateLimitStateManager


class BaseErrorHandler(ABC):
    """Base class for error handlers implementing Chain of Responsibility.

    Subclasses should implement:
    - can_handle(error): Return True if this handler processes the error
    - _do_handle(context): Perform the actual handling

    The chain is traversed by calling handle(), which delegates to the next
    handler if this one can't handle the error.
    """

    def __init__(
        self,
        state_manager: RateLimitStateManager,
        next_handler: IErrorHandler | None = None,
    ) -> None:
        """Initialize the handler.

        Args:
            state_manager: The state manager for tracking cooldowns
            next_handler: The next handler in the chain
        """
        self._state = state_manager
        self._next = next_handler

    def set_next(self, handler: IErrorHandler) -> IErrorHandler:
        """Set the next handler in the chain.

        Args:
            handler: The next handler to call if this one can't handle

        Returns:
            The handler that was set (for fluent chaining)
        """
        self._next = handler
        return handler

    @abstractmethod
    def can_handle(self, error: Exception) -> bool:
        """Check if this handler can process the given error.

        Args:
            error: The exception to check

        Returns:
            True if this handler should process the error
        """

    @abstractmethod
    def _do_handle(self, context: ErrorContext) -> ResilienceAction:
        """Perform the actual error handling.

        Args:
            context: Error context with instance, model, and error details

        Returns:
            ResilienceAction describing what was done
        """

    def handle(self, context: ErrorContext) -> ResilienceAction:
        """Handle the error, delegating to next handler if can't handle.

        Args:
            context: Error context with instance, model, and error details

        Returns:
            ResilienceAction describing what was done
        """
        if self.can_handle(context.error):
            return self._do_handle(context)

        if self._next:
            return self._next.handle(context)

        # No handler could handle the error
        return ResilienceAction(
            type=ActionType.PROCEED,
            reason=f"No handler for {type(context.error).__name__}",
        )
