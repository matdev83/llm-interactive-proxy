"""
Tool Access Control Handler.

Enforces tool access policies on LLM responses by blocking disallowed tool calls
and returning configured block messages.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from cachetools import TTLCache

from src.core.interfaces.tool_call_reactor_interface import (
    IToolCallHandler,
    ToolCallContext,
    ToolCallReactionResult,
)
from src.core.services.tool_access_policy_service import ToolAccessPolicyService

logger = logging.getLogger(__name__)


class ToolAccessControlHandler(IToolCallHandler):
    """Handler that enforces tool access policies on tool calls."""

    def __init__(
        self,
        policy_service: ToolAccessPolicyService,
        priority: int = 90,
        reactor_service: Any | None = None,
    ) -> None:
        """Initialize with policy service.

        Args:
            policy_service: Service for evaluating tool access policies
            priority: Handler priority (default 90, after dangerous-command handler at 100)
            reactor_service: Optional reactor service for telemetry updates
        """
        self._policy_service = policy_service
        self._priority = priority
        self._reactor_service = reactor_service

        # Track sessions that have seen their first blocked tool call
        # Use TTLCache to prevent unbounded memory growth when sessions never cleanup
        # TTL:1 hour, Max size: 10,000 sessions
        self._sessions_with_blocked_tools: TTLCache[str, bool] = TTLCache(
            maxsize=10000, ttl=3600
        )
        self._lock = asyncio.Lock()

    @property
    def name(self) -> str:
        """The unique name of this handler."""
        return "tool_access_control_handler"

    @property
    def priority(self) -> int:
        """The priority of this handler (higher numbers run first)."""
        return self._priority

    async def can_handle(self, context: ToolCallContext) -> bool:
        """Check if this handler can process the given tool call.

        This handler evaluates all tool calls, so always returns True.

        Args:
            context: The tool call context.

        Returns:
            True for all tool calls.
        """
        return True

    async def handle(self, context: ToolCallContext) -> ToolCallReactionResult:
        """Evaluate tool call against policies and swallow if disallowed.

        Args:
            context: The tool call context.

        Returns:
            The reaction result indicating whether to swallow the tool call
            and any replacement response.
        """
        tool_name = context.tool_name
        model_name = context.model_name
        agent = context.calling_agent

        try:
            # Check if tool is allowed by policy
            is_allowed, metadata = self._policy_service.is_tool_allowed(
                tool_name, model_name, agent
            )

            if is_allowed:
                # Tool is allowed, pass through
                logger.debug(
                    f"Tool call '{tool_name}' allowed by policy "
                    f"'{metadata.get('policy_applied')}' in session {context.session_id}"
                )

                # Increment telemetry counter
                if self._reactor_service and hasattr(
                    self._reactor_service, "increment_tool_calls_allowed"
                ):
                    self._reactor_service.increment_tool_calls_allowed()

                return ToolCallReactionResult(
                    should_swallow=False,
                    metadata={
                        "handler": self.name,
                        "tool_name": tool_name,
                        "policy_applied": metadata.get("policy_applied"),
                        "decision": "allowed",
                        "model_name": model_name,
                        "agent": agent,
                        "session_id": context.session_id,
                        "evaluation_time_ms": metadata.get("evaluation_time_ms"),
                    },
                )

            # Tool is blocked, swallow and return block message
            block_message = self._policy_service.get_block_message(
                tool_name, model_name, agent
            )

            # Check if this is the first blocked tool call in this session
            is_first_block = context.session_id not in self._sessions_with_blocked_tools
            if is_first_block:
                async with self._lock:
                    self._sessions_with_blocked_tools[context.session_id] = True
                if logger.isEnabledFor(logging.INFO):
                    logger.info(
                        f"First blocked tool call in session {context.session_id}: '{tool_name}' "
                        f"by policy '{metadata.get('policy_applied')}'"
                    )

            if logger.isEnabledFor(logging.INFO):
                logger.info(
                    f"Blocked tool call '{tool_name}' by policy "
                    f"'{metadata.get('policy_applied')}' in session {context.session_id}"
                )
            if logger.isEnabledFor(logging.DEBUG):
                logger.debug(
                    f"Block reason: {metadata.get('reason')}, "
                    f"model: {model_name}, agent: {agent}"
                )

            # Increment telemetry counter
            if self._reactor_service and hasattr(
                self._reactor_service, "increment_tool_calls_blocked"
            ):
                self._reactor_service.increment_tool_calls_blocked()

            # Optionally add first-block notice to the message
            final_message = block_message
            if is_first_block:
                final_message = f"[Notice: Tool access control is active for this session]\n\n{block_message}"

            return ToolCallReactionResult(
                should_swallow=True,
                replacement_response=final_message,
                metadata={
                    "handler": self.name,
                    "tool_name": tool_name,
                    "policy_applied": metadata.get("policy_applied"),
                    "decision": "blocked",
                    "reason": metadata.get("reason"),
                    "model_name": model_name,
                    "agent": agent,
                    "session_id": context.session_id,
                    "is_first_block_in_session": is_first_block,
                    "evaluation_time_ms": metadata.get("evaluation_time_ms"),
                },
            )

        except Exception as e:
            # On error, fail open (allow the tool call)
            if logger.isEnabledFor(logging.WARNING):
                logger.warning(
                    f"Tool access policy evaluation failed for tool '{tool_name}': {e}",
                    exc_info=True,
                )
            return ToolCallReactionResult(
                should_swallow=False,
                metadata={
                    "handler": self.name,
                    "tool_name": tool_name,
                    "decision": "error_fail_open",
                    "error": str(e),
                },
            )
