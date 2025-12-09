"""Steering policy interfaces and contracts."""

from __future__ import annotations

from abc import ABC, abstractmethod

from .models import SteeringResult


class ISteeringPolicy(ABC):
    """Contract for steering policies that evaluate tool call commands.

    Each policy is responsible for:
    - Determining if it should trigger based on the command context
    - Returning a SteeringResult if triggered, or None otherwise
    - Avoiding side effects beyond telemetry and state tracking

    ## Adding a New Policy
    1. Implement this interface.
    2. Register the implementation in DI (e.g., in SteeringStage).
    3. Add it to the list of policies injected into UnifiedSteeringHandler.

    Example:
    ```python
    class MyPolicy(ISteeringPolicy):
        @property
        def name(self) -> str: return "my_policy"

        @property
        def priority(self) -> int: return 50

        async def evaluate(self, context, command, dry_run=False):
            if "forbidden" in command:
                if not dry_run:
                    # record metrics/state
                    pass
                return SteeringResult(message="Blocked", should_block=True)
            return None
    ```
    """

    @property
    @abstractmethod
    def name(self) -> str:
        """Unique identifier for this policy (used in telemetry)."""
        ...

    @property
    @abstractmethod
    def priority(self) -> int:
        """Priority for policy ordering (higher = evaluated earlier)."""
        ...

    @abstractmethod
    async def evaluate(
        self, context: ToolCallContext, command: str, dry_run: bool = False
    ) -> SteeringResult | None:
        """Evaluate the command and return a steering result if the policy triggers.

        Args:
            context: Tool call context containing session_id, tool_name, arguments
            command: Normalized command string extracted from tool arguments
            dry_run: If True, do not apply side effects (e.g. rate limiting, state updates)

        Returns:
            SteeringResult if policy triggers, None otherwise

        Preconditions:
            - command is a normalized string (whitespace collapsed)

        Postconditions:
            - Returns None or SteeringResult; no exceptions raised
            - Side effects limited to telemetry and state tracking
        """
        ...


# Import cycle prevention: define the interface dependency here
from src.core.interfaces.tool_call_reactor_interface import ToolCallContext

__all__ = ["ISteeringPolicy", "ToolCallContext"]
