"""
Interface definitions for the LLM assessment system.

This module defines the contracts for assessment services, following the
interface pattern used throughout the llm-interactive-proxy project.
"""

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

from src.core.domain.assessment import (
    AssessmentRequest,
    AssessmentResult,
    LLMAssessmentResponse,
    SessionStats,
)
from src.core.domain.chat import ChatMessage

if TYPE_CHECKING:
    from src.core.domain.assessment import SessionAssessmentState


class IAssessmentService(ABC):
    """
    Interface for the core assessment service.

    This service is responsible for performing LLM-based conversation assessment,
    replicating the functionality from gemini-cli's LoopDetectionService.
    """

    @abstractmethod
    async def assess_conversation(
        self, history: list[ChatMessage], session_id: str
    ) -> AssessmentResult:
        """
        Perform LLM-based assessment of conversation history.

        Args:
            history: List of chat messages to analyze
            session_id: Unique identifier for the session

        Returns:
            AssessmentResult with reasoning and confidence score

        Raises:
            AssessmentError: If assessment fails
        """

    @abstractmethod
    async def assess_conversation_safe(
        self, history: list[ChatMessage], session_id: str
    ) -> AssessmentResult | None:
        """
        Perform assessment with graceful error handling.

        This method should never raise exceptions and should return None
        if assessment fails, allowing the main conversation flow to continue.

        Args:
            history: List of chat messages to analyze
            session_id: Unique identifier for the session

        Returns:
            AssessmentResult if successful, None if failed
        """


class ITurnCounterService(ABC):
    """
    Interface for turn counting and assessment timing service.

    This service manages per-session state and determines when assessments
    should be triggered, replicating gemini-cli's turn tracking logic.
    """

    @abstractmethod
    def increment_turn(self, session_id: str) -> int:
        """
        Increment turn count for a session.

        Args:
            session_id: Unique identifier for the session

        Returns:
            New turn count for the session
        """

    @abstractmethod
    def get_turn_count(self, session_id: str) -> int:
        """
        Get current turn count for a session.

        Args:
            session_id: Unique identifier for the session

        Returns:
            Current turn count
        """

    @abstractmethod
    def should_trigger_assessment(self, session_id: str) -> bool:
        """
        Determine if assessment should be triggered for a session.

        This replicates the logic from gemini-cli's turnStarted method.

        Args:
            session_id: Unique identifier for the session

        Returns:
            True if assessment should be triggered
        """

    @abstractmethod
    def mark_assessment_performed(self, session_id: str):
        """
        Mark that an assessment was performed for a session.

        Args:
            session_id: Unique identifier for the session
        """

    @abstractmethod
    def adjust_check_interval(self, session_id: str, confidence: float):
        """
        Adjust assessment interval based on confidence score.

        This replicates gemini-cli's dynamic interval adjustment.

        Args:
            session_id: Unique identifier for the session
            confidence: Confidence score from last assessment (0.0-1.0)
        """

    @abstractmethod
    def disable_for_session(self, session_id: str):
        """
        Disable assessment for a specific session.

        Args:
            session_id: Unique identifier for the session
        """

    @abstractmethod
    def enable_for_session(self, session_id: str):
        """
        Enable assessment for a specific session.

        Args:
            session_id: Unique identifier for the session
        """

    @abstractmethod
    def get_session_stats(self, session_id: str) -> SessionStats:
        """
        Get statistics for a session.

        Args:
            session_id: Unique identifier for the session

        Returns:
            SessionStats object
        """


class IAssessmentRepository(ABC):
    """
    Interface for assessment state persistence.

    This repository manages session assessment state, providing persistence
    and cleanup capabilities for session data.
    """

    @abstractmethod
    def get_session_state(self, session_id: str) -> "SessionAssessmentState":
        """
        Get assessment state for a session.

        Args:
            session_id: Unique identifier for the session

        Returns:
            SessionAssessmentState (creates new if doesn't exist)
        """

    @abstractmethod
    def update_session_state(
        self, state: "SessionAssessmentState", update_timestamp: bool = True
    ):
        """
        Update assessment state for a session.

        Args:
            state: Updated session assessment state
            update_timestamp: Whether the repository should update the state's timestamp
        """

    @abstractmethod
    def delete_session_state(self, session_id: str):
        """
        Delete assessment state for a session.

        Args:
            session_id: Unique identifier for the session
        """

    @abstractmethod
    def cleanup_expired_sessions(self, max_age_seconds: int = 3600):
        """
        Clean up expired session states.

        Args:
            max_age_seconds: Maximum age in seconds before cleanup
        """

    @abstractmethod
    def get_all_session_ids(self) -> list[str]:
        """
        Get all active session IDs.

        Returns:
            List of session IDs
        """


class IAssessmentBackendService(ABC):
    """
    Interface for assessment backend communication.

    This service handles communication with the LLM backend for assessment,
    abstracting backend-specific details and providing a unified interface.
    """

    @abstractmethod
    async def perform_assessment(self, request: AssessmentRequest) -> LLMAssessmentResponse:
        """
        Perform assessment using the configured backend.

        Args:
            request: Assessment request with messages and context

        Returns:
            LLMAssessmentResponse with assessment reasoning and confidence

        Raises:
            AssessmentBackendError: If backend communication fails
        """

    @abstractmethod
    def is_backend_available(self) -> bool:
        """
        Check if the assessment backend is available.

        Returns:
            True if backend is available and responsive
        """

    @abstractmethod
    async def health_check(self) -> bool:
        """
        Perform a health check on the assessment backend.

        Returns:
            True if backend is healthy
        """


class IAssessmentMetrics(ABC):
    """
    Interface for assessment metrics collection.

    This service collects and reports metrics about assessment performance
    and behavior for monitoring and optimization.
    """

    @abstractmethod
    def record_assessment_triggered(self, session_id: str):
        """Record that an assessment was triggered."""

    @abstractmethod
    def record_assessment_completed(
        self, session_id: str, confidence: float, duration: float
    ):
        """Record that an assessment was completed."""

    @abstractmethod
    def record_steering_intervention(self, session_id: str, confidence: float):
        """Record that a steering intervention was triggered."""

    @abstractmethod
    def record_assessment_error(self, session_id: str, _error_type: str):
        """Record that an assessment error occurred."""

    @abstractmethod
    def record_circuit_breaker_open(self):
        """Record that the circuit breaker opened."""

    @abstractmethod
    def record_cache_hit(self, session_id: str):
        """Record that an assessment cache hit occurred."""

    @abstractmethod
    def record_cache_miss(self, session_id: str):
        """Record that an assessment cache miss occurred."""


class IAssessmentLogger(ABC):
    """
    Interface for assessment logging.

    This service provides structured logging for assessment decisions
    and system behavior for debugging and analysis.
    """

    @abstractmethod
    def log_assessment_result(self, result: AssessmentResult):
        """Log an assessment result."""

    @abstractmethod
    def log_steering_intervention(
        self, session_id: str, reasoning: str, confidence: float
    ):
        """Log a steering intervention."""

    @abstractmethod
    def log_assessment_error(self, session_id: str, error: Exception):
        """Log an assessment error."""

    @abstractmethod
    def log_turn_increment(self, session_id: str, turn_count: int):
        """Log a turn increment."""

    @abstractmethod
    def log_interval_adjustment(
        self, session_id: str, old_interval: int, new_interval: int, confidence: float
    ):
        """Log an interval adjustment."""
