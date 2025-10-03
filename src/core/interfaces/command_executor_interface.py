"""Interface for command execution."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from src.core.domain.command_results import CommandResult


class ICommandExecutor(ABC):
    """Interface for executing parsed commands."""

    @abstractmethod
    async def execute(
        self,
        command: dict[str, Any],
        *,
        session_id: str,
        context: dict[str, Any] | None = None,
    ) -> CommandResult:
        """Run a single parsed command and return a domain CommandResult.

        Args:
            command: Parsed command details
            session_id: Session identifier
            context: Optional context for execution

        Returns:
            CommandResult with execution outcome
        """
