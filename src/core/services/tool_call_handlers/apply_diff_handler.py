"""
Apply Diff Tool Call Handler.

This module implements a tool call handler that monitors for 'apply_diff' tool calls
and provides steering instructions to use 'patch_file' instead, with rate limiting.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Any

from src.core.domain.tool_call_reactor import (
    ToolCallRateLimit,
    ToolCallReaction,
    ToolCallReactionConfig,
    ToolCallReactionMode,
    ToolCallSteeringResponse,
)
from src.core.interfaces.tool_call_reactor_interface import (
    IToolCallHandler,
    IToolCallHistoryTracker,
    ToolCallContext,
    ToolCallReactionResult,
)

logger = logging.getLogger(__name__)


class ApplyDiffHandler(IToolCallHandler):
    """Handler for apply_diff tool calls that provides steering instructions.

    This handler monitors for 'apply_diff' tool calls and swallows them to provide
    steering instructions recommending the use of 'patch_file' instead, which is
    considered superior due to automated QA checks.

    The handler includes rate limiting to prevent spamming the same session
    with repeated steering messages within a short time window.
    """

    def __init__(
        self,
        history_tracker: IToolCallHistoryTracker | None = None,
        rate_limit_window_seconds: int = 60,
        steering_message: str | None = None,
    ):
        """Initialize the apply_diff handler.

        Args:
            history_tracker: Optional history tracker for rate limiting
            rate_limit_window_seconds: Time window for rate limiting (default: 60 seconds)
            steering_message: Custom steering message (uses default if None)
        """
        self._history_tracker = history_tracker
        self._rate_limit_window = rate_limit_window_seconds
        self._last_steering_times: dict[str, datetime] = {}

        # Default steering message
        self._steering_message = steering_message or (
            "You tried to use apply_diff tool. Please prefer to use patch_file tool instead, "
            "as it is superior to apply_diff and provides automated Python QA checks."
        )

        # Create the reaction configuration
        self._reaction_config = ToolCallReactionConfig(
            tool_name_pattern="apply_diff",
            mode=ToolCallReactionMode.ACTIVE,
            rate_limit=ToolCallRateLimit(
                calls_per_window=1,
                window_seconds=self._rate_limit_window,
            ),
            enabled=True,
        )

        # Create the steering response
        self._steering_response = ToolCallSteeringResponse(
            content=self._steering_message,
            role="user",
            metadata={
                "handler": self.name,
                "steering_type": "tool_preference",
                "recommended_tool": "patch_file",
                "discouraged_tool": "apply_diff",
            },
        )

        # Create the reaction
        self._reaction = ToolCallReaction(
            config=self._reaction_config,
            steering_response=self._steering_response,
            name=self.name,
            description="Steers users away from apply_diff towards patch_file with automated QA",
        )

    @property
    def name(self) -> str:
        """The unique name of this handler."""
        return "apply_diff_steering_handler"

    @property
    def priority(self) -> int:
        """The priority of this handler (higher numbers run first)."""
        return 100  # High priority for tool steering

    async def can_handle(self, context: ToolCallContext) -> bool:
        """Check if this handler can process the given tool call.

        Args:
            context: The tool call context.

        Returns:
            True if this handler can process the tool call.
        """
        # Check if the tool name matches
        if context.tool_name != "apply_diff":
            return False

        # Check rate limiting
        if not await self._should_provide_steering(context.session_id):
            logger.debug(
                f"Rate limiting apply_diff steering for session {context.session_id}"
            )
            return False

        return True

    async def handle(self, context: ToolCallContext) -> ToolCallReactionResult:
        """Handle the tool call event.

        Args:
            context: The tool call context.

        Returns:
            The reaction result indicating the tool call should be swallowed
            with steering instructions.
        """
        logger.info(
            f"Providing apply_diff steering for session {context.session_id}, "
            f"tool: {context.tool_name}"
        )

        # Update the last steering time
        self._last_steering_times[context.session_id] = datetime.now()

        # Record this steering action if history tracker is available
        if self._history_tracker:
            await self._history_tracker.record_tool_call(
                context.session_id,
                context.tool_name,
                {
                    "steering_provided": True,
                    "steering_message": self._steering_message,
                    "recommended_tool": "patch_file",
                    "handler": self.name,
                    "timestamp": datetime.now(),
                },
            )

        return ToolCallReactionResult(
            should_swallow=True,
            replacement_response=self._steering_message,
            metadata={
                "handler": self.name,
                "steering_type": "tool_preference",
                "original_tool": context.tool_name,
                "recommended_tool": "patch_file",
                "rate_limited": True,
                "rate_limit_window_seconds": self._rate_limit_window,
            },
        )

    async def _should_provide_steering(self, session_id: str) -> bool:
        """Check if steering should be provided based on rate limiting.

        Args:
            session_id: The session ID to check.

        Returns:
            True if steering should be provided, False if rate limited.
        """
        now = datetime.now()
        last_steering = self._last_steering_times.get(session_id)

        if last_steering is None:
            return True

        time_since_last_steering = now - last_steering
        return time_since_last_steering >= timedelta(seconds=self._rate_limit_window)

    def get_reaction_config(self) -> ToolCallReaction:
        """Get the reaction configuration for this handler.

        Returns:
            The reaction configuration.
        """
        return self._reaction

    def reset_rate_limit(self, session_id: str) -> None:
        """Reset the rate limit for a session.

        Args:
            session_id: The session ID to reset.
        """
        if session_id in self._last_steering_times:
            del self._last_steering_times[session_id]
            logger.debug(f"Reset rate limit for session {session_id}")

    def get_steering_stats(self, session_id: str) -> dict[str, Any]:
        """Get steering statistics for a session.

        Args:
            session_id: The session ID to get stats for.

        Returns:
            Dictionary with steering statistics.
        """
        last_steering = self._last_steering_times.get(session_id)
        now = datetime.now()

        if last_steering is None:
            return {
                "session_id": session_id,
                "steering_count": 0,
                "last_steering": None,
                "time_since_last_steering": None,
                "can_steer_now": True,
            }

        time_since_last = now - last_steering

        return {
            "session_id": session_id,
            "steering_count": 1,  # Simplified - could track actual count
            "last_steering": last_steering.isoformat(),
            "time_since_last_steering_seconds": time_since_last.total_seconds(),
            "can_steer_now": time_since_last
            >= timedelta(seconds=self._rate_limit_window),
            "rate_limit_window_seconds": self._rate_limit_window,
        }
