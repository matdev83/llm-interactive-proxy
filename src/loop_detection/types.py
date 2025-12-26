from typing import TYPE_CHECKING, Any

from pydantic import BaseModel

if TYPE_CHECKING:
    pass


class LoopDetectorConfig(BaseModel):
    """Configuration for loop detector."""

    content_chunk_size: int
    content_loop_threshold: int
    max_history_length: int


class LoopDetectorStats(BaseModel):
    """Statistics for TokenWindowLoopDetector."""

    is_enabled: bool
    loop_detected: bool
    history_length: int
    in_code_block: bool
    tracked_chunks: int
    config: LoopDetectorConfig


class LoopDetectorState(BaseModel):
    """Current state of TokenWindowLoopDetector."""

    stream_content_history_length: int
    last_content_index: int
    loop_detected: bool
    in_code_block: bool
    content_stats_size: int


class LoopDetectorInternalState(BaseModel):
    """Internal state for saving/restoring TokenWindowLoopDetector."""

    stream_content_history: str
    content_stats: dict[int, list[int]]  # Key is hash(chunk), value is list of indices
    last_content_index: int
    loop_detected: bool
    in_code_block: bool


class LongDetectorStats(BaseModel):
    """Statistics for long pattern detector."""

    content_length: int
    min_pattern_length: int
    max_pattern_length: int
    min_repetitions: int


class HybridDetectorStats(BaseModel):
    """Statistics for HybridLoopDetector."""

    is_enabled: bool
    detection_method: str
    short_detector: LoopDetectorStats
    long_detector: LongDetectorStats
    total_events: int


class HybridDetectorState(BaseModel):
    """Current state of HybridLoopDetector."""

    short_detector_state: (
        LoopDetectorState  # From TokenWindowLoopDetector.get_current_state()
    )
    long_detector_content_length: int
    total_events: int


class HybridDetectorInternalState(BaseModel):
    """Internal state for saving/restoring HybridLoopDetector."""

    short_detector_state: dict[str, Any]  # Stored as dict to match internal return type
    long_detector_content: str
    loop_events: list[Any]  # list[LoopDetectionEvent] but avoiding circular import
    long_detector_last_check_length: int = 0


class PatternThresholdsModel(BaseModel):
    """Thresholds for pattern detection."""

    min_repetitions: int
    min_total_length: int


class StandardLoopDetectorConfig(BaseModel):
    """Configuration for Standard LoopDetector."""

    buffer_size: int
    max_pattern_length: int
    short_threshold: PatternThresholdsModel
    medium_threshold: PatternThresholdsModel
    long_threshold: PatternThresholdsModel


class StandardLoopDetectorStats(BaseModel):
    """Statistics for Standard LoopDetector."""

    is_active: bool
    last_detection_position: int
    config: StandardLoopDetectorConfig  # Nested config structure


class StandardLoopDetectorState(BaseModel):
    """Current state of Standard LoopDetector."""

    buffer_content_length: int
    total_processed: int
    last_detection_position: int
    analyzer_state: Any  # PatternAnalyzerSummary | dict[str, Any]
