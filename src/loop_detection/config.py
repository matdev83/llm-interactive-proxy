"""
Configuration management for loop detection functionality.

Handles loading and validation of loop detection settings from various sources:
- Environment variables
- Configuration files
- Runtime commands
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class PatternThresholds:
    """Thresholds for different pattern lengths."""
    min_repetitions: int
    min_total_length: int


@dataclass
class LoopDetectionConfig:
    """Configuration for loop detection functionality."""
    
    # Core settings
    enabled: bool = True
    buffer_size: int = 2048
    max_pattern_length: int = 500
    
    # Pattern thresholds
    short_pattern_threshold: PatternThresholds = None
    medium_pattern_threshold: PatternThresholds = None
    long_pattern_threshold: PatternThresholds = None
    
    # Whitelist patterns that should not trigger detection
    whitelist: list[str] = None
    
    def __post_init__(self):
        """Initialize default thresholds if not provided."""
        if self.short_pattern_threshold is None:
            self.short_pattern_threshold = PatternThresholds(
                min_repetitions=8,  # Reduced to catch more patterns
                min_total_length=100  # 100 unicode chars minimum
            )
        
        if self.medium_pattern_threshold is None:
            self.medium_pattern_threshold = PatternThresholds(
                min_repetitions=4,  # Reduced to catch medium patterns
                min_total_length=100  # 100 unicode chars minimum
            )
        
        if self.long_pattern_threshold is None:
            self.long_pattern_threshold = PatternThresholds(
                min_repetitions=3,  # Keep at 3 for long patterns
                min_total_length=100  # 100 unicode chars minimum
            )
        
        if self.whitelist is None:
            self.whitelist = ["...", "---", "===", "```"]
    
    @classmethod
    def from_dict(cls, config_dict: dict[str, Any]) -> LoopDetectionConfig:
        """Create configuration from dictionary."""
        config = cls()
        
        if "enabled" in config_dict:
            config.enabled = bool(config_dict["enabled"])
        
        if "buffer_size" in config_dict:
            config.buffer_size = int(config_dict["buffer_size"])
        
        if "max_pattern_length" in config_dict:
            config.max_pattern_length = int(config_dict["max_pattern_length"])
        
        if "whitelist" in config_dict:
            config.whitelist = list(config_dict["whitelist"])
        
        # Handle thresholds
        thresholds = config_dict.get("thresholds", {})
        
        if "short_patterns" in thresholds:
            short = thresholds["short_patterns"]
            config.short_pattern_threshold = PatternThresholds(
                min_repetitions=int(short.get("min_repetitions", 12)),
                min_total_length=int(short.get("min_total_length", 50))
            )
        
        if "medium_patterns" in thresholds:
            medium = thresholds["medium_patterns"]
            config.medium_pattern_threshold = PatternThresholds(
                min_repetitions=int(medium.get("min_repetitions", 6)),
                min_total_length=int(medium.get("min_total_length", 100))
            )
        
        if "long_patterns" in thresholds:
            long = thresholds["long_patterns"]
            config.long_pattern_threshold = PatternThresholds(
                min_repetitions=int(long.get("min_repetitions", 3)),
                min_total_length=int(long.get("min_total_length", 200))
            )
        
        return config
    
    @classmethod
    def from_env_vars(cls, env_dict: dict[str, str]) -> LoopDetectionConfig:
        """Create configuration from environment variables."""
        config = cls()
        
        if "LOOP_DETECTION_ENABLED" in env_dict:
            config.enabled = env_dict["LOOP_DETECTION_ENABLED"].lower() in ("true", "1", "yes", "on")
        
        if "LOOP_DETECTION_BUFFER_SIZE" in env_dict:
            config.buffer_size = int(env_dict["LOOP_DETECTION_BUFFER_SIZE"])
        
        if "LOOP_DETECTION_MAX_PATTERN_LENGTH" in env_dict:
            config.max_pattern_length = int(env_dict["LOOP_DETECTION_MAX_PATTERN_LENGTH"])
        
        # Threshold environment variables
        if "LOOP_DETECTION_MIN_REPETITIONS_SHORT" in env_dict:
            config.short_pattern_threshold.min_repetitions = int(
                env_dict["LOOP_DETECTION_MIN_REPETITIONS_SHORT"]
            )
        
        if "LOOP_DETECTION_MIN_REPETITIONS_MEDIUM" in env_dict:
            config.medium_pattern_threshold.min_repetitions = int(
                env_dict["LOOP_DETECTION_MIN_REPETITIONS_MEDIUM"]
            )
        
        if "LOOP_DETECTION_MIN_REPETITIONS_LONG" in env_dict:
            config.long_pattern_threshold.min_repetitions = int(
                env_dict["LOOP_DETECTION_MIN_REPETITIONS_LONG"]
            )
        
        return config
    
    def get_threshold_for_pattern_length(self, pattern_length: int) -> PatternThresholds:
        """Get appropriate threshold based on pattern length."""
        if pattern_length <= 10:
            return self.short_pattern_threshold
        elif pattern_length <= 50:
            return self.medium_pattern_threshold
        else:
            return self.long_pattern_threshold
    
    def validate(self) -> list[str]:
        """Validate configuration and return list of errors."""
        errors = []
        
        if self.buffer_size <= 0:
            errors.append("buffer_size must be positive")
        
        if self.max_pattern_length <= 0:
            errors.append("max_pattern_length must be positive")
        
        if self.max_pattern_length > self.buffer_size:
            errors.append("max_pattern_length cannot be larger than buffer_size")
        
        # Validate thresholds
        for name, threshold in [
            ("short_pattern", self.short_pattern_threshold),
            ("medium_pattern", self.medium_pattern_threshold),
            ("long_pattern", self.long_pattern_threshold)
        ]:
            if threshold.min_repetitions <= 0:
                errors.append(f"{name}_threshold.min_repetitions must be positive")
            
            if threshold.min_total_length <= 0:
                errors.append(f"{name}_threshold.min_total_length must be positive")
        
        return errors