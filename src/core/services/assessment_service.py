"""
Core LLM assessment service.

This service performs LLM-based conversation assessment, replicating the
functionality from gemini-cli's LoopDetectionService.

Reference: dev/thrdparty/gemini-cli/packages/core/src/services/loopDetectionService.ts
"""

import logging
import time
from typing import Any

from src.core.common.logging_utils import get_logger, is_log_level_enabled
from src.core.domain.assessment import (
    AssessmentRequest,
    AssessmentResult,
    LLMAssessmentResponse,
)
from src.core.domain.chat import ChatMessage
from src.core.domain.configuration.assessment_config import AssessmentConfig
from src.core.interfaces.assessment_service_interface import (
    IAssessmentBackendService,
    IAssessmentService,
)
from src.core.services.assessment_prompts import (
    get_system_prompt,
    get_task_prompt,
    initialize_prompts,
    is_initialized,
)

logger = get_logger(__name__)


class AssessmentError(Exception):
    """Exception raised when assessment fails."""


class AssessmentService(IAssessmentService):
    """
    Core service for performing LLM-based conversation assessment.

    This replicates the assessment logic from gemini-cli's LoopDetectionService,
    including the conversation history trimming and response parsing.
    """

    def __init__(
        self, backend_service: IAssessmentBackendService, config: AssessmentConfig
    ):
        """
        Initialize assessment service.

        Args:
            backend_service: Service for communicating with assessment backend
            config: Assessment configuration
        """
        self.backend_service = backend_service
        self.config = config
        self._ensure_prompts_initialized()

    async def assess_conversation(
        self, history: list[ChatMessage], session_id: str
    ) -> AssessmentResult:
        """
        Perform LLM-based assessment of conversation history.

        This replicates the checkForLoopWithLLM method from gemini-cli.

        Reference: loopDetectionService.ts lines ~300-350

        Args:
            history: List of chat messages to analyze
            session_id: Unique identifier for the session

        Returns:
            AssessmentResult with reasoning and confidence score

        Raises:
            AssessmentError: If assessment fails
        """
        start_time = time.time()

        try:
            # 1. Validate conversation history first
            if not self._validate_history(history):
                if is_log_level_enabled(logger, logging.DEBUG):
                    logger.debug(
                        f"Conversation history validation failed for session {session_id}, skipping assessment"
                    )
                # Return a neutral result when validation fails
                return AssessmentResult(
                    session_id=session_id,
                    reasoning="Conversation history validation failed - insufficient data for meaningful assessment",
                    confidence=0.0,
                    turn_count=len(history),
                )

            # 2. Trim history to recent window (replicate trimRecentHistory)
            recent_history = self._trim_recent_history(history)

            if is_log_level_enabled(logger, logging.DEBUG):
                logger.debug(
                    f"Assessing conversation for session {session_id}: "
                    f"{len(history)} total messages, {len(recent_history)} recent messages"
                )

            # 2. Create assessment request
            request = self._create_assessment_request(recent_history, session_id)

            # 3. Call assessment backend
            response = await self.backend_service.perform_assessment(request)

            # 4. Parse and validate response
            result = self._parse_assessment_response(response, session_id, len(history))

            duration = time.time() - start_time
            if is_log_level_enabled(logger, logging.DEBUG):
                logger.debug(
                    f"Assessment completed for session {session_id}: "
                    f"confidence={result.confidence}, duration={duration:.2f}s"
                )

            return result

        except Exception as e:
            duration = time.time() - start_time
            logger.error(
                f"Assessment failed for session {session_id}: {e}, duration={duration:.2f}s"
            )
            raise AssessmentError(f"Assessment failed: {e}") from e

    @staticmethod
    def _ensure_prompts_initialized() -> None:
        """
        Ensure assessment prompts are loaded before attempting assessment.
        """
        if is_initialized():
            return

        try:
            initialize_prompts()
        except Exception as exc:
            logger.error(
                "Failed to initialize assessment prompts: %s", exc, exc_info=True
            )
            raise AssessmentError("Failed to initialize assessment prompts") from exc

    async def assess_conversation_safe(
        self, history: list[ChatMessage], session_id: str
    ) -> AssessmentResult | None:
        """
        Perform assessment with graceful error handling.

        This method never raises exceptions and returns None if assessment fails,
        allowing the main conversation flow to continue uninterrupted.

        Args:
            history: List of chat messages to analyze
            session_id: Unique identifier for the session

        Returns:
            AssessmentResult if successful, None if failed
        """
        try:
            return await self.assess_conversation(history, session_id)
        except Exception as e:
            logger.warning(
                f"Assessment failed gracefully for session {session_id}: {e}"
            )
            return None

    def _trim_recent_history(self, history: list[ChatMessage]) -> list[ChatMessage]:
        """
        Trim conversation history to recent window.

        This replicates gemini-cli's trimRecentHistory method, keeping only
        the most recent messages within the configured history window.

        Reference: loopDetectionService.ts (trimRecentHistory method)

        Args:
            history: Full conversation history

        Returns:
            Trimmed history within the configured window
        """
        if len(history) <= self.config.history_window:
            return history

        # Keep the most recent messages
        trimmed = history[-self.config.history_window :]

        if is_log_level_enabled(logger, logging.DEBUG):
            logger.debug(
                f"Trimmed conversation history: {len(history)} -> {len(trimmed)} messages"
            )

        return trimmed

    def _create_assessment_request(
        self, history: list[ChatMessage], session_id: str
    ) -> AssessmentRequest:
        """
        Create assessment request with system prompt and task prompt.

        This replicates the request construction from gemini-cli's checkForLoopWithLLM.

        Args:
            history: Conversation history to assess
            session_id: Session identifier

        Returns:
            AssessmentRequest ready for backend processing
        """
        # Construct messages with system prompt and task prompt
        messages = [
            ChatMessage(role="system", content=get_system_prompt()),
            *history,
            ChatMessage(role="user", content=get_task_prompt()),
        ]

        return AssessmentRequest(
            session_id=session_id,
            messages=messages,
            turn_count=len(history),
            prompt_id=f"assessment_{session_id}_{int(time.time())}",
        )

    def _parse_assessment_response(
        self,
        response: LLMAssessmentResponse | dict[str, Any] | Any,
        session_id: str,
        turn_count: int,
    ) -> AssessmentResult:
        """
        Parse and validate assessment response from backend.

        Args:
            response: LLMAssessmentResponse from assessment backend
            session_id: Session identifier
            turn_count: Current turn count

        Returns:
            Parsed AssessmentResult

        Raises:
            AssessmentError: If response is invalid
        """
        try:
            response_model = self._coerce_assessment_response(response)
            reasoning = response_model.reasoning
            confidence = response_model.confidence

            # Validate reasoning
            if not reasoning.strip():
                raise AssessmentError("Invalid reasoning: must be non-empty string")

            # Validate confidence range
            if not 0.0 <= confidence <= 1.0:
                raise AssessmentError(
                    f"Invalid confidence: {confidence} (must be 0.0-1.0)"
                )

            # Create result
            result = AssessmentResult.from_llm_response(
                response_model.model_dump(), session_id, turn_count
            )

            if is_log_level_enabled(logger, logging.DEBUG):
                logger.debug(
                    f"Parsed assessment response: reasoning='{reasoning[:100]}...', "
                    f"confidence={confidence}, is_unproductive={result.is_unproductive}"
                )

            return result

        except (ValueError, TypeError, KeyError) as e:
            raise AssessmentError(f"Failed to parse assessment response: {e}") from e

    def _coerce_assessment_response(
        self, response: LLMAssessmentResponse | dict[str, Any] | Any
    ) -> LLMAssessmentResponse:
        if isinstance(response, LLMAssessmentResponse):
            return response

        if isinstance(response, dict):
            return LLMAssessmentResponse(**response)

        if hasattr(response, "model_dump") and callable(response.model_dump):
            dumped = response.model_dump()  # type: ignore[attr-defined]
            if isinstance(dumped, dict):
                reasoning = dumped.get("reasoning", "")
                confidence = dumped.get("confidence", 0.0)
                return LLMAssessmentResponse(
                    reasoning=str(reasoning) if reasoning is not None else "",
                    confidence=float(confidence) if confidence is not None else 0.0,
                )
            return LLMAssessmentResponse(reasoning="", confidence=0.0)

        if hasattr(response, "reasoning") and hasattr(response, "confidence"):
            reasoning = getattr(response, "reasoning", None)
            confidence = getattr(response, "confidence", None)
            return LLMAssessmentResponse(
                reasoning=str(reasoning) if reasoning is not None else "",
                confidence=float(confidence) if confidence is not None else 0.0,
            )

        raise AssessmentError(
            f"Invalid assessment response type: {type(response).__name__}"
        )

    def _validate_history(self, history: list[ChatMessage]) -> bool:
        """
        Validate conversation history before assessment.

        Args:
            history: Conversation history to validate

        Returns:
            True if history is valid for assessment
        """
        if not history:
            if is_log_level_enabled(logger, logging.DEBUG):
                logger.debug("Empty conversation history, skipping assessment")
            return False

        # Check for minimum number of messages for meaningful assessment
        if len(history) < 5:
            if is_log_level_enabled(logger, logging.DEBUG):
                logger.debug(
                    f"Insufficient conversation history ({len(history)} messages), "
                    f"skipping assessment"
                )
            return False

        # Check for recent assistant messages (need assistant activity to assess)
        recent_assistant_messages = [
            msg for msg in history[-10:] if msg.role == "assistant"
        ]
        if len(recent_assistant_messages) < 2:
            if is_log_level_enabled(logger, logging.DEBUG):
                logger.debug("Insufficient recent assistant messages for assessment")
            return False
        return True
