"""Model replacement service implementation.

This module implements the random model replacement service, which enables
probabilistic swapping of user-specified backend:model pairs with alternative
replacement pairs during a session.
"""

from __future__ import annotations

import asyncio
import logging
import random
from collections import OrderedDict
from collections.abc import Callable
from typing import TYPE_CHECKING

from src.core.domain.configuration.replacement_config import ReplacementConfig
from src.core.domain.replacement_state import ReplacementState
from src.core.domain.request_context import RequestContext
from src.core.services.replacement_metrics import ReplacementMetrics

if TYPE_CHECKING:
    from src.core.services.backend_registry import BackendRegistry

logger = logging.getLogger(__name__)

# Maximum number of session states to keep in memory to prevent unbounded growth.
# 10,000 sessions is roughly ~2-3 MB of memory, providing a large window
# for active sessions without unbounded growth. Eviction uses LRU policy.
MAX_SESSION_STATES = 10_000

# Maximum number of disabled session IDs to keep in memory.
# 1,000 disabled sessions is roughly ~50-100 KB of memory.
MAX_DISABLED_SESSIONS = 1_000


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

        # Performance optimization: Use OrderedDict for O(1) state lookup with LRU eviction
        # This provides constant-time access to session state regardless of
        # the number of concurrent sessions, with automatic eviction of oldest entries
        # to prevent unbounded memory growth
        self._session_states: OrderedDict[str, ReplacementState] = OrderedDict()
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
        # Log every request in DEBUG mode for better visibility during development/troubleshooting.
        self._probability_log_every_n = 1
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
                f"turn_count={self._config.turn_count}",
                exc_info=True,
            )
            raise

        # Validate replacement backend exists and cache parsed values
        if self._config.enabled:
            try:
                parsed = self._config.parse_backend_model()

                # Performance optimization: Cache parsed backend:model to avoid
                # repeated string parsing on every activation
                self._cached_replacement_backend = parsed.backend
                self._cached_replacement_model = parsed.model

                registered_backends = self._backend_registry.get_registered_backends()
                if parsed.backend not in registered_backends:
                    error_msg = (
                        f"Replacement backend '{parsed.backend}' is not registered. "
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

        if logger.isEnabledFor(logging.INFO):
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
            if logger.isEnabledFor(logging.DEBUG):
                logger.debug(f"Replacement disabled for session {session_id}")
            # Track session-level opt-out (Requirement 9.2)
            self._metrics.record_opt_out(session_id, "session")
            return False

        # Check for opt-out header
        disable_header = request_context.get_header("x-disable-replacement", "")
        if disable_header and disable_header.lower() == "true":
            if logger.isEnabledFor(logging.DEBUG):
                logger.debug(f"Replacement disabled by header for session {session_id}")
            # Track header-based opt-out (Requirement 9.1)
            self._metrics.record_opt_out(session_id, "header")
            return False

        # Get state, but don't create it yet
        state = self._session_states.get(session_id)

        # If state doesn't exist, it's the first turn of the session.
        # Guarantee the original model is used and skip the dice roll.
        if state is None:
            state = ReplacementState()
            self._session_states[session_id] = state
            self._session_states.move_to_end(session_id)
            self._evict_oldest_sessions_if_needed()
            if logger.isEnabledFor(logging.DEBUG):
                logger.debug(
                    f"First turn for session {session_id}; skipping replacement check."
                )
            return False

        # If we're here, it's not the first turn. Move state to end for LRU.
        self._session_states.move_to_end(session_id)

        # Enforce cool-down period if active
        if state.consume_cool_down():
            if logger.isEnabledFor(logging.DEBUG):
                logger.debug(
                    f"Enforcing cool-down for session {session_id}; skipping dice roll."
                )
            return False

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
        ) and logger.isEnabledFor(logging.DEBUG):
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

        # Move to end (most recently used) for LRU tracking
        self._session_states.move_to_end(session_id)

        # Validate replacement backend is still available
        try:
            registered_backends = self._backend_registry.get_registered_backends()
            if state.replacement_backend not in registered_backends:
                if logger.isEnabledFor(logging.WARNING):
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
            if logger.isEnabledFor(logging.WARNING):
                logger.warning(
                    f"Error checking replacement backend availability for session {session_id}: {e}. "
                    f"Falling back to original backend '{original_backend}:{original_model}'",
                    exc_info=True,
                )
            # Deactivate replacement and fall back to original
            state.deactivate()
            return (original_backend, original_model)

        # If replacement is active, use replacement
        if logger.isEnabledFor(logging.DEBUG):
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
                parsed = self._config.parse_backend_model()
                replacement_backend = parsed.backend
                replacement_model = parsed.model
            else:
                replacement_backend = self._cached_replacement_backend
                replacement_model = self._cached_replacement_model

            state = self._session_states.get(session_id)
            if state is None:
                state = ReplacementState()
                self._session_states[session_id] = state
                # Move to end (most recently used) for LRU tracking
                self._session_states.move_to_end(session_id)
                # Evict oldest entries if over limit
                self._evict_oldest_sessions_if_needed()
            else:
                # Move to end (most recently used) for LRU tracking
                self._session_states.move_to_end(session_id)

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

            if logger.isEnabledFor(logging.INFO):
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
            # Move to end (most recently used) for LRU tracking
            self._session_states.move_to_end(session_id)
            # Track turn completion for metrics (Requirement 4.1)
            self._metrics.record_turn_completion(session_id)

            state.decrement_turn()

            if not state.active and logger.isEnabledFor(logging.INFO):
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
            # Move to end (most recently used) for LRU tracking
            self._session_states.move_to_end(session_id)
            # Evict oldest entries if over limit
            self._evict_oldest_sessions_if_needed()
        else:
            # Move to end (most recently used) for LRU tracking
            self._session_states.move_to_end(session_id)
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
                self._session_states.move_to_end(session_id)
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
        # Evict oldest disabled sessions if over limit
        if len(self._disabled_sessions) > MAX_DISABLED_SESSIONS:
            # Remove oldest entries (convert to list, take oldest, remove from set)
            excess = len(self._disabled_sessions) - MAX_DISABLED_SESSIONS
            # Since sets don't have order, we'll remove sessions that are not in _session_states
            # (they're likely older/inactive)
            to_remove = [
                sid
                for sid in self._disabled_sessions
                if sid not in self._session_states
            ][:excess]
            for sid in to_remove:
                self._disabled_sessions.discard(sid)
            if logger.isEnabledFor(logging.DEBUG):
                logger.debug(
                    f"Evicted {len(to_remove)} old disabled sessions to enforce size limit "
                    f"({MAX_DISABLED_SESSIONS})"
                )

        # Deactivate any active replacement
        state = self._session_states.get(session_id)
        if state is not None and state.active:
            state.deactivate()
            if logger.isEnabledFor(logging.INFO):
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

        # Cleanup metrics to prevent memory leak
        self._metrics.cleanup_session(session_id)

        # Periodically prune historical timestamps (every ~100 cleanups to amortize cost)
        # Using a simple counter approach or just random check
        if random.random() < 0.01:
            self._metrics.prune_history()

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

    def _evict_oldest_sessions_if_needed(self) -> None:
        """Evict oldest session states if over size limit (LRU eviction).

        This method prevents unbounded memory growth by removing the least
        recently used session states when the limit is exceeded. Eviction
        only removes inactive sessions to avoid disrupting active replacements.
        """
        # Only evict if we're over the limit
        if len(self._session_states) <= MAX_SESSION_STATES:
            return

        # Try to evict inactive sessions
        max_iterations = len(self._session_states)  # Prevent infinite loop
        iterations = 0
        evicted_count = 0

        while (
            len(self._session_states) > MAX_SESSION_STATES
            and iterations < max_iterations
        ):
            iterations += 1
            # Get oldest entry (first in OrderedDict)
            oldest_session_id, oldest_state = next(iter(self._session_states.items()))

            # Only evict inactive sessions to avoid disrupting active replacements
            if oldest_state.active:
                # Skip active sessions - move to end and try next
                self._session_states.move_to_end(oldest_session_id)
                continue

            # Evict inactive session
            self._session_states.popitem(last=False)  # Remove oldest (first) item
            # Also remove from disabled_sessions if present
            self._disabled_sessions.discard(oldest_session_id)
            evicted_count += 1

        # If we still exceed the limit after trying to evict inactive sessions,
        # it means all remaining sessions are active
        if len(self._session_states) > MAX_SESSION_STATES:
            active_count = sum(
                1 for state in self._session_states.values() if state.active
            )
            if logger.isEnabledFor(logging.WARNING):
                logger.warning(
                    f"Session states limit exceeded ({len(self._session_states)} > {MAX_SESSION_STATES}). "
                    f"All {active_count} remaining sessions are active and cannot be evicted. "
                    f"Consider increasing MAX_SESSION_STATES or ensuring EoS events are emitted."
                )

        if evicted_count > 0 and logger.isEnabledFor(logging.DEBUG):
            logger.debug(
                f"Evicted {evicted_count} inactive session(s) "
                f"to enforce size limit ({MAX_SESSION_STATES})"
            )
