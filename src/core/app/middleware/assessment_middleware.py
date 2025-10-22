"""
Assessment middleware for LLM-based conversation assessment.

This middleware monitors conversation turns and triggers LLM-based assessment
when unproductive patterns might be present, replicating gemini-cli behavior.

Reference: dev/thrdparty/gemini-cli/packages/core/src/services/loopDetectionService.ts
"""

from src.core.common.logging_utils import get_logger
from src.core.domain.chat import ChatMessage, ChatRequest
from src.core.domain.configuration.assessment_config import AssessmentConfig
from src.core.interfaces.assessment_service_interface import (
    IAssessmentService,
    ITurnCounterService,
)
from src.core.services.assessment_prompts import get_steering_template

logger = get_logger(__name__)


class AssessmentMiddleware:
    """
    Middleware that monitors conversation turns and triggers LLM-based assessment.

    This replicates the functionality from gemini-cli's LoopDetectionService,
    including turn counting, assessment triggering, and steering message injection.
    """

    def __init__(
        self,
        assessment_service: IAssessmentService,
        turn_counter_service: ITurnCounterService,
        config: AssessmentConfig,
    ):
        """
        Initialize assessment middleware.

        Args:
            assessment_service: Service for performing assessments
            turn_counter_service: Service for turn counting and timing
            config: Assessment configuration
        """
        self.assessment_service = assessment_service
        self.turn_counter_service = turn_counter_service
        self.config = config

    async def process(self, request: ChatRequest) -> ChatRequest:
        """
        Process request through assessment middleware.

        This method:
        1. Checks if assessment is enabled
        2. Increments turn counter (replicates turnStarted)
        3. Checks if assessment should be triggered
        4. Performs assessment if needed
        5. Handles assessment results (steering, interval adjustment)

        Args:
            request: Incoming chat request

        Returns:
            Potentially modified chat request with steering messages
        """
        if not self.config.enabled:
            return request

        session_id = self._get_session_id(request)

        try:
            # 1. Increment turn counter (replicate turnStarted)
            turn_count = self.turn_counter_service.increment_turn(session_id)

            logger.debug(f"Turn incremented for session {session_id}: {turn_count}")

            # 2. Check if assessment should be triggered
            if self.turn_counter_service.should_trigger_assessment(session_id):
                logger.info(
                    f"Triggering assessment for session {session_id} at turn {turn_count}"
                )

                # 3. Perform assessment
                assessment_result = (
                    await self.assessment_service.assess_conversation_safe(
                        request.messages, session_id
                    )
                )

                # 4. Handle assessment result
                if assessment_result:
                    logger.info(
                        f"Assessment result for session {session_id}: "
                        f"confidence={assessment_result.confidence}, "
                        f"threshold={self.config.confidence_threshold}, "
                        f"should_intervene={assessment_result.should_intervene}"
                    )

                    # Mark assessment as performed
                    self.turn_counter_service.mark_assessment_performed(session_id)

                    # Check if intervention is needed
                    if assessment_result.should_intervene:
                        logger.warning(
                            f"Steering intervention triggered for session {session_id}: "
                            f"confidence={assessment_result.confidence}"
                        )

                        # Inject steering message
                        request = self._inject_steering_message(
                            request, assessment_result
                        )

                    # Adjust check interval based on confidence
                    self.turn_counter_service.adjust_check_interval(
                        session_id, assessment_result.confidence
                    )

                    logger.debug(
                        f"Assessment completed for session {session_id}: "
                        f"confidence={assessment_result.confidence}, "
                        f"intervention={assessment_result.should_intervene}"
                    )
                else:
                    logger.warning(
                        f"Assessment failed for session {session_id}, continuing without intervention"
                    )

            return request

        except Exception as e:
            # Never let assessment errors break the main conversation flow
            logger.error(f"Assessment middleware error for session {session_id}: {e}")
            return request

    def _get_session_id(self, request: ChatRequest) -> str:
        """
        Extract or generate session ID from request.

        Args:
            request: Chat request

        Returns:
            Session ID for tracking
        """
        # Try to get session ID from request metadata
        if hasattr(request, "session_id") and request.session_id:
            return request.session_id

        # Try to get from headers or other sources
        # This would need to be implemented based on how sessions are tracked
        # For now, generate a simple ID based on request hash
        request_hash = hash(str(request.messages[-5:]) if request.messages else "empty")
        return f"session_{abs(request_hash)}"

    def _inject_steering_message(
        self, request: ChatRequest, assessment_result
    ) -> ChatRequest:
        """
        Inject steering message into conversation.

        This creates a system message warning about the detected loop,
        similar to how gemini-cli handles steering interventions.

        Args:
            request: Original chat request
            assessment_result: Assessment result with reasoning

        Returns:
            Modified chat request with steering message
        """
        # Create steering message using template from file
        steering_template = get_steering_template()
        steering_content = steering_template.format(
            reasoning=assessment_result.reasoning
        )

        import time

        steering_message = ChatMessage(
            role="system",
            content=steering_content,
            metadata={
                "is_assessment_steering": True,
                "confidence": assessment_result.confidence,
                "session_id": assessment_result.session_id,
                "timestamp": time.time(),
                "reasoning": assessment_result.reasoning,
            },
        )

        # Add steering message to conversation history
        new_messages = [*list(request.messages), steering_message]

        # Create new request with steering message using Pydantic model_copy
        modified_request = request.model_copy(update={"messages": new_messages})

        logger.info(
            f"Injected steering message for session {assessment_result.session_id}: "
            f"reasoning={assessment_result.reasoning[:50]}..."
        )

        return modified_request

    def _should_skip_assessment(self, request: ChatRequest) -> bool:
        """
        Check if assessment should be skipped for this request.

        Args:
            request: Chat request to evaluate

        Returns:
            True if assessment should be skipped
        """
        # Skip if no messages
        if not request.messages:
            return True

        # Skip if conversation is too short
        if len(request.messages) < 5:
            return True

        # Skip if recent message is already a steering message
        recent_messages = request.messages[-3:]
        for msg in recent_messages:
            if (
                hasattr(msg, "metadata")
                and msg.metadata
                and msg.metadata.get("is_assessment_steering")
            ):
                return True

        return False

    def get_middleware_info(self) -> dict:
        """
        Get information about middleware state.

        Returns:
            Dictionary with middleware information
        """
        return {
            "enabled": self.config.enabled,
            "turn_threshold": self.config.turn_threshold,
            "confidence_threshold": self.config.confidence_threshold,
            "backend": self.config.backend,
            "model": self.config.model,
        }
