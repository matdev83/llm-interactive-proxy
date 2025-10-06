"""
Loop detection module for detecting repetitive patterns in LLM responses.

This module provides functionality to detect when LLM responses contain
repetitive patterns that indicate the model is stuck in a loop, allowing
for automatic cancellation of such requests.
"""

from .config import InternalLoopDetectionConfig
from .streaming import analyze_complete_response_for_loops

__all__ = [
    "InternalLoopDetectionConfig",
    "analyze_complete_response_for_loops",
]
