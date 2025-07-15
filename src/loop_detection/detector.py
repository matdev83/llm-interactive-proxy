"""
Main loop detection logic.

This module provides the LoopDetector class which manages response buffers,
analyzes patterns, and determines when to trigger loop detection events.
"""

from __future__ import annotations

import logging
from typing import Optional, Callable, List, Any
from dataclasses import dataclass
from collections import deque

from .config import LoopDetectionConfig
from .patterns import PatternAnalyzer, PatternMatch

logger = logging.getLogger(__name__)


@dataclass
class LoopDetectionEvent:
    """Event triggered when a loop is detected."""
    pattern: str
    repetition_count: int
    total_length: int
    confidence: float
    buffer_content: str
    timestamp: float


class ResponseBuffer:
    """Manages a sliding window buffer of response content."""
    
    def __init__(self, max_size: int = 2048):
        self.max_size = max_size
        self.buffer = deque(maxlen=max_size)
        self.total_length = 0
    
    def append(self, text: str) -> None:
        """Append text to the buffer.

        The previous implementation tried to maintain ``total_length`` by
        decrementing before the deque dropped an element and incrementing after
        each append.  When ``deque.maxlen`` is reached the element is actually
        *popped from the left **after*** the new element is appended, which
        resulted in an off-by-one error.  The simple, cheap and correct
        approach is to append the whole text first and then set
        ``total_length`` from the real deque size (``len(self.buffer)``).
        The small ``len`` call is negligible compared to the cost of pattern
        analysis and removes the risk of drift.
        """

        for char in text:
            self.buffer.append(char)  # deque handles overflow automatically

        # Keep authoritative count (avoids off-by-one errors)
        self.total_length = len(self.buffer)
    
    def get_content(self) -> str:
        """Get the current buffer content as a string."""
        return ''.join(self.buffer)
    
    def get_recent_content(self, length: int) -> str:
        """Get the most recent content up to specified length."""
        content = self.get_content()
        return content[-length:] if len(content) > length else content
    
    def clear(self) -> None:
        """Clear the buffer."""
        self.buffer.clear()
        self.total_length = 0
    
    def size(self) -> int:
        """Get current buffer size."""
        return len(self.buffer)


