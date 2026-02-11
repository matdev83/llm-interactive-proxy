"""
Loop Breaking Service with API Cancellation and Steering Message Generation.

This service provides complete loop breaking functionality:
1. Detects loops using text-based pattern detection
2. Triggers API cancellation to stop token waste
3. Generates steering messages
4. Retries the request with steering message attached
"""

from __future__ import annotations

import json
import logging
from collections.abc import Callable, Mapping
from typing import Any

from src.core.common.logging_utils import get_logger
from src.core.domain.chat import ChatMessage, ChatRequest
from src.core.domain.request_context import RequestContext
from src.core.interfaces.backend_processor_interface import IBackendProcessor
from src.core.interfaces.loop_detector_interface import ILoopDetector
from src.core.ports.streaming_contracts import StreamingContent

logger = get_logger(__name__)


class LoopBreakingService:
    """
    Service that implements complete loop breaking functionality.

    This service integrates loop detection with API cancellation and steering message generation
    to provide the loop breaking mechanism originally intended in the system.
    """

    def __init__(
        self,
        loop_detector: ILoopDetector,
        backend_processor: IBackendProcessor | None = None,
    ) -> None:
        """
        Initialize loop breaking service.

        Args:
            loop_detector: Loop detector for text pattern detection
            backend_processor: Backend processor for handling retries
        """
        self.loop_detector = loop_detector
        self.backend_processor = backend_processor

    async def process_streaming_content(
        self,
        content: StreamingContent,
        session_id: str,
        cancel_callback: Callable[[], Any] | None = None,
    ) -> tuple[StreamingContent, bool]:
        """
        Process streaming content and check for loops with proper breaking action.

        Args:
            content: The streaming content to process
            session_id: Session ID for logging and tracking
            cancel_callback: Optional callback to trigger API cancellation

        Returns:
            Tuple of (processed_content, should_break_stream)
        """
        if content.is_empty and not content.is_done:
            return content, False

        # Process content for loop detection
        raw_content = content.content
        if isinstance(raw_content, bytes):
            content_str = raw_content.decode("utf-8", errors="ignore")
        elif isinstance(raw_content, dict):
            content_str = json.dumps(raw_content)
        else:
            content_str = str(raw_content or "")
        detection_event = self.loop_detector.process_chunk(content_str)

        if not detection_event:
            # No loop detected, pass through content
            return content, False

        # Loop detected - trigger breaking flow
        logger.warning(
            f"Loop detected in streaming response: pattern='{detection_event.pattern[:50]}...', "
            f"repetitions={detection_event.repetition_count}, session_id={session_id}"
        )

        # Step 1: Trigger API cancellation if callback is available
        if cancel_callback is not None:
            logger.info(
                f"Triggering API cancellation due to loop detection - session_id={session_id}"
            )
            try:
                await cancel_callback()
                logger.info(
                    f"API cancellation triggered successfully - session_id={session_id}"
                )
            except Exception as e:
                logger.error(
                    f"Failed to trigger API cancellation - session_id={session_id}, error={e}",
                    exc_info=True,
                )

        # Step 2: Generate steering message
        steering_message = await self._generate_steering_message(
            detection_event, session_id
        )

        # Step 3: Create break content with steering information
        break_content = self._create_break_content(detection_event, steering_message)

        return break_content, True

    async def _generate_steering_message(self, detection_event, session_id: str) -> str:
        """
        Generate an appropriate steering message for the detected loop.

        Args:
            detection_event: The loop detection event containing pattern and repetition details
            session_id: Session ID for logging

        Returns:
            Steering message to guide the LLM
        """
        if logger.isEnabledFor(logging.DEBUG):
            logger.debug(
                "Generating fallback loop steering message for session %s", session_id
            )
        return (
            "I noticed a repetitive response pattern "
            f"({detection_event.repetition_count} repetitions). "
            "Please stop repeating and provide a different, concrete next step."
        )

    def _create_break_content(
        self, detection_event, steering_message: str
    ) -> StreamingContent:
        """
        Create StreamingContent with loop break information.

        Args:
            detection_event: The loop detection event
            steering_message: The generated steering message

        Returns:
            StreamingContent containing break information
        """
        content = (
            f"[LOOP BROKEN] Pattern '{detection_event.pattern[:50]}...' "
            f"was repeated {detection_event.repetition_count} times. "
            f"Steering: {steering_message}"
        )

        return StreamingContent(
            content=content,
            is_done=True,
            is_cancellation=True,
            metadata={
                "loop_detected": True,
                "pattern": detection_event.pattern,
                "repetition_count": detection_event.repetition_count,
                "steering_message": steering_message,
                "loop_broken": True,
            },
        )

    async def create_retry_request_with_steering(
        self,
        original_request: ChatRequest,
        detection_event,
        session_id: str,
    ) -> ChatRequest:
        """
        Create a retry request with steering message attached.

        Args:
            original_request: The original request that triggered the loop
            detection_event: The loop detection event for context
            session_id: Session ID for tracking

        Returns:
            New ChatRequest with steering message
        """
        # Generate steering message
        steering_message = await self._generate_steering_message(
            detection_event, session_id
        )

        # Create retry messages with steering added as system message
        retry_messages = list(original_request.messages)
        steering_system_message = ChatMessage(
            role="system",
            content=(
                f"The previous response was canceled due to a loop detection. "
                f"Please continue with a different approach.\n\n"
                f"Loop Details:\n"
                f"- Pattern: '{detection_event.pattern}'\n"
                f"- Repetitions: {detection_event.repetition_count}\n\n"
                f"Steering Guidance: {steering_message}"
            ),
        )
        retry_messages.append(steering_system_message)

        # Return new request with steering message
        return original_request.model_copy(update={"messages": retry_messages})

    async def process_loop_breaking_retry(
        self,
        original_request: ChatRequest,
        detection_event,
        session_id: str,
        context: RequestContext | Mapping[str, Any] | None = None,
    ) -> Any:
        """
        Complete loop breaking flow: cancel API and retry with steering.

        Args:
            original_request: The original request
            detection_event: Loop detection event
            session_id: Session ID
            context: Request context for retry

        Returns:
            Backend response from retry attempt
        """
        if self.backend_processor is None:
            logger.error(
                f"Backend processor not available - cannot retry - session_id={session_id}"
            )
            raise RuntimeError(
                "Cannot retry request without backend processor configured"
            )

        logger.info(
            f"Initiating loop breaking retry - session_id={session_id}, "
            f"pattern='{detection_event.pattern[:50]}...'"
        )

        # Create retry request with steering
        retry_request = await self.create_retry_request_with_steering(
            original_request, detection_event, session_id
        )

        # Execute retry
        request_context: RequestContext | None
        if context is None:
            request_context = None
        elif isinstance(context, RequestContext):
            request_context = context
        else:
            request_context = RequestContext(
                headers=context.get("headers", {}),
                cookies=context.get("cookies", {}),
                state=context.get("state"),
                app_state=context.get("app_state"),
                client_host=context.get("client_host"),
                session_id=context.get("session_id"),
                agent=context.get("agent"),
                original_request=context.get("original_request"),
                processing_context=context.get("processing_context"),
            )

        return await self.backend_processor.process_backend_request(
            request=retry_request,
            session_id=session_id,
            context=request_context,
        )
