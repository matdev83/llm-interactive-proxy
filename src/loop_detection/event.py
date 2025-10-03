"""
Loop detection events.

This module defines the LoopDetectionEvent dataclass used for reporting
loop detection events.
"""

from __future__ import annotations

from dataclasses import dataclass

from src.core.interfaces.model_bases import InternalDTO


@dataclass
class LoopDetectionEvent(InternalDTO):
    """Event triggered when a loop is detected."""

    pattern: str
    repetition_count: int
    total_length: int
    confidence: float
    buffer_content: str
    timestamp: float
