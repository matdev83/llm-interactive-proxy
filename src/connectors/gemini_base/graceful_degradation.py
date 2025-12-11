"""
Graceful degradation helpers for Gemini OAuth connectors.

This module provides helper functions and state management for graceful
degradation during rate limiting, including:
- Model fallback mapping
- Rate limit error detection
- Cooldown state management
- Retry delay calculations
"""

import logging
import random
import time
from typing import Any

from src.connectors.gemini_base.config import (
    GracefulDegradationConfig,
    GracefulDegradationMetrics,
    ModelRetryState,
)
from src.core.common.exceptions import BackendError

logger = logging.getLogger(__name__)


def is_rate_limit_like_error(error: BackendError) -> bool:
    """Determine whether an error should trigger graceful degradation retries.

    Args:
        error: The BackendError to check.

    Returns:
        True if the error indicates rate limiting or empty response.
    """
    code = getattr(error, "code", None)
    status = getattr(error, "status_code", None)
    return status == 429 or (isinstance(code, str) and code in {"empty_response"})


def is_model_in_cooldown(
    model: str,
    retry_states: dict[str, ModelRetryState],
) -> bool:
    """Check if a model is currently in cooldown.

    Args:
        model: The model to check.
        retry_states: Dictionary of model retry states.

    Returns:
        True if model is in cooldown, False otherwise.
    """
    state = retry_states.get(model)
    if not state:
        return False
    return time.time() < state.cooldown_until


def set_model_cooldown(
    model: str,
    retry_states: dict[str, ModelRetryState],
    cooldown_duration: float,
) -> None:
    """Put a model into cooldown state.

    Args:
        model: The model to put in cooldown.
        retry_states: Dictionary of model retry states.
        cooldown_duration: Duration of cooldown in seconds.
    """
    if model not in retry_states:
        retry_states[model] = ModelRetryState()

    state = retry_states[model]
    state.cooldown_until = time.time() + cooldown_duration
    state.attempts = 0  # Reset attempts after cooldown
    state.probe_success_count = 0

    logger.info(f"Model {model} put in cooldown until {state.cooldown_until}")


def calculate_retry_delay(
    attempt: int,
    retry_delays: list[float],
    jitter_factor: float = 0.25,
    initial_delay: float = 2.0,
    min_delay: float = 0.5,
) -> float:
    """Calculate delay for a retry attempt with jitter.

    Args:
        attempt: The current attempt number (0-indexed).
        retry_delays: List of base delays for retries.
        jitter_factor: Jitter as fraction of base delay (e.g., 0.25 = +/-25%).
        initial_delay: Delay for the first attempt (attempt 0).
        min_delay: Minimum delay to return.

    Returns:
        The calculated delay in seconds with jitter applied.
    """
    if attempt == 0:
        # Initial delay after 429 to avoid immediate retry burst
        base_delay = initial_delay
    else:
        # Retry with configured delays
        delay_idx = min(attempt - 1, len(retry_delays) - 1)
        base_delay = retry_delays[delay_idx]

    # Add jitter: ±jitter_factor of the base delay to prevent synchronized retries
    jitter_range = base_delay * jitter_factor
    jitter = random.uniform(-jitter_range, jitter_range)
    return max(min_delay, base_delay + jitter)


class GracefulDegradationManager:
    """Manages graceful degradation state for a connector."""

    def __init__(
        self,
        config: GracefulDegradationConfig,
        metrics: GracefulDegradationMetrics | None = None,
    ) -> None:
        """Initialize the graceful degradation manager.

        Args:
            config: Configuration for graceful degradation behavior.
            metrics: Optional metrics tracker. Created if not provided.
        """
        self.config = config
        self.metrics = metrics or GracefulDegradationMetrics()
        self.model_retry_states: dict[str, ModelRetryState] = {}
        self.permanently_failed = False

    def is_rate_limit_like_error(self, error: BackendError) -> bool:
        """Determine whether an error should trigger graceful degradation."""
        return is_rate_limit_like_error(error)

    def is_in_cooldown(self, model: str) -> bool:
        """Check if a model is currently in cooldown."""
        return is_model_in_cooldown(model, self.model_retry_states)

    def set_cooldown(self, model: str) -> None:
        """Put a model into cooldown state."""
        set_model_cooldown(
            model, self.model_retry_states, self.config.cooldown_duration
        )

    def calculate_delay(self, attempt: int) -> float:
        """Calculate delay for a retry attempt."""
        return calculate_retry_delay(attempt, self.config.retry_delays)

    def get_or_create_state(self, model: str) -> ModelRetryState:
        """Get or create a retry state for a model.

        Args:
            model: The model to get state for.

        Returns:
            The ModelRetryState for the model.
        """
        if model not in self.model_retry_states:
            self.model_retry_states[model] = ModelRetryState()
        return self.model_retry_states[model]

    def get_models_to_try(self, original_model: str, disable_fallback: bool = False) -> list[str]:
        """Return only the original model; fallbacks are handled upstream."""
        return [original_model]

    def record_attempt(self) -> None:
        """Record an attempt in metrics."""
        self.metrics.record_attempt()

    def record_wait(self, wait_seconds: float) -> None:
        """Record wait time in metrics."""
        self.metrics.record_wait(wait_seconds)

    def record_fallback(self) -> None:
        """Record a fallback invocation in metrics."""
        self.metrics.record_fallback()

    def record_duration(self, duration_seconds: float) -> None:
        """Record total duration in metrics."""
        self.metrics.record_duration(duration_seconds)

    def start_invocation(self) -> float:
        """Start tracking an invocation.

        Returns:
            Start time for duration tracking.
        """
        self.metrics.total_invocations += 1
        return time.time()

    def mark_permanently_failed(self) -> None:
        """Mark graceful degradation as permanently failed."""
        self.permanently_failed = True

    def get_metrics(self) -> dict[str, Any]:
        """Get current metrics as a dictionary."""
        return self.metrics.as_dict()


__all__ = [
    "GracefulDegradationManager",
    "calculate_retry_delay",
    "is_model_in_cooldown",
    "is_rate_limit_like_error",
    "set_model_cooldown",
]
