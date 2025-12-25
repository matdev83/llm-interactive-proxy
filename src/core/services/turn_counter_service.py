"""
Turn counter service for LLM assessment system.

This service manages turn counting and assessment timing for each session,
replicating the logic from gemini-cli's LoopDetectionService.

Reference: dev/thrdparty/gemini-cli/packages/core/src/services/loopDetectionService.ts
"""

import logging

from src.core.common.logging_utils import get_logger
from src.core.domain.assessment import SessionStats
from src.core.domain.configuration.assessment_config import AssessmentConfig
from src.core.interfaces.assessment_service_interface import (
    IAssessmentRepository,
    ITurnCounterService,
)

logger = get_logger(__name__)


class TurnCounterService(ITurnCounterService):
    """
    Service for managing turn counts and assessment timing.

    This replicates the turn tracking and trigger logic from gemini-cli's
    LoopDetectionService, including the dynamic interval adjustment.
    """

    def __init__(self, repository: IAssessmentRepository, config: AssessmentConfig):
        """
        Initialize turn counter service.

        Args:
            repository: Repository for session state persistence
            config: Assessment configuration
        """
        self.repository = repository
        self.config = config

    def increment_turn(self, session_id: str) -> int:
        """
        Increment turn count for a session.

        This replicates the turn increment logic from gemini-cli's turnStarted method.

        Args:
            session_id: Unique identifier for the session

        Returns:
            New turn count for the session
        """
        if not session_id or not str(session_id).strip():
            raise ValueError("session_id must be a non-empty string")

        state = self.repository.get_session_state(session_id)
        turn_count = state.increment_turn()
        # State already updated its timestamp during increment_turn; avoid duplicate work.
        self.repository.update_session_state(state)

        if logger.isEnabledFor(logging.DEBUG):
            logger.debug(
                "turn_incremented",
                session_id=session_id,
                turn_count=turn_count,
            )
        return turn_count

    def get_turn_count(self, session_id: str) -> int:
        """
        Get current turn count for a session.

        Args:
            session_id: Unique identifier for the session

        Returns:
            Current turn count
        """
        if not session_id or not str(session_id).strip():
            raise ValueError("session_id must be a non-empty string")

        state = self.repository.get_session_state(session_id)
        return state.turn_count

    def should_trigger_assessment(self, session_id: str) -> bool:
        """
        Determine if assessment should be triggered for a session.

        This replicates the logic from gemini-cli's turnStarted method:
        - Must be past turn threshold (LLM_CHECK_AFTER_TURNS)
        - Must be past the check interval since last assessment
        - Must not be disabled for the session

        Reference: loopDetectionService.ts lines ~155-170

        Args:
            session_id: Unique identifier for the session

        Returns:
            True if assessment should be triggered
        """
        if not session_id or not str(session_id).strip():
            raise ValueError("session_id must be a non-empty string")

        state = self.repository.get_session_state(session_id)

        # Check if disabled for this session
        if state.disabled_for_session or self.config.is_session_disabled(session_id):
            if logger.isEnabledFor(logging.DEBUG):
                logger.debug(f"Assessment disabled for session {session_id}")
            return False

        # Check if we've reached the turn threshold
        if state.turn_count < self.config.turn_threshold:
            if logger.isEnabledFor(logging.DEBUG):
                logger.debug(
                    f"Session {session_id} turn count {state.turn_count} below threshold {self.config.turn_threshold}"
                )
            return False

        # Check if enough turns have passed since last assessment
        # For the first assessment (when last_check_turn == 0), only check turn threshold
        if state.last_check_turn > 0:
            turns_since_last_check = state.turn_count - state.last_check_turn
            if turns_since_last_check < state.current_check_interval:
                if logger.isEnabledFor(logging.DEBUG):
                    logger.debug(
                        f"Session {session_id} turns since last check {turns_since_last_check} below interval {state.current_check_interval}"
                    )
                return False

        if logger.isEnabledFor(logging.DEBUG):
            logger.debug(f"Assessment should be triggered for session {session_id}")
        return True

    def mark_assessment_performed(self, session_id: str):
        """
        Mark that an assessment was performed for a session.

        This updates the last_check_turn to the current turn count.

        Args:
            session_id: Unique identifier for the session
        """
        if not session_id or not str(session_id).strip():
            raise ValueError("session_id must be a non-empty string")

        state = self.repository.get_session_state(session_id)
        state.mark_assessment_performed()
        self.repository.update_session_state(state)

        if logger.isEnabledFor(logging.DEBUG):
            logger.debug(
                f"Assessment marked as performed for session {session_id}. New check interval: {state.current_check_interval}"
            )

    def adjust_check_interval(self, session_id: str, confidence: float):
        """
        Adjust assessment interval based on confidence score.

        This replicates gemini-cli's dynamic interval adjustment formula:
        MIN + (MAX - MIN) * (1 - confidence)

        Higher confidence = shorter intervals (more frequent checks)
        Lower confidence = longer intervals (less frequent checks)

        Reference: loopDetectionService.ts lines ~385-390

        Args:
            session_id: Unique identifier for the session
            confidence: Confidence score from last assessment (0.0-1.0)
        """
        if not session_id or not str(session_id).strip():
            raise ValueError("session_id must be a non-empty string")

        state = self.repository.get_session_state(session_id)
        old_interval = state.current_check_interval

        state.update_check_interval(
            confidence, self.config.min_interval, self.config.max_interval
        )

        self.repository.update_session_state(state)

        if logger.isEnabledFor(logging.DEBUG):
            logger.debug(
                f"Adjusted check interval for session {session_id}: "
                f"{old_interval} -> {state.current_check_interval} (confidence: {confidence})"
            )

    def disable_for_session(self, session_id: str):
        """
        Disable assessment for a specific session.

        Args:
            session_id: Unique identifier for the session
        """
        state = self.repository.get_session_state(session_id)
        state.disabled_for_session = True
        self.repository.update_session_state(state)

        logger.info(f"Assessment disabled for session {session_id}")

    def enable_for_session(self, session_id: str):
        """
        Enable assessment for a specific session.

        Args:
            session_id: Unique identifier for the session
        """
        state = self.repository.get_session_state(session_id)
        state.disabled_for_session = False
        self.repository.update_session_state(state)

        logger.info(f"Assessment enabled for session {session_id}")

    def get_session_stats(self, session_id: str) -> SessionStats:
        """
        Get statistics for a session.

        Args:
            session_id: Unique identifier for the session

        Returns:
            SessionStats object
        """
        state = self.repository.get_session_state(session_id)
        return SessionStats(
            turn_count=state.turn_count,
            last_check_turn=state.last_check_turn,
            current_check_interval=state.current_check_interval,
            disabled_for_session=state.disabled_for_session,
            assessment_count=len(state.assessment_history),
            turns_since_last_check=state.turn_count - state.last_check_turn,
        )
