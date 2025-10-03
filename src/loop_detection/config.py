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

from src.core.interfaces.model_bases import InternalDTO


def _coerce_to_bool(value: Any) -> bool:
    """Convert a loosely-typed configuration value into a boolean."""

    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"true", "1", "yes", "on"}:
            return True
        if normalized in {"false", "0", "no", "off", ""}:
            return False
        if logger.isEnabledFor(logging.WARNING):
            logger.warning(
                "Unexpected boolean value '%s' in loop detection config; treating as truthy",
                value,
            )
        return True

    if isinstance(value, (int, float)):
        return bool(value)

    if isinstance(value, bool):
        return value

    if value is None:
        return False

    if logger.isEnabledFor(logging.WARNING):
        logger.warning(
            "Unexpected type %s for loop detection boolean config; treating as truthy",
            type(value).__name__,
        )
    return True

logger = logging.getLogger(__name__)


@dataclass
class PatternThresholds(InternalDTO):
    """Thresholds for different pattern lengths."""

    min_repetitions: int
    min_total_length: int


@dataclass
class LoopDetectionConfig(InternalDTO):
    """Configuration for loop detection functionality."""

    # Core settings
    enabled: bool = True
    buffer_size: int = 16384
    max_pattern_length: int = 8192
    # How many new characters must be processed before running another costly
    # pattern analysis pass.  This directly trades CPU time for latency of
    # detection.  A value of 0 (or negative) disables the interval optimisation.
    analysis_interval: int = 64

    # Hash-chunk algorithm parameters (ported from gemini-cli)
    # Size of the fixed window used to hash and compare content chunks.
    # Increased from the historical default (50) to 100 based on regression
    # tests that exercise real-world bug reports with ~280 character loops.
    content_chunk_size: int = 100
    # Number of repeated identical chunks required (within close proximity)
    # before flagging a loop. Lowered from 10 to 6 to detect loops faster
    # with fewer repetitions needed.
    content_loop_threshold: int = 6
    # Maximum characters of recent history to keep when scanning
    # Maintain enough history to keep multiple repetitions of ~300 char patterns.
    max_history_length: int = 4096

    # Pattern thresholds
    short_pattern_threshold: PatternThresholds | None = None
    medium_pattern_threshold: PatternThresholds | None = None
    long_pattern_threshold: PatternThresholds | None = None

    # Whitelist patterns that should not trigger detection
    whitelist: list[str] | None = None

    def __post_init__(self) -> None:
        """Initialize default thresholds if not provided."""
        if self.short_pattern_threshold is None:
            self.short_pattern_threshold = PatternThresholds(
                min_repetitions=3,
                min_total_length=100,
            )

        if self.medium_pattern_threshold is None:
            self.medium_pattern_threshold = PatternThresholds(
                min_repetitions=4,
                min_total_length=200,
            )

        if self.long_pattern_threshold is None:
            self.long_pattern_threshold = PatternThresholds(
                min_repetitions=3,
                min_total_length=300,
            )

        if self.whitelist is None:
            self.whitelist = ["...", "---", "===", "```"]

    @classmethod
    def from_dict(cls, config_dict: dict[str, Any]) -> LoopDetectionConfig:
        """Create configuration from dictionary."""
        config = cls()

        if "enabled" in config_dict:
            config.enabled = _coerce_to_bool(config_dict["enabled"])

        if "buffer_size" in config_dict:
            config.buffer_size = int(config_dict["buffer_size"])

        if "max_pattern_length" in config_dict:
            config.max_pattern_length = int(config_dict["max_pattern_length"])

        if "analysis_interval" in config_dict:
            config.analysis_interval = int(config_dict["analysis_interval"])

        # New hash-chunk parameters
        if "content_chunk_size" in config_dict:
            config.content_chunk_size = int(config_dict["content_chunk_size"])
        if "content_loop_threshold" in config_dict:
            config.content_loop_threshold = int(config_dict["content_loop_threshold"])
        if "max_history_length" in config_dict:
            config.max_history_length = int(config_dict["max_history_length"])

        if "whitelist" in config_dict:
            config.whitelist = list(config_dict["whitelist"])

        # Handle thresholds (support legacy and updated schema keys)
        thresholds = config_dict.get("thresholds") or config_dict.get(
            "pattern_thresholds", {}
        )

        if "short_patterns" in thresholds:
            short = thresholds["short_patterns"]
            config.short_pattern_threshold = PatternThresholds(
                min_repetitions=int(short.get("min_repetitions", 3)),
                min_total_length=int(short.get("min_total_length", 100)),
            )

        if "medium_patterns" in thresholds:
            medium = thresholds["medium_patterns"]
            config.medium_pattern_threshold = PatternThresholds(
                min_repetitions=int(medium.get("min_repetitions", 4)),
                min_total_length=int(medium.get("min_total_length", 200)),
            )

        if "long_patterns" in thresholds:
            long = thresholds["long_patterns"]
            config.long_pattern_threshold = PatternThresholds(
                min_repetitions=int(long.get("min_repetitions", 3)),
                min_total_length=int(long.get("min_total_length", 300)),
            )

        if "exact_match" in thresholds:
            exact = thresholds["exact_match"]
            config.short_pattern_threshold = PatternThresholds(
                min_repetitions=int(exact.get("min_repetitions", 3)),
                min_total_length=int(exact.get("min_total_length", 100)),
            )

        if "semantic_match" in thresholds:
            semantic = thresholds["semantic_match"]
            config.medium_pattern_threshold = PatternThresholds(
                min_repetitions=int(semantic.get("min_repetitions", 4)),
                min_total_length=int(semantic.get("min_total_length", 200)),
            )

        if "long_match" in thresholds:
            long = thresholds["long_match"]
            config.long_pattern_threshold = PatternThresholds(
                min_repetitions=int(long.get("min_repetitions", 3)),
                min_total_length=int(long.get("min_total_length", 300)),
            )

        return config

    @classmethod
    def from_env_vars(cls, env_dict: dict[str, str]) -> LoopDetectionConfig:
        """Create configuration from environment variables."""
        config = cls()

        if "LOOP_DETECTION_ENABLED" in env_dict:
            config.enabled = env_dict["LOOP_DETECTION_ENABLED"].lower() in (
                "true",
                "1",
                "yes",
                "on",
            )

        if "LOOP_DETECTION_BUFFER_SIZE" in env_dict:
            config.buffer_size = int(env_dict["LOOP_DETECTION_BUFFER_SIZE"])

        if "LOOP_DETECTION_MAX_PATTERN_LENGTH" in env_dict:
            config.max_pattern_length = int(
                env_dict["LOOP_DETECTION_MAX_PATTERN_LENGTH"]
            )

        if "LOOP_DETECTION_ANALYSIS_INTERVAL" in env_dict:
            config.analysis_interval = int(env_dict["LOOP_DETECTION_ANALYSIS_INTERVAL"])

        # New hash-chunk parameters (optional)
        if "LOOP_DETECTION_CONTENT_CHUNK_SIZE" in env_dict:
            config.content_chunk_size = int(
                env_dict["LOOP_DETECTION_CONTENT_CHUNK_SIZE"]
            )
        if "LOOP_DETECTION_CONTENT_LOOP_THRESHOLD" in env_dict:
            config.content_loop_threshold = int(
                env_dict["LOOP_DETECTION_CONTENT_LOOP_THRESHOLD"]
            )
        if "LOOP_DETECTION_MAX_HISTORY_LENGTH" in env_dict:
            config.max_history_length = int(
                env_dict["LOOP_DETECTION_MAX_HISTORY_LENGTH"]
            )

        # Threshold environment variables
        if (
            "LOOP_DETECTION_MIN_REPETITIONS_SHORT" in env_dict
            and config.short_pattern_threshold is not None
        ):
            config.short_pattern_threshold.min_repetitions = int(
                env_dict["LOOP_DETECTION_MIN_REPETITIONS_SHORT"]
            )

        if (
            "LOOP_DETECTION_MIN_REPETITIONS_MEDIUM" in env_dict
            and config.medium_pattern_threshold is not None
        ):
            config.medium_pattern_threshold.min_repetitions = int(
                env_dict["LOOP_DETECTION_MIN_REPETITIONS_MEDIUM"]
            )

        if (
            "LOOP_DETECTION_MIN_REPETITIONS_LONG" in env_dict
            and config.long_pattern_threshold is not None
        ):
            config.long_pattern_threshold.min_repetitions = int(
                env_dict["LOOP_DETECTION_MIN_REPETITIONS_LONG"]
            )

        return config

    def get_threshold_for_pattern_length(
        self, pattern_length: int
    ) -> PatternThresholds:
        """Get appropriate threshold based on pattern length."""
        if pattern_length <= 10:
            assert self.short_pattern_threshold is not None
            return self.short_pattern_threshold
        elif pattern_length <= 50:
            assert self.medium_pattern_threshold is not None
            return self.medium_pattern_threshold
        else:
            assert self.long_pattern_threshold is not None
            return self.long_pattern_threshold

    def validate(self) -> list[str]:
        """Validate configuration and return list of errors."""
        errors = []

        if self.buffer_size <= 0:
            errors.append("buffer_size must be positive")

        if self.max_pattern_length <= 0:
            errors.append("max_pattern_length must be positive")

        # Allow pattern length to exceed buffer - the detector will handle
        # clipping automatically when the buffer is smaller than the maximum
        # pattern size requested by configuration/testing scenarios.

        # Validate thresholds
        for name, threshold in [
            ("short_pattern", self.short_pattern_threshold),
            ("medium_pattern", self.medium_pattern_threshold),
            ("long_pattern", self.long_pattern_threshold),
        ]:
            if threshold is not None:
                if threshold.min_repetitions <= 0:
                    errors.append(f"{name}_threshold.min_repetitions must be positive")

                if threshold.min_total_length <= 0:
                    errors.append(f"{name}_threshold.min_total_length must be positive")

        if self.analysis_interval < 0:
            errors.append("analysis_interval cannot be negative")

        return errors

    @property
    def pattern_thresholds(self) -> dict[str, PatternThresholds]:
        """Expose pattern thresholds using the regression-test friendly schema."""
        assert self.short_pattern_threshold is not None
        assert self.medium_pattern_threshold is not None
        assert self.long_pattern_threshold is not None

        return {
            "exact_match": self.short_pattern_threshold,
            "semantic_match": self.medium_pattern_threshold,
            "long_match": self.long_pattern_threshold,
        }

    @pattern_thresholds.setter
    def pattern_thresholds(self, thresholds: dict[str, PatternThresholds]) -> None:
        """Allow bulk assignment of thresholds via the public mapping."""
        if "exact_match" in thresholds:
            self.short_pattern_threshold = thresholds["exact_match"]

        if "semantic_match" in thresholds:
            self.medium_pattern_threshold = thresholds["semantic_match"]

        if "long_match" in thresholds:
            self.long_pattern_threshold = thresholds["long_match"]
