"""
Rate limit state management for the resilience layer.

This module tracks availability state at two granularities:
1. Backend Instance (e.g., "openai.1") - affects ALL models on that instance
2. (Instance, Model) pair (e.g., ("openai.1", "gpt-4o")) - affects only that model

Lookup Order:
- First check instance-level state (if instance is limited/disabled, reject immediately)
- Then check model-level state (if specific model is limited, reject for that model)
"""

from __future__ import annotations

import logging
import time
from collections.abc import MutableMapping
from dataclasses import dataclass
from enum import Enum

from cachetools import TTLCache

logger = logging.getLogger(__name__)


class InstanceStatus(Enum):
    """Status of a backend connector instance."""

    ACTIVE = "active"  # Normal operation
    RATE_LIMITED = "rate_limited"  # Temporary cooldown (429 with retry-after)
    DISABLED = "disabled"  # Permanent failure (auth error, invalid key)


@dataclass
class InstanceState:
    """State for a backend connector instance."""

    status: InstanceStatus = InstanceStatus.ACTIVE
    cooldown_until: float | None = None  # Unix timestamp when cooldown ends
    disabled_reason: str | None = None  # Why instance was disabled
    disabled_at: float | None = None  # When instance was disabled


@dataclass
class ModelState:
    """State for a specific model on an instance."""

    cooldown_until: float | None = None  # Unix timestamp when cooldown ends
    retry_count: int = 0  # Number of consecutive failures
    unsupported_permanent: bool = False
    unsupported_reason: str | None = None
    unsupported_at: float | None = None


@dataclass
class AvailabilityResult:
    """Result of checking availability."""

    available: bool
    reason: str = ""
    cooldown_remaining: float | None = None


