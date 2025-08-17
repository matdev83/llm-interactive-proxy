"""
Base command implementation.

This module provides the base class for all commands in the new architecture.
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from collections.abc import Mapping
from typing import Any

from src.core.domain.command_results import CommandResult
from src.core.domain.session import Session

logger = logging.getLogger(__name__)


class BaseCommand(ABC):
    """Base class for all commands in the new architecture."""

    name: str
    format: str = ""
    description: str = ""
    examples: list[str] = []

    @abstractmethod
    async def execute(
        self, args: Mapping[str, Any], session: Session, context: Any = None
    ) -> CommandResult:
        """
        Execute the command.

        Args:
            args: Command arguments
            session: The session
            context: Optional context

        Returns:
            The command result
        """
