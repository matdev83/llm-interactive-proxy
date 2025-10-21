"""
Core LLM assessment service.

This service performs LLM-based conversation assessment, replicating the
functionality from gemini-cli's LoopDetectionService.

Reference: dev/thrdparty/gemini-cli/packages/core/src/services/loopDetectionService.ts
"""

import time
from typing import Any

from src.core.common.logging_utils import get_logger
from src.core.domain.assessment import AssessmentRequest, AssessmentResult
from src.core.domain.chat import ChatMessage
from src.core.domain.configuration.assessment_config import AssessmentConfig
from src.core.interfaces.assessment_service_interface import (
    IAssessmentBackendService,
    IAssessmentService,
)
from src.core.services.assessment_prompts import get_system_prompt, get_task_prompt

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
            # 1. Trim history to recent window (replicate trimRecentHistory)
            recent_history = self._trim_recent_history(history)

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
        self, response: dict[str, Any], session_id: str, turn_count: int
    ) -> AssessmentResult:
        """
        Parse and validate assessment response from backend.

        Expected response format (matching gemini-cli schema):
        {
          "reasoning": "Your analysis of the conversation state",
          "confidence": 0.85
        }

        Args:
            response: Raw response from assessment backend
            session_id: Session identifier
            turn_count: Current turn count

        Returns:
            Parsed AssessmentResult

        Raises:
            AssessmentError: If response is invalid
        """
        try:
            # Validate required fields
            if "reasoning" not in response:
                raise AssessmentError(
                    "Missing 'reasoning' field in assessment response"
                )

            if "confidence" not in response:
                raise AssessmentError(
                    "Missing 'confidence' field in assessment response"
                )

            reasoning = response["reasoning"]
            confidence = float(response["confidence"])

            # Validate reasoning
            if not isinstance(reasoning, str) or not reasoning.strip():
                raise AssessmentError("Invalid reasoning: must be non-empty string")

            # Validate confidence range
            if not 0.0 <= confidence <= 1.0:
                raise AssessmentError(
                    f"Invalid confidence: {confidence} (must be 0.0-1.0)"
                )

            # Create result
            result = AssessmentResult.from_llm_response(
                response, session_id, turn_count
            )

            logger.debug(
                f"Parsed assessment response: reasoning='{reasoning[:100]}...', "
                f"confidence={confidence}, is_unproductive={result.is_unproductive}"
            )

            return result

        except (ValueError, TypeError, KeyError) as e:
            raise AssessmentError(f"Failed to parse assessment response: {e}") from e

    def _validate_history(self, history: list[ChatMessage]) -> bool:
        """
        Validate conversation history before assessment.

        Args:
            history: Conversation history to validate

        Returns:
            True if history is valid for assessment
        """
        if not history:
            logger.debug("Empty conversation history, skipping assessment")
            return False

        # Check for minimum number of messages for meaningful assessment
        if len(history) < 5:
            logger.debug(
                f"Conversation too short for assessment: {len(history)} messages"
            )
            return False

        # Check for recent assistant messages (need assistant activity to assess)
        recent_assistant_messages = [
            msg for msg in history[-10:] if msg.role == "assistant"
        ]

        if len(recent_assistant_messages) < 2:
            logger.debug("Insufficient recent assistant messages for assessment")
            return False

        return True