class RateLimitStateManager:
    """Tracks rate-limit state at two granularities with retry-after support.

    This class maintains state for:
    - Backend instances (API key level rate limits)
    - (Instance, Model) pairs (model-specific rate limits)

    Thread Safety:
        This class is NOT thread-safe. In async context, access should be
        serialized or use appropriate locking if needed.
    """

    def __init__(self) -> None:
        """Initialize the state manager."""
        # Use TTLCache to prevent unbounded growth (memory leak protection).
        # TTL of 3600s (1 hour) is sufficient for most rate limits.
        # Maxsize prevents memory exhaustion if random keys are generated.
        self._instance_state: MutableMapping[str, InstanceState] = TTLCache(
            maxsize=1000, ttl=3600
        )
        self._model_state: MutableMapping[tuple[str, str], ModelState] = TTLCache(
            maxsize=10000, ttl=3600
        )

    # -------------------------------------------------------------------------
    # Instance-Level Operations
    # -------------------------------------------------------------------------

    def get_instance_status(self, instance_id: str) -> InstanceStatus:
        """Get the current status of a backend instance.

        Args:
            instance_id: Backend connector instance identifier

        Returns:
            Current InstanceStatus (ACTIVE, RATE_LIMITED, or DISABLED)
        """
        state = self._instance_state.get(instance_id)
        if not state:
            return InstanceStatus.ACTIVE

        if state.status == InstanceStatus.DISABLED:
            return InstanceStatus.DISABLED

        if state.status == InstanceStatus.RATE_LIMITED:
            if state.cooldown_until and time.time() < state.cooldown_until:
                return InstanceStatus.RATE_LIMITED
            # Cooldown expired, remove from state to free memory
            self._instance_state.pop(instance_id, None)

        return InstanceStatus.ACTIVE

    def is_instance_available(self, instance_id: str) -> bool:
        """Check if instance can accept ANY requests.

        Args:
            instance_id: Backend connector instance identifier

        Returns:
            False if instance is rate-limited OR disabled
        """
        return self.get_instance_status(instance_id) == InstanceStatus.ACTIVE

    def check_instance_availability(self, instance_id: str) -> AvailabilityResult:
        """Check instance availability with detailed reason.

        Args:
            instance_id: Backend connector instance identifier

        Returns:
            AvailabilityResult with status, reason, and cooldown info
        """
        status = self.get_instance_status(instance_id)

        if status == InstanceStatus.ACTIVE:
            return AvailabilityResult(available=True)

        state = self._instance_state.get(instance_id)
        if not state:
            # Should be covered by status check, but for safety
            return AvailabilityResult(available=True)

        if status == InstanceStatus.DISABLED:
            return AvailabilityResult(
                available=False,
                reason=f"Instance disabled: {state.disabled_reason or 'unknown'}",
            )

        if status == InstanceStatus.RATE_LIMITED:
            remaining = (
                state.cooldown_until - time.time() if state.cooldown_until else 0.0
            )
            return AvailabilityResult(
                available=False,
                reason="Instance rate limited",
                cooldown_remaining=max(0.0, remaining),
            )

        return AvailabilityResult(available=True)

    def set_instance_cooldown(
        self, instance_id: str, retry_after_seconds: float
    ) -> None:
        """Set instance-level cooldown from retry-after header.

        This affects ALL models on this instance.

        Args:
            instance_id: Backend connector instance identifier
            retry_after_seconds: Duration of cooldown in seconds
        """
        cooldown_until = time.time() + retry_after_seconds
        state = self._instance_state.get(instance_id)

        if state and state.status == InstanceStatus.DISABLED:
            # Don't overwrite disabled status with rate limit
            logger.debug(
                "Instance %s is disabled, ignoring cooldown request", instance_id
            )
            return

        self._instance_state[instance_id] = InstanceState(
            status=InstanceStatus.RATE_LIMITED,
            cooldown_until=cooldown_until,
        )
        logger.info(
            "Instance %s rate limited for %.1f seconds (all models affected)",
            instance_id,
            retry_after_seconds,
        )

    def disable_instance(self, instance_id: str, reason: str) -> None:
        """Permanently disable instance (auth failure, invalid config).

        Args:
            instance_id: Backend connector instance identifier
            reason: Human-readable reason for disabling
        """
        self._instance_state[instance_id] = InstanceState(
            status=InstanceStatus.DISABLED,
            disabled_reason=reason,
            disabled_at=time.time(),
        )
        logger.warning(
            "Instance %s permanently disabled: %s",
            instance_id,
            reason,
        )

    def reactivate_instance(self, instance_id: str) -> bool:
        """Manually reactivate a disabled instance.

        Args:
            instance_id: Backend connector instance identifier

        Returns:
            True if instance was reactivated, False if not found or already active
        """
        state = self._instance_state.get(instance_id)
        if not state:
            return False

        if state.status == InstanceStatus.ACTIVE:
            return False

        self._instance_state[instance_id] = InstanceState(status=InstanceStatus.ACTIVE)
        logger.info("Instance %s reactivated", instance_id)
        return True

    # -------------------------------------------------------------------------
    # Model-Level Operations
    # -------------------------------------------------------------------------

    def is_model_available(self, instance_id: str, model: str) -> bool:
        """Check if specific model on instance can accept requests.

        Instance availability is checked first.

        Args:
            instance_id: Backend connector instance identifier
            model: Model name

        Returns:
            False if instance is unavailable OR model is in cooldown
        """
        # Instance-level takes precedence
        if not self.is_instance_available(instance_id):
            return False

        # Check model-specific cooldown
        key = (instance_id, model)
        state = self._model_state.get(key)
        if not state:
            return True

        if state.unsupported_permanent:
            return False

        if state.cooldown_until is None:
            return True

        if time.time() >= state.cooldown_until:
            # Cooldown expired, remove from state
            if state.unsupported_permanent:
                state.cooldown_until = None
                self._model_state[key] = state
            else:
                self._model_state.pop(key, None)
            return True

        return False

    def check_model_availability(
        self, instance_id: str, model: str
    ) -> AvailabilityResult:
        """Check model availability with detailed reason.

        Args:
            instance_id: Backend connector instance identifier
            model: Model name

        Returns:
            AvailabilityResult with status, reason, and cooldown info
        """
        # Check instance first
        instance_result = self.check_instance_availability(instance_id)
        if not instance_result.available:
            return instance_result

        # Check model-specific
        key = (instance_id, model)
        state = self._model_state.get(key)

        if not state:
            return AvailabilityResult(available=True)

        if state.unsupported_permanent:
            return AvailabilityResult(
                available=False,
                reason=(
                    f"Model {model} permanently unsupported on {instance_id}: "
                    f"{state.unsupported_reason or 'unknown reason'}"
                ),
            )

        if state.cooldown_until is None:
            return AvailabilityResult(available=True)

        if time.time() >= state.cooldown_until:
            # Cooldown expired, remove from state
            if state.unsupported_permanent:
                state.cooldown_until = None
                self._model_state[key] = state
            else:
                self._model_state.pop(key, None)
            return AvailabilityResult(available=True)

        remaining = state.cooldown_until - time.time()
        return AvailabilityResult(
            available=False,
            reason=f"Model {model} rate limited on {instance_id}",
            cooldown_remaining=max(0.0, remaining),
        )

    def set_model_cooldown(
        self, instance_id: str, model: str, retry_after_seconds: float
    ) -> None:
        """Set model-level cooldown from retry-after header.

        This only affects the specific (instance, model) pair.

        Args:
            instance_id: Backend connector instance identifier
            model: Model name
            retry_after_seconds: Duration of cooldown in seconds
        """
        cooldown_until = time.time() + retry_after_seconds
        key = (instance_id, model)

        existing = self._model_state.get(key)
        if existing and existing.unsupported_permanent:
            logger.debug(
                "Model %s on %s is permanently unsupported, ignoring cooldown request",
                model,
                instance_id,
            )
            return
        retry_count = existing.retry_count + 1 if existing else 1

        self._model_state[key] = ModelState(
            cooldown_until=cooldown_until,
            retry_count=retry_count,
        )
        logger.info(
            "Model %s on instance %s rate limited for %.1f seconds",
            model,
            instance_id,
            retry_after_seconds,
        )

    def mark_model_unsupported(self, instance_id: str, model: str, reason: str) -> None:
        """Mark a specific (instance, model) pair as permanently unsupported."""
        key = (instance_id, model)
        existing = self._model_state.get(key)
        retry_count = existing.retry_count if existing else 0
        self._model_state[key] = ModelState(
            cooldown_until=None,
            retry_count=retry_count,
            unsupported_permanent=True,
            unsupported_reason=reason,
            unsupported_at=time.time(),
        )
        logger.warning(
            "Model %s permanently unsupported on instance %s: %s",
            model,
            instance_id,
            reason,
        )

    def clear_model_unsupported(self, instance_id: str, model: str) -> bool:
        """Explicitly clear permanent unsupported state for a pair."""
        key = (instance_id, model)
        state = self._model_state.get(key)
        if not state or not state.unsupported_permanent:
            return False

        if state.cooldown_until is None and state.retry_count == 0:
            self._model_state.pop(key, None)
        else:
            state.unsupported_permanent = False
            state.unsupported_reason = None
            state.unsupported_at = None
            self._model_state[key] = state
        logger.info(
            "Cleared permanent unsupported state for model %s on instance %s",
            model,
            instance_id,
        )
        return True

    def clear_unsupported_for_instance(self, instance_id: str) -> int:
        """Explicitly clear permanent unsupported state for all models on instance."""
        cleared = 0
        for (candidate_instance, model), state in list(self._model_state.items()):
            if candidate_instance != instance_id or not state.unsupported_permanent:
                continue
            if self.clear_model_unsupported(instance_id, model):
                cleared += 1
        return cleared

    # -------------------------------------------------------------------------
    # Cooldown Management
    # -------------------------------------------------------------------------

    def get_cooldown_remaining(
        self, instance_id: str, model: str | None = None
    ) -> float | None:
        """Get seconds remaining in cooldown (for logging/headers).

        Args:
            instance_id: Backend connector instance identifier
            model: Optional model name; if None, only checks instance

        Returns:
            Seconds remaining in cooldown, or None if not in cooldown
        """
        # Check instance first
        state = self._instance_state.get(instance_id)
        if state and state.cooldown_until:
            remaining = state.cooldown_until - time.time()
            if remaining > 0:
                return remaining

        # Check model if provided
        if model:
            key = (instance_id, model)
            model_state = self._model_state.get(key)
            if model_state and model_state.cooldown_until:
                remaining = model_state.cooldown_until - time.time()
                if remaining > 0:
                    return remaining

        return None

    def clear_cooldown(self, instance_id: str, model: str | None = None) -> None:
        """Clear cooldown after successful request (recovery probe).

        Args:
            instance_id: Backend connector instance identifier
            model: Optional model name; if None, clears instance cooldown
        """
        if model:
            key = (instance_id, model)
            if key in self._model_state:
                self._model_state[key].cooldown_until = None
                self._model_state[key].retry_count = 0
                logger.debug(
                    "Cleared cooldown for model %s on instance %s", model, instance_id
                )
        else:
            state = self._instance_state.get(instance_id)
            if state and state.status == InstanceStatus.RATE_LIMITED:
                state.status = InstanceStatus.ACTIVE
                state.cooldown_until = None
                logger.debug("Cleared cooldown for instance %s", instance_id)

    # -------------------------------------------------------------------------
    # Diagnostics
    # -------------------------------------------------------------------------

    def get_all_instance_states(self) -> dict[str, dict]:
        """Get all instance states for diagnostics.

        Returns:
            Dictionary mapping instance_id to state info
        """
        result = {}
        for instance_id, state in self._instance_state.items():
            status = self.get_instance_status(instance_id)
            result[instance_id] = {
                "status": status.value,
                "cooldown_remaining": self.get_cooldown_remaining(instance_id),
                "disabled_reason": state.disabled_reason,
                "disabled_at": state.disabled_at,
            }
        return result

    def get_all_model_states(self) -> dict[str, dict]:
        """Get all model states for diagnostics.

        Returns:
            Dictionary mapping "instance_id:model" to state info
        """
        result = {}
        for (instance_id, model), state in self._model_state.items():
            key = f"{instance_id}:{model}"
            result[key] = {
                "cooldown_remaining": self.get_cooldown_remaining(instance_id, model),
                "retry_count": state.retry_count,
                "unsupported_permanent": state.unsupported_permanent,
                "unsupported_reason": state.unsupported_reason,
                "unsupported_at": state.unsupported_at,
            }
        return result
