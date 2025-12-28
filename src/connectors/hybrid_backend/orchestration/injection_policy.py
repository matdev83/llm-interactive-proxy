"""InjectionPolicy service for reasoning injection decisions.

This service extracts injection decision logic from HybridConnector to provide
focused, testable components for injection policy evaluation.

Requirements satisfied:
- Req 8: Injection Policy Extraction
"""

import logging
import random
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from src.core.config.app_config import AppConfig
    from src.core.interfaces.configuration_interface import IAppIdentityConfig

from src.connectors.hybrid_backend.models.injection_decision import InjectionDecision

logger = logging.getLogger(__name__)


class InjectionPolicy:
    """Service for reasoning injection decisions.

    This service encapsulates all logic for deciding whether to inject reasoning
    for a given request, including first-turn detection, forced initial turns,
    adaptive backoff, and probability-based injection.
    """

    def __init__(self, config: "AppConfig") -> None:
        """Initialize InjectionPolicy.

        Args:
            config: Application configuration
        """
        self.config = config
        self._reasoning_backoff_remaining = 0

    @staticmethod
    def _extract_message_role(message: Any) -> str | None:
        """Best-effort extraction of a message role.

        Args:
            message: Message object in various formats

        Returns:
            Role string or None if not found
        """
        role = getattr(message, "role", None)
        if isinstance(role, str) and role:
            return role

        if isinstance(message, dict):
            role_value = message.get("role")
            return role_value if isinstance(role_value, str) else None

        if hasattr(message, "model_dump") and callable(message.model_dump):
            try:
                dumped = message.model_dump()
                if isinstance(dumped, dict):
                    role_value = dumped.get("role")
                else:
                    role_value = None
                if isinstance(role_value, str):
                    return role_value
            except (AttributeError, TypeError, ValueError) as e:
                if logger.isEnabledFor(logging.DEBUG):
                    logger.debug(
                        "Failed to extract role via model_dump: %s", e, exc_info=True
                    )
                return None

        if hasattr(message, "get") and callable(message.get):
            try:
                role_value = message.get("role")
                if isinstance(role_value, str):
                    return role_value
            except (AttributeError, TypeError, KeyError) as e:
                if logger.isEnabledFor(logging.DEBUG):
                    logger.debug(
                        "Failed to extract role via get method: %s", e, exc_info=True
                    )
                return None

        return None

    def _is_first_user_turn(
        self,
        processed_messages: list[Any] | None,
        request_messages: list[Any] | None,
    ) -> bool:
        """Determine whether the current request represents the first user turn.

        Args:
            processed_messages: Messages after command processing
            request_messages: Original request messages

        Returns:
            True if this is the first user turn, False otherwise
        """
        messages_to_check: list[Any] = []
        if processed_messages:
            messages_to_check = list(processed_messages)
        elif request_messages:
            messages_to_check = list(request_messages)

        if not messages_to_check:
            # No prior context available; treat as first turn to err on the side of reasoning.
            return True

        for message in messages_to_check:
            role = self._extract_message_role(message)
            if not role:
                continue
            normalized_role = role.strip().lower()
            if normalized_role in {"assistant", "tool", "function"}:
                return False

        return True

    def should_inject(
        self,
        processed_messages: list[Any] | None,
        request_messages: list[Any] | None,
        probability_override: float | None = None,
        identity: "IAppIdentityConfig | None" = None,
    ) -> InjectionDecision:
        """Determine whether reasoning should be injected.

        Args:
            processed_messages: Messages after command processing
            request_messages: Original request messages
            probability_override: Optional probability override for this request
            identity: Optional identity configuration (for turn count)

        Returns:
            InjectionDecision containing decision, reason, and metadata
        """
        # Determine probability to use
        if probability_override is not None:
            temp_reasoning_probability = probability_override
        else:
            temp_reasoning_probability = (
                self.config.backends.reasoning_injection_probability
            )

        # Check if this is the first user turn
        is_first_turn = self._is_first_user_turn(
            processed_messages=processed_messages, request_messages=request_messages
        )

        # Check if current turn is within the force initial turns window
        turn_count = getattr(identity, "session_turn_count", None) if identity else None

        force_reasoning_for_initial_turns = (
            self.config.backends.hybrid_reasoning_force_initial_turns > 0
            and turn_count is not None
            and turn_count <= self.config.backends.hybrid_reasoning_force_initial_turns
        )

        # Check adaptive backoff state
        adaptive_backoff_active = False
        if (
            self._reasoning_backoff_remaining > 0
            and not force_reasoning_for_initial_turns
            and not is_first_turn
        ):
            adaptive_backoff_active = True
            self._reasoning_backoff_remaining -= 1
            logger.info(
                "Reasoning model injection decision: SKIP (adaptive backoff active), remaining=%s",
                self._reasoning_backoff_remaining,
            )

        # Decision logic
        if force_reasoning_for_initial_turns:
            use_reasoning = True
            reason = (
                f"FORCE (within initial turns window), probability={temp_reasoning_probability}, "
                f"turn={turn_count}/{self.config.backends.hybrid_reasoning_force_initial_turns}"
            )
            logger.info(
                "Reasoning model injection decision: %s",
                reason,
            )
        elif is_first_turn:
            use_reasoning = True
            reason = (
                f"FORCE (first user turn), probability={temp_reasoning_probability}"
            )
            logger.info(
                "Reasoning model injection decision: %s",
                reason,
            )
        elif adaptive_backoff_active:
            use_reasoning = False
            reason = f"SKIP (adaptive backoff active), remaining={self._reasoning_backoff_remaining}"
        else:
            random_draw = random.random()
            use_reasoning = random_draw < temp_reasoning_probability
            reason = (
                f"{'USE' if use_reasoning else 'SKIP'} (probability={temp_reasoning_probability}, "
                f"draw={random_draw:.4f})"
            )
            logger.info(
                "Reasoning model injection decision: %s",
                reason,
            )

        return InjectionDecision(
            should_inject=use_reasoning,
            reason=reason,
            is_first_turn=is_first_turn,
            probability_used=temp_reasoning_probability,
            backoff_remaining=self._reasoning_backoff_remaining,
        )

    def update_backoff(self, success: bool) -> None:
        """Update adaptive backoff state based on phase outcome.

        Args:
            success: Whether the reasoning phase completed successfully (and within latency threshold)
        """
        if success:
            # Reset backoff on success
            self._reasoning_backoff_remaining = 0
        else:
            # Set backoff on failure (latency exceeded threshold)
            backoff_turns = getattr(
                self.config.backends, "hybrid_reasoning_backoff_turns", 0
            )
            if backoff_turns > 0:
                # Increment existing backoff or set new
                self._reasoning_backoff_remaining = (
                    self._reasoning_backoff_remaining + backoff_turns
                )
                logger.info(
                    "Adaptive backoff activated: %s turn(s) remaining",
                    self._reasoning_backoff_remaining,
                )
