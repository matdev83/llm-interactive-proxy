"""End-of-Session tool call handler.

This handler detects completion tool calls and emits End-of-Session signals
via the EndOfSessionService.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from src.core.config.models.end_of_session import EndOfSessionConfig
from src.core.domain.events.end_of_session_events import (
    EndOfSessionSignal,
    EndOfSessionSignalType,
    EndOfSessionTerminationCategory,
)
from src.core.interfaces.end_of_session_service_interface import IEndOfSessionService
from src.core.interfaces.tool_call_reactor_interface import (
    IToolCallHandler,
    ToolCallContext,
    ToolCallReactionResult,
)
from src.services.test_execution_reminder.completion_signal_detector import (
    CompletionSignalDetector,
)

logger = logging.getLogger(__name__)


class EndOfSessionToolCallHandler(IToolCallHandler):
    """Tool call handler that detects completion tool calls and emits EoS signals.

    This handler observes tool calls for completion tools (e.g., attempt_completion,
    finish) and emits End-of-Session signals via the EndOfSessionService. The handler
    does not interfere with tool call processing (fail-open, non-swallowing).
    """

    def __init__(
        self,
        end_of_session_service: IEndOfSessionService,
        config: EndOfSessionConfig,
    ) -> None:
        """Initialize the End-of-Session tool call handler.

        Args:
            end_of_session_service: Service for recording EoS signals
            config: End-of-Session configuration
        """
        self._eos_service = end_of_session_service
        self._config = config

    @property
    def name(self) -> str:
        """Return the unique name of this handler."""
        return "end_of_session_tool_call_handler"

    @property
    def priority(self) -> int:
        """Return the priority of this handler.

        Priority is set to 85, which is:
        - Below TestExecutionReminderHandler (90) to allow steering interventions
          to block completion (swallow tool calls) before EoS is emitted.
        - Above generic config steering handlers (typically 50-80).
        """
        return 85

    async def can_handle(self, context: ToolCallContext) -> bool:
        """Check if this handler can process the given tool call.

        This handler only processes completion tool calls. It checks if the
        tool name matches known completion tools.

        Args:
            context: The tool call context

        Returns:
            True if this is a completion tool call, False otherwise
        """
        # Skip if EoS detection is disabled
        if not self._config.enabled or not self._config.detect_tool_completion:
            return False

        # Check for session_id (required context)
        if not context.session_id:
            if logger.isEnabledFor(logging.DEBUG):
                logger.debug(
                    "EoS tool call handler: Missing session_id in context, skipping",
                    extra={"tool_name": context.tool_name},
                )
            return False

        # Early exit if session has already ended (hot-path dedupe)
        if self._eos_service.has_ended(context.session_id):
            if logger.isEnabledFor(logging.DEBUG):
                logger.debug(
                    "EoS tool call handler: Session %s already ended, skipping",
                    context.session_id,
                )
            return False

        # Check if this is a completion tool
        return CompletionSignalDetector.is_completion_tool(context.tool_name)

    async def handle(self, context: ToolCallContext) -> ToolCallReactionResult:
        """Handle the tool call event by emitting an EoS signal.

        This handler emits an End-of-Session signal but does not swallow the
        tool call, allowing normal processing to continue.

        Args:
            context: The tool call context

        Returns:
            ToolCallReactionResult indicating the tool call should not be swallowed
        """
        # Extract session_id from context
        session_id = context.session_id
        if not session_id:
            if logger.isEnabledFor(logging.DEBUG):
                logger.debug(
                    "EoS tool call handler: Missing session_id in context, skipping emission",
                    extra={"tool_name": context.tool_name},
                )
            return ToolCallReactionResult(should_swallow=False)

        # Create EoS signal
        signal = EndOfSessionSignal(
            session_id=session_id,
            signal_type=EndOfSessionSignalType.TOOL_COMPLETION,
            termination_category=EndOfSessionTerminationCategory.NORMAL,
            observed_at=datetime.now(timezone.utc),
            reason=f"Completion tool call detected: {context.tool_name}",
            backend=context.backend_name,
            protocol=None,  # Tool calls don't have explicit protocol
            request_id=None,  # Tool calls don't have explicit request_id
        )

        # Emit signal (fail-open on errors)
        try:
            await self._eos_service.record_signal(signal)
            if logger.isEnabledFor(logging.DEBUG):
                logger.debug(
                    "EoS signal emitted for completion tool call: session=%s, tool=%s",
                    session_id,
                    context.tool_name,
                    extra={
                        "session_id": session_id,
                        "tool_name": context.tool_name,
                        "signal_type": EndOfSessionSignalType.TOOL_COMPLETION.value,
                    },
                )
        except Exception as e:
            logger.warning(
                "Failed to record EoS signal from tool call handler: %s",
                e,
                exc_info=True,
                extra={
                    "session_id": session_id,
                    "tool_name": context.tool_name,
                },
            )

        # Return non-swallowing result to allow normal processing
        return ToolCallReactionResult(should_swallow=False)
