"""
Agent response formatter interface.

This module defines the interface for agent-specific response formatting.
"""

from __future__ import annotations

from typing import Any, Protocol

from src.core.domain.session import Session


class IAgentResponseFormatter(Protocol):
    """Interface for agent-specific response formatting operations."""

    async def format_command_result_for_agent(
        self, command_result: Any, session: Session
    ) -> dict[str, Any]:
        """Format a command result for the specific agent type."""
        ...