class LoopDetector:
    """Main loop detection class."""
    
    def __init__(
        self,
        config: Optional[LoopDetectionConfig] = None,
        on_loop_detected: Optional[Callable[[LoopDetectionEvent], None]] = None
    ):
        self.config = config or LoopDetectionConfig()
        self.on_loop_detected = on_loop_detected
        
        # Validate configuration
        config_errors = self.config.validate()
        if config_errors:
            raise ValueError(f"Invalid loop detection configuration: {', '.join(config_errors)}")
        
        # Initialize components
        self.buffer = ResponseBuffer(max_size=self.config.buffer_size)
        self.pattern_analyzer = PatternAnalyzer(
            max_pattern_length=self.config.max_pattern_length,
            whitelist=self.config.whitelist
        )
        
        # State tracking
        self.is_active = self.config.enabled
        self.total_processed = 0
        self.last_detection_position = -1
        
        logger.info(f"LoopDetector initialized: enabled={self.is_active}, "
                   f"buffer_size={self.config.buffer_size}, "
                   f"max_pattern_length={self.config.max_pattern_length}")
    
    def process_chunk(self, chunk: str) -> Optional[LoopDetectionEvent]:
        """Process a chunk of response text and check for loops."""
        if not self.is_active or not chunk:
            return None
        
        # Add chunk to buffer
        self.buffer.append(chunk)
        self.total_processed += len(chunk)
        
        # Only analyze if we have enough content
        if self.buffer.size() < 50:  # Minimum content threshold
            return None
        
        # Get current buffer content
        buffer_content = self.buffer.get_content()
        
        # Analyze for patterns
        matches = self.pattern_analyzer.find_patterns_in_text(buffer_content)
        
        # Check if any matches meet our thresholds
        for match in matches:
            if self._should_trigger_detection(match):
                event = self._create_detection_event(match, buffer_content)
                
                # Update state
                self.last_detection_position = self.total_processed
                
                # Log the detection
                logger.warning(f"Loop detected: pattern='{match.pattern[:50]}...', "
                              f"repetitions={match.repetition_count}, "
                              f"confidence={match.confidence:.2f}")
                
                # Trigger callback if provided
                if self.on_loop_detected:
                    try:
                        self.on_loop_detected(event)
                    except Exception as e:
                        logger.error(f"Error in loop detection callback: {e}")
                
                return event
        
        return None
    
    def _should_trigger_detection(self, match: PatternMatch) -> bool:
        """Determine if a pattern match should trigger loop detection."""
        pattern_length = len(match.pattern)
        threshold = self.config.get_threshold_for_pattern_length(pattern_length)
        
        # Check repetition count threshold
        if match.repetition_count < threshold.min_repetitions:
            return False
        
        # Check total length threshold
        if match.total_length < threshold.min_total_length:
            return False
        
        # Check confidence threshold (minimum 0.5)
        if match.confidence < 0.5:
            return False
        
        # Avoid triggering multiple times for the same area
        detection_gap = 100  # Minimum characters between detections
        if (self.last_detection_position >= 0 and 
            self.total_processed - self.last_detection_position < detection_gap):
            return False
        
        return True
    
    def _create_detection_event(self, match: PatternMatch, buffer_content: str) -> LoopDetectionEvent:
        """Create a loop detection event from a pattern match."""
        import time
        
        return LoopDetectionEvent(
            pattern=match.pattern,
            repetition_count=match.repetition_count,
            total_length=match.total_length,
            confidence=match.confidence,
            buffer_content=buffer_content,
            timestamp=time.time()
        )
    
    def enable(self) -> None:
        """Enable loop detection."""
        self.is_active = True
        logger.info("Loop detection enabled")
    
    def disable(self) -> None:
        """Disable loop detection."""
        self.is_active = False
        logger.info("Loop detection disabled")
    
    def is_enabled(self) -> bool:
        """Check if loop detection is enabled."""
        return self.is_active
    
    def reset(self) -> None:
        """Reset the detector state."""
        self.buffer.clear()
        self.total_processed = 0
        self.last_detection_position = -1
        logger.debug("Loop detector state reset")
    
    def get_stats(self) -> dict:
        """Get detector statistics."""
        return {
            "enabled": self.is_active,
            "total_processed": self.total_processed,
            "buffer_size": self.buffer.size(),
            "last_detection_position": self.last_detection_position,
            "config": {
                "buffer_size": self.config.buffer_size,
                "max_pattern_length": self.config.max_pattern_length,
                "short_threshold": {
                    "min_repetitions": self.config.short_pattern_threshold.min_repetitions,
                    "min_total_length": self.config.short_pattern_threshold.min_total_length
                },
                "medium_threshold": {
                    "min_repetitions": self.config.medium_pattern_threshold.min_repetitions,
                    "min_total_length": self.config.medium_pattern_threshold.min_total_length
                },
                "long_threshold": {
                    "min_repetitions": self.config.long_pattern_threshold.min_repetitions,
                    "min_total_length": self.config.long_pattern_threshold.min_total_length
                }
            }
        }
    
    def update_config(self, new_config: LoopDetectionConfig) -> None:
        """Update the detector configuration."""
        # Validate new configuration
        config_errors = new_config.validate()
        if config_errors:
            raise ValueError(f"Invalid loop detection configuration: {', '.join(config_errors)}")
        
        self.config = new_config
        self.is_active = new_config.enabled
        
        # Update components
        if self.buffer.max_size != new_config.buffer_size:
            # Create new buffer with new size
            old_content = self.buffer.get_content()
            self.buffer = ResponseBuffer(max_size=new_config.buffer_size)
            if old_content:
                # Keep the most recent content that fits
                recent_content = old_content[-new_config.buffer_size:] if len(old_content) > new_config.buffer_size else old_content
                self.buffer.append(recent_content)
        
        self.pattern_analyzer = PatternAnalyzer(
            max_pattern_length=new_config.max_pattern_length,
            whitelist=new_config.whitelist
        )
        
        logger.info(f"Loop detector configuration updated: enabled={self.is_active}")