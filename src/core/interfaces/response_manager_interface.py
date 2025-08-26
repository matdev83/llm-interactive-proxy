"""
Response manager interface.

This module defines the interface for response processing and formatting.
"""

from __future__ import annotations

from typing import Protocol

from src.core.domain.processed_result import ProcessedResult
from src.core.domain.responses import ResponseEnvelope
from src.core.domain.session import Session


class IResponseManager(Protocol):
    """Interface for response management operations."""

    async def process_command_result(
        self, command_result: ProcessedResult, session: Session
    ) -> ResponseEnvelope:
        """Process a command-only result into a ResponseEnvelope."""
        ...
