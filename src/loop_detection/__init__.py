"""
Loop detection module for detecting repetitive patterns in LLM responses.

This module provides functionality to detect when LLM responses contain
repetitive patterns that indicate the model is stuck in a loop, allowing
for automatic cancellation of such requests.
"""

from .detector import LoopDetector, LoopDetectionEvent
from .config import LoopDetectionConfig
from .patterns import PatternAnalyzer
from .streaming import LoopDetectionStreamingResponse, wrap_streaming_content_with_loop_detection, analyze_complete_response_for_loops

__all__ = [
    "LoopDetector",
    "LoopDetectionEvent",
    "LoopDetectionConfig", 
    "PatternAnalyzer",
    "LoopDetectionStreamingResponse",
    "wrap_streaming_content_with_loop_detection",
    "analyze_complete_response_for_loops"
]