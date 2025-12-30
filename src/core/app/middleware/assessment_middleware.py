"""
Assessment middleware for LLM-based conversation assessment.

This middleware monitors conversation turns and triggers LLM-based assessment
when unproductive patterns might be present, replicating gemini-cli behavior.

Reference: dev/thrdparty/gemini-cli/packages/core/src/services/loopDetectionService.ts
"""

import logging
from dataclasses import dataclass
from uuid import uuid4

from src.core.common.exceptions import (
    NonForwardableEnforcementError,
    NonForwardableTagLimitExceededError,
)
from src.core.common.logging_utils import get_logger
from src.core.domain.chat import ChatMessage, ChatRequest
from src.core.domain.configuration.assessment_config import AssessmentConfig
from src.core.domain.non_forwardable import NonForwardableTagScope
from src.core.interfaces.assessment_service_interface import (
    IAssessmentService,
    ITurnCounterService,
)
from src.core.interfaces.non_forwardable_interface import (
    INonForwardableMessageIdentityService,
    INonForwardableMessageRegistry,
)
from src.core.services.assessment_prompts import get_steering_template

logger = get_logger(__name__)


@dataclass(frozen=True)
class MiddlewareInfo:
    """Information about assessment middleware state."""

    enabled: bool
    turn_threshold: int
    confidence_threshold: float
    backend: str
    model: str


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
        non_forwardable_registry: INonForwardableMessageRegistry | None = None,
        non_forwardable_identity_service: (
            INonForwardableMessageIdentityService | None
        ) = None,
    ):
        """
        Initialize assessment middleware.

        Args:
            assessment_service: Service for performing assessments
            turn_counter_service: Service for turn counting and timing
            config: Assessment configuration
            non_forwardable_registry: Optional registry for tagging non-forwardable messages
            non_forwardable_identity_service: Optional service for computing message identities
        """
        self.assessment_service = assessment_service
        self.turn_counter_service = turn_counter_service
        self.config = config
        self._non_forwardable_registry = non_forwardable_registry
        self._non_forwardable_identity_service = non_forwardable_identity_service

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

            if logger.isEnabledFor(logging.DEBUG):
                logger.debug(f"Turn incremented for session {session_id}: {turn_count}")

            # 2. Check if assessment should be triggered
            if self.turn_counter_service.should_trigger_assessment(session_id):
                if logger.isEnabledFor(logging.INFO):
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
                    if logger.isEnabledFor(logging.INFO):
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
                        if logger.isEnabledFor(logging.WARNING):
                            logger.warning(
                                f"Steering intervention triggered for session {session_id}: "
                                f"confidence={assessment_result.confidence}"
                            )

                        # Inject steering message
                        request = await self._inject_steering_message(
                            request, assessment_result
                        )

                    # Adjust check interval based on confidence
                    self.turn_counter_service.adjust_check_interval(
                        session_id, assessment_result.confidence
                    )

                    if logger.isEnabledFor(logging.DEBUG):
                        logger.debug(
                            f"Assessment completed for session {session_id}: "
                            f"confidence={assessment_result.confidence}, "
                            f"intervention={assessment_result.should_intervene}"
                        )
                else:
                    if logger.isEnabledFor(logging.WARNING):
                        logger.warning(
                            f"Assessment failed for session {session_id}, continuing without intervention"
                        )

            return request

        except Exception as e:
            # Never let assessment errors break the main conversation flow
            if logger.isEnabledFor(logging.ERROR):
                logger.error(
                    f"Assessment middleware error for session {session_id}: {e}"
                )
            return request

    def _get_session_id(self, request: ChatRequest) -> str:
        """
        Extract or generate session ID from request.

        This method follows a precedence order similar to RequestProcessor's session resolution:
        1. request.session_id (set by controller layer)
        2. request.extra_body["session_id"] (metadata fallback)
        3. Generate UUID fallback (should rarely be used)

        Note: AssessmentMiddleware does not have access to RequestContext, so it cannot check
        headers/cookies like RequestProcessor does. In practice, the controller layer should
        set request.session_id before middleware runs, ensuring consistency with RequestProcessor.

        Args:
            request: Chat request

        Returns:
            Session ID for tracking (must be non-empty per Requirement 8.1)

        See Also:
            - RequestProcessor.resolve_session_id() for full session resolution logic
            - Requirement 8.1: Session identity coverage across entry points
        """
        # Try to get session ID from request metadata (highest priority)
        # Controller layer (ChatController.handle_chat_completion) sets this at line 488
        if hasattr(request, "session_id") and request.session_id:
            return request.session_id

        # Try to get from request.extra_body (fallback for session_id passed via metadata)
        if hasattr(request, "extra_body") and isinstance(request.extra_body, dict):
            extra_session_id = request.extra_body.get("session_id")
            if isinstance(extra_session_id, str) and extra_session_id:
                return extra_session_id

        # Last resort: generate a UUID-based session ID
        # This should rarely be used in production - session_id should be set by controller layer
        # before middleware runs. UUID is stable within a single Python process (unlike hash).
        # Requirement 8.1: "MUST resolve or create a non-empty session identifier"
        # Note: This fallback creates a new session per request, which may not match the
        # session_id used by RequestProcessor/enforcer if controller doesn't set request.session_id.
        session_id = f"session_{uuid4().hex}"
        if logger.isEnabledFor(logging.WARNING):
            logger.warning(
                f"AssessmentMiddleware: Generated UUID-based session ID fallback: {session_id}. "
                f"Session ID should be set by controller layer (request.session_id or "
                f"request.extra_body['session_id']) before middleware runs. "
                f"This fallback creates a new session per request, which may not match the "
                f"session_id used by RequestProcessor/enforcer."
            )
        return session_id

    async def _inject_steering_message(
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

        # Tag the steering message as non-forwardable (client-history-only scope)
        if (
            self._non_forwardable_registry is not None
            and self._non_forwardable_identity_service is not None
        ):
            try:
                identity = self._non_forwardable_identity_service.compute_identity(
                    steering_message
                )
                await self._non_forwardable_registry.tag_identities(
                    session_id=assessment_result.session_id,
                    identities=[identity],
                    scope=NonForwardableTagScope.CLIENT_HISTORY_ONLY,
                    reason="assessment_steering",
                )
                if logger.isEnabledFor(logging.DEBUG):
                    logger.debug(
                        f"Tagged assessment steering message as client-history-only for session {assessment_result.session_id}, "
                        f"identity={identity[:16]}..."
                    )
            except NonForwardableTagLimitExceededError:
                # Fail closed - capacity exceeded (Req 14.3, 10.1)
                raise
            except Exception as e:
                # Fail closed on any tagging failure to prevent leakage (Req 10.1)
                raise NonForwardableEnforcementError(
                    f"Failed to tag assessment steering message as non-forwardable: {e}",
                    details={"session_id": assessment_result.session_id},
                ) from e

        # Add steering message to conversation history
        new_messages = [*list(request.messages), steering_message]
        injection_start_index = len(
            request.messages
        )  # Index where injected messages begin

        # Store injection boundary in request metadata for later use in RequestContext.
        # ChatRequest is a frozen Pydantic model, so we must update extra_body via model_copy
        # rather than mutating it in-place.
        existing_extra_body = (
            request.extra_body
            if hasattr(request, "extra_body") and request.extra_body
            else {}
        )
        new_extra_body = {
            **existing_extra_body,
            "_proxy_injected_messages_start_index": injection_start_index,
        }

        # Create new request with steering message using Pydantic model_copy
        modified_request = request.model_copy(
            update={
                "messages": new_messages,
                "extra_body": new_extra_body,
            }
        )

        if logger.isEnabledFor(logging.INFO):
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

    def get_middleware_info(self) -> MiddlewareInfo:
        """
        Get information about middleware state.

        Returns:
            MiddlewareInfo with middleware state
        """
        return MiddlewareInfo(
            enabled=self.config.enabled,
            turn_threshold=self.config.turn_threshold,
            confidence_threshold=self.config.confidence_threshold,
            backend=self.config.backend,
            model=self.config.model,
        )
