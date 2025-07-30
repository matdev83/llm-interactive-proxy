"""
Main loop detection logic.

This module provides the LoopDetector class which manages response buffers,
analyzes patterns, and determines when to trigger loop detection events.
"""

from __future__ import annotations

import logging
from collections import deque
from dataclasses import dataclass
from typing import Callable

from .config import LoopDetectionConfig
from .patterns import BlockAnalyzer, BlockMatch

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
        # Track actual stored content length for proper sliding window behavior
        self.stored_length = 0
    
    def append(self, text: str) -> None:
        """Append text to the buffer.
        
        Stores text chunks instead of individual characters for better performance.
        Manages sliding window behavior manually to maintain exact size limits.
        """
        if not text:
            return
            
        text_len = len(text)
        
        # If adding this text would exceed max_size, remove old content first
        if self.stored_length + text_len > self.max_size:
            # Remove old chunks until we have enough space
            excess = self.stored_length + text_len - self.max_size
            while excess > 0 and self.buffer:
                old_chunk = self.buffer.popleft()
                old_len = len(old_chunk)
                self.stored_length -= old_len
                excess -= old_len
        
        # Add the new text chunk
        self.buffer.append(text)
        self.stored_length += text_len
        self.total_length += text_len
    
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
        self.stored_length = 0
    
    def size(self) -> int:
        """Get current buffer size."""
        return self.stored_length


class LoopDetector:
    """Main loop detection class."""
    
    def __init__(
        self,
        config: LoopDetectionConfig | None = None,
        on_loop_detected: Callable[[LoopDetectionEvent], None] | None = None
    ):
        self.config = config or LoopDetectionConfig()
        self.on_loop_detected = on_loop_detected
        
        # Validate configuration
        config_errors = self.config.validate()
        if config_errors:
            raise ValueError(f"Invalid loop detection configuration: {', '.join(config_errors)}")
        
        # Initialize components
        self.buffer = ResponseBuffer(max_size=self.config.buffer_size)
        self.block_analyzer = BlockAnalyzer(
            min_block_length=100,
            max_block_length=self.config.max_pattern_length,
            whitelist=self.config.whitelist
        )
        
        # State tracking
        self.is_active = self.config.enabled
        self.total_processed = 0
        self.last_detection_position = -1
        # Track the last position (character count) where heavy analysis was
        # performed so we can skip redundant work when only a few new
        # characters have arrived (important for token-by-token streaming).
        self._last_analysis_position = -1
        
        logger.info(f"LoopDetector initialized: enabled={self.is_active}, "
                   f"buffer_size={self.config.buffer_size}, "
                   f"max_pattern_length={self.config.max_pattern_length}")
    
    def process_chunk(self, chunk: str) -> LoopDetectionEvent | None:
        """Process a chunk of response text and check for loops."""
        if not self.is_active or not chunk:
            return None
        
        chunk_len = len(chunk)
        
        # Add chunk to buffer
        self.buffer.append(chunk)
        self.total_processed += chunk_len

        # Only analyze if we have enough content
        if self.buffer.size() < 50:  # Minimum content threshold
            return None

        # Respect analysis interval optimisation (if enabled)
        interval = getattr(self.config, "analysis_interval", 0)
        if interval > 0 and self._last_analysis_position >= 0 and self.total_processed - self._last_analysis_position < interval:
            return None

        # Get current buffer content (only now that we're going to use it)
        buffer_content = self.buffer.get_content()

        # Analyze for blocks
        matches = self.block_analyzer.find_blocks_in_text(buffer_content)
        
        # Check if any matches meet our thresholds
        for match in matches:
            if self._should_trigger_detection(match):
                event = self._create_detection_event(match, buffer_content)
                
                # Update state
                self.last_detection_position = self.total_processed
                
                # Log the detection
                logger.warning(f"Loop detected: block='{match.block[:50]}...', "
                              f"repetitions={match.repetition_count}, "
                              f"confidence={match.confidence:.2f}")
                
                # Trigger callback if provided
                if self.on_loop_detected:
                    try:
                        self.on_loop_detected(event)
                    except Exception as e:
                        logger.error(f"Error in loop detection callback: {e}")
                
                # Record that we did an analysis and triggered detection
                self._last_analysis_position = self.total_processed
                return event
        
        # Record that analysis was executed even if nothing was found so the
        # next call will be skipped until enough new data arrives.
        self._last_analysis_position = self.total_processed
        return None
    
    def _should_trigger_detection(self, match: BlockMatch) -> bool:
        """Determine if a block match should trigger loop detection."""
        block_length = len(match.block)
        threshold = self.config.get_threshold_for_pattern_length(block_length)
        
        # Check repetition count threshold
        if match.repetition_count < threshold.min_repetitions:
            return False
        
        # Check total length threshold
        if match.total_length < threshold.min_total_length:
            return False
        
        # Dynamic confidence threshold - allow lower confidence for very
        # short repeating units (e.g. single characters or short words) to
        # avoid missing blatant loops like "ERROR ERROR ..." which would have
        # a low diversity score by their very nature.
        # For substantial blocks (>=100 chars) we rely on size + repetition
        # thresholds and therefore do *not* enforce a confidence floor.  For
        # medium-sized blocks we keep the 0.5 limit; for tiny units we accept
        # 0.3 (see above).
        if block_length < 100:
            min_confidence = 0.3 if block_length <= 10 else 0.5
            if match.confidence < min_confidence:
                return False
        
        # Avoid triggering multiple times for the same area
        detection_gap = 100  # Minimum characters between detections
        return not (self.last_detection_position >= 0 and self.total_processed - self.last_detection_position < detection_gap)
    
    def _create_detection_event(self, match: BlockMatch, buffer_content: str) -> LoopDetectionEvent:
        """Create a loop detection event from a pattern match."""
        import time
        
        return LoopDetectionEvent(
            pattern=match.block,
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
        self._last_analysis_position = -1
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
        
        self.block_analyzer = BlockAnalyzer(
            min_block_length=100,
            max_block_length=new_config.max_pattern_length,
            whitelist=new_config.whitelist
        )

        # Force re-analysis after configuration changes
        self._last_analysis_position = -1
        
        logger.info(f"Loop detector configuration updated: enabled={self.is_active}")