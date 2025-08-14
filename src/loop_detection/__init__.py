"""
Loop detection module for detecting repetitive patterns in LLM responses.

This module provides functionality to detect when LLM responses contain
repetitive patterns that indicate the model is stuck in a loop, allowing
for automatic cancellation of such requests.
"""

from .config import LoopDetectionConfig
from .detector import LoopDetectionEvent, LoopDetector
from .streaming import (
    LoopDetectionStreamingResponse,
    analyze_complete_response_for_loops,
    wrap_streaming_content_with_loop_detection,
)

__all__ = [
    "LoopDetectionConfig",
    "LoopDetectionEvent",
    "LoopDetectionStreamingResponse",
    "LoopDetector",
    "analyze_complete_response_for_loops",
    "wrap_streaming_content_with_loop_detection",
]
