"""
Resilience coordinator for backend error handling.

The ResilienceCoordinator is the main entry point for the resilience layer,
coordinating pre-call availability checks and post-call failure handling.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from src.core.interfaces.provider_error_classifier_interface import (
    IProviderErrorClassifier,
)
from src.core.interfaces.resilience_interface import (
    ActionType,
    ErrorContext,
    IErrorHandler,
    ResilienceAction,
    ResilienceDecision,
)
from src.core.services.resilience.circuit_breaker_state import (
    CircuitBreakerStateManager,
)
from src.core.services.resilience.rate_limit_state import (
    InstanceStatus,
    RateLimitStateManager,
)

if TYPE_CHECKING:
    from src.core.services.health.endpoint_registry import EndpointRegistry

logger = logging.getLogger(__name__)


class ResilienceCoordinator:
    """Coordinates resilience decisions before/after backend calls.

    This is the main entry point for the resilience layer, used by
    BackendService to check availability and record outcomes.

    Usage:
        coordinator = ResilienceCoordinator(state_manager, error_handler_chain)

        # Before calling backend
        decision = coordinator.check_availability("openai.1", "gpt-4o")
        if not decision.should_proceed():
            raise RateLimitExceededError(decision.reason)

        # After successful call
        coordinator.record_success("openai.1", "gpt-4o")

        # After failed call
        action = coordinator.record_failure("openai.1", "gpt-4o", error)
    """

    def __init__(
        self,
        state_manager: RateLimitStateManager,
        provider_error_classifier: IProviderErrorClassifier,
        error_handler_chain: IErrorHandler | None = None,
        default_cooldown: float = 60.0,
        circuit_breaker_state: CircuitBreakerStateManager | None = None,
        endpoint_registry: EndpointRegistry | None = None,
        health_gating_enabled: bool = False,
    ) -> None:
        """Initialize the coordinator.

        Args:
            state_manager: The state manager for tracking cooldowns
            error_handler_chain: Optional chain of error handlers
            default_cooldown: Default cooldown duration when retry-after is not provided
            provider_error_classifier: Canonical provider error classifier
        """
        self._state = state_manager
        self._error_chain = error_handler_chain
        self._default_cooldown = default_cooldown
        self._provider_error_classifier = provider_error_classifier
        self._circuit_breaker_state = circuit_breaker_state
        self._endpoint_registry = endpoint_registry
        self._health_gating_enabled = health_gating_enabled

    @property
    def state_manager(self) -> RateLimitStateManager:
        """Access the underlying state manager for diagnostics."""
        return self._state

    def check_availability(self, instance_id: str, model: str) -> ResilienceDecision:
        """Check if a request to the given instance/model should proceed.

        Checks in order:
        1. Instance-level status (disabled or rate limited)
        2. Model-level cooldown

        Args:
            instance_id: Backend connector instance identifier (e.g., "openai.1")
            model: Model name being requested

        Returns:
            ResilienceDecision indicating whether to proceed or reject
        """
        if self._health_gating_enabled and self._endpoint_registry is not None:
            backend_name = instance_id.split(":", 1)[0]
            if not self._endpoint_registry.is_backend_healthy(backend_name):
                return ResilienceDecision(
                    action=ActionType.REJECT,
                    reason="endpoint_unhealthy",
                    instance_id=instance_id,
                    model=model,
                )

        if self._circuit_breaker_state is not None:
            circuit_decision = self._circuit_breaker_state.check(instance_id)
            if not circuit_decision.should_proceed:
                return ResilienceDecision(
                    action=ActionType.REJECT,
                    reason=circuit_decision.reason,
                    cooldown_remaining=circuit_decision.cooldown_remaining,
                    instance_id=instance_id,
                    model=model,
                )

        # Check instance first
        instance_status = self._state.get_instance_status(instance_id)

        if instance_status == InstanceStatus.DISABLED:
            instance_result = self._state.check_instance_availability(instance_id)
            return ResilienceDecision(
                action=ActionType.REJECT,
                reason=instance_result.reason or "Instance disabled",
                instance_id=instance_id,
                model=model,
            )

        if instance_status == InstanceStatus.RATE_LIMITED:
            instance_result = self._state.check_instance_availability(instance_id)
            return ResilienceDecision(
                action=ActionType.REJECT,
                reason="Instance rate limited (all models)",
                cooldown_remaining=instance_result.cooldown_remaining,
                instance_id=instance_id,
                model=model,
            )

        # Check model-specific cooldown
        model_result = self._state.check_model_availability(instance_id, model)
        if not model_result.available:
            return ResilienceDecision(
                action=ActionType.REJECT,
                reason=model_result.reason or f"Model {model} rate limited",
                cooldown_remaining=model_result.cooldown_remaining,
                instance_id=instance_id,
                model=model,
            )

        return ResilienceDecision(
            action=ActionType.PROCEED,
            instance_id=instance_id,
            model=model,
        )

    def try_acquire_circuit_breaker_probe(self, instance_id: str) -> bool:
        """Reserve half-open probe capacity for the current request."""
        if self._circuit_breaker_state is None:
            return True
        return self._circuit_breaker_state.try_acquire_half_open_probe(instance_id)

    def release_circuit_breaker_probe(self, instance_id: str) -> None:
        """Release previously reserved half-open probe capacity."""
        if self._circuit_breaker_state is None:
            return
        self._circuit_breaker_state.release_half_open_probe(instance_id)

    def record_success(self, instance_id: str, model: str) -> None:
        """Record a successful request, clearing any model cooldown.

        A successful request indicates the model is working, so we clear
        the model-level cooldown. Instance-level cooldown is not cleared
        here as it may affect other models.

        Args:
            instance_id: Backend connector instance identifier
            model: Model name that succeeded
        """
        # Clear model-level cooldown on success
        self._state.clear_cooldown(instance_id, model)
        if self._circuit_breaker_state is not None:
            self._circuit_breaker_state.record_success(instance_id)

        if logger.isEnabledFor(logging.DEBUG):
            logger.debug(
                "Recorded success for %s:%s, cleared any cooldown",
                instance_id,
                model,
            )

    def record_failure(
        self, instance_id: str, model: str, error: Exception
    ) -> ResilienceAction:
        """Process a failure and determine the appropriate action.

        Delegates to the error handler chain if available, otherwise
        applies default handling.

        Args:
            instance_id: Backend connector instance identifier
            model: Model name that failed
            error: The exception that occurred

        Returns:
            ResilienceAction describing what was done
        """
        extra = getattr(error, "__resilience_context__", None)
        context = ErrorContext(
            instance_id=instance_id,
            model=model,
            error=error,
            extra=extra if isinstance(extra, dict) else {},
        )

        classification = self._provider_error_classifier.classify(error)
        if classification.code == "unsupported_on_instance":
            self._state.mark_model_unsupported(
                instance_id,
                model,
                reason=classification.reason,
            )
            if logger.isEnabledFor(logging.INFO):
                logger.info(
                    "Marked permanent unsupported pair %s:%s (%s)",
                    instance_id,
                    model,
                    classification.reason,
                )
            return ResilienceAction(
                type=ActionType.PROCEED,
                reason="unsupported_on_instance",
            )

        # Try the error handler chain (it will delegate through the chain)
        if self._error_chain:
            action = self._error_chain.handle(context)
            if action.type != ActionType.PROCEED or action.reason:
                if logger.isEnabledFor(logging.DEBUG):
                    logger.debug(
                        "Error handled by chain for %s:%s: %s",
                        instance_id,
                        model,
                        action.type.value,
                    )
                return action

        # Default handling: log and return no action
        if logger.isEnabledFor(logging.DEBUG):
            logger.debug(
                "No handler for error on %s:%s: %s",
                instance_id,
                model,
                type(error).__name__,
            )

        return ResilienceAction(
            type=ActionType.PROCEED,  # No special action taken
            reason=f"Unhandled error: {type(error).__name__}",
        )

    def set_error_handler_chain(self, handler: IErrorHandler) -> None:
        """Set or replace the error handler chain.

        Args:
            handler: The first handler in the chain
        """
        self._error_chain = handler
