"""Model replacement service implementation.

This module implements the random model replacement service, which enables
probabilistic swapping of user-specified backend:model pairs with alternative
replacement pairs during a session.
"""

from __future__ import annotations

import asyncio
import logging
import random
from collections.abc import Callable
from typing import TYPE_CHECKING

from src.core.domain.configuration.replacement_config import ReplacementConfig
from src.core.domain.replacement_state import ReplacementState
from src.core.domain.request_context import RequestContext
from src.core.services.replacement_metrics import ReplacementMetrics

if TYPE_CHECKING:
    from src.core.services.backend_registry import BackendRegistry

logger = logging.getLogger(__name__)


class ModelReplacementService:
    """Service for managing random model replacement.

    This service implements probabilistic model replacement with the following features:
    - Configurable probability-based replacement triggering
    - Per-session state management with turn-based windows
    - Thread-safe concurrent session handling
    - Opt-out mechanisms (header-based and session-level)
    - Comprehensive logging for monitoring and debugging
    """

    def __init__(
        self,
        config: ReplacementConfig,
        backend_registry: BackendRegistry,
        random_generator: Callable[[], float] | None = None,
    ) -> None:
        """Initialize the replacement service.

        Args:
            config: Replacement configuration
            backend_registry: Registry for validating backends
            random_generator: Optional random number generator for testing

        Raises:
            ValueError: If configuration is invalid or replacement backend is not registered
        """
        self._config = config
        self._backend_registry = backend_registry
        self._random_generator = random_generator or random.random

        # Performance optimization: Use dictionary for O(1) state lookup
        # This provides constant-time access to session state regardless of
        # the number of concurrent sessions
        self._session_states: dict[str, ReplacementState] = {}
        self._disabled_sessions: set[str] = set()

        # Performance optimization: Minimize lock contention by only locking
        # during state mutations (activate_replacement). Read operations
        # (should_replace, get_effective_backend_model) are lock-free for
        # better concurrency performance
        self._lock = asyncio.Lock()

        # Performance optimization: Cache parsed backend:model to avoid
        # repeated string parsing on every activation
        self._cached_replacement_backend: str | None = None
        self._cached_replacement_model: str | None = None

        # Performance optimization: Cache configuration values for faster
        # access during probability evaluation (avoid attribute lookups)
        self._cached_enabled: bool = config.enabled
        self._cached_probability: float = config.probability
        self._cached_turn_count: int = config.turn_count

        # Metrics tracking for monitoring and analysis
        self._metrics = ReplacementMetrics()

        # Performance optimization: Sample probability check debug logs to reduce
        # hot-path overhead while still emitting visibility points.
        self._probability_log_every_n = 1000
        self._probability_log_counter = 0

        # Validate configuration with detailed error logging
        try:
            self._config.validate_config()
        except ValueError as e:
            logger.error(
                f"Model replacement service configuration validation failed: {e}. "
                f"Configuration: enabled={self._config.enabled}, "
                f"probability={self._config.probability}, "
                f"backend_model={self._config.backend_model}, "
                f"turn_count={self._config.turn_count}"
            )
            raise

        # Validate replacement backend exists and cache parsed values
        if self._config.enabled:
            try:
                replacement_backend, replacement_model = (
                    self._config.parse_backend_model()
                )

                # Performance optimization: Cache parsed backend:model to avoid
                # repeated string parsing on every activation
                self._cached_replacement_backend = replacement_backend
                self._cached_replacement_model = replacement_model

                registered_backends = self._backend_registry.get_registered_backends()
                if replacement_backend not in registered_backends:
                    error_msg = (
                        f"Replacement backend '{replacement_backend}' is not registered. "
                        f"Available backends: {', '.join(registered_backends)}"
                    )
                    logger.error(
                        f"Model replacement service initialization failed: {error_msg}"
                    )
                    raise ValueError(error_msg)
            except ValueError:
                # Re-raise ValueError from backend validation
                raise
            except Exception as e:
                logger.error(
                    f"Error validating replacement backend: {e}. "
                    f"Backend model: {self._config.backend_model}",
                    exc_info=True,
                )
                raise ValueError(f"Failed to validate replacement backend: {e}") from e

        logger.info(
            f"Model replacement service initialized: "
            f"enabled={self._config.enabled}, "
            f"probability={self._config.probability}, "
            f"backend_model={self._config.backend_model}, "
            f"turn_count={self._config.turn_count}"
        )

    def should_replace(
        self,
        session_id: str,
        request_context: RequestContext,
    ) -> bool:
        """Determine if replacement should be triggered for this request.

        Args:
            session_id: The session identifier
            request_context: The request context containing headers and state

        Returns:
            True if replacement should be triggered, False otherwise
        """
        # Performance optimization: Use cached enabled flag to avoid attribute lookup
        if not self._cached_enabled:
            return False

        # Check if session is disabled
        if session_id in self._disabled_sessions:
            logger.debug(f"Replacement disabled for session {session_id}")
            # Track session-level opt-out (Requirement 9.2)
            self._metrics.record_opt_out(session_id, "session")
            return False

        # Check for opt-out header
        disable_header = request_context.get_header("x-disable-replacement", "")
        if disable_header and disable_header.lower() == "true":
            logger.debug(f"Replacement disabled by header for session {session_id}")
            # Track header-based opt-out (Requirement 9.1)
            self._metrics.record_opt_out(session_id, "header")
            return False

        # Get or create state
        state = self._session_states.get(session_id)
        if state is None:
            state = ReplacementState()
            self._session_states[session_id] = state

        # If already active, continue replacement
        if state.active:
            return True

        # Track probability check for metrics
        self._metrics.record_probability_check(session_id)

        # Sample debug logging to avoid per-call overhead in hot paths.
        self._probability_log_counter += 1

        # Performance optimization: Use cached probability value for faster comparison
        # Evaluate probability using efficient random number generation
        random_value = self._random_generator()
        should_activate = random_value < self._cached_probability

        # Log probability check for debugging and monitoring (Requirement 6.4)
        if (
            self._probability_log_counter == 1
            or self._probability_log_counter % self._probability_log_every_n == 0
        ):
            logger.debug(
                f"Replacement probability check for session {session_id}: "
                f"random={random_value:.4f}, threshold={self._cached_probability:.4f}, "
                f"activate={should_activate}"
            )

        return should_activate

    def get_effective_backend_model(
        self,
        session_id: str,
        original_backend: str,
        original_model: str,
    ) -> tuple[str, str]:
        """Get the effective backend:model to use for this request.

        Args:
            session_id: The session identifier
            original_backend: The user-specified backend name
            original_model: The user-specified model name

        Returns:
            Tuple of (backend, model) to use for the request
        """
        state = self._session_states.get(session_id)

        # If replacement is not active, use original
        if state is None or not state.active:
            return (original_backend, original_model)

        # Validate replacement backend is still available
        try:
            registered_backends = self._backend_registry.get_registered_backends()
            if state.replacement_backend not in registered_backends:
                logger.warning(
                    f"Replacement backend '{state.replacement_backend}' is no longer available "
                    f"for session {session_id}. Falling back to original backend "
                    f"'{original_backend}:{original_model}'. "
                    f"Available backends: {', '.join(registered_backends)}"
                )
                # Deactivate replacement and fall back to original
                state.deactivate()
                return (original_backend, original_model)
        except Exception as e:
            logger.warning(
                f"Error checking replacement backend availability for session {session_id}: {e}. "
                f"Falling back to original backend '{original_backend}:{original_model}'",
                exc_info=True,
            )
            # Deactivate replacement and fall back to original
            state.deactivate()
            return (original_backend, original_model)

        # If replacement is active, use replacement
        logger.debug(
            f"Using replacement model for session {session_id}: "
            f"{state.replacement_backend}:{state.replacement_model}"
        )
        return (state.replacement_backend, state.replacement_model)

    async def activate_replacement(
        self,
        session_id: str,
        original_backend: str,
        original_model: str,
    ) -> None:
        """Activate replacement for a session.

        Args:
            session_id: The session identifier
            original_backend: The user-specified backend name
            original_model: The user-specified model name
        """
        async with self._lock:
            # Performance optimization: Use cached parsed values instead of
            # parsing backend_model string on every activation
            if (
                self._cached_replacement_backend is None
                or self._cached_replacement_model is None
            ):
                # Fallback to parsing if cache is not initialized (shouldn't happen)
                replacement_backend, replacement_model = (
                    self._config.parse_backend_model()
                )
            else:
                replacement_backend = self._cached_replacement_backend
                replacement_model = self._cached_replacement_model

            state = self._session_states.get(session_id)
            if state is None:
                state = ReplacementState()
                self._session_states[session_id] = state

            # Performance optimization: Use cached turn_count value
            state.activate(
                turn_count=self._cached_turn_count,
                original_backend=original_backend,
                original_model=original_model,
                replacement_backend=replacement_backend,
                replacement_model=replacement_model,
            )

            # Track activation for metrics (Requirement 3.2)
            self._metrics.record_activation(session_id, self._cached_turn_count)

            logger.info(
                f"Replacement activated for session {session_id}: "
                f"{original_backend}:{original_model} -> "
                f"{replacement_backend}:{replacement_model} "
                f"for {self._cached_turn_count} turns"
            )

    def complete_turn(self, session_id: str) -> None:
        """Mark a turn as complete and update replacement state.

        Args:
            session_id: The session identifier
        """
        state = self._session_states.get(session_id)
        if state is not None and state.active:
            # Track turn completion for metrics (Requirement 4.1)
            self._metrics.record_turn_completion(session_id)

            state.decrement_turn()

            if not state.active:
                logger.info(
                    f"Replacement deactivated for session {session_id}: "
                    f"returning to {state.original_backend}:{state.original_model}"
                )

    def get_state(self, session_id: str) -> ReplacementState:
        """Get current replacement state for a session.

        Args:
            session_id: The session identifier

        Returns:
            The replacement state for the session
        """
        state = self._session_states.get(session_id)
        if state is None:
            state = ReplacementState()
            self._session_states[session_id] = state
        else:
            # Validate state integrity
            if not self._validate_state(state):
                logger.error(
                    f"Detected corrupted replacement state for session {session_id}: "
                    f"active={state.active}, turns_remaining={state.turns_remaining}, "
                    f"original_backend={state.original_backend}, original_model={state.original_model}, "
                    f"replacement_backend={state.replacement_backend}, replacement_model={state.replacement_model}. "
                    f"Resetting to inactive state."
                )
                # Reset to clean state
                state = ReplacementState()
                self._session_states[session_id] = state
        return state

    def _validate_state(self, state: ReplacementState) -> bool:
        """Validate that replacement state is not corrupted.

        Args:
            state: The replacement state to validate

        Returns:
            True if state is valid, False if corrupted
        """
        try:
            # Check for invalid combinations
            if state.active:
                # If active, must have positive turns remaining
                if state.turns_remaining <= 0:
                    return False
                # If active, must have backend and model information
                if not state.original_backend or not state.original_model:
                    return False
                if not state.replacement_backend or not state.replacement_model:
                    return False
            else:
                # If inactive, turns_remaining should be 0
                if state.turns_remaining != 0:
                    return False

            return state.turns_remaining >= 0
        except Exception as e:
            logger.error(f"Error validating replacement state: {e}", exc_info=True)
            return False

    def disable_for_session(self, session_id: str) -> None:
        """Disable replacement for a specific session.

        Args:
            session_id: The session identifier
        """
        self._disabled_sessions.add(session_id)

        # Deactivate any active replacement
        state = self._session_states.get(session_id)
        if state is not None and state.active:
            state.deactivate()
            logger.info(
                f"Replacement disabled and deactivated for session {session_id}"
            )

    def cleanup_session(self, session_id: str) -> None:
        """Clean up state for an ended session.

        Args:
            session_id: The session identifier
        """
        self._session_states.pop(session_id, None)
        self._disabled_sessions.discard(session_id)

    def get_metrics(self) -> ReplacementMetrics:
        """Get current replacement metrics.

        Returns:
            The replacement metrics object
        """
        return self._metrics

    def log_metrics_summary(self) -> None:
        """Log a comprehensive metrics summary."""
        self._metrics.log_summary()

    def reset_metrics(self) -> None:
        """Reset all metrics to initial state."""
        self._metrics.reset()
