"""Unified Steering Handler - Single entry point for tool call steering."""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from typing import Any

from src.core.interfaces.tool_call_reactor_interface import (
    IToolCallHandler,
    ToolCallContext,
    ToolCallReactionResult,
)

from .command_utils import extract_command_from_arguments, normalize_whitespace
from .interfaces import ISteeringPolicy
from .models import SteeringResult

logger = logging.getLogger(__name__)


class UnifiedSteeringHandler(IToolCallHandler):
    """Unified steering handler that evaluates tool calls via priority-ordered policies.

    This handler:
    - Extracts and normalizes commands once per tool call
    - Evaluates policies in priority order (highest first)
    - Short-circuits on first policy match
    - Falls back to no-op if no policies match
    - Emits structured telemetry for each evaluation
    """

    def __init__(
        self,
        policies: list[ISteeringPolicy],
        enabled: bool = True,
        priority_overrides: dict[str, int] | None = None,
        monotonic: Callable[[], float] | None = None,
    ) -> None:
        """Initialize the unified steering handler.

        Args:
            policies: List of steering policies (will be sorted by priority)
            enabled: Whether steering is enabled
            priority_overrides: Optional map of policy name to priority
            monotonic: Time source for testing (defaults to time.monotonic)
        """
        self._enabled = enabled
        self._monotonic = monotonic or time.monotonic
        self._priority_overrides = priority_overrides or {}

        # Sort policies by priority (highest first), taking overrides into account
        def get_priority(policy: ISteeringPolicy) -> int:
            return self._priority_overrides.get(policy.name, policy.priority)

        self._policies = sorted(
            [p for p in policies if p],
            key=get_priority,
            reverse=True,
        )

        if logger.isEnabledFor(logging.INFO):
            logger.info(
                "Initialized UnifiedSteeringHandler with %d policies: %s",
                len(self._policies),
                [p.name for p in self._policies],
            )

    @property
    def name(self) -> str:
        return "unified_steering_handler"

    @property
    def priority(self) -> int:
        # High priority to ensure steering happens before general execution
        return 95

    async def can_handle(self, context: ToolCallContext) -> bool:
        """Check if any policy can handle this tool call."""
        if not self._enabled:
            return False

        command = extract_command_from_arguments(context.tool_arguments)
        normalized = normalize_whitespace(command) if command else ""

        # Check if any policy would trigger
        for policy in self._policies:
            try:
                result = await policy.evaluate(context, normalized, dry_run=True)
                if result:
                    return True
            except Exception as e:
                if logger.isEnabledFor(logging.WARNING):
                    logger.warning(
                        "Policy %s raised exception during can_handle: %s",
                        policy.name,
                        e,
                        exc_info=True,
                    )
                # Continue to next policy on error
                continue

        return False

    async def handle(self, context: ToolCallContext) -> ToolCallReactionResult:
        """Handle tool call by evaluating policies in priority order."""
        if not self._enabled:
            return ToolCallReactionResult(should_swallow=False)

        start_time = self._monotonic()
        command = extract_command_from_arguments(context.tool_arguments)
        normalized = normalize_whitespace(command) if command else ""
        evaluated_policies: list[str] = []
        matched_policy: str | None = None
        result: SteeringResult | None = None

        # Evaluate policies in priority order
        for policy in self._policies:
            evaluated_policies.append(policy.name)

            try:
                policy_result = await policy.evaluate(
                    context, normalized, dry_run=False
                )
                if policy_result:
                    result = policy_result
                    matched_policy = policy.name
                    break  # Short-circuit on first match
            except Exception as e:
                if logger.isEnabledFor(logging.ERROR):
                    logger.error(
                        "Policy %s raised exception: %s",
                        policy.name,
                        e,
                        exc_info=True,
                    )
                # Continue to next policy on error (graceful degradation)
                continue

        elapsed = self._monotonic() - start_time

        # Emit telemetry
        self._emit_telemetry(
            context=context,
            command=normalized,
            evaluated_policies=evaluated_policies,
            matched_policy=matched_policy,
            result=result,
            elapsed=elapsed,
        )

        # Return result if matched
        if result:
            # Prefer source from policy result, fallback to unified_steering
            source = result.metadata.get("source", "unified_steering")

            return ToolCallReactionResult(
                should_swallow=result.should_block,
                replacement_response=result.message,
                metadata={
                    "handler": self.name,
                    "matched_policy": matched_policy,
                    "tool_name": context.tool_name,
                    "command": normalized[:200],  # Truncate for logging
                    "source": source,
                    **result.metadata,
                },
            )

        # No policy matched - pass through
        return ToolCallReactionResult(should_swallow=False)

    def _emit_telemetry(
        self,
        context: ToolCallContext,
        command: str,
        evaluated_policies: list[str],
        matched_policy: str | None,
        result: SteeringResult | None,
        elapsed: float,
    ) -> None:
        """Emit structured telemetry for this evaluation.

        Args:
            context: The tool call context.
            command: The normalized command string.
            evaluated_policies: List of policy names that were evaluated.
            matched_policy: The name of the policy that matched (if any).
            result: The SteeringResult if a policy matched, otherwise None.
            elapsed: The time taken for evaluation in seconds.
        """
        if not logger.isEnabledFor(logging.INFO):
            return

        log_data: dict[str, Any] = {
            "session_id": context.session_id,
            "tool_name": context.tool_name,
            "command_preview": command[:100],
            "evaluated_policies": evaluated_policies,
            "matched_policy": matched_policy,
            "outcome": "steered" if result else "pass_through",
            "elapsed_ms": round(elapsed * 1000, 2),
        }

        if result:
            log_data["severity"] = result.severity
            log_data["should_block"] = result.should_block

        logger.info("Unified steering evaluation: %s", log_data)


__all__ = ["UnifiedSteeringHandler"]
